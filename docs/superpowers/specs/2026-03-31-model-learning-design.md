# Section 2: Model and Learning — Design Spec

**Date:** 2026-03-31
**Scope:** Deep Ensemble (2.1) + Learned Regime Classifier (2.2) + ML Health Frontend
**Success criteria:** Ensemble calibration ECE ≤ 0.08 on holdout; regime classifier macro F1 ≥ 0.65 on last-20% holdout (fall back to heuristic if below)

---

## 1. Deep Ensemble to Replace MC Dropout (2.1)

### Problem

MC dropout with 5 passes estimates uncertainty within one model's representation. It cannot detect out-of-distribution inputs — when the market enters an unseen regime, dropout variance barely changes. The ML gate passes signals at full weight when it should be most skeptical.

### Solution

Train 3 `SignalLSTM` instances per pair on overlapping temporal splits. At inference, run all three forward passes (no dropout) and use inter-model disagreement as the uncertainty estimate.

### Training

**Temporal splits (per pair):**
- Member 0: candles 0–80%
- Member 1: candles 10–90%
- Member 2: candles 20–100%

Overlapping windows ensure each model sees a different regime mix while still sharing enough data for convergence.

**Minimum data:** Each temporal slice must yield ≥ `seq_len * 2` (100) samples after NEUTRAL subsampling. If a slice fails this check, skip that member. A 2-member ensemble is valid (see Partial Load below). If fewer than 2 slices are viable, fall back to single-model training.

**Training flow:**
- New `train_ensemble()` function in `trainer.py` that loops over 3 temporal splits
- Members are independent — train in parallel via thread pool (`asyncio.gather` + `to_thread`) for ~3x speedup vs. sequential
- Calls refactored `train_one_model()` (extracted from current `train()`) for each member
- Same `TrainConfig` hyperparams across all members — only the data slice differs
- Temperature scaling applied per member independently
- Class rebalancing (NEUTRAL subsampling) applied within each slice

**Checkpoint format:**
```
models/btc_usdt_swap/
  ensemble_0.pt
  ensemble_1.pt
  ensemble_2.pt
  ensemble_config.json
```

**`ensemble_config.json` schema:**
```json
{
  "n_members": 3,
  "input_size": 24,
  "hidden_size": 128,
  "num_layers": 2,
  "seq_len": 50,
  "feature_names": ["ret", "body_ratio", "..."],
  "members": [
    {
      "index": 0,
      "trained_at": "2026-03-31T12:00:00",
      "val_loss": 0.42,
      "temperature": 1.1,
      "data_range": [0.0, 0.8]
    },
    {
      "index": 1,
      "trained_at": "2026-03-31T12:05:00",
      "val_loss": 0.39,
      "temperature": 1.05,
      "data_range": [0.1, 0.9]
    },
    {
      "index": 2,
      "trained_at": "2026-03-31T12:10:00",
      "val_loss": 0.41,
      "temperature": 1.08,
      "data_range": [0.2, 1.0]
    }
  ],
  "flow_used": true,
  "regime_used": true,
  "btc_used": false
}
```

**Checkpoint atomicity:** Write all member `.pt` files + `ensemble_config.json` to a staging directory (`<pair>/.ensemble_staging/`), then atomic-rename to replace the live directory contents. This prevents `_reload_predictors()` from seeing a half-written ensemble.

**Backward compatibility:** Predictor loading detects `ensemble_config.json` → `EnsemblePredictor`. Falls back to `model_config.json` → legacy single-model `Predictor` with MC dropout.

### Inference

**New `EnsemblePredictor` class in `predictor.py`:**

1. Load all 3 member models from checkpoint directory
2. Feature mapping and window extraction (same as current Predictor)
3. Forward pass through all 3 members in `.eval()` mode (no dropout)
4. Weighted aggregation using per-member staleness decay:

```python
def model_weight(age_days):
    if age_days <= 7:
        return 1.0
    elif age_days <= 21:
        return 1.0 - (age_days - 7) / 14 * 0.7  # decays to 0.3
    else:
        return 0.3
```

Weights normalized to sum to 1. Mean probs and mean regression computed as weighted averages.

5. Uncertainty from disagreement:
```python
disagreement = weighted_var(all_probs, weights).mean()
uncertainty_penalty = min(1.0, disagreement * settings.ensemble_disagreement_scale)
confidence = raw_confidence * (1.0 - uncertainty_penalty)
```

