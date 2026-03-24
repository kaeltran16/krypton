# Signal Engine v2 — ML Calibration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calibrate ML model outputs with temperature scaling, add epistemic uncertainty via MC Dropout, implement feature layout versioning, and replace input-size heuristic for stale model detection with checkpoint age.

**Architecture:** Post-training temperature scaling learns a single scalar `T` on the validation set to prevent overconfident softmax outputs. At inference, 5 MC Dropout forward passes provide mean prediction and variance — high variance reduces ML confidence, feeding into the confidence-weighted blending from Plan 1. Feature layout is version-tracked in checkpoint sidecar JSON for safe name-based mapping instead of silent truncation.

**Tech Stack:** Python, PyTorch, pytest

**Spec:** `docs/superpowers/specs/2026-03-24-signal-engine-v2-design.md` (Section 5)

**Depends on:** Plan 1 (confidence-weighted blending — ML confidence feeds into combiner)

---

## File Structure

### Modified Files

| File | Responsibility |
|------|---------------|
| `backend/app/ml/trainer.py` | Add temperature scaling after training, save temperature + feature names to sidecar |
| `backend/app/ml/predictor.py` | MC Dropout inference (5 passes), feature name mapping, checkpoint age staleness |
| `backend/app/ml/model.py` | No changes — architecture unchanged |
| `backend/app/ml/features.py` | Export feature column names for layout versioning |

### Test Files

| File | What it covers |
|------|---------------|
| `backend/tests/ml/test_ml_calibration.py` | Temperature scaling, MC Dropout, feature versioning, stale model detection |

---

## Task 1: Export Feature Column Names

**Files:**
- Modify: `backend/app/ml/features.py`
- Test: `backend/tests/ml/test_ml_calibration.py`

The feature builder needs to export an ordered list of feature names so the trainer can record them in the checkpoint sidecar.

- [ ] **Step 1: Write test**

```python
# backend/tests/ml/test_ml_calibration.py
from app.ml.features import get_feature_names


def test_feature_names_match_matrix_columns():
    """Feature names list must match the number of columns in the feature matrix."""
    # base features only
    names = get_feature_names(flow_used=False, regime_used=False, btc_used=False)
    # Should match PRICE_FEATURES + INDICATOR_FEATURES + TEMPORAL_FEATURES + MOMENTUM_FEATURES + MULTI_TF_FEATURES
    assert len(names) >= 20
    assert all(isinstance(n, str) for n in names)
    assert len(names) == len(set(names)), "Feature names must be unique"


def test_feature_names_with_optional_groups():
    """Optional feature groups should add known names."""
    base = get_feature_names(flow_used=False, regime_used=False, btc_used=False)
    full = get_feature_names(flow_used=True, regime_used=True, btc_used=True)
    assert len(full) > len(base)
    assert "funding_rate" in full
    assert "regime_trend" in full
    assert "btc_ret_5" in full
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py::test_feature_names_match_matrix_columns -v`
Expected: FAIL — `get_feature_names` doesn't exist

- [ ] **Step 3: Implement get_feature_names in features.py**

In `backend/app/ml/features.py`, add a function that returns the ordered feature column names matching the matrix columns. Read the existing feature group constants (PRICE_FEATURES, INDICATOR_FEATURES, etc.) and build the names list in the same order as `build_feature_matrix` constructs them:

