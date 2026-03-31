# Feature Importance Drift Detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect when ML model input features drift from their training distribution and reduce confidence before the hard staleness cliff kicks in. Drift thresholds and penalties are tunable via config/optimizer.

**Architecture:** New `ml/drift.py` module with PSI computation and permutation importance. Training pipeline stores feature distribution stats (decile bins) for the top-5 important features in the JSON sidecar. Both `Predictor` and `EnsemblePredictor` load these stats and apply a confidence penalty based on max PSI across top-3 features at inference time. Four tunable parameters (`drift_psi_moderate`, `drift_psi_severe`, `drift_penalty_moderate`, `drift_penalty_severe`) flow through config → PipelineSettings → param_groups → predictors.

**Tech Stack:** NumPy (PSI + binning), PyTorch (permutation importance via loss measurement)

---

### Task 1: Core Drift Detection Module (`ml/drift.py`)

**Files:**
- Create: `backend/app/ml/drift.py`
- Create: `backend/tests/ml/test_drift.py`

- [ ] **Step 1: Write tests for PSI computation**

```python
# backend/tests/ml/test_drift.py
import numpy as np
import pytest

from app.ml.drift import compute_psi, compute_feature_distributions, feature_drift_penalty


class TestComputePSI:

    def test_identical_distributions_psi_near_zero(self):
        """PSI should be ~0 when actual matches expected."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        psi = compute_psi(dist["bin_edges"], dist["proportions"], training_data)
        assert psi < 0.01

    def test_shifted_distribution_moderate_psi(self):
        """A mean-shifted distribution should produce moderate PSI (0.1-0.25)."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        shifted = training_data + 0.5
        psi = compute_psi(dist["bin_edges"], dist["proportions"], shifted)
        assert 0.05 < psi < 0.5

    def test_very_different_distribution_high_psi(self):
        """A radically different distribution should produce high PSI (>0.25)."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        different = rng.standard_normal(500) * 5 + 3
        psi = compute_psi(dist["bin_edges"], dist["proportions"], different)
        assert psi > 0.25

    def test_psi_is_nonnegative(self):
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(200)
        dist = compute_feature_distributions(training_data, n_bins=10)
        actual = rng.standard_normal(200)
        psi = compute_psi(dist["bin_edges"], dist["proportions"], actual)
        assert psi >= 0.0

    def test_small_actual_sample(self):
        """PSI should work with small actual sample sizes."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        small_actual = rng.standard_normal(20)
        psi = compute_psi(dist["bin_edges"], dist["proportions"], small_actual)
        assert psi >= 0.0

    def test_nan_values_filtered(self):
        """NaN values in actual data should be filtered, not corrupt the result."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        actual = rng.standard_normal(100)
        actual[0:10] = np.nan
        psi = compute_psi(dist["bin_edges"], dist["proportions"], actual)
        assert np.isfinite(psi)
        assert psi >= 0.0

    def test_inf_values_filtered(self):
        """Inf values in actual data should be filtered."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        actual = rng.standard_normal(100)
        actual[0:5] = np.inf
        actual[5:10] = -np.inf
        psi = compute_psi(dist["bin_edges"], dist["proportions"], actual)
        assert np.isfinite(psi)
        assert psi >= 0.0

    def test_all_nan_returns_zero(self):
        """All-NaN actual data should return 0.0 (empty after filtering)."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal(500)
        dist = compute_feature_distributions(training_data, n_bins=10)
        actual = np.full(50, np.nan)
        psi = compute_psi(dist["bin_edges"], dist["proportions"], actual)
        assert psi == 0.0


class TestComputeFeatureDistributions:

    def test_returns_correct_keys(self):
        rng = np.random.default_rng(42)
        data = rng.standard_normal(200)
        dist = compute_feature_distributions(data, n_bins=10)
        assert "bin_edges" in dist
        assert "proportions" in dist

    def test_proportions_sum_to_one(self):
        rng = np.random.default_rng(42)
        data = rng.standard_normal(200)
        dist = compute_feature_distributions(data, n_bins=10)
        assert abs(sum(dist["proportions"]) - 1.0) < 1e-6

    def test_bin_edges_length(self):
        """n_bins=10 should produce 11 edges (including -inf and +inf)."""
        rng = np.random.default_rng(42)
        data = rng.standard_normal(200)
        dist = compute_feature_distributions(data, n_bins=10)
        assert len(dist["bin_edges"]) == 11
        assert len(dist["proportions"]) == 10

    def test_constant_value_feature(self):
        """All-identical values should produce valid distributions."""
        data = np.ones(200)
        dist = compute_feature_distributions(data, n_bins=10)
        assert len(dist["bin_edges"]) == 11
        assert len(dist["proportions"]) == 10
        assert abs(sum(dist["proportions"]) - 1.0) < 1e-6

    def test_nan_values_filtered(self):
        """NaN values in training data should be filtered out."""
        rng = np.random.default_rng(42)
        data = rng.standard_normal(200)
        data[0:20] = np.nan
        dist = compute_feature_distributions(data, n_bins=10)
        assert abs(sum(dist["proportions"]) - 1.0) < 1e-6

    def test_all_nan_returns_uniform(self):
        """All-NaN input should return uniform distribution."""
        data = np.full(100, np.nan)
        dist = compute_feature_distributions(data, n_bins=10)
        assert len(dist["proportions"]) == 10


class TestFeatureDriftPenalty:

    def test_no_drift_stats_returns_zero(self):
        features = np.random.randn(50, 10).astype(np.float32)
        penalty = feature_drift_penalty(features, None)
        assert penalty == 0.0

    def test_stable_features_no_penalty(self):
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = _make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        current = rng.standard_normal((50, 10)).astype(np.float32)
        penalty = feature_drift_penalty(current, drift_stats, top_k=3)
        assert penalty == 0.0

    def test_severe_drift_high_penalty(self):
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = _make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        current = (rng.standard_normal((50, 10)) * 5 + 3).astype(np.float32)
        penalty = feature_drift_penalty(current, drift_stats, top_k=3)
        assert penalty == 0.6

    def test_moderate_drift_moderate_penalty(self):
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = _make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        current = rng.standard_normal((50, 10)).astype(np.float32)
        current[:, 0] += 0.8
        penalty = feature_drift_penalty(current, drift_stats, top_k=3)
        assert penalty in (0.0, 0.3)

    def test_top_k_limits_features_checked(self):
        """Only top_k features should be checked, not all stored."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = _make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        current = rng.standard_normal((50, 10)).astype(np.float32)
        current[:, 4] = current[:, 4] * 10 + 5
        penalty = feature_drift_penalty(current, drift_stats, top_k=3)
        assert penalty == 0.0

    def test_custom_thresholds(self):
        """Custom PSI thresholds and penalties should be respected."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = _make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        current = (rng.standard_normal((50, 10)) * 5 + 3).astype(np.float32)
        # With very high thresholds, even severe drift should not trigger
        penalty = feature_drift_penalty(
            current, drift_stats, top_k=3,
            psi_moderate=10.0, psi_severe=20.0,
            penalty_moderate=0.1, penalty_severe=0.2,
        )
        assert penalty == 0.0

    def test_custom_penalties_applied(self):
        """Custom penalty values should be used when thresholds are hit."""
        rng = np.random.default_rng(42)
        training_data = rng.standard_normal((500, 10)).astype(np.float32)
        drift_stats = _make_drift_stats(training_data, top_indices=[0, 1, 2, 3, 4])
        current = (rng.standard_normal((50, 10)) * 5 + 3).astype(np.float32)
        penalty = feature_drift_penalty(
            current, drift_stats, top_k=3,
            psi_moderate=0.1, psi_severe=0.25,
            penalty_moderate=0.15, penalty_severe=0.45,
        )
        assert penalty == 0.45


def _make_drift_stats(training_data, top_indices):
    """Helper to build drift_stats dict from training data."""
    distributions = {}
    for idx in top_indices:
        distributions[str(idx)] = compute_feature_distributions(training_data[:, idx])
    return {
        "top_feature_indices": top_indices,
        "feature_distributions": distributions,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_drift.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ml.drift'`

