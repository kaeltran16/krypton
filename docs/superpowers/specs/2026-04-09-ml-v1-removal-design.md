# ML V1 Classification Removal + Regression Config Fix

**Date:** 2026-04-09
**Status:** Approved
**Motivation:** Training produces best_epoch=1 on all ensemble members because the API's `TrainRequest` defaults are tuned for the old v1 classification model (lr=1e-3, hidden=128, batch=64) and override the regression-tuned defaults (lr=5e-4, hidden=96, batch=128). Additionally, the v1 classification code is dead weight — all production models are v2 regression.

## Problem

The `TrainRequest` Pydantic model in `api/ml.py` passes v1-era hyperparameters to `RegressionTrainConfig`:

| Parameter | API default (v1) | RegressionTrainConfig default | Effect |
|-----------|-----------------|-------------------------------|--------|
| `lr` | 1e-3 | 5e-4 | 2x too aggressive — overshoots from epoch 1 |
| `hidden_size` | 128 | 96 | Overparameterized for ~20k samples |
| `batch_size` | 64 | 128 | Noisier gradients |

Result: all 9 ensemble members (3 pairs × 3 folds) converge at epoch 1 and never improve.

## Solution

1. Delete all v1 classification code (model, trainer, dataset, labels, predictor, ensemble predictor, drift stats)
2. Rename v2 classes to drop the "Regression" prefix (they're the only version now)
3. Align `TrainRequest` defaults to the regression config

## Deletions

### model.py
- Delete `SignalLSTM` class (v1 classification model, dual-head: cls + reg)
- Keep `TemporalAttention` (shared by both)
- Rename `SignalLSTMv2` → `SignalLSTM`

### dataset.py
- Delete `CandleDataset` (v1, no validity filtering)
- Rename `RegressionDataset` → `CandleDataset`

### trainer.py
- Delete `compute_class_weights`, `FocalLoss`, `_ENSEMBLE_SPLITS`, `TrainConfig` (v1), `Trainer` (v1 classification trainer, ~600 lines)
- Keep `_WALKFORWARD_FOLDS`
- Rename `RegressionTrainConfig` → `TrainConfig`, `RegressionTrainer` → `Trainer`

### labels.py
- Delete `LabelConfig`, `generate_labels`, direction constants (`NEUTRAL`, `LONG`, `SHORT`)
- Rename `RegressionTargetConfig` → `TargetConfig`, `generate_regression_targets` → `generate_targets`

### data_loader.py
- Delete `prepare_training_data` (v1, calls `generate_labels`)
- Rename `prepare_regression_data` → `prepare_training_data`

### predictor.py
- Delete `Predictor` (v1 single-model inference)
- Rename `RegressionPredictor` → `Predictor`

### ensemble_predictor.py
- Delete `EnsemblePredictor` (v1 classification ensemble)
- Rename `RegressionEnsemblePredictor` → `EnsemblePredictor`

### drift.py
- Delete `compute_drift_stats` (v1 classification permutation importance)
- Delete `_permutation_importance` (v1 helper)
- Rename `compute_regression_drift_stats` → `compute_drift_stats`
- Rename `_regression_permutation_importance` → `_permutation_importance`

## Config Fix

### api/ml.py `TrainRequest`
```python
# Before (v1 defaults)
epochs: int = Field(default=100, ge=1, le=500)
batch_size: int = Field(default=64, ge=8, le=512)
hidden_size: int = Field(default=128, ge=32, le=512)
lr: float = Field(default=1e-3, gt=0)

# After (regression defaults)
epochs: int = Field(default=80, ge=1, le=500)
batch_size: int = Field(default=128, ge=8, le=512)
hidden_size: int = Field(default=96, ge=32, le=512)
lr: float = Field(default=5e-4, gt=0)
```

### api/ml.py `_reload_predictors`
- Remove `model_version` v1/v2 branching — always load `EnsemblePredictor` (formerly `RegressionEnsemblePredictor`)
- Remove legacy single-file `Predictor` fallback (`best_model.pt` without `ensemble_config.json`)
- Remove `from app.ml.predictor import Predictor` and `from app.ml.ensemble_predictor import EnsemblePredictor` (v1 imports)

### api/ml.py training endpoint
- Remove `from app.ml.data_loader import prepare_training_data` (v1 import)
- Remove `from app.ml.labels import LabelConfig` (v1 import)
- Update `RegressionTrainer` → `Trainer`, `RegressionTrainConfig` → `TrainConfig`

## Rename Summary

| Old name | New name |
|----------|----------|
| `SignalLSTMv2` | `SignalLSTM` |
| `RegressionDataset` | `CandleDataset` |
| `RegressionTrainer` | `Trainer` |
| `RegressionTrainConfig` | `TrainConfig` |
| `RegressionEnsemblePredictor` | `EnsemblePredictor` |
| `RegressionPredictor` | `Predictor` |
| `prepare_regression_data` | `prepare_training_data` |
| `generate_regression_targets` | `generate_targets` |
| `RegressionTargetConfig` | `TargetConfig` |
| `compute_regression_drift_stats` | `compute_drift_stats` |
| `_regression_permutation_importance` | `_permutation_importance` |

## Test Changes

### Delete
- `test_trainer.py`: `compute_class_weights` tests
- `test_ml_calibration.py`: all tests (v1 `SignalLSTM` calibration)
- `test_ensemble_predictor.py`: v1 `EnsemblePredictor` tests
- `test_labels.py`: `generate_labels` / `LabelConfig` tests
- `test_data_loader.py`: `prepare_training_data` (v1) tests
- `test_drift.py`: v1 `compute_drift_stats` test using `CandleDataset` + `SignalLSTM`
- `test_ml.py` (api tests): v1 `SignalLSTM` model creation

### Update
- All remaining tests importing renamed classes get updated imports
- `test_model.py`: remove v1 `SignalLSTM` tests, update `SignalLSTMv2` → `SignalLSTM`

## Not Changing

- `model_version: "v2"` in saved `ensemble_config.json` — existing models on disk use it, we just won't branch on it
- `combiner.py` / `blend_with_ml` — already version-agnostic (takes score + confidence)
- Walk-forward fold boundaries, training loop logic, quality gates, early stopping
- `TemporalAttention` — shared, stays as-is

## Validation

After implementation:
1. `docker exec krypton-api-1 python -m pytest` — all tests pass
2. Trigger training via API, confirm models train with correct defaults (best_epoch > 1)
3. Verify `_reload_predictors` loads models without v1/v2 branching