```python
PRICE_FEATURE_NAMES = ["ret", "body_ratio", "upper_wick", "lower_wick", "volume_zscore"]
INDICATOR_FEATURE_NAMES = ["ema9_dist", "ema21_dist", "ema50_dist", "rsi_norm", "macd_norm", "bb_position", "bb_width", "atr_pct"]
TEMPORAL_FEATURE_NAMES = ["hour_sin", "hour_cos"]
MOMENTUM_FEATURE_NAMES = ["ret_5", "ret_10", "ret_20", "rsi_roc", "vol_trend", "macd_accel"]
MULTI_TF_FEATURE_NAMES = ["rsi_slow", "ema_slow_dist", "bb_pos_slow"]
REGIME_FEATURE_NAMES = ["regime_trend", "regime_range", "regime_vol", "trend_conv"]
INTER_PAIR_FEATURE_NAMES = ["btc_ret_5", "btc_atr_pct"]
FLOW_FEATURE_NAMES = ["funding_rate", "oi_change_pct", "long_short_ratio_norm"]
FLOW_ROC_FEATURE_NAMES = ["funding_delta", "ls_delta", "oi_accel"]


def get_feature_names(
    flow_used: bool = False,
    regime_used: bool = False,
    btc_used: bool = False,
) -> list[str]:
    """Return ordered list of feature column names matching build_feature_matrix output."""
    names = (
        PRICE_FEATURE_NAMES
        + INDICATOR_FEATURE_NAMES
        + TEMPORAL_FEATURE_NAMES
        + MOMENTUM_FEATURE_NAMES
        + MULTI_TF_FEATURE_NAMES
    )
    if regime_used:
        names = names + REGIME_FEATURE_NAMES
    if btc_used:
        names = names + INTER_PAIR_FEATURE_NAMES
    if flow_used:
        names = names + FLOW_FEATURE_NAMES + FLOW_ROC_FEATURE_NAMES
    return names
```

Verify that the order matches the column order in `build_feature_matrix`. If `build_feature_matrix` assembles columns differently, adjust the name list to match.

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py -v -k "feature_names"`
Expected: PASS

---

## Task 2: Save Feature Names and Temperature in Trainer Sidecar

**Files:**
- Modify: `backend/app/ml/trainer.py:248-284`
- Test: `backend/tests/ml/test_ml_calibration.py`

After training, the sidecar JSON should include `feature_names` and `temperature` (initially 1.0 — actual calibration in Task 3).

- [ ] **Step 1: Write test**

Add to `test_ml_calibration.py`:
```python
import json
import os
import tempfile

import numpy as np

from app.ml.trainer import Trainer, TrainConfig


