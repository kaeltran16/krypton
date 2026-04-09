# ML Scoring System Overhaul: Classification to Regression

**Date**: 2026-04-09
**Status**: Approved design, pending implementation plan

## Problem Statement

The current ML scoring system uses 3-class classification (LONG/SHORT/NEUTRAL) with a fixed 1.5% threshold for label generation. This produces fundamentally broken label distributions across assets:

- **BTC**: 27.4% NEUTRAL / 35.7% LONG / 36.9% SHORT — relatively balanced but models achieve only 37-44% accuracy (barely above 33% random baseline)
- **ETH**: 7.0% NEUTRAL / 46.2% LONG / 46.9% SHORT — near-binary, models reach ~53% on best members but one member is dead at 33.7%
- **WIF**: 0.4% NEUTRAL / 47.5% LONG / 52.1% SHORT — all 3 ensemble members have 0% NEUTRAL recall (complete class collapse)

Additionally, live ML confidence scores (0.27-0.35) never reach the 0.65 blend threshold, making ML functionally disabled in production.

### Root Causes

1. Fixed 1.5% threshold doesn't adapt to per-asset volatility
2. No feature standardization — scales differ 50x+ across features, hurting LSTM gradient flow
3. ~200 warmup rows zero-filled with corrupted indicator values enter training
4. Model overparameterized for data volume (~600K params, ~8.9K 1H training samples)
5. Confidence penalty stack too aggressive (MC variance + drift + age + missing features)
6. Single temporal split validation doesn't test cross-regime generalization
7. Dead ensemble members averaged in rather than excluded

## Design

### 1. Labeling: Regression Targets

Replace 3-class classification with continuous regression.

**Primary target**: ATR-normalized forward return.

```
forward_return = (close[t + horizon] - close[t]) / close[t]
target = forward_return / atr_pct[t]
```

ATR normalization makes targets comparable across assets and volatility regimes. A +1.5 target means "expecting a move of 1.5x current ATR" regardless of whether that's BTC or WIF.

**Horizon**: Configurable per timeframe. Default 48 for 15m (24 hours ahead), 24 for 1H.

**ATR safety guard**: Skip samples where `atr_pct < 1e-6` when computing targets. This covers the first ~14 candles (ATR warmup) and rare flat-price periods mid-series where division would produce infinite or wildly inflated targets.

**SL/TP secondary targets**: Kept as ATR-multiplier regression (MAE/MFE). Only computed for samples where `abs(forward_return) > noise_floor` (default 0.3 ATR) to avoid learning noise levels from flat candles. For reference, ~70-80% of 15m candles across all pairs exceed 0.3 ATR forward movement over a 48-candle horizon, so the SL/TP training set remains substantial.

**What this eliminates**: `LabelConfig.threshold_pct`, per-class imbalance, focal loss, class weights, `WeightedRandomSampler`, temperature scaling, geometric balanced accuracy.

### 2. Feature Pipeline

Three changes to feature engineering.

**Warmup row removal**: Track the maximum indicator lookback (200 candles for EMA(200)) and slice off warmup rows before training. With ~20K 15m candles, losing 200 is ~1% of data. The actual warmup count is computed dynamically as `max(lookback for each selected feature)` — if feature selection drops EMA(200), warmup shrinks accordingly.

**Redis cache increase**: The current cache holds 200 candles per pair per timeframe (hardcoded in 5 locations in `main.py`). This must increase to **300** to accommodate warmup (up to 200) + seq_len (50) + buffer. During inference: require `warmup + seq_len` candles available. Return None if insufficient.

**Z-score standardization**: After winsorization (1st/99th percentile, kept), compute per-feature mean and std over the training window. Apply `(x - mean) / std`. Store stats in the model config sidecar JSON for inference to use the same transform.

**Feature selection**: Integrated into the walk-forward training pipeline. After fold 1 trains on all features, run permutation importance on its validation set. Drop features contributing less than 1% of total importance. Folds 2 and 3 then train using only the selected feature subset. This avoids a separate preliminary training step — fold 1 serves double duty as both the first ensemble member and the feature selector. The selected feature list becomes per-pair and is stored in the config sidecar.

**15m as primary training data**: Train on 15m candles (~19,998 samples vs 8,942 for 1H). This roughly doubles effective training data. 1H training remains available but is not the default.

### 3. Model Architecture

`SignalLSTMv2` — smaller, regression-first.

