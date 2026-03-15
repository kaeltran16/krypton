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
Veto:       if LLM contradicts → do not emit (hard veto)
Final:      apply LLM adjustment → threshold check (engine_signal_threshold) → emit
SL/TP:      use ML regression if available, else ATR defaults; tighten SL on LLM caution
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
- TP2 maximum: 8.0 x ATR (`ml_tp2_max_atr`) — prevents unreachable targets from model outliers
- Risk/reward floor: TP1/SL >= 1.0 (`ml_rr_floor`)

Values are clamped to these bounds after reading from the ML model output, before computing price levels.

**Data flow for ML regression outputs:** After `ensemble.py` is deleted, the ML regression values (`sl_atr`, `tp1_atr`, `tp2_atr`) are sourced directly from `ml_predictor.predict()` return dict. The pipeline passes these values to `calculate_levels()` alongside the ATR value. No intermediate layer is needed — the predictor already returns these fields.

**Extended `calculate_levels()` signature:**

```python
def calculate_levels(
    direction: str,                    # "LONG" or "SHORT"
    current_price: float,
    atr: float,
    llm_levels: dict | None = None,    # optional LLM-provided levels (highest priority)
    ml_atr_multiples: dict | None = None,  # {"sl_atr": float, "tp1_atr": float, "tp2_atr": float}
    llm_opinion: str | None = None,    # "confirm", "caution", or "contradict"
    sl_bounds: tuple[float, float] = (0.5, 3.0),   # (ml_sl_min_atr, ml_sl_max_atr)
    tp1_min_atr: float = 1.0,
    tp2_max_atr: float = 8.0,
    rr_floor: float = 1.0,
    caution_sl_factor: float = 0.8,
) -> dict:
```

**Level selection priority:** LLM explicit levels (if validated) > ML regression multiples (clamped to safety bounds) > ATR defaults (1.5 / 2.0 / 3.0). When using ML or ATR defaults and `llm_opinion == "caution"`, the SL distance is multiplied by `caution_sl_factor` (tightened) before computing the price level.

LLM override still applies: if the LLM provides custom SL/TP levels that pass validation, those take precedence (and caution tightening does not apply, since the LLM already expressed its view through the explicit levels).

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

No change to LLM response format (confirm/caution/contradict with confidence). The existing `compute_final_score()` adjustments apply to the blended score, with two additional behaviors preserved from `ensemble.py`:

**LLM contradict = hard veto:** If the LLM opinion is "contradict", the signal is **not emitted**, regardless of the final score. This preserves the current `ensemble.py` behavior where contradict is a hard veto. The hard veto check happens in `run_pipeline()` after `compute_final_score()` returns and before the `engine_signal_threshold` comparison. `compute_final_score()` itself is unchanged — the veto is an explicit `if llm_opinion == "contradict": return` guard.

**LLM caution = SL tightening:** If the LLM opinion is "caution" and the LLM does not provide its own explicit levels, the SL distance is tightened by a configurable multiplier `llm_caution_sl_factor` (default 0.8, i.e., 20% tighter). This preserves the current `ensemble.py` behavior (`sl_atr * 0.8`). The tightening is applied in `calculate_levels()` after selecting the SL source (ML or ATR default) and before computing the price level.

**LLM gate behavioral change:** Previously, the ML path used `ml_llm_threshold` (a 0-1 float compared against ML confidence) while the indicator path used `engine_llm_threshold` (an int compared against -100 to +100 score). In the unified pipeline, only `engine_llm_threshold` is used, compared against the blended score. This means the LLM gate triggers based on overall signal strength rather than ML confidence alone. Threshold tuning may be needed after rollout.

**Signal emission threshold:** The unified pipeline uses `engine_signal_threshold` (default 50) as the emission threshold, applied to the final score after LLM adjustment. With ML blending at 25% weight, the blended score distribution will shift slightly compared to indicator-only scores. Monitor signal emission rates after rollout and tune the threshold if needed.

### 5. Configuration