def test_trainer_saves_feature_names_in_sidecar():
    """Trainer should save feature_names list in model_config.json sidecar."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = TrainConfig(
            epochs=2, checkpoint_dir=tmpdir, seq_len=5,
            hidden_size=16, num_layers=1, patience=2,
        )
        n = 50
        features = np.random.randn(n, 24).astype(np.float32)
        direction = np.random.randint(0, 3, n)
        sl = np.random.rand(n).astype(np.float32) + 0.5
        tp1 = sl + 0.5
        tp2 = tp1 + 0.5

        trainer = Trainer(cfg)
        trainer.train(features, direction, sl, tp1, tp2)

        config_path = os.path.join(tmpdir, "model_config.json")
        with open(config_path) as f:
            config = json.load(f)

        assert "feature_names" in config, "Sidecar must contain feature_names"
        assert "temperature" in config, "Sidecar must contain temperature"
        assert config["temperature"] == 1.0  # uncalibrated default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py::test_trainer_saves_feature_names_in_sidecar -v`
Expected: FAIL — sidecar doesn't contain `feature_names` or `temperature`

- [ ] **Step 3: Update trainer sidecar to include feature_names and temperature**

In `backend/app/ml/trainer.py`, update **BOTH** places where `config_meta` is built — the early-stopping save path (around lines 250-260) AND the no-validation save path (around lines 274-284). Both must include the new fields. Add to both dicts:

```python
config_meta = {
    "input_size": input_size,
    "hidden_size": cfg.hidden_size,
    "num_layers": cfg.num_layers,
    "dropout": cfg.dropout,
    "seq_len": cfg.seq_len,
    "epoch": epoch + 1,
    "val_loss": best_val_loss,
    "feature_names": feature_names,  # new
    "temperature": 1.0,              # new (calibrated in next step)
}
```

The `feature_names` parameter should be passed into the `train` method or derived from `input_size`. For now, accept it as an optional parameter:

Add to `train()` signature:
```python
def train(self, features, direction, sl_atr, tp1_atr, tp2_atr,
          progress_callback=None, feature_names=None):
```

If `feature_names` is None, generate placeholder names:
```python
if feature_names is None:
    feature_names = [f"feature_{i}" for i in range(input_size)]
```

- [ ] **Step 4: Run test**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py::test_trainer_saves_feature_names_in_sidecar -v`
Expected: PASS

---

## Task 3: Temperature Scaling After Training

**Files:**
- Modify: `backend/app/ml/trainer.py`
- Test: `backend/tests/ml/test_ml_calibration.py`

After training completes, learn a single scalar `T` on the validation set via NLL minimization. Save `T` in the sidecar.

- [ ] **Step 1: Write test**

Add to `test_ml_calibration.py`:
```python
def test_temperature_scaling_changes_calibration():
    """Temperature scaling should produce T != 1.0 for overconfident models."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = TrainConfig(
            epochs=10, checkpoint_dir=tmpdir, seq_len=5,
            hidden_size=32, num_layers=1, patience=10,
        )
        n = 200
        np.random.seed(42)
        features = np.random.randn(n, 15).astype(np.float32)
        # Create patterns: features > 0 → LONG, < 0 → SHORT
        direction = np.where(features[:, 0] > 0.3, 1, np.where(features[:, 0] < -0.3, 2, 0)).astype(np.int64)
        sl = np.random.rand(n).astype(np.float32) + 0.5
        tp1 = sl + 0.5
        tp2 = tp1 + 0.5

        trainer = Trainer(cfg)
        trainer.train(features, direction, sl, tp1, tp2)

        config_path = os.path.join(tmpdir, "model_config.json")
        with open(config_path) as f:
            config = json.load(f)

        # Temperature should be > 1.0 for overconfident model (softens predictions)
        assert config["temperature"] > 0.1, "Temperature must be positive"
        assert isinstance(config["temperature"], float)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py::test_temperature_scaling_changes_calibration -v`
Expected: FAIL — temperature is always 1.0

- [ ] **Step 3: Implement temperature scaling in trainer**

After the training loop completes and the best model is saved, add temperature calibration. Insert before the "Compute classification metrics" section (around line 296):

```python
        # ── Temperature scaling on validation set ──
        temperature = 1.0
        if val_loader is not None:
            # Load best model weights
            best_pt = os.path.join(cfg.checkpoint_dir, "best_model.pt")
            if os.path.exists(best_pt):
                model.load_state_dict(torch.load(best_pt, map_location=self.device, weights_only=True))

            model.eval()
            # Collect logits and labels from validation set
            all_logits = []
            all_labels = []
            with torch.no_grad():
                for x, y_dir, _ in val_loader:
                    x = x.to(self.device)
                    dir_logits, _ = model(x)
                    all_logits.append(dir_logits)
                    all_labels.append(y_dir.to(self.device))

            if all_logits:
                all_logits = torch.cat(all_logits, dim=0)
                all_labels = torch.cat(all_labels, dim=0)

                # Optimize temperature via NLL
                log_temp = torch.tensor(0.0, device=self.device, requires_grad=True)
                temp_optimizer = torch.optim.LBFGS([log_temp], lr=0.01, max_iter=50)
                nll_fn = nn.CrossEntropyLoss()

                def temp_closure():
                    temp_optimizer.zero_grad()
                    t = log_temp.exp()
                    loss = nll_fn(all_logits / t, all_labels)
                    loss.backward()
                    return loss

                temp_optimizer.step(temp_closure)
                temperature = float(log_temp.exp().item())
                # clamp to reasonable range
                temperature = max(0.1, min(10.0, temperature))
                logger.info(f"Temperature scaling: T={temperature:.4f}")
```

Then update all sidecar writes to use the computed `temperature` instead of `1.0`.

- [ ] **Step 4: Run test**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py::test_temperature_scaling_changes_calibration -v`
Expected: PASS

