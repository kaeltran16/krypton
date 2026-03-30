# Deep Ensemble + Regime Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace MC dropout uncertainty with a 3-member deep ensemble and replace heuristic regime detection with a learned LightGBM classifier.

**Architecture:** Train 3 `SignalLSTM` instances per pair on overlapping temporal splits; aggregate predictions with staleness-weighted disagreement. Train a global LightGBM 4-class regime classifier on retrospective labels from all pairs. Both integrate as drop-in replacements for existing interfaces (`Predictor.predict()` and `compute_regime_mix()`).

**Tech Stack:** PyTorch (ensemble), LightGBM (regime), FastAPI (API endpoints), React/Tailwind (health UI)

**Note on commits:** Per CLAUDE.md, do NOT commit after each task. The per-task commit steps below are logical checkpoints only. Commit once at the end when all tasks are complete.

---

## File Structure

**New files:**
| File | Responsibility |
|------|---------------|
| `backend/app/ml/ensemble_predictor.py` | `EnsemblePredictor` class — loads N members, weighted inference, disagreement |
| `backend/app/engine/regime_labels.py` | Retrospective 4-class regime label generation from candle data |
| `backend/app/engine/regime_classifier.py` | LightGBM wrapper — train, predict, load/save, staleness check |
| `backend/tests/ml/test_ensemble_predictor.py` | EnsemblePredictor unit tests |
| `backend/tests/ml/test_ensemble_training.py` | `train_ensemble()` unit tests |
| `backend/tests/engine/test_regime_labels.py` | Label generation tests |
| `backend/tests/engine/test_regime_classifier.py` | Regime classifier tests |
| `backend/tests/api/test_ml_health.py` | `/api/ml/health` endpoint test |
| `web/src/features/system/components/MLHealthStatus.tsx` | Ensemble + classifier health rows |

**Modified files:**
| File | Change |
|------|--------|
| `backend/requirements.txt` | Add `lightgbm>=4.0.0`, `joblib` |
| `backend/Dockerfile:11-14` | Add `libgomp1` to apt-get |
| `backend/app/ml/trainer.py` | Extract `train_one_model()`, add `train_ensemble()` |
| `backend/app/api/ml.py:600-627` | Update `_reload_predictors()` for ensemble detection; add `/ml/health` and `/regime/train` |
| `backend/app/api/ml.py:77-349` | Update training endpoint to call `train_ensemble()` |
| `backend/app/engine/regime.py:23-42` | Integrate classifier into `compute_regime_mix()` |
| `backend/app/main.py:143-189` | Add `ensemble_disagreement` to `_build_raw_indicators()` |
| `backend/app/main.py:1830-1834` | Init `regime_classifier` on app.state |
| `backend/app/db/models.py:207-274` | Add `ensemble_disagreement_scale` to PipelineSettings |
| `backend/app/config.py` | Add `ensemble_disagreement_scale` default |
| `web/src/shared/lib/api.ts` | Add `getMLHealth()` |
| `web/src/features/system/types.ts` | Add `MLHealthResponse` type |
| `web/src/features/system/components/SystemDiagnostics.tsx:201-219` | Replace ML models row with `MLHealthStatus` |

---

### Task 1: Dependencies and Config

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/Dockerfile:11-14`
- Modify: `backend/app/db/models.py:265-267`
- Modify: `backend/app/config.py`

- [ ] **Step 1: Add lightgbm to requirements.txt**

Add after the `scikit-optimize>=0.10` line:

```
lightgbm>=4.0.0
joblib
```

- [ ] **Step 2: Add libgomp1 to Dockerfile**

In `backend/Dockerfile`, change the apt-get line from:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    redis-tools \
  && rm -rf /var/lib/apt/lists/*
```

to:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    redis-tools \
    libgomp1 \
  && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 3: Add ensemble_disagreement_scale to PipelineSettings**

In `backend/app/db/models.py`, after the `ew_ic_lookback_days` field (line 267), add:

```python
    ensemble_disagreement_scale: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 4: Add default in config.py**

In `backend/app/config.py`, after the existing ML config fields, add:

```python
    ensemble_disagreement_scale: float = 8.0
```

- [ ] **Step 5: Create Alembic migration**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add ensemble_disagreement_scale to pipeline_settings"
```

- [ ] **Step 6: Apply migration**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head
```

- [ ] **Step 7: Rebuild Docker image**

Run:
```bash
cd backend && docker compose build api
```

- [ ] **Step 8: Verify lightgbm imports**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python3 -c "import lightgbm; import joblib; print('OK', lightgbm.__version__)"
```
Expected: `OK 4.x.x`

- [ ] **Step 9: Commit**

```bash
git add backend/requirements.txt backend/Dockerfile backend/app/db/models.py backend/app/config.py backend/alembic/versions/
git commit -m "feat(deps): add lightgbm, libgomp1, ensemble_disagreement_scale config"
```

---

### Task 2: Trainer Refactor — Extract `train_one_model()`

**Files:**
- Modify: `backend/app/ml/trainer.py:48-399`
- Test: `backend/tests/ml/test_trainer.py` (existing — verify no regression)

The current `Trainer.train()` is a 350-line method. We extract the core logic into `train_one_model()` so `train_ensemble()` can call it per member.

- [ ] **Step 1: Write test for train_one_model**

Create `backend/tests/ml/test_ensemble_training.py`:

```python
"""Tests for ensemble training pipeline."""

import os
import shutil
import tempfile

import numpy as np
import pytest

from app.ml.trainer import TrainConfig, Trainer


@pytest.fixture
def tmp_checkpoint():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def synthetic_data():
    """Generate synthetic training data (200 samples, 15 features)."""
    rng = np.random.default_rng(42)
    n = 200
    features = rng.standard_normal((n, 15)).astype(np.float32)
    direction = rng.integers(0, 3, size=n).astype(np.int64)
    sl = rng.uniform(0.5, 2.0, size=n).astype(np.float32)
    tp1 = rng.uniform(1.0, 3.0, size=n).astype(np.float32)
    tp2 = rng.uniform(2.0, 5.0, size=n).astype(np.float32)
    return features, direction, sl, tp1, tp2


def test_train_one_model_returns_result(tmp_checkpoint, synthetic_data):
    features, direction, sl, tp1, tp2 = synthetic_data
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    result = trainer.train_one_model(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    assert "best_val_loss" in result
    assert "direction_accuracy" in result
    assert os.path.isfile(os.path.join(tmp_checkpoint, "best_model.pt"))
    assert os.path.isfile(os.path.join(tmp_checkpoint, "model_config.json"))


def test_train_one_model_matches_old_train(tmp_checkpoint, synthetic_data):
    """train_one_model is a drop-in for the old train() method."""
    features, direction, sl, tp1, tp2 = synthetic_data
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    result = trainer.train_one_model(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    assert "train_loss" in result
    assert "val_loss" in result
    assert "version" in result
    assert "precision_per_class" in result
    assert "recall_per_class" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_training.py::test_train_one_model_returns_result -v
```
Expected: FAIL with `AttributeError: 'Trainer' object has no attribute 'train_one_model'`

- [ ] **Step 3: Extract train_one_model from train**

In `backend/app/ml/trainer.py`, rename `train` to `train_one_model` and create a thin `train` wrapper that calls it. The key change is renaming and adding `train` as an alias:

Replace the method signature at line 48:

```python
    def train(
        self,
        features: np.ndarray,
        direction: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        progress_callback: callable | None = None,
        feature_names: list[str] | None = None,
    ) -> dict:
        """Run full training loop.

        Returns dict with train_loss, val_loss, best_epoch.
        """
```

with:

```python
    def train_one_model(
        self,
        features: np.ndarray,
        direction: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        progress_callback: callable | None = None,
        feature_names: list[str] | None = None,
    ) -> dict:
        """Train a single SignalLSTM model.

        Returns dict with train_loss, val_loss, best_epoch, direction_accuracy,
        precision_per_class, recall_per_class, version.
        """
```

Then at the end of the class (after `train_one_model`), add:

```python
    def train(
        self,
        features: np.ndarray,
        direction: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        progress_callback: callable | None = None,
        feature_names: list[str] | None = None,
    ) -> dict:
        """Backward-compatible wrapper for train_one_model."""
        return self.train_one_model(
            features, direction, sl_atr, tp1_atr, tp2_atr,
            progress_callback, feature_names,
        )
```

- [ ] **Step 4: Run new test + existing tests**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_training.py tests/ml/test_trainer.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ml/trainer.py backend/tests/ml/test_ensemble_training.py
git commit -m "refactor(ml): extract train_one_model from Trainer.train"
```

---

### Task 3: Ensemble Training — `train_ensemble()`

**Files:**
- Modify: `backend/app/ml/trainer.py`
- Test: `backend/tests/ml/test_ensemble_training.py`

- [ ] **Step 1: Write failing tests for train_ensemble**

Append to `backend/tests/ml/test_ensemble_training.py`:

```python
import json