**New config fields:**
- `engine_ml_weight: float = 0.25` — ML weight in blended score
- `ml_sl_min_atr: float = 0.5` — Minimum SL distance in ATR
- `ml_sl_max_atr: float = 3.0` — Maximum SL distance in ATR
- `ml_tp1_min_atr: float = 1.0` — Minimum TP1 distance in ATR
- `ml_tp2_max_atr: float = 8.0` — Maximum TP2 distance in ATR
- `ml_rr_floor: float = 1.0` — Minimum TP1/SL ratio
- `llm_caution_sl_factor: float = 0.8` — SL tightening multiplier when LLM opinion is "caution"

**Temporary config fields (removed after rollout):**
- `engine_unified_shadow: bool = True` — shadow mode; unified pipeline logs but does not emit signals

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
- `main.py:run_pipeline()` — unified single path, ML blending step after indicator scoring, hard veto guard on LLM contradict before threshold check
- `combiner.py` — new `blend_with_ml()` function for the post-preliminary blending step; `calculate_levels()` extended with ML-driven SL/TP code path, safety clamping, and caution SL tightening
- LLM prompt template — unified template that includes all context sources
- `config.py` — new fields added, `ml_llm_threshold` removed

**Tests:**
- `backend/tests/ml/test_ensemble.py` — removed (ensemble.py deleted)
- `backend/tests/test_pipeline_ml.py` — rewritten to test unified pipeline behavior
- New tests for `blend_with_ml()` and ML-driven `calculate_levels()` in combiner tests
- New tests for LLM behavioral guarantees:
  - Hard veto: pipeline does not emit when LLM opinion is "contradict", even with a high blended score
  - Caution SL tightening: SL distance is multiplied by `llm_caution_sl_factor` when LLM is "caution" and no explicit LLM levels
  - Caution with LLM levels: tightening does not apply when LLM provides explicit levels
- New tests for agreement flag: same-sign → "agree", opposite-sign → "disagree", either zero → "neutral"
- Integration test: `run_pipeline()` with mocked ML predictor present vs absent, verifying blended score differs from indicator-only score and influences emission
- LLM prompt rendering test: verify the unified template includes ML context when available and omits it cleanly when not

**Signal model:** No schema changes. ML score stored in existing `raw_indicators` JSON dict.

**Note on position_scale:** The current `ensemble.py` returns a `position_scale` multiplier that was never used by the pipeline (`main.py` ignores it). This is intentionally not carried forward. Position sizing continues to use `PositionSizer` based on risk settings and SL distance.

### 8. Observability

The unified pipeline should log a single structured JSON line per signal evaluation:
```json
{
  "pair": "BTC-USDT-SWAP", "timeframe": "1H",
  "tech_score": 45, "flow_score": 20, "onchain_score": null, "pattern_score": 10,
  "ml_score": 72, "ml_confidence": 0.82,
  "indicator_preliminary": 38, "blended_score": 47, "final_score": 52,
  "llm_opinion": "confirm", "ml_available": true,
  "agreement": "agree", "emitted": true
}
```

Null values indicate the source was unavailable. This replaces the separate log lines currently used by the ML and indicator paths.

### 9. Rollout Strategy

To safely transition from the dual-path to unified pipeline in a live trading system:

**Shadow mode (first deployment):** Add a `engine_unified_shadow: bool = True` config flag. When enabled, the unified pipeline runs and logs its full evaluation (Section 8), but **signal emission is suppressed** — signals are logged with `"shadow": true` but not persisted or broadcast. The old dual-path pipeline continues to emit signals as before. This allows comparing unified pipeline decisions against the production path without risk.

**Comparison logging:** During shadow mode, the log line includes an additional field `"old_path_would_emit": bool` computed by running the legacy decision logic (ML shortcut or rule-based) on the same inputs. Divergences between `emitted` and `old_path_would_emit` are logged at WARN level for review.

**Cutover:** Once shadow mode logs show acceptable divergence rates (reviewed manually), set `engine_unified_shadow = false` to activate the unified pipeline and remove the old dual-path code. The shadow flag and comparison logging are temporary — remove them in a follow-up cleanup after the transition period.

## Out of Scope

- Retraining the ML model (existing training pipeline works as-is)
- Frontend changes (signal display is unchanged; scores are still -100 to +100)
- Changes to outcome resolution logic
- Changes to the ML feature engineering or model architecture