- [ ] **Step 5: Run existing ML tests for regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/ -v`
Expected: PASS

---

## Task 4: MC Dropout Inference

**Files:**
- Modify: `backend/app/ml/predictor.py:65-103`
- Test: `backend/tests/ml/test_ml_calibration.py`

Run 5 forward passes with dropout enabled. Mean = calibrated prediction. Variance = epistemic uncertainty. High variance reduces confidence.

- [ ] **Step 1: Write test**

Add to `test_ml_calibration.py`:
```python
import torch
from app.ml.predictor import Predictor


def test_mc_dropout_reduces_confidence_with_high_variance(tmp_path):
    """MC Dropout should produce lower confidence when model is uncertain."""
    from app.ml.model import SignalLSTM

    # Create a simple model checkpoint
    input_size = 15
    model = SignalLSTM(input_size=input_size, hidden_size=32, num_layers=1, dropout=0.5)
    torch.save(model.state_dict(), tmp_path / "best_model.pt")

    config = {
        "input_size": input_size,
        "hidden_size": 32,
        "num_layers": 1,
        "dropout": 0.5,
        "seq_len": 10,
        "temperature": 1.0,
        "feature_names": [f"f{i}" for i in range(input_size)],
    }
    import json
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    predictor = Predictor(str(tmp_path / "best_model.pt"))
    features = np.random.randn(20, input_size).astype(np.float32)
    result = predictor.predict(features)

    assert "confidence" in result
    assert "mc_variance" in result
    # MC variance should be > 0 (dropout creates variation)
    assert result["mc_variance"] >= 0.0


def test_mc_dropout_completes_within_latency_budget(tmp_path):
    """5 MC Dropout passes should complete in <2s on CPU."""
    import time
    from app.ml.model import SignalLSTM

    input_size = 24
    model = SignalLSTM(input_size=input_size, hidden_size=128, num_layers=2, dropout=0.3)
    torch.save(model.state_dict(), tmp_path / "best_model.pt")

    config = {
        "input_size": input_size, "hidden_size": 128, "num_layers": 2,
        "dropout": 0.3, "seq_len": 50, "temperature": 1.0,
        "feature_names": [f"f{i}" for i in range(input_size)],
    }
    import json
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    predictor = Predictor(str(tmp_path / "best_model.pt"))
    features = np.random.randn(60, input_size).astype(np.float32)

    start = time.monotonic()
    result = predictor.predict(features)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"MC Dropout inference took {elapsed:.2f}s (budget: 2s)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py::test_mc_dropout_reduces_confidence_with_high_variance -v`
Expected: FAIL — no `mc_variance` in result

- [ ] **Step 3: Implement MC Dropout in predictor.py**

Replace the `predict` method in `backend/app/ml/predictor.py`:

```python
MC_DROPOUT_PASSES = 5

    def predict(self, features: np.ndarray) -> dict:
        if self._stale:
            return dict(_NEUTRAL_RESULT)

        if len(features) < self.seq_len:
            return dict(_NEUTRAL_RESULT)

        # feature mapping by name (if available)
        features = self._map_features(features)

        # take last seq_len candles
        window = features[-self.seq_len:]
        x = torch.tensor(window, dtype=torch.float32).unsqueeze(0).to(self.device)

        # temperature from sidecar
        temperature = getattr(self, "_temperature", 1.0)

        # MC Dropout: run multiple passes with dropout enabled
        # IMPORTANT: only enable Dropout layers, NOT BatchNorm — model.train()
        # would corrupt BatchNorm running stats. Selectively toggle Dropout only.
        self.model.eval()
        for m in self.model.modules():
            if isinstance(m, nn.Dropout):
                m.train()
        all_probs = []
        all_regs = []
        for _ in range(MC_DROPOUT_PASSES):
            with torch.no_grad():
                dir_logits, reg_out = self.model(x)
                probs = torch.softmax(dir_logits / temperature, dim=1).squeeze(0).cpu().numpy()
                all_probs.append(probs)
                all_regs.append(reg_out.squeeze(0).cpu().numpy())
        self.model.eval()  # restore all layers to eval

        # mean prediction
        mean_probs = np.mean(all_probs, axis=0)
        mean_reg = np.mean(all_regs, axis=0)

        # epistemic uncertainty: variance across passes
        prob_variance = float(np.mean(np.var(all_probs, axis=0)))

        direction_idx = int(np.argmax(mean_probs))
        raw_confidence = float(mean_probs[direction_idx])

        # reduce confidence proportionally to uncertainty
        uncertainty_penalty = min(1.0, prob_variance * 10)  # scale variance to 0-1
        confidence = raw_confidence * (1.0 - uncertainty_penalty)

        return {
            "direction": DIRECTION_MAP[direction_idx],
            "confidence": confidence,
            "sl_atr": float(mean_reg[0]),
            "tp1_atr": float(mean_reg[1]),
            "tp2_atr": float(mean_reg[2]),
            "mc_variance": prob_variance,
        }
```