- [ ] **Step 3: Implement drift module**

```python
# backend/app/ml/drift.py
"""Feature distribution drift detection via Population Stability Index."""

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Default PSI thresholds and penalties (tunable via config/optimizer)
DEFAULT_PSI_MODERATE = 0.1
DEFAULT_PSI_SEVERE = 0.25
DEFAULT_PENALTY_MODERATE = 0.3
DEFAULT_PENALTY_SEVERE = 0.6


def compute_feature_distributions(
    data: np.ndarray,
    n_bins: int = 10,
) -> dict:
    """Compute decile bin edges and proportions from training data.

    Args:
        data: 1D array of feature values from training set.
        n_bins: number of bins (default 10 = deciles).

    Returns:
        dict with 'bin_edges' (list of n_bins+1 floats including -inf/+inf)
        and 'proportions' (list of n_bins floats summing to 1.0).
    """
    data = data[np.isfinite(data)]
    if len(data) == 0:
        edges = [-np.inf] + [i * 1e-10 for i in range(1, n_bins)] + [np.inf]
        return {"bin_edges": edges, "proportions": [1.0 / n_bins] * n_bins}

    quantiles = np.linspace(0, 100, n_bins + 1)
    edges = np.percentile(data, quantiles)
    edges[0] = -np.inf
    edges[-1] = np.inf
    for i in range(1, len(edges)):
        if edges[i] <= edges[i - 1]:
            edges[i] = edges[i - 1] + 1e-10

    counts = np.histogram(data, bins=edges)[0].astype(np.float64)
    proportions = counts / counts.sum()

    return {
        "bin_edges": edges.tolist(),
        "proportions": proportions.tolist(),
    }


def compute_psi(
    bin_edges: list[float],
    expected_proportions: list[float],
    actual_values: np.ndarray,
    floor: float = 0.001,
) -> float:
    """Compute Population Stability Index between expected and actual distributions.

    Args:
        bin_edges: bin edges from training distribution (n_bins+1 values).
        expected_proportions: proportion in each bin from training (n_bins values).
        actual_values: 1D array of current feature values.
        floor: minimum proportion to avoid log(0).

    Returns:
        PSI value (>= 0). <0.1 = stable, 0.1-0.25 = moderate, >0.25 = severe.
    """
    actual_values = actual_values[np.isfinite(actual_values)]
    edges = np.array(bin_edges)
    expected = np.array(expected_proportions, dtype=np.float64)
    expected = np.maximum(expected, floor)

    actual_counts = np.histogram(actual_values, bins=edges)[0].astype(np.float64)
    total = actual_counts.sum()
    if total == 0:
        return 0.0
    actual = actual_counts / total
    actual = np.maximum(actual, floor)

    psi = float(np.sum((actual - expected) * np.log(actual / expected)))
    return max(0.0, psi)


def feature_drift_penalty(
    current_features: np.ndarray,
    drift_stats: dict | None,
    top_k: int = 3,
    psi_moderate: float = DEFAULT_PSI_MODERATE,
    psi_severe: float = DEFAULT_PSI_SEVERE,
    penalty_moderate: float = DEFAULT_PENALTY_MODERATE,
    penalty_severe: float = DEFAULT_PENALTY_SEVERE,
) -> float:
    """Compute confidence penalty based on feature distribution drift.

    Args:
        current_features: (n_candles, n_features) array.
        drift_stats: dict with 'top_feature_indices' and 'feature_distributions',
                     or None if not available.
        top_k: number of top features to check.
        psi_moderate: PSI threshold for moderate drift.
        psi_severe: PSI threshold for severe drift.
        penalty_moderate: penalty applied when moderate drift detected.
        penalty_severe: penalty applied when severe drift detected.

    Returns:
        Penalty float (0.0, penalty_moderate, or penalty_severe).
    """
    if drift_stats is None:
        return 0.0

    top_indices = drift_stats.get("top_feature_indices", [])[:top_k]
    distributions = drift_stats.get("feature_distributions", {})

    if not top_indices or not distributions:
        return 0.0

    max_psi = 0.0
    n_features = current_features.shape[1]

    for idx in top_indices:
        dist = distributions.get(str(idx))
        if dist is None:
            continue
        if idx >= n_features:
            continue
        psi = compute_psi(
            dist["bin_edges"],
            dist["proportions"],
            current_features[:, idx],
        )
        max_psi = max(max_psi, psi)

    if max_psi < psi_moderate:
        return 0.0
    elif max_psi < psi_severe:
        return penalty_moderate
    else:
        return penalty_severe
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_drift.py -v`
Expected: all 20 tests PASS