```
Input: (batch, 50, n_features)
  |
  v
InputNorm: per-feature BatchNorm1d (unchanged)
  |
  v
LSTM(hidden=96, layers=2, dropout=0.3)
  |
  v
TemporalAttention (unchanged)
  + Multi-scale pooling: avg of last [5, 10, 25] steps (unchanged)
  + Project concatenated [96*4] -> 96
  |
  v
Primary head: Linear(96, 48) -> ReLU -> Linear(48, 1)
  Output: predicted ATR-normalized forward return (no activation)
  |
  v
Secondary head: Linear(96, 48) -> ReLU -> Linear(48, 3) -> ReLU
  Output: sl_atr, tp1_atr, tp2_atr (non-negative)
```

**Parameter count**: ~80-100K (down from ~600K). With ~19K training samples, this gives ~190 samples/param.

**Preserved**: Temporal attention, multi-scale pooling, input BatchNorm, MC dropout (5 passes), noise injection (0.02 std during training only).

**Removed**: Classification head, temperature scaling, 3-class softmax.

**Loss function**:
```
loss = huber(return_pred, return_target, delta=1.0)
     + 0.3 * smooth_l1(sltp_pred, sltp_target)   [non-noise samples only]
```

### 4. Training Pipeline

**Walk-forward 3-fold validation** (replaces overlapping temporal splits):

```
Fold 1: train [0%, 60%]  -> val [60%, 75%]
Fold 2: train [0%, 75%]  -> val [75%, 90%]
Fold 3: train [0%, 90%]  -> val [90%, 100%]
```

Each fold produces one ensemble member, validated on genuinely unseen future data. This naturally creates the 3-member ensemble.

**Training config**:

| Parameter     | Current | New   |
|---------------|---------|-------|
| seq_len       | 100     | 50    |
| epochs        | 100     | 80    |
| batch_size    | 64      | 128   |
| lr            | 1e-3    | 5e-4  |
| warmup_epochs | 5       | 3     |
| patience      | 20      | 15    |
| min_epochs    | 40      | 30    |
| weight_decay  | 1e-4    | 1e-3  |

**Early stopping**: Validation Huber loss, patience 15, min_epochs 30.

**Directional accuracy gate**: Track `sign(pred) == sign(target)` on val set as a monitoring metric. If directional accuracy < 52% after min_epochs, abort that member. It's not learning signal.

**Ensemble quality gates** (applied after all folds complete):
- Val Huber loss < 2x best member's loss
- Directional accuracy > 52%
- Prediction std > 0.01 (not predicting a constant)

Members that fail are **excluded** from ensemble_config.json. A 2-member or 1-member ensemble is acceptable. If zero members pass, the pair gets no ML model.

### 5. Inference & Integration

**Prediction to ml_score**:
```
ml_score = clamp(prediction * 40, -100, 100)
```

A +2.5 ATR prediction saturates at +100. A +0.5 ATR prediction maps to +20 (mild signal).

**Confidence calculation**:
```
base_confidence = sigmoid(abs(prediction) / uncertainty - 1.0)
```

Gives ~0.5 at break-even (magnitude = uncertainty), higher when the model is sure.

**Two penalties only** (multiplicative):
- Drift penalty: PSI-based, 0.3 or 0.6 reduction (unchanged)
- Staleness penalty: >14 days capped at 0.3 (unchanged)

Removed: age penalty (redundant with staleness), missing feature penalty (unnecessary — z-score fills missing with 0/mean, prediction magnitude shrinks naturally).

**Blend threshold**: 0.65 -> **0.40**. Adaptive weight ramp:
```
if confidence < 0.40: return indicator_score  # ignore ML
t = (confidence - 0.40) / 0.40
ml_weight = 0.2 + 0.3 * t   # range [0.2, 0.5]
blended = indicator * (1 - ml_weight) + ml_score * ml_weight
```

**SL/TP**: Secondary head predictions flow into `calculate_levels()` priority cascade unchanged (ML regression -> LLM explicit -> ATR defaults). Guardrails unchanged.

**Fallback**: If pair has no viable model, `blend_with_ml()` receives None and returns the indicator score. Same interface as today.

### 6. File Changes