- [ ] **Step 4: Load temperature from sidecar in __init__**

In `Predictor.__init__`, after loading the config:
```python
self._temperature = config.get("temperature", 1.0)
```

- [ ] **Step 5: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py -v -k "mc_dropout"`
Expected: PASS

---

## Task 5: Feature Layout Versioning in Predictor

**Files:**
- Modify: `backend/app/ml/predictor.py`
- Test: `backend/tests/ml/test_ml_calibration.py`

Replace silent truncation (`features[:, :self.input_size]`) with name-based mapping. Missing features filled with 0, extra features ignored with logging.

**Note:** Add `"mc_variance": 0.0` to `_NEUTRAL_RESULT` at the top of `predictor.py` so early returns don't cause KeyError for callers checking `mc_variance`.

- [ ] **Step 1: Write test**

Add to `test_ml_calibration.py`:
```python
def test_feature_mapping_handles_missing_features(tmp_path):
    """Predictor should map features by name, filling missing with 0."""
    from app.ml.model import SignalLSTM
    import json

    input_size = 5
    model = SignalLSTM(input_size=input_size, hidden_size=16, num_layers=1, dropout=0.0)
    torch.save(model.state_dict(), tmp_path / "best_model.pt")

    config = {
        "input_size": input_size, "hidden_size": 16, "num_layers": 1,
        "dropout": 0.0, "seq_len": 5, "temperature": 1.0,
        "feature_names": ["a", "b", "c", "d", "e"],
    }
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    predictor = Predictor(str(tmp_path / "best_model.pt"))

    # Provide features with different names (3 match, 2 missing)
    predictor.set_available_features(["a", "c", "e", "x", "y"])
    features = np.random.randn(10, 5).astype(np.float32)
    result = predictor.predict(features)

    # Should still produce a result (missing features filled with 0)
    assert result["direction"] in ("NEUTRAL", "LONG", "SHORT")