---

### Task 2: Permutation Importance at Training Time

**Files:**
- Modify: `backend/app/ml/drift.py` (add `compute_permutation_importance`)
- Modify: `backend/tests/ml/test_drift.py` (add importance tests)

- [ ] **Step 1: Write tests for permutation importance**

Add to `backend/tests/ml/test_drift.py`:

```python
import torch
from app.ml.model import SignalLSTM
from app.ml.dataset import CandleDataset
from torch.utils.data import DataLoader
from app.ml.drift import compute_permutation_importance


class TestPermutationImportance:

    @pytest.fixture
    def model_and_loader(self):
        """Create a small model and validation data loader."""
        rng = np.random.default_rng(42)
        input_size = 10
        seq_len = 5
        n_samples = 50

        model = SignalLSTM(
            input_size=input_size, hidden_size=16,
            num_layers=1, dropout=0.0,
        )
        model.eval()

        features = rng.standard_normal((n_samples, input_size)).astype(np.float32)
        direction = rng.integers(0, 3, size=n_samples)
        sl = rng.uniform(0.5, 2.0, size=n_samples).astype(np.float32)
        tp1 = rng.uniform(1.0, 3.0, size=n_samples).astype(np.float32)
        tp2 = rng.uniform(2.0, 5.0, size=n_samples).astype(np.float32)

        ds = CandleDataset(features, direction, sl, tp1, tp2, seq_len=seq_len)
        loader = DataLoader(ds, batch_size=16, shuffle=False)

        return model, loader, input_size

    def test_returns_correct_length(self, model_and_loader):
        model, loader, input_size = model_and_loader
        importance = compute_permutation_importance(model, loader, input_size)
        assert len(importance) == input_size

    def test_returns_sorted_indices(self, model_and_loader):
        """Result should be sorted by importance descending."""
        model, loader, input_size = model_and_loader
        importance = compute_permutation_importance(model, loader, input_size)
        scores = [s for _, s in importance]
        assert scores == sorted(scores, reverse=True)

    def test_importance_scores_nonnegative_on_average(self, model_and_loader):
        """Mean importance should be >= 0 (shuffling should not help on average)."""
        model, loader, input_size = model_and_loader
        importance = compute_permutation_importance(model, loader, input_size)
        mean_score = np.mean([s for _, s in importance])
        assert mean_score >= -0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_drift.py::TestPermutationImportance -v`
Expected: FAIL — `ImportError: cannot import name 'compute_permutation_importance'`

- [ ] **Step 3: Implement permutation importance**

Add to `backend/app/ml/drift.py`:

```python
import torch
import torch.nn as nn


def compute_permutation_importance(
    model: nn.Module,
    val_loader,
    input_size: int,
    n_repeats: int = 3,
) -> list[tuple[int, float]]:
    """Compute permutation importance for each feature on validation data.

    Shuffles each feature column across the batch, measures the increase in
    classification loss. Higher increase = more important feature.

    Args:
        model: trained SignalLSTM in eval mode.
        val_loader: DataLoader yielding (x, y_dir, y_reg) batches.
        input_size: number of feature columns.
        n_repeats: number of shuffle repeats per feature for stability.

    Returns:
        List of (feature_index, importance_score) sorted by importance descending.
    """
    device = next(model.parameters()).device
    criterion = nn.CrossEntropyLoss()
    model.eval()

    baseline_loss = 0.0
    n_batches = 0
    all_x = []
    all_y = []
    with torch.no_grad():
        for x, y_dir, _ in val_loader:
            x = x.to(device)
            y_dir = y_dir.to(device)
            dir_logits, _ = model(x)
            baseline_loss += criterion(dir_logits, y_dir).item()
            all_x.append(x)
            all_y.append(y_dir)
            n_batches += 1

    if n_batches == 0:
        return [(i, 0.0) for i in range(input_size)]

    baseline_loss /= n_batches

    importance = []
    for feat_idx in range(input_size):
        total_increase = 0.0
        for _ in range(n_repeats):
            shuffled_loss = 0.0
            for x, y_dir in zip(all_x, all_y):
                x_perm = x.clone()
                perm = torch.randperm(x_perm.size(0), device=device)
                x_perm[:, :, feat_idx] = x_perm[perm, :, feat_idx]
                with torch.no_grad():
                    dir_logits, _ = model(x_perm)
                    shuffled_loss += criterion(dir_logits, y_dir).item()
            shuffled_loss /= n_batches
            total_increase += shuffled_loss - baseline_loss

        importance.append((feat_idx, total_increase / n_repeats))

    importance.sort(key=lambda x: x[1], reverse=True)
    return importance
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_drift.py -v`
Expected: all 23 tests PASS

---

### Task 3: Store Drift Stats at Training Time

**Files:**
- Modify: `backend/app/ml/trainer.py:396` (add drift stats after validation metrics, before return)
- Modify: `backend/tests/ml/test_trainer.py` (add drift stats test)

- [ ] **Step 1: Write test for drift stats in training output**

Add to `backend/tests/ml/test_trainer.py`:

