# Design: Direction-Neutral Scoring Architecture

**Date:** 2026-03-26
**Status:** Draft
**Scope:** Backend signal engine — `engine/traditional.py`, `main.py` pipeline, `engine/llm.py`, `prompts/signal_analysis.txt`
**Depends on:** Implemented specs: `2026-03-25-mr-pressure-scoring-bias-design.md`, `2026-03-26-order-flow-scoring-overhaul.md`

---

## Problem Statement

Despite previous fixes (mr_pressure dynamic caps, multiplicative volume, LLM prompt neutralization, order flow overhaul), the engine still produces 82% LONG for BTC, 73% LONG for ETH, and 74% SHORT for WIF. The longest same-direction streak is 47 signals.

Prior specs addressed exhaustion detection and flow data quality. This spec targets four structural asymmetries in the scoring math that those specs left intact.

### Root Cause Summary

The engine has five layers of scoring, but only one pushes counter-trend — and that layer is actively suppressed:

| Layer | Direction | Dampened during trends? |
|-------|-----------|------------------------|
| Tech: trend_score | With-trend | No |
| Flow: OI, CVD, book | With-trend | **No** |
| Flow: funding, L/S | Counter-trend | **Yes** (final_mult) |
| Confluence | With-trend | Only by mr_pressure |
| LLM | Pre-assigned with-trend | No |

Counter-trend signals cannot overcome with-trend signals because:

1. **trend_score uses binary DI direction** — DI+=16 vs DI-=15 produces the same +1 as DI+=35 vs DI-=10
2. **Flow dampening is asymmetric** — `final_mult` applies to contrarian components only (funding, L/S), while directional components (OI, CVD, book) contribute at full strength aligned with trend
3. **LLM is pre-assigned a direction** — told "evaluate this LONG setup" before analyzing
4. **Squeeze amplifies MR direction only** — in bearish conditions where RSI < 50, MR is positive (oversold) and squeeze amplifies the LONG push even when the dominant signal is bearish

---

## Changes

### Change 1: Continuous DI Direction

**Files:** `backend/app/engine/traditional.py`
**Location:** `compute_technical_score`, line computing `trend_score`

**Problem:** The trend_score direction is a binary switch:
```python
di_sign = 1 if di_plus_val > di_minus_val else -1
trend_score = di_sign * sigmoid_scale(adx_val, center=15, steepness=0.30) * caps["trend_cap"]
```

DI+=18 vs DI-=15 gives di_sign=+1 — same as DI+=35 vs DI-=10. During pullbacks, DI+ barely edges DI- but trend_score acts as if the trend is fully confirmed.

**Fix:** Replace binary switch with continuous DI spread through `sigmoid_score` (bipolar, -1 to +1):

```python
di_sum = di_plus_val + di_minus_val
di_spread = (di_plus_val - di_minus_val) / di_sum if di_sum > 0 else 0.0
di_direction = sigmoid_score(di_spread, center=0, steepness=DI_SPREAD_STEEPNESS)
trend_score = di_direction * sigmoid_scale(adx_val, center=15, steepness=sp.get("trend_score_steepness", 0.30)) * caps["trend_cap"]
```

`sigmoid_score` maps di_spread to [-1, +1]:
- DI+=35, DI-=10: spread=0.56, sigmoid ≈ +0.88 (strong bullish — close to current)
- DI+=22, DI-=15: spread=0.19, sigmoid ≈ +0.47 (moderate — half of current)
- DI+=16, DI-=15: spread=0.03, sigmoid ≈ +0.09 (near zero — currently +1.0)
- DI+=10, DI-=30: spread=-0.50, sigmoid ≈ -0.85 (strong bearish)

**New constant:** `DI_SPREAD_STEEPNESS` in `SIGMOID_PARAMS`, default `3.0`. At steepness=3.0:
- spread of ±0.5 produces ±0.88 (near saturation for clear trends)
- spread of ±0.1 produces ±0.29 (weak signal for ambiguous DI)

