# Unified ML + Indicator Signal Pipeline

**Date:** 2026-03-13
**Status:** Approved

## Problem

The current signal engine has two mutually exclusive paths: when ML models are loaded, the ML path runs and skips all indicator-based scoring. When ML is unavailable, only indicators run. The two never work together, which wastes information and forces an all-or-nothing choice between interpretability (indicators) and learned patterns (ML).

## Solution

Merge both paths into a single unified pipeline where indicators always run, ML contributes an additional score when available, and the ML model's regression outputs drive SL/TP placement instead of fixed ATR multipliers.

## Design

### 1. Pipeline Restructuring

**New flow:**

```
Always:     indicators → tech + flow + pattern + onchain scores
If ML:      ML predict → direction + confidence + SL/TP regression
Combine:    blended_score = weighted_sum(indicator_preliminary, ml_score)
LLM gate:   if |blended_score| >= llm_threshold → LLM opinion
Final:      apply LLM adjustment → threshold check → emit
SL/TP:      use ML regression if available, else ATR defaults
```

Key changes:
- Indicators always run, regardless of whether ML is loaded.
- ML runs alongside indicators and contributes a score, not a shortcut path.
- Single combine step merges everything before the LLM gate.
- LLM sees both indicator scores and ML prediction for richer context.

### 2. Score Blending Logic

**ML output to score conversion (-100 to +100):**

| ML Direction | Score |
|---|---|
| NEUTRAL | 0 |
| LONG | +confidence x 100 (e.g., 0.82 -> +82) |
| SHORT | -confidence x 100 (e.g., 0.75 -> -75) |

**ML confidence gating:** ML score only contributes to the blend when confidence >= `ml_confidence_threshold` (default 0.65). Below this threshold, the ML score is treated as 0 (effectively unavailable). This prevents low-confidence noise from polluting the indicator signal.

**Blending formula:**

Blending happens as a separate step AFTER `compute_preliminary_score()` returns the indicator-only score. This keeps the existing adaptive weight redistribution logic for indicators untouched.

```python
# Step 1: Indicator preliminary (existing logic, unchanged)
indicator_preliminary = compute_preliminary_score(
    tech_score, flow_score, onchain_score, pattern_score,
    tech_weight, flow_weight, onchain_weight, pattern_weight
)
# Adaptive redistribution still applies here when sources are missing

# Step 2: Blend with ML (new step, outside compute_preliminary_score)
if ml_score is not None and ml_confidence >= ml_confidence_threshold:
    blended = indicator_preliminary * (1 - engine_ml_weight) + ml_score * engine_ml_weight
else:
    blended = indicator_preliminary  # current behavior
```

Default `engine_ml_weight` = 0.25. The indicator weights (tech 40%, flow 22%, onchain 23%, pattern 15%) are the defaults before adaptive redistribution — when a source is unavailable, its weight is zeroed and the remaining indicator weights are renormalized to sum to 1.0. This happens independently of the ML weight, which operates on the already-normalized indicator preliminary.

**Rationale for 25% default:** ML is trained on the same underlying data as the indicators. Too much weight would double-count. 25% is enough to tip borderline signals when ML agrees, or dampen them when ML disagrees. Users can tune upward if the model proves accurate.

Agreement/disagreement is handled naturally by the math. The LLM also sees both raw values and can flag disagreements explicitly.

### 3. ML-Driven SL/TP Levels

When ML prediction is available and confidence >= `ml_confidence_threshold`:
```
SL  = entry +/- ml.sl_atr x ATR
TP1 = entry +/- ml.tp1_atr x ATR
TP2 = entry +/- ml.tp2_atr x ATR
```

Otherwise, fall back to current fixed multipliers (1.5 / 2.0 / 3.0 x ATR).

**Safety bounds** (applied in `combiner.py:calculate_levels()` when using ML-driven values):
- SL minimum: 0.5 x ATR (`ml_sl_min_atr`)
- SL maximum: 3.0 x ATR (`ml_sl_max_atr`)
- TP1 minimum: 1.0 x ATR (`ml_tp1_min_atr`)
- TP2 minimum: TP1 x 1.2
- Risk/reward floor: TP1/SL >= 1.0 (`ml_rr_floor`)

Values are clamped to these bounds after reading from the ML model output, before computing price levels.

**Data flow for ML regression outputs:** After `ensemble.py` is deleted, the ML regression values (`sl_atr`, `tp1_atr`, `tp2_atr`) are sourced directly from `ml_predictor.predict()` return dict. The pipeline passes these values to `calculate_levels()` alongside the ATR value. No intermediate layer is needed — the predictor already returns these fields.

LLM override still applies: if the LLM provides custom SL/TP levels that pass validation, those take precedence.