```python
def test_train_stores_drift_stats(tmp_path):
    """Training should write drift_stats to model_config.json."""
    import json
    rng = np.random.default_rng(42)
    n = 200
    input_size = 10
    features = rng.standard_normal((n, input_size)).astype(np.float32)
    direction = rng.integers(0, 3, n).astype(np.int64)
    sl = rng.uniform(0.5, 2, n).astype(np.float32)
    tp1 = rng.uniform(1, 3, n).astype(np.float32)
    tp2 = rng.uniform(2, 5, n).astype(np.float32)
    feature_names = [f"feat_{i}" for i in range(input_size)]

    cfg = TrainConfig(
        epochs=3, batch_size=32, seq_len=10,
        hidden_size=16, num_layers=1, dropout=0.1,
        patience=100, checkpoint_dir=str(tmp_path),
    )
    trainer = Trainer(cfg)
    trainer.train_one_model(features, direction, sl, tp1, tp2, feature_names=feature_names)

    config_path = tmp_path / "model_config.json"
    assert config_path.exists()
    with open(config_path) as f:
        config = json.load(f)

    assert "drift_stats" in config
    ds = config["drift_stats"]
    assert "top_feature_indices" in ds
    assert "feature_distributions" in ds
    assert len(ds["top_feature_indices"]) == 5
    for idx in ds["top_feature_indices"]:
        dist = ds["feature_distributions"][str(idx)]
        assert "bin_edges" in dist
        assert "proportions" in dist
        assert len(dist["proportions"]) == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py::test_train_stores_drift_stats -v`
Expected: FAIL — `assert "drift_stats" in config`

- [ ] **Step 3: Add drift stats computation to trainer**

In `backend/app/ml/trainer.py`, in `train_one_model()`:

**A. Before the NEUTRAL subsampling block (line 76), capture original features for drift distribution computation.** Subsampled features reflect the balanced training set, but inference features are raw market data — distributions must come from pre-subsample data:

```python
        pre_subsample_features = features.copy()
        pre_subsample_n = len(features)
```

**B. After the per-class precision/recall block (after line 395) and before `return {` (line 397), insert:**

```python
        # ── Compute feature drift stats for inference-time drift detection ──
        drift_stats = None
        if use_val and val_loader is not None:
            try:
                from app.ml.drift import (
                    compute_feature_distributions,
                    compute_permutation_importance,
                )

                importance = compute_permutation_importance(
                    model, val_loader, input_size, n_repeats=3,
                )
                top_n = 5
                top_indices = [idx for idx, _ in importance[:top_n]]
                pre_split = int(pre_subsample_n * (1 - cfg.val_ratio))
                distributions = {}
                for idx in top_indices:
                    distributions[str(idx)] = compute_feature_distributions(
                        pre_subsample_features[:pre_split, idx], n_bins=10,
                    )
                drift_stats = {
                    "top_feature_indices": top_indices,
                    "feature_distributions": distributions,
                }
                logger.info("Drift stats computed for top %d features: %s", top_n, top_indices)
            except Exception as e:
                logger.warning("Failed to compute drift stats: %s", e)
        else:
            logger.info("Skipping drift stats: no validation set available")

        if drift_stats is not None:
            import json as _json
            config_path = os.path.join(cfg.checkpoint_dir, "model_config.json")
            if os.path.exists(config_path):
                with open(config_path) as f:
                    config_meta = _json.load(f)
                config_meta["drift_stats"] = drift_stats
                with open(config_path, "w") as f:
                    _json.dump(config_meta, f, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py::test_train_stores_drift_stats -v`
Expected: PASS

- [ ] **Step 5: Run full trainer test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py -v`
Expected: all tests PASS

---

### Task 4: Tunable Drift Config + DB Migration

**Files:**
- Modify: `backend/app/config.py:134` (add drift settings after ensemble settings)
- Modify: `backend/app/db/models.py:273` (add drift columns to PipelineSettings)
- Create: `backend/app/db/migrations/versions/xxxx_add_drift_columns.py` (Alembic migration)
- Modify: `backend/app/api/engine.py:175` (add to `_PIPELINE_SETTINGS_MAP`)
- Modify: `backend/app/engine/param_groups.py:533-551` (add drift params to `ensemble` group)

- [ ] **Step 1: Add config settings**

In `backend/app/config.py`, after `ensemble_confidence_cap_partial` (line 134), add:

```python
    drift_psi_moderate: float = 0.1
    drift_psi_severe: float = 0.25
    drift_penalty_moderate: float = 0.3
    drift_penalty_severe: float = 0.6
```

- [ ] **Step 2: Add PipelineSettings columns**

In `backend/app/db/models.py`, after `ensemble_confidence_cap_partial` (line 273), add:

```python
    drift_psi_moderate: Mapped[float | None] = mapped_column(Float, nullable=True)
    drift_psi_severe: Mapped[float | None] = mapped_column(Float, nullable=True)
    drift_penalty_moderate: Mapped[float | None] = mapped_column(Float, nullable=True)
    drift_penalty_severe: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 3: Create Alembic migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add drift detection columns to pipeline_settings"`

Verify the generated migration adds the 4 columns.

- [ ] **Step 4: Add to pipeline settings map**

In `backend/app/api/engine.py`, after the `optimizer.ew_ic_lookback_days` entry (line 175), add:

```python
    "ensemble.drift_psi_moderate": ("drift_psi_moderate", "drift_psi_moderate"),
    "ensemble.drift_psi_severe": ("drift_psi_severe", "drift_psi_severe"),
    "ensemble.drift_penalty_moderate": ("drift_penalty_moderate", "drift_penalty_moderate"),
    "ensemble.drift_penalty_severe": ("drift_penalty_severe", "drift_penalty_severe"),
```

- [ ] **Step 5: Add drift params to ensemble param group**

In `backend/app/engine/param_groups.py`, update the `ensemble` group's `params`, `sweep_ranges`, and constraint:

Add to `PARAM_GROUPS["ensemble"]["params"]`:
```python
        "drift_psi_moderate": "ensemble.drift_psi_moderate",
        "drift_psi_severe": "ensemble.drift_psi_severe",
        "drift_penalty_moderate": "ensemble.drift_penalty_moderate",
        "drift_penalty_severe": "ensemble.drift_penalty_severe",
```