| File | Change |
|------|--------|
| `ml/labels.py` | New `generate_regression_targets()`. Params: horizon, noise_floor. Returns forward_return (ATR-normalized) + SL/TP targets. Old function kept but unused. |
| `ml/features.py` | Add `drop_warmup_rows()`, `compute_standardization_stats()`, `apply_standardization()`. Feature selection via importance threshold. |
| `ml/model.py` | New `SignalLSTMv2`. Primary: 1 return output. Secondary: 3 SL/TP outputs. hidden=96, layers=2. |
| `ml/trainer.py` | Huber loss. Walk-forward 3-fold. New early stopping on val loss + directional accuracy gate. Quality gate logic. |
| `ml/dataset.py` | `CandleDataset` takes regression targets. Remove class fields. |
| `ml/data_loader.py` | Call `generate_regression_targets()`. Return standardization stats. |
| `ml/predictor.py` | New `RegressionPredictor`. Maps prediction -> score/confidence. Simplified penalties. |
| `ml/ensemble_predictor.py` | Adapt to regression. Member quality gate on load. |
| `ml/drift.py` | No changes. |
| `ml/utils.py` | Remove `geometric_balanced_accuracy()`. Add `directional_accuracy()`. |
| `engine/combiner.py` | Threshold 0.65 -> 0.40. Update weight ramp. Update `compute_agreement()` to accept numeric ml_score (derive direction from sign). |
| `engine/backtester.py` | Pass `ml_weight_min`/`ml_weight_max` from config to `blend_with_ml()` instead of using stale constant defaults. |
| `config.py` | Updated defaults: `ml_confidence_threshold` 0.65 -> 0.40, `engine_ml_weight_min` 0.05 -> 0.20, `engine_ml_weight_max` 0.30 -> 0.50. New: `ml_seq_len=50`. |
| `main.py` | Redis cache size 200 -> 300 in all 5 `lrange`/`ltrim` locations. |

**Unchanged interfaces**: `blend_with_ml()` signature (ml_score, ml_confidence), `calculate_levels()` (ATR multipliers), WebSocket broadcasts, API endpoints.

**Changed schema**: `ensemble_config.json` per-member fields update:
- **Removed**: `temperature`, `precision_per_class`, `recall_per_class`, `direction_accuracy` (classification-specific)
- **Added**: `val_huber_loss`, `directional_accuracy` (sign-based), `prediction_std`, `excluded` (bool, quality gate result)
- **Kept**: `index`, `trained_at`, `val_loss`, `best_epoch`, `total_epochs`, `data_range`
- Consumers to update: `EnsemblePredictor.__init__`, `_reload_predictors()` in `api/ml.py`

### 7. Success Criteria

The overhaul is successful if:

1. **At least 2 of 3 pairs** produce ensemble models that pass quality gates (directional accuracy > 52%, prediction std > 0.01)
2. **Best pair achieves > 55% directional accuracy** on walk-forward validation (current best is ETH at ~53% with classification — regression should match or exceed this)
3. **ML confidence exceeds 0.40 for > 20% of live candles** — meaning ML actually contributes to signal blending, unlike today where it contributes to 0%
4. **No pair is worse off** — pairs where ML fails quality gates get no model (ML returns None), which is equivalent to today's effective behavior. The pipeline never degrades.

If all three pairs fail quality gates after the first training run, investigate feature selection and hyperparameters before concluding the approach doesn't work. The regression formulation is sound; the question is whether the data contains learnable signal.

### 8. Testing

- **Unit: `generate_regression_targets()`** — ATR normalization correctness, horizon handling, NaN-free output, noise_floor filtering for SL/TP
- **Unit: feature standardization** — zero-mean/unit-variance after transform, stored stats match, inference reproduces training transform
- **Unit: `SignalLSTMv2`** — output shapes (batch, 1) and (batch, 3), gradient flow, MC dropout produces variance > 0
- **Unit: quality gates** — member exclusion when loss/accuracy thresholds fail, degenerate prediction detection
- **Unit: confidence formula** — sigmoid behavior at break-even, penalty multiplication, threshold gating
- **Integration: end-to-end** — `build_feature_matrix()` -> `generate_regression_targets()` -> `CandleDataset` -> forward pass -> score/confidence mapping
- **Update existing**: `test_ml.py` and `test_ml_health.py` for new model format

### 9. Rollout

Old classification checkpoints are incompatible with the new predictor. This is a clean break:

1. Deploy new code
2. Trigger training run on 15m data for all 3 pairs
3. New checkpoints written to `models/<pair>/`
4. If training produces no viable members for a pair, ML returns None (same as current effective behavior)
5. Old `.pt` files can be cleaned up after confirming new models load

No shadow mode or gradual rollout — the current ML is already contributing zero signal in production.