`ensemble_disagreement_scale` defaults to 8.0 (configurable via `PipelineSettings`). Lower than MC dropout's 10 because ensemble disagreement is a stronger signal — inter-model variance is inherently larger than intra-model dropout variance. Expected `disagreement` range: 0.01–0.15 for in-distribution inputs, 0.15–0.40 for regime transitions.

6. Output dict — identical shape to current `Predictor.predict()`:
```python
{
    "direction": "LONG" | "SHORT" | "NEUTRAL",
    "confidence": float,
    "sl_atr": float,
    "tp1_atr": float,
    "tp2_atr": float,
    "ensemble_disagreement": float  # new field (mc_variance was never persisted)
}
```

The combiner's `blend_with_ml()` reads `ml_score` and `ml_confidence` (derived from the prediction dict before calling blend), so the new field is non-breaking. `mc_variance` was computed by the old `Predictor` but never stored in signal metadata or `raw_indicators` — only used in tests. The new `ensemble_disagreement` field is stored in signal `raw_indicators` JSONB for diagnostics. Legacy single-model `Predictor` continues to return `mc_variance` for its own test coverage.

**Partial load behavior:**
- **3/3 members loaded:** Full ensemble inference as described above.
- **2/3 members loaded:** Weighted average of 2 members. Confidence capped at `0.5` (reduced trust). Log warning.
- **1/3 members loaded:** Fall back to single-model mode (same as legacy `Predictor` with MC dropout on that one model).
- **0/3 members loaded:** Pair marked as ML-unavailable. `blend_with_ml()` receives `None` confidence and skips ML blending.

### Loading

`_reload_predictors()` checks for `ensemble_config.json` first → loads `EnsemblePredictor`. Falls back to `model_config.json` → loads legacy `Predictor`. Same dict key in `app.state.ml_predictors`, same `.predict()` interface.

---

## 2. Learned Regime Classifier (2.2)

### Problem

The current regime detector uses two hard-coded indicators (ADX and BB width). It cannot use order flow or on-chain features, and it lags regime transitions by several candles due to 0.3 EMA smoothing.

### Solution

Train a LightGBM multiclass classifier on retrospectively labeled regime data. Outputs 4-class probabilities (`trending`, `ranging`, `volatile`, `steady`) that serve as a drop-in replacement for the current `compute_regime_mix()` return value.

### New Module: `engine/regime_classifier.py`

**Features (~11 engineered from candle data + optional flow):**
- ADX, ADX delta (5-candle), ADX delta (10-candle)
- BB width, BB width delta (5-candle)
- ATR percent, ATR percent delta (5-candle)
- Volume trend (10-candle OBV slope)
- Funding rate change (if available)
- OI change percent (if available)
- Ensemble disagreement from 2.1 (if available)

Simple tabular input, no sequence dimension.

### Retrospective Label Generation (`engine/regime_labels.py`)

For each candle, look forward 48 candles (configurable via `horizon` param):
- **Trending:** directional move > 2x ATR with expanding or stable volatility
- **Steady:** directional move > 1.5x ATR with contracting volatility (strong trend, low vol)
- **Volatile:** ATR expands > 1.5x without sustained direction (> 1.5x ATR)
- **Ranging:** none of the above (price within 1x ATR band, stable or contracting vol)

4 classes match the existing `compute_regime_mix()` return shape (`trending`/`ranging`/`volatile`/`steady`). Hard label = dominant class. LightGBM `predict_proba()` outputs become the soft mix at inference.

**Minimum data:** Requires ≥ 500 candles across all pairs combined (after dropping the last `horizon` candles that lack forward labels). If below threshold, training endpoint returns 400 with message.

### Training

- **Single global model** (not per-pair) — regime behavior is more universal than directional prediction. Pooling all pairs gives 3x the training data.
- `lightgbm.LGBMClassifier` with `objective='multiclass'`, `num_class=4`
- Checkpoint: `models/regime/regime_classifier.joblib` + `regime_config.json` (feature names, training timestamp, per-class precision/recall/F1, macro F1, confusion matrix)

### Integration with `engine/regime.py`

- `compute_regime_mix()` checks if `app.state.regime_classifier` exists
- If yes: build feature row → `predict_proba()` → returns `{"trending": 0.6, "ranging": 0.25, "volatile": 0.10, "steady": 0.05}`
- If no: existing ADX + BB width heuristic (unchanged)
- Return type is identical (4-key dict summing to 1.0) — downstream consumers (combiner, weight tables) are unaffected