**Impact on `compute_trend_conviction`:** This function also uses binary `direction = 1 if di_plus > di_minus else -1`. Update it to accept the continuous `di_direction` value and use its sign for the direction comparisons (EMA alignment penalty, price confirmation). The conviction magnitude calculations remain unchanged.

**Downstream impact on `di_direction()` in `confluence.py`:** This function is a separate utility for confluence scoring (parent TF DI direction). It remains binary — confluence compares parent vs child alignment, where binary is appropriate. No change needed.

**Backward compatibility:** In strong trends (DI spread > 0.4), the sigmoid output is > 0.82, so trend_score drops by at most ~18%. In ambiguous conditions (DI spread < 0.15), trend_score drops dramatically — this is the intended fix. Threshold may need a 2-3 point reduction if signal emission rate drops for strong-trend scenarios. Monitor after deployment.

### Change 2: Uniform Flow Dampening

**Files:** `backend/app/engine/traditional.py`
**Location:** `compute_order_flow_score`, lines computing individual sub-scores

**Problem:** `final_mult` (conviction + regime dampening) applies only to funding and L/S:
```python
funding_score = sigmoid_score(-funding, ...) * FUNDING_MAX * final_mult  # dampened
ls_score = sigmoid_score(1.0 - ls, ...) * LS_MAX * final_mult            # dampened
oi_score = price_dir * sigmoid_score(oi_change, ...) * OI_MAX            # NOT dampened
cvd_score = sigmoid_score(cvd_normalized, ...) * CVD_MAX                 # NOT dampened
book_score = sigmoid_score(book_imbalance, ...) * BOOK_MAX               # NOT dampened
```

During strong trends, funding and L/S get multiplied by ~0.3-0.4 while OI, CVD, and book contribute at 100%. Net flow score is trend-following despite being conceptually "order flow."

**Fix:** Compute all sub-scores at full strength, then apply `final_mult` to the total:

```python
funding_score = sigmoid_score(-funding, center=0, steepness=funding_steepness) * FUNDING_MAX
oi_score = price_dir * sigmoid_score(oi_change, center=0, steepness=OI_STEEPNESS) * OI_MAX if price_dir != 0 else 0.0
ls_score = sigmoid_score(1.0 - ls, center=0, steepness=ls_steepness) * LS_MAX
cvd_score = ...  # unchanged computation
book_score = ...  # unchanged computation

total = (funding_score + oi_score + ls_score + cvd_score + book_score) * final_mult
```

**Rationale:** During strong trends, tech is the trend-following signal — it should dominate. Flow (all of it) should contribute less during high-conviction trends, and more during transitions/pullbacks when conviction drops. This makes the dampening direction-neutral: it doesn't selectively suppress counter-trend while amplifying with-trend.

**Impact:** In strong trends (final_mult ≈ 0.35), the total flow score shrinks uniformly. OI and CVD lose their current 100% contribution but the contrarian/directional mix remains balanced. During pullbacks (conviction drops, final_mult rises toward 1.0), all flow components contribute fully — including the contrarian signals that were previously suppressed.

**`details` dict:** Sub-scores in the returned `details` dict (`funding_score`, `oi_score`, `ls_score`, `cvd_score`, `book_score`) will store **pre-dampening** values — the raw contribution of each component before `final_mult` is applied. This is more useful for debugging and diagnostics. The dampened total is reflected in `score`. The `final_mult` value is already in `details` so callers can reconstruct `score ≈ round(sum(sub_scores) * final_mult)`.

**Backward compatibility:** The absolute flow contribution during strong trends will decrease (OI/CVD/book were previously undampened). This is intentional — those components were compounding the trend bias. The preliminary score will shift slightly toward tech during strong trends. No threshold change needed since both LONG and SHORT flow contributions shrink equally.

### Change 3: Direction-Independent LLM

**Files:** `backend/app/main.py` (pipeline), `backend/app/engine/combiner.py` (`compute_llm_contribution`), `backend/app/prompts/signal_analysis.txt`