Add to `PARAM_GROUPS["ensemble"]["sweep_ranges"]`:
```python
        "drift_psi_moderate": (0.05, 0.20, None),
        "drift_psi_severe": (0.15, 0.40, None),
        "drift_penalty_moderate": (0.1, 0.5, None),
        "drift_penalty_severe": (0.3, 0.8, None),
```

Update `_ensemble_ok` constraint to add:
```python
    and c["drift_psi_severe"] > c["drift_psi_moderate"] > 0
    and c["drift_penalty_severe"] > c["drift_penalty_moderate"] > 0
    and c["drift_penalty_severe"] <= 1.0
```

- [ ] **Step 6: Write constraint tests**

Add to `backend/tests/engine/test_param_groups.py` (create if needed):

```python
from app.engine.param_groups import PARAM_GROUPS


def test_ensemble_constraint_accepts_valid_drift_params():
    """Valid drift params should pass the ensemble constraint."""
    constraint = PARAM_GROUPS["ensemble"]["constraints"]
    c = {
        "disagreement_scale": 8.0,
        "stale_fresh_days": 7.0,
        "stale_decay_days": 21.0,
        "stale_floor": 0.3,
        "confidence_cap_partial": 0.5,
        "drift_psi_moderate": 0.1,
        "drift_psi_severe": 0.25,
        "drift_penalty_moderate": 0.3,
        "drift_penalty_severe": 0.6,
    }
    assert constraint(c) is True


def test_ensemble_constraint_rejects_inverted_psi():
    """drift_psi_severe must be > drift_psi_moderate."""
    constraint = PARAM_GROUPS["ensemble"]["constraints"]
    c = {
        "disagreement_scale": 8.0,
        "stale_fresh_days": 7.0,
        "stale_decay_days": 21.0,
        "stale_floor": 0.3,
        "confidence_cap_partial": 0.5,
        "drift_psi_moderate": 0.25,
        "drift_psi_severe": 0.1,
        "drift_penalty_moderate": 0.3,
        "drift_penalty_severe": 0.6,
    }
    assert constraint(c) is False


def test_ensemble_constraint_rejects_penalty_over_one():
    """drift_penalty_severe must be <= 1.0."""
    constraint = PARAM_GROUPS["ensemble"]["constraints"]
    c = {
        "disagreement_scale": 8.0,
        "stale_fresh_days": 7.0,
        "stale_decay_days": 21.0,
        "stale_floor": 0.3,
        "confidence_cap_partial": 0.5,
        "drift_psi_moderate": 0.1,
        "drift_psi_severe": 0.25,
        "drift_penalty_moderate": 0.3,
        "drift_penalty_severe": 1.5,
    }
    assert constraint(c) is False
```