### 4. LLM Prompt Enhancement

Single unified prompt that includes all available context:

```
Context provided to LLM:
+-- Indicator scores (always)
|   +-- Technical: score + breakdown (EMA, MACD, RSI, BB)
|   +-- Order flow: score + breakdown (funding, OI, L/S ratio)
|   +-- Pattern: score + detected patterns list
|   +-- On-chain: score + breakdown (netflow, whales, NUPL)
+-- ML prediction (when available)
|   +-- Direction + confidence
|   +-- Suggested SL/TP ATR multipliers
+-- Blended preliminary score
+-- Agreement flag (indicators and ML agree/disagree on direction)
+-- News context (when available)
```

**Agreement flag definition:** "agree" if indicator_preliminary and ml_score have the same sign (both positive or both negative). "disagree" if they have opposite signs. "neutral" if either is zero.

No change to LLM response format (confirm/caution/contradict with confidence). The existing `compute_final_score()` adjustments apply to the blended score.

**LLM gate behavioral change:** Previously, the ML path used `ml_llm_threshold` (a 0-1 float compared against ML confidence) while the indicator path used `engine_llm_threshold` (an int compared against -100 to +100 score). In the unified pipeline, only `engine_llm_threshold` is used, compared against the blended score. This means the LLM gate triggers based on overall signal strength rather than ML confidence alone. Threshold tuning may be needed after rollout.

### 5. Configuration

**New config fields:**
- `engine_ml_weight: float = 0.25` — ML weight in blended score
- `ml_sl_min_atr: float = 0.5` — Minimum SL distance in ATR
- `ml_sl_max_atr: float = 3.0` — Maximum SL distance in ATR
- `ml_tp1_min_atr: float = 1.0` — Minimum TP1 distance in ATR
- `ml_rr_floor: float = 1.0` — Minimum TP1/SL ratio

**Removed during implementation:**
- `ml_llm_threshold` — currently defined in `config.py` and used in `main.py`; to be removed and consolidated into the single `engine_llm_threshold`

**Existing fields retained:**
- `ml_enabled` — controls whether ML models are loaded at startup
- `ml_confidence_threshold` — gates both ML score contribution to blend AND ML SL/TP usage
- All indicator weights unchanged

### 6. Backward Compatibility

- `ml_enabled = false` -> identical to current behavior
- `ml_enabled = true` but no model trained -> predictor dict is empty (no checkpoint files found by `_reload_predictors`), so `ml_predictor` is None for that pair; the blending step's else branch runs and `blended = indicator_preliminary` unchanged
- `engine_ml_weight = 0` -> explicitly disables ML contribution even if models are loaded
- `traditional_score` field in Signal will now always be populated (previously set to 0 on the ML path). Historical signals may have `traditional_score = 0` from the old ML path.

### 7. Code Changes

**Removed:**
- `backend/app/ml/ensemble.py` — separate ML ensemble logic replaced by unified combiner
- ML shortcut path in `main.py` (~lines 250-370)
- `ml_llm_threshold` config field

**Modified:**
- `main.py:run_pipeline()` — unified single path, ML blending step after indicator scoring
- `combiner.py` — new `blend_with_ml()` function for the post-preliminary blending step; `calculate_levels()` extended with ML-driven SL/TP code path and safety clamping
- LLM prompt template — unified template that includes all context sources
- `config.py` — new fields added, `ml_llm_threshold` removed

**Tests:**
- `backend/tests/ml/test_ensemble.py` — removed (ensemble.py deleted)
- `backend/tests/test_pipeline_ml.py` — rewritten to test unified pipeline behavior
- New tests for `blend_with_ml()` and ML-driven `calculate_levels()` in combiner tests

**Signal model:** No schema changes. ML score stored in existing `raw_indicators` JSON dict.

**Note on position_scale:** The current `ensemble.py` returns a `position_scale` multiplier that was never used by the pipeline (`main.py` ignores it). This is intentionally not carried forward. Position sizing continues to use `PositionSizer` based on risk settings and SL distance.

### 8. Observability

The unified pipeline should log a single summary line per signal evaluation:
```
pair, timeframe, tech_score, flow_score, onchain_score, pattern_score,
ml_score (or null), ml_confidence (or null), indicator_preliminary,
blended_score, final_score, llm_opinion (or null), ml_available (bool),
agreement (agree/disagree/neutral), emitted (bool)
```

This replaces the separate log lines currently used by the ML and indicator paths.

## Out of Scope

- Retraining the ML model (existing training pipeline works as-is)
- Frontend changes (signal display is unchanged; scores are still -100 to +100)
- Changes to outcome resolution logic
- Changes to the ML feature engineering or model architecture