**Problem:** The LLM is called with the blended score's direction pre-assigned:
```python
direction_label = "LONG" if blended > 0 else "SHORT"
# ... passed to render_prompt(direction=direction_label, ...)
```

The prompt tells the LLM "evaluate this LONG setup." `compute_llm_contribution` then scores factors as aligned/contra relative to this pre-assigned direction. The LLM becomes a confirmation bias amplifier — its job is to justify the direction it was given, not independently assess.

Previous spec `2026-03-22-long-bias-fix-design.md` softened the prompt anchoring but still passes `direction` to the template. The structural issue remains: the LLM's contribution is computed relative to a pre-assigned direction.

**Fix (three parts):**

**Part A — Prompt change** (`signal_analysis.txt`):

Remove all `{direction}` template variable usage. Two locations:

```diff
# Line 22
- Preliminary Indicator Score: {preliminary_score} (Direction: {direction})
+ Preliminary Indicator Score: {preliminary_score} (positive = bullish, negative = bearish)

# Line 30
- The quantitative signals produced a {direction} bias with score {blended_score}. Your job is to independently evaluate whether the data supports this direction, or if factors suggest caution or contradiction.
+ The quantitative signals produced a blended score of {blended_score} (positive = bullish, negative = bearish). Your job is to evaluate the evidence and determine which direction it supports. Assess factors for BOTH long and short scenarios — do not assume one direction.
```

**Part B — LLM contribution** (`combiner.py`):

`compute_llm_contribution` currently takes `direction` (from blended score) and scores each LLM factor as aligned/contra to that direction. Instead, derive direction from the LLM's own factor assessment:

```python
def compute_llm_contribution(
    factors: list[LLMFactor],
    factor_weights: dict[str, float],
    total_cap: float,
) -> int:
    total = 0.0
    for f in factors:
        weight = factor_weights.get(f.type.value, 0.0)
        sign = 1 if f.direction == "bullish" else (-1 if f.direction == "bearish" else 0)
        total += sign * weight * f.strength
    return round(max(-total_cap, min(total_cap, total)))
```

Each factor's direction (bullish/bearish) directly determines its sign. The LLM's net contribution emerges from the balance of bullish vs bearish factors, not from alignment with a pre-assigned direction.

**Part C — Caller changes** (`main.py`):

1. Remove `direction_label` from `compute_llm_contribution` call (drop the second positional arg).
2. Remove `direction=direction_label` from `render_prompt` call — the template no longer uses `{direction}`.
3. The `direction_label` variable itself can be removed unless used elsewhere in the pipeline (check for other references before deleting).

**Impact:** The LLM contribution can now push AGAINST the blended score direction. If the blended score is +25 (LONG) but the LLM identifies strong bearish factors (divergence, exhaustion, crowded positioning), its contribution will be negative, potentially flipping or weakening the signal. Previously, bearish factors in a LONG setup were scored as "contra-aligned" with sign=-1, which paradoxically added negative contribution but framed through the lens of "undermining the LONG thesis" rather than "supporting a SHORT thesis."

**Backward compatibility:** The `direction` parameter is removed from `compute_llm_contribution`. All callers must be updated. The LLM response schema (`LLMFactor`) already has `direction: str` on each factor — no schema change needed.

### Change 4: Squeeze Direction from Dominant Thesis

**Files:** `backend/app/engine/traditional.py`
**Location:** `compute_technical_score`, squeeze score computation

**Problem:**
```python
mean_rev_sign = 1 if mean_rev_score > 0 else (-1 if mean_rev_score < 0 else 0)
squeeze_score = mean_rev_sign * sigmoid_scale(50 - bb_width_pct, ...) * caps["squeeze_cap"]
```

Squeeze direction is locked to mean_rev_score sign. In bearish conditions with RSI < 50, MR is positive (oversold → long), and squeeze amplifies the LONG push — even when the dominant thesis (trend + MR combined) is bearish.