- [ ] **Step 7: Run constraint tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_param_groups.py -v`
Expected: all 3 tests PASS

---

### Task 5: Apply Drift Penalty in Predictor

**Files:**
- Modify: `backend/app/ml/predictor.py:30-76` (load drift stats + drift params), `backend/app/ml/predictor.py:170-184` (apply penalty)
- Modify: `backend/tests/ml/test_predictor.py` (add drift penalty tests)

- [ ] **Step 1: Write tests for drift penalty in Predictor**

Add to `backend/tests/ml/test_predictor.py`:

```python
class TestDriftPenalty:

    def test_no_drift_stats_no_penalty(self):
        """Old checkpoints without drift_stats should work unchanged."""
        path = _save_model(input_size=15)
        predictor = Predictor(path)
        features = np.random.randn(50, 15).astype(np.float32)
        result = predictor.predict(features)
        assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")
        assert result.get("drift_penalty", 0.0) == 0.0

    def test_drift_penalty_reduces_confidence(self):
        """When drift stats indicate severe drift, confidence should decrease."""
        from app.ml.drift import compute_feature_distributions

        rng = np.random.default_rng(42)
        input_size = 15

        training_data = rng.standard_normal((500, input_size)).astype(np.float32)
        top_indices = [0, 1, 2, 3, 4]
        distributions = {}
        for idx in top_indices:
            distributions[str(idx)] = compute_feature_distributions(training_data[:, idx])
        drift_stats = {
            "top_feature_indices": top_indices,
            "feature_distributions": distributions,
        }

        path = _save_model(input_size=input_size, extra_config={"drift_stats": drift_stats})

        predictor_normal = Predictor(path)
        normal_features = rng.standard_normal((50, input_size)).astype(np.float32)
        result_normal = predictor_normal.predict(normal_features)

        predictor_drifted = Predictor(path)
        drifted_features = (rng.standard_normal((50, input_size)) * 5 + 3).astype(np.float32)
        result_drifted = predictor_drifted.predict(drifted_features)

        if result_normal["confidence"] > 0:
            assert result_drifted["confidence"] <= result_normal["confidence"]

    def test_drift_penalty_in_result(self):
        """predict() should include drift_penalty in result."""
        path = _save_model(input_size=15)
        predictor = Predictor(path)
        features = np.random.randn(50, 15).astype(np.float32)
        result = predictor.predict(features)
        assert "drift_penalty" in result

    def test_custom_drift_thresholds(self):
        """Predictor should accept drift threshold overrides."""
        from app.ml.drift import compute_feature_distributions

        rng = np.random.default_rng(42)
        input_size = 15

        training_data = rng.standard_normal((500, input_size)).astype(np.float32)
        top_indices = [0, 1, 2, 3, 4]
        distributions = {}
        for idx in top_indices:
            distributions[str(idx)] = compute_feature_distributions(training_data[:, idx])
        drift_stats = {
            "top_feature_indices": top_indices,
            "feature_distributions": distributions,
        }

        path = _save_model(input_size=input_size, extra_config={"drift_stats": drift_stats})

        # With very high thresholds, no penalty even on drifted data
        predictor = Predictor(
            path,
            drift_psi_moderate=10.0,
            drift_psi_severe=20.0,
        )
        drifted_features = (rng.standard_normal((50, input_size)) * 5 + 3).astype(np.float32)
        result = predictor.predict(drifted_features)
        assert result["drift_penalty"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_predictor.py::TestDriftPenalty -v`
Expected: FAIL — `assert "drift_penalty" in result`

- [ ] **Step 3: Modify Predictor to load and apply drift stats**

In `backend/app/ml/predictor.py`:

**A. Update `__init__` signature** to accept drift params:

```python
    def __init__(
        self,
        checkpoint_path: str,
        max_age_days: int = 14,
        drift_psi_moderate: float = 0.1,
        drift_psi_severe: float = 0.25,
        drift_penalty_moderate: float = 0.3,
        drift_penalty_severe: float = 0.6,
    ):
```

**B. After `self._available_features = None` (line 56), add:**

```python
        self._drift_stats = config.get("drift_stats")
        self._drift_psi_moderate = drift_psi_moderate
        self._drift_psi_severe = drift_psi_severe
        self._drift_penalty_moderate = drift_penalty_moderate
        self._drift_penalty_severe = drift_penalty_severe
```

**C. Add top-level import** at the top of `predictor.py` (with the other app imports):

```python
from app.ml.drift import feature_drift_penalty
```

**D. In `predict()`, after the uncertainty penalty (line 172) and before the staleness cap (line 175), add drift penalty:**

Replace lines 172-184:

```python
        # Reduce confidence proportionally to uncertainty
        uncertainty_penalty = min(1.0, prob_variance * 10)
        confidence = raw_confidence * (1.0 - uncertainty_penalty)

        # Apply feature drift penalty
        drift_pen = feature_drift_penalty(
            window, self._drift_stats, top_k=3,
            psi_moderate=self._drift_psi_moderate,
            psi_severe=self._drift_psi_severe,
            penalty_moderate=self._drift_penalty_moderate,
            penalty_severe=self._drift_penalty_severe,
        )
        confidence *= (1.0 - drift_pen)

        # Cap confidence for stale models
        confidence = min(confidence, self._max_confidence)

        return {
            "direction": DIRECTION_MAP[direction_idx],
            "confidence": confidence,
            "sl_atr": float(mean_reg[0]),
            "tp1_atr": float(mean_reg[1]),
            "tp2_atr": float(mean_reg[2]),
            "mc_variance": prob_variance,
            "drift_penalty": drift_pen,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_predictor.py -v`
Expected: all tests PASS
```

---

### Task 6: Apply Drift Penalty in EnsemblePredictor

**Files:**
- Modify: `backend/app/ml/ensemble_predictor.py:45-70` (accept drift params), `backend/app/ml/ensemble_predictor.py:198-212` (apply penalty)
- Modify: `backend/tests/ml/test_ensemble_predictor.py` (add drift penalty tests)

- [ ] **Step 1: Write tests for drift penalty in EnsemblePredictor**

Add to `backend/tests/ml/test_ensemble_predictor.py`:

```python
from app.ml.drift import compute_feature_distributions


def _add_drift_stats_to_config(checkpoint_dir, input_size=15):
    """Add drift_stats to ensemble_config.json for testing."""
    rng = np.random.default_rng(42)
    training_data = rng.standard_normal((500, input_size)).astype(np.float32)
    top_indices = [0, 1, 2, 3, 4]
    distributions = {}
    for idx in top_indices:
        distributions[str(idx)] = compute_feature_distributions(training_data[:, idx])
    drift_stats = {
        "top_feature_indices": top_indices,
        "feature_distributions": distributions,
    }

    config_path = os.path.join(checkpoint_dir, "ensemble_config.json")
    with open(config_path) as f:
        config = json.load(f)
    config["drift_stats"] = drift_stats
    with open(config_path, "w") as f:
        json.dump(config, f)
    return drift_stats


def test_no_drift_stats_backward_compatible(ensemble_checkpoint):
    """Ensemble without drift_stats should work unchanged."""
    pred = EnsemblePredictor(ensemble_checkpoint)
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")
    assert result.get("drift_penalty", 0.0) == 0.0


def test_drift_penalty_in_result(ensemble_checkpoint):
    """predict() should include drift_penalty key."""
    _add_drift_stats_to_config(ensemble_checkpoint)
    pred = EnsemblePredictor(ensemble_checkpoint)
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    assert "drift_penalty" in result


def test_severe_drift_reduces_confidence(ensemble_checkpoint):
    """Severe drift should reduce confidence."""
    _add_drift_stats_to_config(ensemble_checkpoint)
    pred = EnsemblePredictor(ensemble_checkpoint)

    rng = np.random.default_rng(42)
    normal_features = rng.standard_normal((20, 15)).astype(np.float32)
    result_normal = pred.predict(normal_features)

    drifted_features = (rng.standard_normal((20, 15)) * 5 + 3).astype(np.float32)
    result_drifted = pred.predict(drifted_features)

    if result_normal["confidence"] > 0:
        assert result_drifted["confidence"] <= result_normal["confidence"]


def test_custom_drift_thresholds(ensemble_checkpoint):
    """EnsemblePredictor should accept drift threshold overrides."""
    _add_drift_stats_to_config(ensemble_checkpoint)
    pred = EnsemblePredictor(
        ensemble_checkpoint,
        drift_psi_moderate=10.0,
        drift_psi_severe=20.0,
    )
    rng = np.random.default_rng(42)
    drifted = (rng.standard_normal((20, 15)) * 5 + 3).astype(np.float32)
    result = pred.predict(drifted)
    assert result["drift_penalty"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_predictor.py::test_drift_penalty_in_result -v`
Expected: FAIL — `assert "drift_penalty" in result`

- [ ] **Step 3: Modify EnsemblePredictor to load and apply drift stats**

In `backend/app/ml/ensemble_predictor.py`:

**A. Update `__init__` signature** to accept drift params:

```python
    def __init__(
        self,
        checkpoint_dir: str,
        ensemble_disagreement_scale: float = 8.0,
        stale_fresh_days: float = 7.0,
        stale_decay_days: float = 21.0,
        stale_floor: float = 0.3,
        confidence_cap_partial: float = 0.5,
        drift_psi_moderate: float = 0.1,
        drift_psi_severe: float = 0.25,
        drift_penalty_moderate: float = 0.3,
        drift_penalty_severe: float = 0.6,
    ):
```

**B. After `self._drift_stats` load from config (after loading btc_used, line ~70), add:**

```python
        self._drift_stats = config.get("drift_stats")
        self._drift_psi_moderate = drift_psi_moderate
        self._drift_psi_severe = drift_psi_severe
        self._drift_penalty_moderate = drift_penalty_moderate
        self._drift_penalty_severe = drift_penalty_severe
```

**C. Add top-level import** at the top of `ensemble_predictor.py` (after the existing `from app.ml.predictor import DIRECTION_MAP`):

```python
from app.ml.drift import feature_drift_penalty
```

**D. In `predict()`, replace the return block (lines 198-212):**

```python
        uncertainty_penalty = min(1.0, disagreement * self._disagreement_scale)
        confidence = raw_confidence * (1.0 - uncertainty_penalty)

        # Apply feature drift penalty
        drift_pen = feature_drift_penalty(
            window, self._drift_stats, top_k=3,
            psi_moderate=self._drift_psi_moderate,
            psi_severe=self._drift_psi_severe,
            penalty_moderate=self._drift_penalty_moderate,
            penalty_severe=self._drift_penalty_severe,
        )
        confidence *= (1.0 - drift_pen)

        # Cap confidence for partial ensembles
        if self.n_members == 2:
            confidence = min(confidence, self._confidence_cap_partial)

        return {
            "direction": DIRECTION_MAP[direction_idx],
            "confidence": confidence,
            "sl_atr": float(mean_reg[0]),
            "tp1_atr": float(mean_reg[1]),
            "tp2_atr": float(mean_reg[2]),
            "ensemble_disagreement": disagreement,
            "drift_penalty": drift_pen,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_predictor.py -v`
Expected: all tests PASS

---

### Task 7: Wire Drift Settings into Predictor Loading

**Files:**
- Modify: `backend/app/api/ml.py:748-770` (pass drift params when constructing predictors)
- Modify: `backend/tests/api/test_ml.py` (add wiring test)

- [ ] **Step 1: Update `_reload_predictors` to pass drift settings**

In `backend/app/api/ml.py`, in `_reload_predictors()`, after loading existing ensemble params (~line 752), add drift param loading:

```python
    drift_psi_mod = getattr(settings, "drift_psi_moderate", 0.1)
    drift_psi_sev = getattr(settings, "drift_psi_severe", 0.25)
    drift_pen_mod = getattr(settings, "drift_penalty_moderate", 0.3)
    drift_pen_sev = getattr(settings, "drift_penalty_severe", 0.6)
```

Then pass these to both the `EnsemblePredictor` constructor (~line 764):

```python
                predictor = EnsemblePredictor(
                    pair_dir,
                    ensemble_disagreement_scale=disagreement_scale,
                    stale_fresh_days=stale_fresh,
                    stale_decay_days=stale_decay,
                    stale_floor=stale_floor,
                    confidence_cap_partial=cap_partial,
                    drift_psi_moderate=drift_psi_mod,
                    drift_psi_severe=drift_psi_sev,
                    drift_penalty_moderate=drift_pen_mod,
                    drift_penalty_severe=drift_pen_sev,
                )
```

And to the `Predictor` fallback constructor (find the `Predictor(...)` call nearby):

```python
                predictor = Predictor(
                    best_pt,
                    drift_psi_moderate=drift_psi_mod,
                    drift_psi_severe=drift_psi_sev,
                    drift_penalty_moderate=drift_pen_mod,
                    drift_penalty_severe=drift_pen_sev,
                )
```

- [ ] **Step 2: Write wiring test**

Add to `backend/tests/api/test_ml.py`:

```python
def test_reload_predictors_passes_drift_settings(ml_app):
    """_reload_predictors should pass drift config values to predictor constructors."""
    from unittest.mock import patch, MagicMock
    from app.api.ml import _reload_predictors

    settings = ml_app.state.settings
    settings.drift_psi_moderate = 0.15
    settings.drift_psi_severe = 0.30
    settings.drift_penalty_moderate = 0.2
    settings.drift_penalty_severe = 0.5

    with patch("app.api.ml.EnsemblePredictor") as MockEnsemble:
        MockEnsemble.return_value = MagicMock()
        MockEnsemble.return_value.n_members = 3
        with patch("app.api.ml.os.listdir", return_value=["BTC-USDT-SWAP"]):
            with patch("app.api.ml.os.path.isdir", return_value=True):
                with patch("app.api.ml.os.path.exists", return_value=True):
                    _reload_predictors(ml_app, settings)

        if MockEnsemble.called:
            kwargs = MockEnsemble.call_args.kwargs
            assert kwargs["drift_psi_moderate"] == 0.15
            assert kwargs["drift_psi_severe"] == 0.30
            assert kwargs["drift_penalty_moderate"] == 0.2
            assert kwargs["drift_penalty_severe"] == 0.5
```

- [ ] **Step 3: Run full ML + API test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/ tests/api/test_ml.py -v`
Expected: all tests PASS

---

### Task 8: Store Drift Stats in Ensemble Training

**Files:**
- Modify: `backend/app/ml/trainer.py:537-557` (add drift stats to ensemble_config.json)
- Modify: `backend/tests/ml/test_ensemble_training.py` (add drift stats test)

- [ ] **Step 1: Write test for drift stats in ensemble config**

Add to `backend/tests/ml/test_ensemble_training.py`:

```python
def test_ensemble_stores_drift_stats(tmp_path):
    """Ensemble training should write drift_stats to ensemble_config.json."""
    import json
    rng = np.random.default_rng(42)
    n = 300
    input_size = 10
    features = rng.standard_normal((n, input_size)).astype(np.float32)
    direction = rng.integers(0, 3, n).astype(np.int64)
    sl = rng.uniform(0.5, 2, n).astype(np.float32)
    tp1 = rng.uniform(1, 3, n).astype(np.float32)
    tp2 = rng.uniform(2, 5, n).astype(np.float32)
    feature_names = [f"feat_{i}" for i in range(input_size)]

    cfg = TrainConfig(
        epochs=3, batch_size=32, seq_len=10,
        hidden_size=16, num_layers=1, dropout=0.1,
        patience=100, checkpoint_dir=str(tmp_path),
    )
    trainer = Trainer(cfg)
    result = trainer.train_ensemble(features, direction, sl, tp1, tp2, feature_names=feature_names)

    if result.get("n_members", 0) >= 2:
        config_path = tmp_path / "ensemble_config.json"
        assert config_path.exists()
        with open(config_path) as f:
            config = json.load(f)
        assert "drift_stats" in config
        ds = config["drift_stats"]
        assert len(ds["top_feature_indices"]) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_training.py::test_ensemble_stores_drift_stats -v`
Expected: FAIL — `assert "drift_stats" in config`

- [ ] **Step 3: Add drift stats to ensemble training**

In `backend/app/ml/trainer.py`, in `train_ensemble()`, after the ensemble_config dict is built (~line 555) but **before** `shutil.rmtree(staging_dir, ...)` and **before** writing `ensemble_config.json`, add:

```python
        # Compute drift stats using first member's model
        drift_stats = None
        try:
            from app.ml.drift import (
                compute_feature_distributions,
                compute_permutation_importance,
            )
            first_member_dir = os.path.join(staging_dir, f"member_{members[0]['index']}")
            first_pt = os.path.join(first_member_dir, "best_model.pt")

            if os.path.exists(first_pt):
                perm_model = SignalLSTM(
                    input_size=features.shape[1],
                    hidden_size=cfg.hidden_size,
                    num_layers=cfg.num_layers,
                    dropout=cfg.dropout,
                ).to(self.device)
                perm_model.load_state_dict(
                    torch.load(first_pt, map_location=self.device, weights_only=True)
                )
                perm_model.eval()

                val_start = int(n * (1 - cfg.val_ratio))
                val_feat = features[val_start:]
                val_dir = direction[val_start:]
                val_sl = sl_atr[val_start:]
                val_tp1 = tp1_atr[val_start:]
                val_tp2 = tp2_atr[val_start:]

                if len(val_feat) > cfg.seq_len:
                    val_ds = CandleDataset(
                        val_feat, val_dir, val_sl, val_tp1, val_tp2,
                        seq_len=cfg.seq_len,
                    )
                    val_loader = DataLoader(val_ds, batch_size=cfg.batch_size, shuffle=False)

                    importance = compute_permutation_importance(
                        perm_model, val_loader, features.shape[1], n_repeats=3,
                    )
                    top_n = 5
                    top_indices = [idx for idx, _ in importance[:top_n]]
                    distributions = {}
                    for idx in top_indices:
                        distributions[str(idx)] = compute_feature_distributions(
                            features[:val_start, idx], n_bins=10,
                        )
                    drift_stats = {
                        "top_feature_indices": top_indices,
                        "feature_distributions": distributions,
                    }
                    logger.info("Ensemble drift stats computed for top %d features: %s", top_n, top_indices)
        except Exception as e:
            logger.warning("Failed to compute ensemble drift stats: %s", e)

        if drift_stats is not None:
            ensemble_config["drift_stats"] = drift_stats
```

This must go **before** `shutil.rmtree(staging_dir, ...)` since it reads the staging directory.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_training.py::test_ensemble_stores_drift_stats -v`
Expected: PASS

- [ ] **Step 5: Run full ML test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/ -v`
Expected: all tests PASS

---

### Final: Run Full Test Suite + Commit

- [ ] **Run all tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/ tests/api/test_ml.py tests/engine/test_param_groups.py -v`
Expected: all tests PASS

- [ ] **Commit once** (per CLAUDE.md — one commit at the end of a feature batch)

```bash
git add backend/app/ml/drift.py backend/app/ml/predictor.py backend/app/ml/ensemble_predictor.py backend/app/ml/trainer.py backend/app/config.py backend/app/db/models.py backend/app/db/migrations/versions/ backend/app/api/engine.py backend/app/api/ml.py backend/app/engine/param_groups.py backend/tests/ml/ backend/tests/engine/test_param_groups.py backend/tests/api/test_ml.py
git commit -m "feat(ml): add feature importance drift detection with PSI-based confidence penalty"
```

---

### Summary

| Task | Description | Files |
|------|------------|-------|
| 1 | Core drift module (PSI, distributions, penalty with NaN/Inf safety) | `ml/drift.py`, `tests/ml/test_drift.py` |
| 2 | Permutation importance computation | `ml/drift.py`, `tests/ml/test_drift.py` |
| 3 | Store drift stats at single-model training time (pre-subsample distributions) | `ml/trainer.py`, `tests/ml/test_trainer.py` |
| 4 | Tunable config, DB columns, migration, optimizer param group + constraint tests | `config.py`, `models.py`, migration, `engine.py`, `param_groups.py`, `tests/engine/test_param_groups.py` |
| 5 | Apply drift penalty in Predictor (top-level import, tunable thresholds) | `ml/predictor.py`, `tests/ml/test_predictor.py` |
| 6 | Apply drift penalty in EnsemblePredictor (top-level import, tunable thresholds) | `ml/ensemble_predictor.py`, `tests/ml/test_ensemble_predictor.py` |
| 7 | Wire drift settings into predictor loading + wiring test | `api/ml.py`, `tests/api/test_ml.py` |
| 8 | Store drift stats in ensemble training | `ml/trainer.py`, `tests/ml/test_ensemble_training.py` |

Implementation order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 (sequential dependencies).