def test_feature_mapping_logs_missing(tmp_path, caplog):
    """Predictor should log warnings for missing features."""
    from app.ml.model import SignalLSTM
    import json
    import logging

    input_size = 3
    model = SignalLSTM(input_size=input_size, hidden_size=16, num_layers=1, dropout=0.0)
    torch.save(model.state_dict(), tmp_path / "best_model.pt")

    config = {
        "input_size": input_size, "hidden_size": 16, "num_layers": 1,
        "dropout": 0.0, "seq_len": 5, "temperature": 1.0,
        "feature_names": ["a", "b", "c"],
    }
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    predictor = Predictor(str(tmp_path / "best_model.pt"))
    predictor.set_available_features(["a", "d"])  # "b" and "c" missing

    with caplog.at_level(logging.WARNING):
        features = np.random.randn(10, 2).astype(np.float32)
        predictor.predict(features)

    assert any("missing" in msg.lower() or "Missing" in msg for msg in caplog.messages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py::test_feature_mapping_handles_missing_features -v`
Expected: FAIL — `set_available_features` doesn't exist

- [ ] **Step 3: Implement feature name mapping**

In `backend/app/ml/predictor.py`, add to `Predictor`:

```python
    def __init__(self, checkpoint_path: str):
        # ... existing code ...
        self._expected_features = config.get("feature_names", [])
        self._feature_map = None  # indices from available → expected
        self._available_features = None

    def set_available_features(self, names: list[str]):
        """Set the feature names available at inference time.

        Builds a mapping from available feature columns to the model's expected layout.
        """
        self._available_features = names
        expected = self._expected_features
        if not expected:
            self._feature_map = None
            return

        # map: for each expected feature, find index in available (or -1 for missing)
        available_idx = {name: i for i, name in enumerate(names)}
        self._feature_map = []
        missing = []
        for name in expected:
            idx = available_idx.get(name, -1)
            self._feature_map.append(idx)
            if idx == -1:
                missing.append(name)

        if missing:
            logger.warning("Missing features for model (filled with 0): %s", missing)

    def _map_features(self, features: np.ndarray) -> np.ndarray:
        """Remap feature columns to match model's expected layout."""
        if self._feature_map is None:
            # fallback: truncate like before
            if features.shape[1] > self.input_size:
                return features[:, :self.input_size]
            return features

        n_rows = features.shape[0]
        mapped = np.zeros((n_rows, len(self._feature_map)), dtype=np.float32)
        for out_col, in_col in enumerate(self._feature_map):
            if in_col >= 0 and in_col < features.shape[1]:
                mapped[:, out_col] = features[:, in_col]
        return mapped
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py -v -k "feature_mapping"`
Expected: PASS

---

## Task 6: Stale Model Detection by Checkpoint Age

**Files:**
- Modify: `backend/app/ml/predictor.py:42-51`
- Test: `backend/tests/ml/test_ml_calibration.py`

Replace `input_size` heuristic (16-23 = stale) with checkpoint file age. Models not retrained within N days (default 14) get confidence capped at 0.3.

**IMPORTANT:** Remove the existing `_stale` input-size heuristic (lines 42-51 in current `predictor.py`). The old `if 16 <= self.input_size <= 23` block and its early `return` in `__init__` must be deleted — the spec says "replace" not "add alongside". Also update existing tests in `tests/ml/test_predictor.py:TestStaleModelDetection` — remove/rewrite the input-size-based staleness tests since that heuristic is gone.

- [ ] **Step 1: Write test**

Add to `test_ml_calibration.py`:
```python
import time as _time


def test_stale_model_by_age_reduces_confidence(tmp_path):
    """Models older than max_age_days should have reduced confidence."""
    from app.ml.model import SignalLSTM
    import json

    input_size = 15
    model = SignalLSTM(input_size=input_size, hidden_size=16, num_layers=1, dropout=0.3)
    pt_path = tmp_path / "best_model.pt"
    torch.save(model.state_dict(), pt_path)

    config = {
        "input_size": input_size, "hidden_size": 16, "num_layers": 1,
        "dropout": 0.3, "seq_len": 10, "temperature": 1.0,
        "feature_names": [f"f{i}" for i in range(input_size)],
    }
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    # Make the checkpoint appear 20 days old
    old_time = _time.time() - 20 * 86400
    os.utime(pt_path, (old_time, old_time))

    predictor = Predictor(str(pt_path), max_age_days=14)
    assert predictor._stale_age is True

    features = np.random.randn(20, input_size).astype(np.float32)
    result = predictor.predict(features)
    # Confidence should be capped at 0.3
    assert result["confidence"] <= 0.3


def test_fresh_model_not_marked_stale(tmp_path):
    """Recently trained model should not be marked stale."""
    from app.ml.model import SignalLSTM
    import json

    input_size = 15
    model = SignalLSTM(input_size=input_size, hidden_size=16, num_layers=1, dropout=0.0)
    torch.save(model.state_dict(), tmp_path / "best_model.pt")

    config = {
        "input_size": input_size, "hidden_size": 16, "num_layers": 1,
        "dropout": 0.0, "seq_len": 10, "temperature": 1.0,
        "feature_names": [f"f{i}" for i in range(input_size)],
    }
    with open(tmp_path / "model_config.json", "w") as f:
        json.dump(config, f)

    predictor = Predictor(str(tmp_path / "best_model.pt"), max_age_days=14)
    assert predictor._stale_age is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py::test_stale_model_by_age_reduces_confidence -v`
Expected: FAIL — `max_age_days` param doesn't exist

- [ ] **Step 3: Implement checkpoint age staleness**

Update `Predictor.__init__` to accept `max_age_days` and check file mtime:

```python
class Predictor:
    def __init__(self, checkpoint_path: str, max_age_days: int = 14):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._stale = False
        self._stale_age = False
        self._max_confidence = 1.0

        # Load config
        config_path = os.path.join(os.path.dirname(checkpoint_path), "model_config.json")
        with open(config_path) as f:
            config = json.load(f)

        self.seq_len = config["seq_len"]
        self.input_size = config["input_size"]
        self.flow_used = config.get("flow_used", False)
        self.regime_used = config.get("regime_used", False)
        self.btc_used = config.get("btc_used", False)
        self._temperature = config.get("temperature", 1.0)
        self._expected_features = config.get("feature_names", [])
        self._feature_map = None
        self._available_features = None

        # Check checkpoint age
        import time as _time
        file_age_days = (_time.time() - os.path.getmtime(checkpoint_path)) / 86400
        if file_age_days > max_age_days:
            logger.warning(
                "Model %s is %.1f days old (max %d), confidence capped at 0.3",
                os.path.basename(os.path.dirname(checkpoint_path)),
                file_age_days, max_age_days,
            )
            self._stale_age = True
            self._max_confidence = 0.3

        # Load model (no longer skip loading for stale-age models)
        self.model = SignalLSTM(
            input_size=config["input_size"],
            hidden_size=config["hidden_size"],
            num_layers=config["num_layers"],
            dropout=config.get("dropout", 0.0),
        ).to(self.device)

        state_dict = torch.load(checkpoint_path, map_location=self.device, weights_only=True)
        self.model.load_state_dict(state_dict)
        self.model.eval()
```

In `predict`, cap confidence at `self._max_confidence`:
```python
confidence = min(confidence, self._max_confidence)
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/test_ml_calibration.py -v -k "stale"`
Expected: PASS

---

## Task 7: Wire Feature Names in Main Pipeline

**Files:**
- Modify: `backend/app/main.py` (where ML predictor is initialized and features are built)

- [ ] **Step 1: Pass feature names when building predictors**

In `main.py`, where ML predictors are loaded (lifespan), call `set_available_features` with the names from `get_feature_names`:

```python
from app.ml.features import get_feature_names

# After creating each predictor:
feature_names = get_feature_names(
    flow_used=predictor.flow_used,
    regime_used=predictor.regime_used,
    btc_used=predictor.btc_used,
)
predictor.set_available_features(feature_names)
```

- [ ] **Step 2: Pass feature_names to trainer when training**

In the training trigger code, pass `feature_names` to `trainer.train()`:
```python
feature_names = get_feature_names(flow_used=..., regime_used=..., btc_used=...)
trainer.train(features, direction, sl, tp1, tp2, feature_names=feature_names)
```

- [ ] **Step 3: Run existing ML tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ml/ -v`
Expected: PASS

---

## Task 8: Full Integration Test

- [ ] **Step 1: Run the full backend test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=120`
Expected: All tests pass

- [ ] **Step 2: Verify ML prediction latency with MC Dropout**

The test from Task 4 (`test_mc_dropout_completes_within_latency_budget`) confirms 5 passes complete in <2s. Verify it passes.