This creates a LONG floor: in "Ranging slight bear" conditions (DI- > DI+, RSI=47), squeeze pushes +12 LONG, flipping the total to LONG despite bearish trend evidence.

**Fix:** Squeeze amplifies the dominant directional thesis (trend + MR), not just MR:

```python
directional_sum = trend_score + mean_rev_score
directional_sign = 1 if directional_sum > 0 else (-1 if directional_sum < 0 else 0)
squeeze_score = directional_sign * sigmoid_scale(50 - bb_width_pct, center=0, steepness=sq_steep) * caps["squeeze_cap"]
```

**Rationale:** Squeeze (low BB width) means price is compressed and a breakout is pending. The breakout should amplify whichever direction the dominant signals point — if trend is strongly positive and MR is mildly negative, squeeze reinforces the trend. If MR has overwhelmed trend (exhaustion), squeeze reinforces the reversal.

**Impact:** In the "Ranging slight bear" scenario from our simulation:
- Before: trend(-10) + MR(+10) + squeeze(+12) = +12 LONG
- After: trend(-10) + MR(+10) = 0 → directional_sign = 0 → squeeze = 0 → total = 0 (neutral)

In a clear downtrend: trend(-30) + MR(+10) = -20 → squeeze amplifies SHORT instead of fighting it.

**Backward compatibility:** In clear uptrends where trend > |MR|, squeeze direction is unchanged (both trend and MR+trend are positive). Only affects ambiguous or counter-trend scenarios.

---

## Interaction Between Changes

Changes are independent and can be implemented in any order. However, the recommended order maximizes testability:

1. **Change 4 (squeeze)** — smallest, most isolated, easy to unit test
2. **Change 1 (continuous DI)** — core technical scoring change, test with existing test_traditional.py
3. **Change 2 (uniform dampening)** — flow scoring change, test with existing test_traditional.py flow tests
4. **Change 3 (LLM independence)** — crosses multiple files, requires prompt template change + combiner signature change

---

## Deployment & Threshold Adjustment

`signal_threshold` is stored in the `PipelineSettings` DB table (runtime-adjustable via the settings API, no redeployment needed). If signal emission rate drops after these changes:

1. Monitor signal count and direction distribution for 24-48h after deployment.
2. If strong-trend signals that should fire are being suppressed, reduce `signal_threshold` by 2-3 points via the settings API.
3. If the direction ratio hasn't improved meaningfully, the remaining bias is market-driven (see "Limitations" below) — do not compensate by lowering the threshold further.

---

## Expected Impact

Using the 12-scenario simulation from the investigation phase:

| Scenario | Before | After (estimated) |
|----------|--------|-------------------|
| Strong uptrend (DI+=30, DI-=12) | +19.9 LONG | +16 LONG (weaker but still LONG) |
| Moderate uptrend (DI+=22, DI-=15) | +15.6 LONG | +8 LONG (reduced, closer to threshold) |
| Weak uptrend (DI+=18, DI-=14) | +3.3 LONG | +1 LONG (near neutral) |
| Ranging slight bear (DI+=12, DI-=15) | +12.4 LONG | -2 SHORT (squeeze no longer flips) |
| Moderate downtrend (DI+=12, DI-=22) | -11.5 SHORT | -10 SHORT (similar) |
| Pullback in uptrend (DI+=16, DI-=18) | +0.7 LONG | -3 SHORT (continuous DI flips direction) |
| Bounce in downtrend (DI+=19, DI-=16) | +7.3 LONG | +3 LONG (weaker) |

BTC direction distribution (estimated): 82% LONG → ~65-70% LONG. Still trend-following in clear uptrends, but producing counter-trend signals during pullbacks.

### Limitations — What This Spec Does Not Fix

This spec targets **structural scoring asymmetries** (math that unfairly amplifies one direction). The remaining ~65-70% LONG reflects two things this spec intentionally leaves alone:

1. **Market-driven bias** — In a genuine uptrend, a trend-following engine *should* produce more LONG signals. This is correct behavior, not a bug.
2. **Momentum indicators** — EMA slope, MACD, and other momentum signals in the tech score are inherently directional. They don't have the same structural asymmetry (no binary switch, no selective dampening) but they do push with-trend. If 65-70% is still too biased during ranging markets, the next investigation should examine whether momentum sub-scores need continuous-direction treatment similar to Change 1.
3. **Combiner weights** — Tech weight (40%) dominates flow (22%). Even with neutral flow scores, a trend-following tech score drives the preliminary score. Adjusting combiner weights is a separate tuning concern, not a structural fix.

After deployment, if the direction distribution during confirmed ranging periods (ADX < 20) is still > 60% in one direction, that indicates remaining structural bias worth investigating.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/engine/traditional.py` | Continuous DI direction, uniform flow dampening, squeeze from dominant thesis |
| `backend/app/engine/constants.py` | New `DI_SPREAD_STEEPNESS` in `SIGMOID_PARAMS` |
| `backend/app/engine/combiner.py` | Remove `direction` param from `compute_llm_contribution` |
| `backend/app/main.py` | Update `compute_llm_contribution` call site, update `render_prompt` call |
| `backend/app/prompts/signal_analysis.txt` | Remove direction anchoring from prompt |
| `backend/tests/engine/test_traditional.py` | Tests for continuous DI, uniform dampening, squeeze direction |
| `backend/tests/engine/test_combiner.py` | Update LLM contribution tests for new signature |

---

## Not Changed

- Regime system (caps, outer weights) — unchanged, continuous DI feeds into same cap-blending logic
- mr_pressure system — unchanged, complementary (addresses exhaustion; this spec addresses scoring geometry)
- ML pipeline — unchanged
- Order flow sub-score computations — unchanged (only WHERE dampening is applied changes)
- Level calculation — unchanged
- Performance tracker — unchanged

---

## Testing Strategy

### Unit Tests

1. **Continuous DI direction:** Verify sigmoid output at key DI spreads (0.5, 0.2, 0.05, -0.3). Verify symmetry (positive spread = negative of negative spread). Verify di_sum=0 edge case returns 0.

2. **Trend score with continuous DI:** Compare against known values. DI+=30, DI-=10 should produce ~88% of current. DI+=16, DI-=15 should produce ~9% of current.

3. **Uniform flow dampening:** Verify all five sub-scores are computed at full strength before multiplication. Verify final_mult applies to total. Verify score still clamps to [-100, +100].

4. **Squeeze from dominant thesis:** Verify squeeze follows trend+MR sign, not just MR sign. Test case where trend is negative, MR is positive, sum is near zero — squeeze should be near zero. Test case where MR overwhelms trend — squeeze should follow MR direction (via the sum).

5. **LLM contribution without direction:** Verify bullish factors produce positive contribution, bearish produce negative, mixed factors produce net based on balance. Verify total_cap clamping still works.

### Integration Tests

6. **Pullback scenario:** Feed candles producing DI+=16, DI-=18, RSI=48. Verify tech score is near zero or slightly negative (not +0.7 LONG as before).

7. **Strong trend regression:** Feed candles with ADX=35, DI+=30, DI-=10. Verify LONG signal still produced (score reduced but above threshold).

### Existing Test Compatibility

8. **Run full test suite** (`pytest tests/engine/`) — existing tests use specific DI values. Tests that assumed binary DI direction will need updating if their scenarios have narrow DI spreads.

### Breaking Tests Inventory

The following existing tests will fail and must be updated during implementation:

#### Change 1 (Continuous DI) — conviction tests need re-validation

These tests use DI values where binary→continuous changes the expected magnitude. They may still pass directionally but assertion values may shift:

- `test_traditional.py:235` — `test_partial_alignment_moderate_conviction`: Uses DI+=12, DI-=25 — continuous direction will be weaker than binary, conviction expectations may change.
- `test_traditional.py:263` — `test_equal_di_low_conviction`: Uses DI+=20, DI-=20 — spread=0, continuous direction=0. Current test expects low conviction; this should still pass but verify.

#### Change 2 (Uniform Flow Dampening) — 3 tests assume selective dampening

- `test_traditional.py:560` — `test_oi_unaffected_by_regime`: Asserts OI score is identical with/without regime. After fix, OI is dampened via `final_mult` on the total, so regime WILL affect the returned score. **Update:** Assert `result_with["score"] <= result_without["score"]` (regime dampens total, reducing OI's contribution).
- `test_traditional.py:725` — `test_oi_unaffected_by_conviction`: Asserts OI score is identical at conviction=0.0 vs 0.9. After fix, conviction dampens the total. **Update:** Assert `abs(result_low["score"]) >= abs(result_high["score"])`.
- `test_traditional.py:802` — `test_cvd_not_affected_by_contrarian_mult`: Asserts CVD sub-score is identical with/without trending regime. After fix, the `details["cvd_score"]` is pre-dampening (raw) so this test should still pass. However, verify that `result_trending["score"] < result_no_regime["score"]` (total is dampened).

#### Change 3 (LLM Independence) — 8 tests use removed `direction` parameter

All tests in the `compute_llm_contribution` section of `test_combiner.py` pass `direction` as the second positional argument. The parameter is removed.

- `test_combiner.py:160` — `test_llm_contribution_single_aligned_factor`: Remove `"LONG"` arg. Bullish factor now always produces positive contribution (no change to expected value).
- `test_combiner.py:167` — `test_llm_contribution_single_opposing_factor`: Remove `"LONG"` arg. Bearish factor now always produces negative contribution (no change to expected value).
- `test_combiner.py:174` — `test_llm_contribution_short_direction`: Remove `"SHORT"` arg. **Rename test.** Bearish factor now produces negative contribution, not positive. **Update expected value:** `round(-5.0 * 3)` instead of `round(5.0 * 3)` — bearish is always negative regardless of context.
- `test_combiner.py:181` — `test_llm_contribution_multiple_factors`: Remove `"LONG"` arg. Bullish factors positive, bearish negative. Expected value: `round((8.0 * 3) + (7.0 * 1) + (-5.0 * 2)) = 21` — unchanged since bullish was already aligned with LONG.
- `test_combiner.py:193` — `test_llm_contribution_capped_positive`: Remove `"LONG"` arg. All bullish → positive, still capped at 35.
- `test_combiner.py:205` — `test_llm_contribution_capped_negative`: Remove `"LONG"` arg. All bearish → negative, still capped at -35.
- `test_combiner.py:216` — `test_llm_contribution_empty_factors`: Remove `"LONG"` arg. Still returns 0.
- `test_combiner.py:222` — `test_llm_contribution_custom_weights`: Remove `"LONG"` arg. Bullish → positive. Still returns 20.

#### Change 4 (Squeeze from Dominant Thesis) — 1 test assumes MR-only direction

- `test_traditional.py:676` — `test_squeeze_sign_matches_mean_rev_sign`: Asserts squeeze sign matches MR sign. After fix, squeeze sign matches `trend_score + mean_rev_score` sign. **Update:** Retrieve `trend_score` and `mean_rev_score` from `result["indicators"]`, compute `directional_sum`, assert squeeze sign matches `directional_sum` sign.

### DI Spread Testing Strategy

Current fixtures (`_make_candles`) generate OHLC data from which DI+/DI- are computed via ADX calculation — you cannot directly specify DI+=18, DI-=15. For Change 1 tests:

- **Test `sigmoid_score` directly** with known DI spread values (0.5, 0.2, 0.05, -0.3) to verify the continuous mapping. This is a pure math test, no fixtures needed.
- **Test `compute_technical_score` with synthetic candles** to verify integration — use `_make_candles(trend="up")` and `_make_candles(trend="flat")` to cover strong vs ambiguous DI scenarios. Assert relative magnitudes (strong trend > flat) rather than exact DI values.
- **Do NOT mock internal DI values** — test through the public interface to catch integration issues.