def test_train_ensemble_produces_3_members(tmp_checkpoint, synthetic_data):
    features, direction, sl, tp1, tp2 = synthetic_data
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    result = trainer.train_ensemble(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    assert len(result["members"]) == 3
    for m in result["members"]:
        assert "val_loss" in m
        assert "data_range" in m
        assert "temperature" in m

    # Check checkpoint files
    assert os.path.isfile(os.path.join(tmp_checkpoint, "ensemble_config.json"))
    for i in range(3):
        assert os.path.isfile(os.path.join(tmp_checkpoint, f"ensemble_{i}.pt"))


def test_train_ensemble_config_json(tmp_checkpoint, synthetic_data):
    features, direction, sl, tp1, tp2 = synthetic_data
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    trainer.train_ensemble(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    with open(os.path.join(tmp_checkpoint, "ensemble_config.json")) as f:
        config = json.load(f)
    assert config["n_members"] == 3
    assert config["input_size"] == 15
    assert config["seq_len"] == 10
    assert len(config["members"]) == 3
    assert config["members"][0]["data_range"] == [0.0, 0.8]
    assert config["members"][1]["data_range"] == [0.1, 0.9]
    assert config["members"][2]["data_range"] == [0.2, 1.0]


def test_train_ensemble_skips_member_with_insufficient_data(tmp_checkpoint):
    """With very few samples, some slices may be too small."""
    rng = np.random.default_rng(42)
    n = 30  # very small dataset
    features = rng.standard_normal((n, 15)).astype(np.float32)
    direction = rng.integers(0, 3, size=n).astype(np.int64)
    sl = rng.uniform(0.5, 2.0, size=n).astype(np.float32)
    tp1 = rng.uniform(1.0, 3.0, size=n).astype(np.float32)
    tp2 = rng.uniform(2.0, 5.0, size=n).astype(np.float32)
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    result = trainer.train_ensemble(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    # Should produce at least 2 members (or fall back)
    assert len(result["members"]) >= 2


def test_train_ensemble_staging_dir_cleaned_up(tmp_checkpoint, synthetic_data):
    """Staging directory should not exist after successful training."""
    features, direction, sl, tp1, tp2 = synthetic_data
    cfg = TrainConfig(epochs=3, checkpoint_dir=tmp_checkpoint, seq_len=10, patience=5)
    trainer = Trainer(cfg)
    trainer.train_ensemble(
        features, direction, sl, tp1, tp2,
        feature_names=[f"f{i}" for i in range(15)],
    )
    staging = os.path.join(tmp_checkpoint, ".ensemble_staging")
    assert not os.path.exists(staging)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_training.py::test_train_ensemble_produces_3_members -v
```
Expected: FAIL with `AttributeError: 'Trainer' object has no attribute 'train_ensemble'`

- [ ] **Step 3: Implement train_ensemble**

Add to `backend/app/ml/trainer.py`, after `train_one_model` and before the `train` wrapper.

First, add a module-level constant **above** the `Trainer` class:

```python
# Temporal split boundaries for 3-member ensemble
_ENSEMBLE_SPLITS = [
    (0.0, 0.8),
    (0.1, 0.9),
    (0.2, 1.0),
]
```

Then add the method inside the `Trainer` class:

```python
    def train_ensemble(
        self,
        features: np.ndarray,
        direction: np.ndarray,
        sl_atr: np.ndarray,
        tp1_atr: np.ndarray,
        tp2_atr: np.ndarray,
        progress_callback: callable | None = None,
        feature_names: list[str] | None = None,
    ) -> dict:
        """Train a 3-member ensemble on overlapping temporal splits.

        Members are trained in parallel via ThreadPoolExecutor for ~3x speedup.
        Members whose slice yields fewer than seq_len * 2 samples are skipped.
        Falls back to single-model training if fewer than 2 members are viable.

        Returns dict with 'members' list and 'n_members'.
        """
        import json as _json
        import shutil
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from datetime import datetime as _dt, timezone as _tz

        cfg = self.config
        n = len(features)
        min_per_slice = cfg.seq_len * 2

        if feature_names is None:
            feature_names = [f"feature_{i}" for i in range(features.shape[1])]

        staging_dir = os.path.join(cfg.checkpoint_dir, ".ensemble_staging")
        os.makedirs(staging_dir, exist_ok=True)

        def _train_member(idx, start_frac, end_frac):
            """Train a single ensemble member on its temporal slice."""
            s = int(n * start_frac)
            e = int(n * end_frac)
            sl_feat = features[s:e]
            sl_dir = direction[s:e]
            sl_sl = sl_atr[s:e]
            sl_tp1 = tp1_atr[s:e]
            sl_tp2 = tp2_atr[s:e]

            if len(sl_feat) < min_per_slice:
                logger.warning(
                    "Ensemble member %d: only %d samples (need %d), skipping",
                    idx, len(sl_feat), min_per_slice,
                )
                return None

            member_dir = os.path.join(staging_dir, f"member_{idx}")
            os.makedirs(member_dir, exist_ok=True)

            member_cfg = TrainConfig(
                epochs=cfg.epochs,
                batch_size=cfg.batch_size,
                seq_len=cfg.seq_len,
                hidden_size=cfg.hidden_size,
                num_layers=cfg.num_layers,
                dropout=cfg.dropout,
                lr=cfg.lr,
                weight_decay=cfg.weight_decay,
                reg_loss_weight=cfg.reg_loss_weight,
                val_ratio=cfg.val_ratio,
                patience=cfg.patience,
                warmup_epochs=cfg.warmup_epochs,
                noise_std=cfg.noise_std,
                label_smoothing=cfg.label_smoothing,
                checkpoint_dir=member_dir,
                neutral_subsample_ratio=cfg.neutral_subsample_ratio,
            )
            member_trainer = Trainer(member_cfg)
            try:
                result = member_trainer.train_one_model(
                    sl_feat, sl_dir, sl_sl, sl_tp1, sl_tp2,
                    progress_callback=progress_callback,
                    feature_names=feature_names,
                )
            except ValueError as e:
                logger.warning("Ensemble member %d failed: %s", idx, e)
                return None

            # Read temperature from saved config
            config_path = os.path.join(member_dir, "model_config.json")
            with open(config_path) as f:
                saved_config = _json.load(f)

            return {
                "index": idx,
                "trained_at": _dt.now(_tz.utc).isoformat(),
                "val_loss": result["best_val_loss"],
                "temperature": saved_config.get("temperature", 1.0),
                "data_range": [start_frac, end_frac],
                "direction_accuracy": result.get("direction_accuracy", 0.0),
                "precision_per_class": result.get("precision_per_class"),
                "recall_per_class": result.get("recall_per_class"),
            }

        # Train all members in parallel
        members = []
        with ThreadPoolExecutor(max_workers=len(_ENSEMBLE_SPLITS)) as pool:
            futures = {
                pool.submit(_train_member, idx, s, e): idx
                for idx, (s, e) in enumerate(_ENSEMBLE_SPLITS)
            }
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    members.append(result)

        # Sort by index so checkpoint naming is deterministic
        members.sort(key=lambda m: m["index"])

        if len(members) < 2:
            logger.warning(
                "Only %d ensemble members viable, falling back to single-model training",
                len(members),
            )
            shutil.rmtree(staging_dir, ignore_errors=True)
            result = self.train_one_model(
                features, direction, sl_atr, tp1_atr, tp2_atr,
                progress_callback, feature_names,
            )
            return {"members": [], "n_members": 0, "fallback": result}

        # Move member checkpoints to final location with canonical names.
        # Write .pt files first, ensemble_config.json LAST — this is the
        # detection file that _reload_predictors() checks, so it must only
        # appear after all .pt files are in place.
        for m in members:
            idx = m["index"]
            src_pt = os.path.join(staging_dir, f"member_{idx}", "best_model.pt")
            dst_pt = os.path.join(cfg.checkpoint_dir, f"ensemble_{idx}.pt")
            shutil.copy2(src_pt, dst_pt)

        # Write ensemble_config.json LAST for atomic visibility
        input_size = features.shape[1]
        ensemble_config = {
            "n_members": len(members),
            "input_size": input_size,
            "hidden_size": cfg.hidden_size,
            "num_layers": cfg.num_layers,
            "dropout": cfg.dropout,
            "seq_len": cfg.seq_len,
            "feature_names": feature_names,
            "members": members,
        }
        with open(os.path.join(cfg.checkpoint_dir, "ensemble_config.json"), "w") as f:
            _json.dump(ensemble_config, f, indent=2)

        # Clean up staging
        shutil.rmtree(staging_dir, ignore_errors=True)

        return {"members": members, "n_members": len(members)}
```

- [ ] **Step 4: Run all ensemble tests**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_training.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Run existing trainer tests for regression**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_trainer.py -v
```
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/ml/trainer.py backend/tests/ml/test_ensemble_training.py
git commit -m "feat(ml): add train_ensemble for 3-member temporal split training"
```

---

### Task 4: EnsemblePredictor

**Files:**
- Create: `backend/app/ml/ensemble_predictor.py`
- Create: `backend/tests/ml/test_ensemble_predictor.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/ml/test_ensemble_predictor.py`:

```python
"""Tests for EnsemblePredictor inference."""

import json
import os
import shutil
import tempfile

import numpy as np
import pytest
import torch

from app.ml.model import SignalLSTM
from app.ml.ensemble_predictor import EnsemblePredictor


@pytest.fixture
def ensemble_checkpoint():
    """Create a temporary ensemble checkpoint with 3 members."""
    d = tempfile.mkdtemp()
    input_size = 15
    hidden_size = 32
    num_layers = 1
    seq_len = 10

    members = []
    for i in range(3):
        model = SignalLSTM(input_size=input_size, hidden_size=hidden_size,
                           num_layers=num_layers, dropout=0.0)
        torch.save(model.state_dict(), os.path.join(d, f"ensemble_{i}.pt"))
        members.append({
            "index": i,
            "trained_at": "2026-03-31T12:00:00",
            "val_loss": 0.4,
            "temperature": 1.0,
            "data_range": [[0.0, 0.8], [0.1, 0.9], [0.2, 1.0]][i],
        })

    config = {
        "n_members": 3,
        "input_size": input_size,
        "hidden_size": hidden_size,
        "num_layers": num_layers,
        "dropout": 0.0,
        "seq_len": seq_len,
        "feature_names": [f"f{j}" for j in range(input_size)],
        "members": members,
    }
    with open(os.path.join(d, "ensemble_config.json"), "w") as f:
        json.dump(config, f)

    yield d
    shutil.rmtree(d)


def test_loads_all_members(ensemble_checkpoint):
    pred = EnsemblePredictor(ensemble_checkpoint)
    assert pred.n_members == 3


def test_predict_returns_expected_keys(ensemble_checkpoint):
    pred = EnsemblePredictor(ensemble_checkpoint)
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")
    assert 0.0 <= result["confidence"] <= 1.0
    assert "ensemble_disagreement" in result
    assert "sl_atr" in result
    assert "tp1_atr" in result
    assert "tp2_atr" in result


def test_predict_too_few_candles_returns_neutral(ensemble_checkpoint):
    pred = EnsemblePredictor(ensemble_checkpoint)
    features = np.random.randn(5, 15).astype(np.float32)  # less than seq_len=10
    result = pred.predict(features)
    assert result["direction"] == "NEUTRAL"
    assert result["confidence"] == 0.0


def test_disagreement_is_nonnegative(ensemble_checkpoint):
    pred = EnsemblePredictor(ensemble_checkpoint)
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    assert result["ensemble_disagreement"] >= 0.0


def test_partial_load_2_members(ensemble_checkpoint):
    """Remove one member checkpoint — should still work with 2."""
    os.remove(os.path.join(ensemble_checkpoint, "ensemble_2.pt"))
    # Update config to reflect 2 members
    with open(os.path.join(ensemble_checkpoint, "ensemble_config.json")) as f:
        config = json.load(f)
    config["members"] = config["members"][:2]
    config["n_members"] = 2
    with open(os.path.join(ensemble_checkpoint, "ensemble_config.json"), "w") as f:
        json.dump(config, f)

    pred = EnsemblePredictor(ensemble_checkpoint)
    assert pred.n_members == 2
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    # Confidence capped at 0.5 for 2-member ensemble
    assert result["confidence"] <= 0.5


def test_feature_mapping(ensemble_checkpoint):
    pred = EnsemblePredictor(ensemble_checkpoint)
    # Provide features in different order
    pred.set_available_features([f"f{14 - j}" for j in range(15)])
    features = np.random.randn(20, 15).astype(np.float32)
    result = pred.predict(features)
    assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")


def test_interface_matches_predictor(ensemble_checkpoint):
    """EnsemblePredictor has same public interface as Predictor."""
    pred = EnsemblePredictor(ensemble_checkpoint)
    assert hasattr(pred, "predict")
    assert hasattr(pred, "set_available_features")
    assert hasattr(pred, "flow_used")
    assert hasattr(pred, "regime_used")
    assert hasattr(pred, "btc_used")
    assert hasattr(pred, "seq_len")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_predictor.py::test_loads_all_members -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ml.ensemble_predictor'`

- [ ] **Step 3: Implement EnsemblePredictor**

Create `backend/app/ml/ensemble_predictor.py`:

```python
"""Ensemble inference for multiple SignalLSTM members."""

import json
import logging
import os
import time

import numpy as np
import torch

from app.ml.model import SignalLSTM

logger = logging.getLogger(__name__)

DIRECTION_MAP = {0: "NEUTRAL", 1: "LONG", 2: "SHORT"}

_NEUTRAL_RESULT = {
    "direction": "NEUTRAL",
    "confidence": 0.0,
    "sl_atr": 0.0,
    "tp1_atr": 0.0,
    "tp2_atr": 0.0,
    "ensemble_disagreement": 0.0,
}


def _model_weight(age_days: float) -> float:
    """Staleness decay for an ensemble member."""
    if age_days <= 7:
        return 1.0
    elif age_days <= 21:
        return 1.0 - (age_days - 7) / 14 * 0.7
    else:
        return 0.3


class EnsemblePredictor:
    """Loads N ensemble members and runs weighted inference."""

    def __init__(
        self,
        checkpoint_dir: str,
        ensemble_disagreement_scale: float = 8.0,
    ):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._disagreement_scale = ensemble_disagreement_scale

        config_path = os.path.join(checkpoint_dir, "ensemble_config.json")
        with open(config_path) as f:
            config = json.load(f)

        self.seq_len = config["seq_len"]
        self.input_size = config["input_size"]
        self._expected_features = config.get("feature_names", [])
        self.flow_used = config.get("flow_used", False)
        self.regime_used = config.get("regime_used", False)
        self.btc_used = config.get("btc_used", False)

        self._feature_map = None
        self._available_features = None
        self._out_idx = None
        self._in_idx = None

        # Load member models
        self._models = []
        self._temperatures = []
        self._weights = []
        self._member_ages_days = []
        now = time.time()

        for member_info in config["members"]:
            idx = member_info["index"]
            pt_path = os.path.join(checkpoint_dir, f"ensemble_{idx}.pt")
            if not os.path.isfile(pt_path):
                logger.warning("Ensemble member %d checkpoint missing: %s", idx, pt_path)
                continue
            try:
                model = SignalLSTM(
                    input_size=config["input_size"],
                    hidden_size=config["hidden_size"],
                    num_layers=config["num_layers"],
                    dropout=config.get("dropout", 0.0),
                ).to(self.device)
                state_dict = torch.load(pt_path, map_location=self.device, weights_only=True)
                model.load_state_dict(state_dict)
                model.eval()

                age_days = (now - os.path.getmtime(pt_path)) / 86400
                weight = _model_weight(age_days)

                self._models.append(model)
                self._temperatures.append(member_info.get("temperature", 1.0))
                self._weights.append(weight)
                self._member_ages_days.append(age_days)
            except Exception as e:
                logger.error("Failed to load ensemble member %d: %s", idx, e)

        self.n_members = len(self._models)
        if self.n_members == 0:
            logger.error("No ensemble members loaded from %s", checkpoint_dir)

    def set_available_features(self, names: list[str]):
        """Set feature names available at inference time."""
        self._available_features = names
        expected = self._expected_features
        if not expected:
            self._feature_map = None
            return

        available_idx = {name: i for i, name in enumerate(names)}
        raw_map = []
        missing = []
        for name in expected:
            idx = available_idx.get(name, -1)
            raw_map.append(idx)
            if idx == -1:
                missing.append(name)

        if missing:
            logger.warning("Missing features for ensemble (filled with 0): %s", missing)

        out_idx = np.array([i for i, c in enumerate(raw_map) if c >= 0], dtype=np.intp)
        in_idx = np.array([c for c in raw_map if c >= 0], dtype=np.intp)
        valid = out_idx < self.input_size
        self._out_idx = out_idx[valid]
        self._in_idx = in_idx[valid]
        self._feature_map = raw_map

    def _map_features(self, features: np.ndarray) -> np.ndarray:
        if self._feature_map is None:
            if features.shape[1] > self.input_size:
                return features[:, :self.input_size]
            return features

        n_rows = features.shape[0]
        mapped = np.zeros((n_rows, self.input_size), dtype=np.float32)
        mapped[:, self._out_idx] = features[:, self._in_idx]
        return mapped

    def predict(self, features: np.ndarray) -> dict:
        """Run ensemble inference.

        Returns dict matching Predictor.predict() interface plus ensemble_disagreement.
        """
        if self.n_members == 0 or len(features) < self.seq_len:
            return dict(_NEUTRAL_RESULT)

        features = self._map_features(features)
        window = features[-self.seq_len:]
        x = torch.tensor(window, dtype=torch.float32).unsqueeze(0).to(self.device)

        all_probs = []
        all_regs = []
        for model, temperature in zip(self._models, self._temperatures):
            with torch.no_grad():
                dir_logits, reg_out = model(x)
                probs = torch.softmax(dir_logits / temperature, dim=1).squeeze(0).cpu().numpy()
                all_probs.append(probs)
                all_regs.append(reg_out.squeeze(0).cpu().numpy())

        all_probs = np.array(all_probs)
        all_regs = np.array(all_regs)
        weights = np.array(self._weights)
        weights = weights / weights.sum()

        # Weighted mean
        mean_probs = np.average(all_probs, axis=0, weights=weights)
        mean_reg = np.average(all_regs, axis=0, weights=weights)

        # Weighted disagreement
        diff = all_probs - mean_probs[None, :]
        disagreement = float(np.average((diff ** 2).mean(axis=1), weights=weights))

        direction_idx = int(np.argmax(mean_probs))
        raw_confidence = float(mean_probs[direction_idx])

        uncertainty_penalty = min(1.0, disagreement * self._disagreement_scale)
        confidence = raw_confidence * (1.0 - uncertainty_penalty)

        # Cap confidence for partial ensembles
        if self.n_members == 2:
            confidence = min(confidence, 0.5)

        return {
            "direction": DIRECTION_MAP[direction_idx],
            "confidence": confidence,
            "sl_atr": float(mean_reg[0]),
            "tp1_atr": float(mean_reg[1]),
            "tp2_atr": float(mean_reg[2]),
            "ensemble_disagreement": disagreement,
        }
```

- [ ] **Step 4: Run all tests**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_predictor.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/ml/ensemble_predictor.py backend/tests/ml/test_ensemble_predictor.py
git commit -m "feat(ml): add EnsemblePredictor with weighted disagreement inference"
```

---

### Task 5: Ensemble Loading — Update `_reload_predictors()`

**Files:**
- Modify: `backend/app/api/ml.py:600-627`
- Modify: `backend/app/api/ml.py:77-349` (training endpoint)
- Modify: `backend/app/main.py:143-189` (raw_indicators)
- Modify: `backend/app/main.py:1830-1834` (app startup)

- [ ] **Step 1: Update _reload_predictors to detect ensembles**

In `backend/app/api/ml.py`, replace `_reload_predictors` (lines 600-627) with:

```python
def _reload_predictors(app, settings):
    """Reload per-pair ML predictors from checkpoints."""
    import os
    from app.ml.predictor import Predictor
    from app.ml.ensemble_predictor import EnsemblePredictor
    from app.ml.features import get_feature_names

    predictors = {}
    checkpoint_dir = getattr(settings, "ml_checkpoint_dir", "models")
    if not os.path.isdir(checkpoint_dir):
        return
    disagreement_scale = getattr(settings, "ensemble_disagreement_scale", 8.0)

    for entry in os.listdir(checkpoint_dir):
        pair_dir = os.path.join(checkpoint_dir, entry)
        if not os.path.isdir(pair_dir):
            continue

        ensemble_config = os.path.join(pair_dir, "ensemble_config.json")
        model_path = os.path.join(pair_dir, "best_model.pt")

        try:
            if os.path.isfile(ensemble_config):
                predictor = EnsemblePredictor(
                    pair_dir, ensemble_disagreement_scale=disagreement_scale,
                )
                logger.info(
                    "Ensemble predictor loaded for %s (%d members)",
                    entry, predictor.n_members,
                )
            elif os.path.isfile(model_path):
                predictor = Predictor(model_path)
                logger.info("Legacy predictor loaded for %s", entry)
            else:
                continue

            feature_names = get_feature_names(
                flow_used=predictor.flow_used,
                regime_used=predictor.regime_used,
                btc_used=predictor.btc_used,
            )
            predictor.set_available_features(feature_names)
            predictors[entry] = predictor
        except Exception as e:
            logger.error("Failed to load ML predictor for %s: %s", entry, e)

    app.state.ml_predictors = predictors
```

- [ ] **Step 2: Update training endpoint to call train_ensemble**

In `backend/app/api/ml.py`, in the `_run()` function inside `start_training`, replace the single-model training call (around lines 277-280):

```python
                trainer = Trainer(train_config)
                pair_result = await asyncio.to_thread(
                    trainer.train, features, direction, sl, tp1, tp2, on_progress, train_feature_names,
                )
```

with:

```python
                trainer = Trainer(train_config)
                ensemble_result = await asyncio.to_thread(
                    trainer.train_ensemble, features, direction, sl, tp1, tp2, on_progress, train_feature_names,
                )

                # If ensemble fell back to single model, use fallback result
                if ensemble_result.get("fallback"):
                    pair_result = ensemble_result["fallback"]
                else:
                    # Use best member's metrics as the pair-level summary
                    best_member = min(ensemble_result["members"], key=lambda m: m["val_loss"])
                    pair_result = {
                        "best_val_loss": best_member["val_loss"],
                        "best_epoch": 0,
                        "train_loss": [],
                        "val_loss": [],
                        "version": "",
                        "direction_accuracy": best_member.get("direction_accuracy", 0.0),
                        "precision_per_class": best_member.get("precision_per_class"),
                        "recall_per_class": best_member.get("recall_per_class"),
                        "ensemble_members": ensemble_result["members"],
                    }
```

Also update the config patching block (around lines 284-293) to patch `ensemble_config.json` instead of `model_config.json` when ensemble training succeeded:

```python
                # Patch config with feature flags
                if ensemble_result.get("fallback"):
                    config_path = os.path.join(pair_checkpoint_dir, "model_config.json")
                else:
                    config_path = os.path.join(pair_checkpoint_dir, "ensemble_config.json")
                if os.path.isfile(config_path):
                    import json as _j
                    with open(config_path) as f:
                        meta = _j.load(f)
                    meta["flow_used"] = flow_used
                    meta["regime_used"] = True
                    meta["btc_used"] = btc_used
                    with open(config_path, "w") as f:
                        _j.dump(meta, f, indent=2)
```

- [ ] **Step 3: Add ensemble_disagreement to _build_raw_indicators**

In `backend/app/main.py`, update the `_build_raw_indicators` function signature (line 143) to accept an additional parameter:

```python
def _build_raw_indicators(
    *, tech_result, tech_conf, flow_result, onchain_score, onchain_conf,
    pat_score, pattern_conf, liq_score, liq_conf, liq_clusters, liq_details,
    confluence_score, confluence_conf, ml_score, ml_confidence,
    blended, indicator_preliminary, scaled, levels, outer, snap_info, llm_contribution,
    regime=None, llm_result=None, ensemble_disagreement=None,
) -> dict:
```

And inside the returned dict (after the `"ml_confidence"` line at ~169), add:

```python
        "ensemble_disagreement": ensemble_disagreement,
```

Then update the call site in `run_pipeline` (around line 1203-1212) to pass the new param:

```python
        "raw_indicators": _build_raw_indicators(
            tech_result=tech_result, tech_conf=tech_conf,
            flow_result=flow_result, onchain_score=onchain_score, onchain_conf=onchain_conf,
            pat_score=pat_score, pattern_conf=pattern_conf,
            liq_score=liq_score, liq_conf=liq_conf, liq_clusters=liq_clusters, liq_details=liq_details,
            confluence_score=confluence_score, confluence_conf=confluence_conf,
            ml_score=ml_score, ml_confidence=ml_confidence,
            blended=blended, indicator_preliminary=indicator_preliminary,
            scaled=scaled, levels=levels, outer=outer, snap_info=snap_info,
            llm_contribution=llm_contribution, regime=regime, llm_result=llm_result,
            ensemble_disagreement=ml_prediction.get("ensemble_disagreement") if ml_prediction else None,
        ),
```

- [ ] **Step 4: Run existing tests**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/ml.py backend/app/main.py
git commit -m "feat(ml): ensemble-aware predictor loading and pipeline integration"
```

---

### Task 6: Regime Labels

**Files:**
- Create: `backend/app/engine/regime_labels.py`
- Create: `backend/tests/engine/test_regime_labels.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/engine/test_regime_labels.py`:

```python
"""Tests for retrospective regime label generation."""

import numpy as np
import pandas as pd
import pytest

from app.engine.regime_labels import generate_regime_labels, LABEL_MAP


@pytest.fixture
def trending_candles():
    """Candles with a strong uptrend."""
    n = 200
    rng = np.random.default_rng(42)
    prices = 100 + np.cumsum(rng.uniform(0.2, 0.8, size=n))  # steady upward drift
    df = pd.DataFrame({
        "open": prices - rng.uniform(0.1, 0.3, n),
        "high": prices + rng.uniform(0.3, 1.0, n),
        "low": prices - rng.uniform(0.3, 1.0, n),
        "close": prices,
        "volume": rng.uniform(100, 1000, n),
    })
    return df


@pytest.fixture
def ranging_candles():
    """Candles oscillating in a tight range."""
    n = 200
    rng = np.random.default_rng(42)
    base = 100 + np.sin(np.linspace(0, 10 * np.pi, n)) * 0.5  # tiny oscillation
    df = pd.DataFrame({
        "open": base - 0.1,
        "high": base + rng.uniform(0.1, 0.3, n),
        "low": base - rng.uniform(0.1, 0.3, n),
        "close": base,
        "volume": rng.uniform(100, 1000, n),
    })
    return df


def test_output_shape(trending_candles):
    labels = generate_regime_labels(trending_candles, horizon=48)
    assert len(labels) == len(trending_candles)
    assert set(labels.unique()).issubset({0, 1, 2, 3})


def test_label_map_has_4_classes():
    assert len(LABEL_MAP) == 4
    assert "trending" in LABEL_MAP.values()
    assert "ranging" in LABEL_MAP.values()
    assert "volatile" in LABEL_MAP.values()
    assert "steady" in LABEL_MAP.values()


def test_last_horizon_candles_are_ranging(trending_candles):
    """Last horizon candles can't look forward — default to ranging."""
    labels = generate_regime_labels(trending_candles, horizon=48)
    # Last 48 candles should be labeled ranging (default) since no forward data
    assert all(labels.iloc[-48:] == 3)  # ranging=3


def test_trending_data_produces_trending_labels(trending_candles):
    labels = generate_regime_labels(trending_candles, horizon=48)
    lookable = labels.iloc[:-48]
    trending_pct = (lookable == 0).mean()  # trending=0
    assert trending_pct > 0.3, f"Expected >30% trending labels, got {trending_pct:.1%}"


def test_ranging_data_produces_ranging_labels(ranging_candles):
    labels = generate_regime_labels(ranging_candles, horizon=48)
    lookable = labels.iloc[:-48]
    ranging_pct = (lookable == 3).mean()  # ranging=3
    assert ranging_pct > 0.3, f"Expected >30% ranging labels, got {ranging_pct:.1%}"


def test_minimum_data_returns_all_default():
    """With fewer candles than horizon, all labels should be default."""
    df = pd.DataFrame({
        "open": [100] * 10,
        "high": [101] * 10,
        "low": [99] * 10,
        "close": [100] * 10,
        "volume": [500] * 10,
    })
    labels = generate_regime_labels(df, horizon=48)
    assert len(labels) == 10
    assert all(labels == 3)  # all ranging (default)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime_labels.py::test_output_shape -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement regime_labels.py**

Create `backend/app/engine/regime_labels.py`:

```python
"""Retrospective regime label generation for classifier training."""

import numpy as np
import pandas as pd

# Class mapping: int → name (must match REGIMES in regime.py)
LABEL_MAP = {0: "trending", 1: "steady", 2: "volatile", 3: "ranging"}
NAME_TO_LABEL = {v: k for k, v in LABEL_MAP.items()}
DEFAULT_LABEL = NAME_TO_LABEL["ranging"]


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def generate_regime_labels(
    df: pd.DataFrame,
    horizon: int = 48,
) -> pd.Series:
    """Generate regime labels by looking forward `horizon` candles.

    For each candle, classifies the forward window as:
    - trending: directional move > 2x ATR with expanding or stable vol
    - steady: directional move > 1.5x ATR with contracting vol
    - volatile: ATR expands > 1.5x without sustained direction (> 1.5x ATR)
    - ranging: none of the above

    Args:
        df: OHLCV DataFrame.
        horizon: Number of candles to look forward.

    Returns:
        pd.Series of integer labels (0=trending, 1=steady, 2=volatile, 3=ranging).
    """
    n = len(df)
    labels = np.full(n, DEFAULT_LABEL, dtype=np.int64)

    if n <= horizon:
        return pd.Series(labels, index=df.index)

    atr = _compute_atr(df).values
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    for i in range(n - horizon):
        window_close = close[i:i + horizon]
        window_high = high[i:i + horizon]
        window_low = low[i:i + horizon]
        current_atr = atr[i]
        if current_atr <= 0:
            continue

        # Directional move: net close change
        net_move = abs(window_close[-1] - window_close[0])
        # Max drawdown from start in both directions
        max_up = window_high.max() - window_close[0]
        max_down = window_close[0] - window_low.min()

        # ATR expansion: compare window ATR to current
        window_tr = np.maximum(
            window_high - window_low,
            np.maximum(
                np.abs(window_high - np.roll(window_close, 1)),
                np.abs(window_low - np.roll(window_close, 1)),
            ),
        )
        window_tr[0] = window_high[0] - window_low[0]
        window_atr = window_tr.mean()
        atr_expansion = window_atr / current_atr

        is_directional = net_move > 1.5 * current_atr
        is_strongly_directional = net_move > 2.0 * current_atr
        vol_expanding = atr_expansion > 1.1
        vol_contracting = atr_expansion < 0.9

        if is_strongly_directional and not vol_contracting:
            labels[i] = NAME_TO_LABEL["trending"]
        elif is_directional and vol_contracting:
            labels[i] = NAME_TO_LABEL["steady"]
        elif atr_expansion > 1.5 and not is_directional:
            labels[i] = NAME_TO_LABEL["volatile"]
        # else: ranging (default)

    return pd.Series(labels, index=df.index)
```

- [ ] **Step 4: Run all label tests**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime_labels.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/regime_labels.py backend/tests/engine/test_regime_labels.py
git commit -m "feat(engine): add retrospective 4-class regime label generation"
```

---

### Task 7: Regime Classifier

**Files:**
- Create: `backend/app/engine/regime_classifier.py`
- Create: `backend/tests/engine/test_regime_classifier.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/engine/test_regime_classifier.py`:

```python
"""Tests for LightGBM regime classifier."""

import os
import shutil
import tempfile

import numpy as np
import pytest

from app.engine.regime_classifier import RegimeClassifier


@pytest.fixture
def tmp_model_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def synthetic_regime_data():
    """Generate synthetic features + labels for 4 regimes."""
    rng = np.random.default_rng(42)
    n = 600
    features = rng.standard_normal((n, 11)).astype(np.float32)
    labels = rng.integers(0, 4, size=n).astype(np.int64)
    feature_names = [
        "adx", "adx_delta_5", "adx_delta_10",
        "bb_width", "bb_width_delta_5",
        "atr_pct", "atr_pct_delta_5",
        "volume_trend",
        "funding_rate_change", "oi_change_pct",
        "ensemble_disagreement",
    ]
    return features, labels, feature_names


def test_train_and_predict(tmp_model_dir, synthetic_regime_data):
    features, labels, feature_names = synthetic_regime_data
    clf = RegimeClassifier()
    metrics = clf.train(features, labels, feature_names)
    assert "macro_f1" in metrics
    assert "accuracy" in metrics
    assert metrics["macro_f1"] >= 0.0

    # Predict
    probs = clf.predict_proba(features[:1])
    assert set(probs.keys()) == {"trending", "ranging", "volatile", "steady"}
    assert abs(sum(probs.values()) - 1.0) < 1e-5


def test_save_and_load(tmp_model_dir, synthetic_regime_data):
    features, labels, feature_names = synthetic_regime_data
    clf = RegimeClassifier()
    clf.train(features, labels, feature_names)
    clf.save(tmp_model_dir)

    assert os.path.isfile(os.path.join(tmp_model_dir, "regime_classifier.joblib"))
    assert os.path.isfile(os.path.join(tmp_model_dir, "regime_config.json"))

    loaded = RegimeClassifier.load(tmp_model_dir)
    probs = loaded.predict_proba(features[:1])
    assert set(probs.keys()) == {"trending", "ranging", "volatile", "steady"}


def test_staleness_check(tmp_model_dir, synthetic_regime_data):
    features, labels, feature_names = synthetic_regime_data
    clf = RegimeClassifier()
    clf.train(features, labels, feature_names)
    clf.save(tmp_model_dir)

    loaded = RegimeClassifier.load(tmp_model_dir)
    assert not loaded.is_stale(max_age_days=30)


def test_predict_proba_returns_4_classes(tmp_model_dir, synthetic_regime_data):
    features, labels, feature_names = synthetic_regime_data
    clf = RegimeClassifier()
    clf.train(features, labels, feature_names)
    probs = clf.predict_proba(features[0:1])
    assert len(probs) == 4
    for v in probs.values():
        assert 0.0 <= v <= 1.0


def test_build_features_from_candle_data():
    """Test feature extraction helper."""
    from app.engine.regime_classifier import build_regime_features
    import pandas as pd

    rng = np.random.default_rng(42)
    n = 100
    df = pd.DataFrame({
        "open": rng.uniform(99, 101, n),
        "high": rng.uniform(101, 103, n),
        "low": rng.uniform(97, 99, n),
        "close": rng.uniform(99, 101, n),
        "volume": rng.uniform(100, 1000, n),
    })
    features, names = build_regime_features(df)
    assert features.shape[0] == n
    assert features.shape[1] >= 7  # at least base features
    assert len(names) == features.shape[1]
    # No NaN after warmup
    assert not np.isnan(features[20:]).any()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime_classifier.py::test_train_and_predict -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement regime_classifier.py**

Create `backend/app/engine/regime_classifier.py`:

```python
"""LightGBM regime classifier — train, predict, persistence."""

import json
import logging
import os
import time

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd

from app.engine.regime_labels import LABEL_MAP

logger = logging.getLogger(__name__)

# Reverse map: int → name
_IDX_TO_NAME = dict(LABEL_MAP)
# Regime names in class order
_CLASS_NAMES = [_IDX_TO_NAME[i] for i in range(4)]

MIN_TRAINING_SAMPLES = 500
MIN_MACRO_F1 = 0.65


def build_regime_features(
    df: pd.DataFrame,
    flow: list[dict] | None = None,
    ensemble_disagreement: list[float] | None = None,
) -> tuple[np.ndarray, list[str]]:
    """Build feature matrix for regime classification.

    Args:
        df: OHLCV DataFrame.
        flow: Optional order flow dicts with funding_rate, oi_change_pct.
        ensemble_disagreement: Optional per-candle disagreement values.

    Returns:
        (features array, feature names list)
    """
    n = len(df)
    close = df["close"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)
    volume = df["volume"].values.astype(np.float64)

    # ATR
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().values
    atr_pct = np.where(close > 0, atr / close, 0.0)

    # ADX (simplified: directional movement index)
    up_move = high - np.roll(high, 1)
    down_move = np.roll(low, 1) - low
    up_move[0] = 0
    down_move[0] = 0
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    smoothed_tr = pd.Series(tr).ewm(span=14, adjust=False).mean().values
    smoothed_plus = pd.Series(plus_dm).ewm(span=14, adjust=False).mean().values
    smoothed_minus = pd.Series(minus_dm).ewm(span=14, adjust=False).mean().values
    plus_di = np.where(smoothed_tr > 0, smoothed_plus / smoothed_tr * 100, 0.0)
    minus_di = np.where(smoothed_tr > 0, smoothed_minus / smoothed_tr * 100, 0.0)
    dx = np.where(plus_di + minus_di > 0, np.abs(plus_di - minus_di) / (plus_di + minus_di) * 100, 0.0)
    adx = pd.Series(dx).ewm(span=14, adjust=False).mean().values

    # Bollinger width
    sma20 = pd.Series(close).rolling(20, min_periods=1).mean().values
    std20 = pd.Series(close).rolling(20, min_periods=1).std(ddof=0).values
    bb_width = np.where(sma20 > 0, (2 * std20) / sma20, 0.0)

    # Deltas
    adx_delta_5 = adx - np.roll(adx, 5)
    adx_delta_5[:5] = 0
    adx_delta_10 = adx - np.roll(adx, 10)
    adx_delta_10[:10] = 0
    bb_width_delta_5 = bb_width - np.roll(bb_width, 5)
    bb_width_delta_5[:5] = 0
    atr_pct_delta_5 = atr_pct - np.roll(atr_pct, 5)
    atr_pct_delta_5[:5] = 0

    # OBV slope (volume trend)
    obv = np.cumsum(np.where(np.diff(close, prepend=close[0]) > 0, volume, -volume))
    obv_series = pd.Series(obv)
    vol_trend = np.zeros(n)
    for i in range(10, n):
        y = obv[i - 10:i]
        x = np.arange(10, dtype=np.float64)
        vol_trend[i] = np.polyfit(x, y, 1)[0]
    # Normalize
    vol_std = np.std(vol_trend[10:]) if n > 10 else 1.0
    if vol_std > 0:
        vol_trend = vol_trend / vol_std

    features_list = [adx, adx_delta_5, adx_delta_10, bb_width, bb_width_delta_5,
                     atr_pct, atr_pct_delta_5, vol_trend]
    names = ["adx", "adx_delta_5", "adx_delta_10", "bb_width", "bb_width_delta_5",
             "atr_pct", "atr_pct_delta_5", "volume_trend"]

    # Optional flow features
    if flow and len(flow) == n:
        funding = np.array([f.get("funding_rate", 0.0) or 0.0 for f in flow], dtype=np.float64)
        funding_delta = funding - np.roll(funding, 5)
        funding_delta[:5] = 0
        oi_change = np.array([f.get("oi_change_pct", 0.0) or 0.0 for f in flow], dtype=np.float64)
        features_list.extend([funding_delta, oi_change])
        names.extend(["funding_rate_change", "oi_change_pct"])

    # Optional ensemble disagreement
    if ensemble_disagreement and len(ensemble_disagreement) == n:
        features_list.append(np.array(ensemble_disagreement, dtype=np.float64))
        names.append("ensemble_disagreement")

    result = np.column_stack(features_list).astype(np.float32)
    # Replace NaN with 0
    result = np.nan_to_num(result, nan=0.0)
    return result, names


class RegimeClassifier:
    """LightGBM 4-class regime classifier."""

    def __init__(self):
        self._model = None
        self._feature_names = None
        self._trained_at = None

    def train(
        self,
        features: np.ndarray,
        labels: np.ndarray,
        feature_names: list[str],
    ) -> dict:
        """Train the classifier. Returns metrics dict."""
        from datetime import datetime, timezone

        n = len(features)
        # Holdout split (last 20%)
        split = int(n * 0.8)
        X_train, X_test = features[:split], features[split:]
        y_train, y_test = labels[:split], labels[split:]

        self._model = lgb.LGBMClassifier(
            objective="multiclass",
            num_class=4,
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            verbose=-1,
        )
        self._model.fit(X_train, y_train)
        self._feature_names = feature_names
        self._trained_at = datetime.now(timezone.utc).isoformat()

        # Compute metrics on holdout
        y_pred = self._model.predict(X_test)
        accuracy = float((y_pred == y_test).mean())

        # Per-class precision, recall, F1
        per_class = {}
        f1s = []
        for cls_id, cls_name in _IDX_TO_NAME.items():
            tp = int(((y_pred == cls_id) & (y_test == cls_id)).sum())
            fp = int(((y_pred == cls_id) & (y_test != cls_id)).sum())
            fn = int(((y_pred != cls_id) & (y_test == cls_id)).sum())
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
            per_class[cls_name] = {"precision": prec, "recall": rec, "f1": f1}
            f1s.append(f1)

        macro_f1 = float(np.mean(f1s))

        return {
            "accuracy": accuracy,
            "macro_f1": macro_f1,
            "per_class": per_class,
            "n_train": len(y_train),
            "n_test": len(y_test),
        }

    def _align_features(self, features: np.ndarray, feature_names: list[str] | None) -> np.ndarray:
        """Align input features to match training feature order.

        If the model was trained with 11 features (including flow + disagreement)
        but only 8 base features are available at inference, missing features are
        filled with 0.
        """
        if self._feature_names is None or feature_names is None:
            return features
        if feature_names == self._feature_names:
            return features

        name_to_idx = {n: i for i, n in enumerate(feature_names)}
        row = features[0:1] if features.ndim == 2 else features.reshape(1, -1)
        aligned = np.zeros((1, len(self._feature_names)), dtype=np.float32)
        for i, name in enumerate(self._feature_names):
            src_idx = name_to_idx.get(name, -1)
            if src_idx >= 0 and src_idx < row.shape[1]:
                aligned[0, i] = row[0, src_idx]
        return aligned

    def predict_proba(self, features: np.ndarray, feature_names: list[str] | None = None) -> dict:
        """Predict regime probabilities for a single sample (or first row).

        Args:
            features: Feature array (1D or 2D).
            feature_names: Optional feature names for alignment. If the model
                was trained with more features than provided, missing ones are
                filled with 0.

        Returns dict with trending/ranging/volatile/steady probabilities.
        """
        if self._model is None:
            raise RuntimeError("Classifier not trained or loaded")
        if features.ndim == 1:
            features = features.reshape(1, -1)
        features = self._align_features(features, feature_names)
        probs = self._model.predict_proba(features[0:1])[0]
        return {name: float(probs[i]) for i, name in enumerate(_CLASS_NAMES)}

    def save(self, directory: str):
        """Save model + config to directory."""
        os.makedirs(directory, exist_ok=True)
        joblib.dump(self._model, os.path.join(directory, "regime_classifier.joblib"))

        config = {
            "feature_names": self._feature_names,
            "trained_at": self._trained_at,
            "n_classes": 4,
            "class_names": _CLASS_NAMES,
        }
        with open(os.path.join(directory, "regime_config.json"), "w") as f:
            json.dump(config, f, indent=2)

    @classmethod
    def load(cls, directory: str) -> "RegimeClassifier":
        """Load a saved classifier."""
        obj = cls()
        obj._model = joblib.load(os.path.join(directory, "regime_classifier.joblib"))
        config_path = os.path.join(directory, "regime_config.json")
        with open(config_path) as f:
            config = json.load(f)
        obj._feature_names = config.get("feature_names")
        obj._trained_at = config.get("trained_at")
        return obj

    def is_stale(self, max_age_days: int = 30) -> bool:
        """Check if model is older than max_age_days."""
        from datetime import datetime, timezone
        if not self._trained_at:
            return True
        try:
            trained = datetime.fromisoformat(self._trained_at)
            age = (datetime.now(timezone.utc) - trained).days
            return age > max_age_days
        except (ValueError, TypeError):
            return True
```

- [ ] **Step 4: Run all regime classifier tests**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime_classifier.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/regime_classifier.py backend/tests/engine/test_regime_classifier.py
git commit -m "feat(engine): add LightGBM 4-class regime classifier"
```

---

### Task 8: Regime Integration — Update `compute_regime_mix()`

**Files:**
- Modify: `backend/app/engine/regime.py:23-42`
- Modify: `backend/app/main.py:1830-1834`
- Test: `backend/tests/engine/test_regime.py` (existing — verify no regression)

- [ ] **Step 1: Write test for classifier-backed regime mix**

Create `backend/tests/engine/test_regime_classifier_integration.py`:

```python
"""Test integration of regime classifier with compute_regime_mix."""

import numpy as np
import pytest

from app.engine.regime import compute_regime_mix, REGIMES


def test_compute_regime_mix_without_classifier():
    """Existing heuristic still works when no classifier provided."""
    result = compute_regime_mix(0.8, 0.7)
    assert set(result.keys()) == set(REGIMES)
    assert abs(sum(result.values()) - 1.0) < 1e-6


def test_compute_regime_mix_with_classifier():
    """When classifier provided, its output is used."""
    class MockClassifier:
        def predict_proba(self, features, feature_names=None):
            return {"trending": 0.6, "ranging": 0.2, "volatile": 0.1, "steady": 0.1}
        def is_stale(self, max_age_days=30):
            return False

    result = compute_regime_mix(0.8, 0.7, classifier=MockClassifier(),
                                 classifier_features=np.zeros((1, 11)))
    assert result["trending"] == 0.6
    assert result["ranging"] == 0.2


def test_compute_regime_mix_stale_classifier_uses_heuristic():
    """Stale classifier falls back to heuristic."""
    class StaleClassifier:
        def predict_proba(self, features, feature_names=None):
            return {"trending": 0.9, "ranging": 0.0, "volatile": 0.1, "steady": 0.0}
        def is_stale(self, max_age_days=30):
            return True

    result = compute_regime_mix(0.1, 0.1, classifier=StaleClassifier(),
                                 classifier_features=np.zeros((1, 11)))
    # Should use heuristic (low trend, low vol → ranging dominant)
    assert result["ranging"] > result["trending"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime_classifier_integration.py::test_compute_regime_mix_with_classifier -v
```
Expected: FAIL with `TypeError: compute_regime_mix() got an unexpected keyword argument 'classifier'`

- [ ] **Step 3: Update compute_regime_mix**

In `backend/app/engine/regime.py`, replace the `compute_regime_mix` function (lines 23-42) with:

```python
def compute_regime_mix(
    trend_strength: float,
    vol_expansion: float,
    classifier=None,
    classifier_features=None,
    classifier_feature_names=None,
) -> dict:
    """Compute continuous regime mix from trend strength and volatility expansion.

    If a trained regime classifier is provided and not stale, uses it instead
    of the heuristic. Falls back to heuristic otherwise.

    Args:
        trend_strength: 0-1 from sigmoid_scale(adx, center=20, steepness=0.25)
        vol_expansion: 0-1 from sigmoid_scale(bb_width_pct, center=50, steepness=0.08)
        classifier: Optional RegimeClassifier instance.
        classifier_features: Optional feature array for the classifier.
        classifier_feature_names: Optional feature names for alignment (handles
            cases where available features differ from training features).

    Returns:
        Dict with trending/ranging/volatile/steady weights summing to 1.0.
    """
    if classifier is not None and classifier_features is not None:
        if not classifier.is_stale():
            return classifier.predict_proba(classifier_features, classifier_feature_names)

    # Heuristic fallback
    raw_trending = trend_strength * vol_expansion
    raw_ranging = (1 - trend_strength) * (1 - vol_expansion)
    raw_volatile = (1 - trend_strength) * vol_expansion
    raw_steady = trend_strength * (1 - vol_expansion)
    return {
        "trending": raw_trending,
        "ranging": raw_ranging,
        "volatile": raw_volatile,
        "steady": raw_steady,
    }
```

- [ ] **Step 4: Add regime_classifier to app.state at startup**

In `backend/app/main.py`, after the ML predictor loading block (line 1834), add:

```python
    # Load regime classifier if available
    app.state.regime_classifier = None
    regime_model_dir = os.path.join(
        getattr(settings, "ml_checkpoint_dir", "models"), "regime"
    )
    if os.path.isdir(regime_model_dir):
        try:
            from app.engine.regime_classifier import RegimeClassifier
            clf = RegimeClassifier.load(regime_model_dir)
            if not clf.is_stale():
                app.state.regime_classifier = clf
                logger.info("Regime classifier loaded (not stale)")
            else:
                logger.warning("Regime classifier is stale (>30 days), using heuristic")
        except Exception as e:
            logger.error("Failed to load regime classifier: %s", e)
```

Add `import os` to the top of main.py imports if not already present.

- [ ] **Step 5: Run all regime tests**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime.py tests/engine/test_regime_classifier_integration.py -v
```
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/regime.py backend/app/main.py backend/tests/engine/test_regime_classifier_integration.py
git commit -m "feat(engine): integrate regime classifier into compute_regime_mix"
```

---

### Task 9: API Endpoints — `/api/regime/train` and `/api/ml/health`

**Files:**
- Modify: `backend/app/api/ml.py`
- Create: `backend/tests/api/test_ml_health.py`

- [ ] **Step 1: Write failing tests for /api/ml/health**

Create `backend/tests/api/test_ml_health.py`:

```python
"""Tests for ML health endpoint."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
async def ml_health_app(app):
    """Extend base app fixture with fields needed by ML health endpoint.

    The `app` and `client` fixtures from conftest share the same FastAPI instance,
    so mutations here are visible to `client`.
    """
    mock_predictor = MagicMock()
    mock_predictor.n_members = 3
    mock_predictor._weights = [1.0, 1.0, 0.3]
    mock_predictor._member_ages_days = [2.0, 5.0, 25.0]
    app.state.ml_predictors = {"btc_usdt_swap": mock_predictor}
    app.state.regime_classifier = None
    return app


@pytest.mark.asyncio
async def test_ml_health_returns_structure(ml_health_app, client, auth_cookies):
    resp = await client.get("/api/ml/health", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "ml_health" in data
    assert "ensemble" in data["ml_health"]
    assert "regime_classifier" in data["ml_health"]
    ensemble = data["ml_health"]["ensemble"]
    assert ensemble["pairs_loaded"] == 1
    assert ensemble["members_loaded"] == 3
    assert ensemble["members_stale"] == 1
    assert ensemble["oldest_member_days"] == 25.0
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_ml_health.py -v
```
Expected: FAIL (404 — endpoint doesn't exist)

- [ ] **Step 3: Add /api/ml/health endpoint**

In `backend/app/api/ml.py`, add after the existing `POST /api/ml/reload` endpoint:

```python
@router.get("/health", dependencies=[require_auth()])
async def ml_health(request: Request):
    """Return ML subsystem health."""
    predictors = getattr(request.app.state, "ml_predictors", {})
    classifier = getattr(request.app.state, "regime_classifier", None)

    # Ensemble info
    total_members = 0
    stale_members = 0
    oldest_member_days = 0
    for pred in predictors.values():
        n = getattr(pred, "n_members", 1)
        total_members += n
        weights = getattr(pred, "_weights", [])
        for w in weights:
            if w <= 0.3:
                stale_members += 1
        # Track oldest member age from checkpoint file mtimes
        for pt_age in getattr(pred, "_member_ages_days", []):
            if pt_age > oldest_member_days:
                oldest_member_days = pt_age

    # Regime classifier info
    clf_active = classifier is not None
    clf_age = None
    clf_fallback = not clf_active
    if classifier:
        from datetime import datetime, timezone
        try:
            trained = datetime.fromisoformat(classifier._trained_at)
            clf_age = (datetime.now(timezone.utc) - trained).days
        except (ValueError, TypeError, AttributeError):
            clf_age = None
        clf_fallback = classifier.is_stale()

    return {
        "ml_health": {
            "ensemble": {
                "pairs_loaded": len(predictors),
                "members_loaded": total_members,
                "members_stale": stale_members,
                "oldest_member_days": round(oldest_member_days, 1),
            },
            "regime_classifier": {
                "active": clf_active and not clf_fallback,
                "age_days": clf_age,
                "fallback": clf_fallback,
            },
        }
    }
```

- [ ] **Step 4: Add /api/regime/train endpoint**

Add a new router for regime endpoints. At the top of `backend/app/api/ml.py`, add to imports (verify `datetime`, `timedelta`, `timezone`, `select`, `Candle`, `asyncio`, `os`, `np` are already imported — they should be from the existing file):

```python
import numpy as np  # add if not already present
from app.engine.regime_classifier import RegimeClassifier, build_regime_features, MIN_TRAINING_SAMPLES, MIN_MACRO_F1
from app.engine.regime_labels import generate_regime_labels
```

Then add the endpoint:

```python
@router.post("/regime/train", dependencies=[require_auth()])
async def train_regime_classifier(request: Request, lookback_days: int = 90, horizon: int = 48):
    """Train global regime classifier on candle data from all pairs."""
    db = request.app.state.db
    settings = request.app.state.settings
    pairs = getattr(settings, "pairs", ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "WIF-USDT-SWAP"])

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    all_features = []
    all_labels = []

    for pair in pairs:
        async with db.session_factory() as session:
            rows = (await session.execute(
                select(Candle)
                .where(Candle.pair == pair, Candle.timeframe == "1h", Candle.ts >= cutoff)
                .order_by(Candle.ts)
            )).scalars().all()

        if len(rows) < horizon + 20:
            continue

        import pandas as pd
        df = pd.DataFrame([{
            "open": float(r.open), "high": float(r.high),
            "low": float(r.low), "close": float(r.close),
            "volume": float(r.volume),
        } for r in rows])

        labels = generate_regime_labels(df, horizon=horizon)
        features, feature_names = build_regime_features(df)

        # Drop last horizon rows (labels are default there) and warmup rows
        valid = slice(20, len(df) - horizon)
        all_features.append(features[valid])
        all_labels.append(labels.values[valid])

    if not all_features:
        raise HTTPException(400, "No pairs had enough candle data")

    combined_features = np.concatenate(all_features)
    combined_labels = np.concatenate(all_labels)

    if len(combined_features) < MIN_TRAINING_SAMPLES:
        raise HTTPException(
            400,
            f"Only {len(combined_features)} samples available (need {MIN_TRAINING_SAMPLES})",
        )

    clf = RegimeClassifier()
    metrics = await asyncio.to_thread(
        clf.train, combined_features, combined_labels, feature_names,
    )

    if metrics["macro_f1"] < MIN_MACRO_F1:
        logger.warning(
            "Regime classifier F1 %.3f below threshold %.3f — not promoting",
            metrics["macro_f1"], MIN_MACRO_F1,
        )
        return {"status": "rejected", "reason": "below_f1_threshold", "metrics": metrics}

    # Save model
    regime_dir = os.path.join(getattr(settings, "ml_checkpoint_dir", "models"), "regime")
    clf.save(regime_dir)
    request.app.state.regime_classifier = clf
    logger.info("Regime classifier trained and promoted (F1=%.3f)", metrics["macro_f1"])

    return {"status": "promoted", "metrics": metrics}
```

Add `import numpy as np` to the imports at the top of `ml.py` if not already present.

- [ ] **Step 5: Run all API tests**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_ml_health.py -v
```
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/ml.py backend/tests/api/test_ml_health.py
git commit -m "feat(api): add /ml/health and /regime/train endpoints"
```

---

### Task 10: Frontend — ML Health Status

**Files:**
- Modify: `web/src/shared/lib/api.ts`
- Modify: `web/src/features/system/types.ts`
- Create: `web/src/features/system/components/MLHealthStatus.tsx`
- Modify: `web/src/features/system/components/SystemDiagnostics.tsx:201-219`

- [ ] **Step 1: Add MLHealthResponse type**

In `web/src/features/system/types.ts`, add at the end:

```typescript
export interface MLHealthResponse {
  ml_health: {
    ensemble: {
      pairs_loaded: number;
      members_loaded: number;
      members_stale: number;
      oldest_member_days: number;
    };
    regime_classifier: {
      active: boolean;
      age_days: number | null;
      fallback: boolean;
    };
  };
}
```

- [ ] **Step 2: Add getMLHealth to API client**

In `web/src/shared/lib/api.ts`, add after the existing `getMLStatus` method:

```typescript
  getMLHealth: () => request<MLHealthResponse>("/api/ml/health"),
```

Add the import for `MLHealthResponse` at the top of the file if types are imported from there, or inline it.

- [ ] **Step 3: Create MLHealthStatus component**

Create `web/src/features/system/components/MLHealthStatus.tsx`:

```tsx
import { useEffect, useState } from "react";
import { api } from "@/shared/lib/api";
import type { MLHealthResponse } from "../types";

export function MLHealthStatus() {
  const [data, setData] = useState<MLHealthResponse | null>(null);

  useEffect(() => {
    api.getMLHealth().then(setData).catch(() => {});
  }, []);

  if (!data) {
    return (
      <div className="space-y-2">
        <StatusRow label="ML Ensemble" value="Loading..." color="text-on-surface-variant" />
        <StatusRow label="Regime Classifier" value="Loading..." color="text-on-surface-variant" />
      </div>
    );
  }

  const { ensemble, regime_classifier } = data.ml_health;

  const ensembleColor =
    ensemble.members_loaded === 0
      ? "text-short"
      : ensemble.members_stale > 0
        ? "text-primary"
        : "text-long";

  const ensembleText =
    ensemble.members_loaded === 0
      ? "No models"
      : ensemble.members_stale > 0
        ? `${ensemble.members_loaded - ensemble.members_stale}/${ensemble.members_loaded} models, ${ensemble.members_stale} stale`
        : `${ensemble.members_loaded} models (${ensemble.pairs_loaded} pairs)`;

  const regimeColor = regime_classifier.active ? "text-long" : "text-primary";
  const regimeText = regime_classifier.active
    ? `Classifier active${regime_classifier.age_days !== null ? ` (${regime_classifier.age_days}d)` : ""}`
    : "Using heuristic fallback";

  return (
    <div className="space-y-2">
      <StatusRow label="ML Ensemble" value={ensembleText} color={ensembleColor} />
      <StatusRow label="Regime" value={regimeText} color={regimeColor} />
    </div>
  );
}

function StatusRow({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-[10px] font-bold text-on-surface-variant uppercase">{label}</span>
      <span className={`text-xs font-bold tabular-nums ${color}`}>{value}</span>
    </div>
  );
}
```

- [ ] **Step 4: Update SystemDiagnostics to use MLHealthStatus**

In `web/src/features/system/components/SystemDiagnostics.tsx`, add the import at the top:

```typescript
import { MLHealthStatus } from "./MLHealthStatus";
```

Then in the `FreshnessSection` component (lines 201-219), replace the static ML Models row:

```tsx
      <div className="flex justify-between items-center">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase">ML Models</span>
        <span className={`text-xs font-bold tabular-nums ${freshness.ml_models_loaded === 0 ? "text-primary" : "text-on-surface"}`}>
          {freshness.ml_models_loaded === 0 ? "No models loaded" : `${freshness.ml_models_loaded} models`}
        </span>
      </div>
```

with:

```tsx
      <MLHealthStatus />
```

- [ ] **Step 5: Verify frontend builds**

Run:
```bash
cd web && pnpm build
```
Expected: Build succeeds

- [ ] **Step 6: Commit**

```bash
git add web/src/features/system/types.ts web/src/shared/lib/api.ts web/src/features/system/components/MLHealthStatus.tsx web/src/features/system/components/SystemDiagnostics.tsx
git commit -m "feat(ui): add ML health status with ensemble and regime classifier details"
```

---

## Spec Coverage Check

| Spec Section | Task |
|---|---|
| 1. Deep Ensemble Training (temporal splits, parallel, staging) | Task 2, 3 |
| 1. EnsemblePredictor (weighted inference, disagreement, partial load) | Task 4 |
| 1. Ensemble loading + backward compat | Task 5 |
| 2. Regime label generation (4-class, forward-looking) | Task 6 |
| 2. Regime classifier (LightGBM, train, predict, staleness) | Task 7 |
| 2. Integration with compute_regime_mix + RegimeWeights interaction | Task 8 |
| 3. Modified POST /api/ml/train | Task 5 |
| 3. Modified POST /api/ml/reload | Task 5 |
| 3. New POST /api/regime/train | Task 9 |
| 3. New GET /api/ml/health | Task 9 |
| 4. Frontend MLHealthStatus | Task 10 |
| 5. Dependencies (lightgbm, libgomp1) | Task 1 |
| 6. Config (ensemble_disagreement_scale) | Task 1 |
| 7. What doesn't change (blend_with_ml, regime return type) | Verified in Task 5, 8 |
| 8. Deployment checklist | Covered by task ordering |

### Spec Deviations (intentional)

| Spec says | Plan does | Rationale |
|-----------|-----------|-----------|
| `EnsemblePredictor` in `predictor.py` | Separate `ensemble_predictor.py` | Avoids bloating the 200-line predictor module |