**Staleness:** If the regime model is older than 30 days, fall back to the heuristic. Regime dynamics shift slower than directional prediction, so the window is wider than the ensemble's 21-day decay.

**Interaction with `RegimeWeights`:** The `RegimeWeights` per-pair optimization system (caps + outer weights learned via `regime_optimizer.py`) continues to operate as an override layer on top of the classifier's output. `blend_caps(regime_mix, regime_weights)` and `blend_outer_weights(regime_mix, regime_weights)` work identically regardless of whether `regime_mix` came from the heuristic or the classifier. However, existing `RegimeWeights` entries were optimized against the heuristic's regime distribution. After deploying the classifier, trigger a full `regime_optimizer` re-run for all pairs to re-learn caps/weights against the new regime source. Until re-optimization, existing weights remain valid but suboptimal.

---

## 3. API Endpoints

### Modified: `POST /api/ml/train`

Existing endpoint internals change to call `train_ensemble()` instead of single-model `train()`. Request shape unchanged. `MLTrainingRun` result JSONB stores per-member metrics (val_loss, data_range, temperature) alongside existing per-pair results.

### Modified: `POST /api/ml/reload`

Detects `ensemble_config.json` and loads `EnsemblePredictor` automatically. Falls back to legacy single-model loading.

### New: `POST /api/regime/train`

Accepts optional overrides:
```json
{
  "lookback_days": 90,
  "horizon": 48
}
```

Pulls candle data for all pairs, generates retrospective labels, trains LightGBM. Returns 400 if fewer than 500 candles available. Returns training metrics (macro F1, per-class precision/recall, confusion matrix). If macro F1 < 0.65 on holdout, logs warning and does NOT promote the model — keeps existing classifier or heuristic.

### New: `GET /api/ml/health`

Returns ML subsystem health:
```json
{
  "ml_health": {
    "ensemble": {
      "members_loaded": 3,
      "members_stale": 0,
      "oldest_member_days": 5
    },
    "regime_classifier": {
      "active": true,
      "age_days": 12,
      "fallback": false
    }
  }
}
```

---

## 4. Frontend — ML Health Indicator

**Location:** `SystemDiagnostics.tsx` — replace the current single-number `ml_models_loaded` display in the Data Freshness section with the detailed ensemble + classifier rows below.

**API client:** New `getMLHealth()` method in `shared/lib/api.ts` calling `GET /api/ml/health`.

**Component:** `MLHealthStatus` component in the engine or system feature:
- **Ensemble row:** "3/3 models loaded" (green) / "2/3 models loaded, 1 stale" (yellow) / "No models" (red)
- **Regime row:** "Classifier active" (green) / "Using heuristic fallback" (yellow)

Uses existing Badge/status dot patterns from shared components. No new UI primitives.

**Data fetching:** Fetch on mount + refresh when navigating to the page. No continuous polling.

---

## 5. Dependencies

- **New Python dependency:** `lightgbm>=4.0.0` (for regime classifier)
- **New system dependency:** `libgomp1` — add to Dockerfile `apt-get install` line (required by LightGBM's OpenMP runtime)
- **No new frontend dependencies**

## 6. New Config Keys

Added to `PipelineSettings` (runtime-tunable):
- `ensemble_disagreement_scale: float = 8.0` — multiplier for disagreement → confidence penalty

No new keys needed for regime classifier — staleness (30d) and min-quality (F1 ≥ 0.65) are hardcoded constants in the classifier module.

## 7. What Doesn't Change

- `blend_with_ml()` interface — same inputs (`ml_score`, `ml_confidence`), just receives better confidence values
- `compute_regime_mix()` return type — same 4-key dict shape (`trending`/`ranging`/`volatile`/`steady`)
- `RegimeWeights` per-pair override system — continues as a layer on top of regime mix
- WebSocket signal broadcast — unchanged
- Signal persistence schema — `ensemble_disagreement` goes into existing `raw_indicators` JSONB
- Existing config keys (`ml_confidence_threshold`, `ml_weight_min/max`, etc.)

## 8. Deployment Checklist

1. Deploy code + rebuild Docker image (picks up `libgomp1` + `lightgbm`)
2. Call `POST /api/ml/train` — trains 3-member ensembles per pair (parallel members, ~15-30 min)
3. Call `POST /api/regime/train` — trains global regime classifier (~2-5 min)
4. Trigger `regime_optimizer` re-run for all pairs to re-learn caps/weights against classifier output
5. Verify via `GET /api/ml/health` — all ensemble members loaded, classifier active
