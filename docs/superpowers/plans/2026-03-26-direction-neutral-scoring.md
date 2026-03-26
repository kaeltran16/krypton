# Direction-Neutral Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate four structural directional asymmetries in the scoring engine that cause 82% LONG bias for BTC.

**Architecture:** Four independent changes to the scoring math: (1) continuous DI direction replaces binary switch, (2) uniform flow dampening instead of selective, (3) direction-independent LLM contribution, (4) squeeze amplifies dominant thesis not just MR. All changes are in the backend engine layer.

**Tech Stack:** Python, FastAPI, pytest, pandas, numpy

**Spec:** `docs/superpowers/specs/2026-03-26-direction-neutral-scoring-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/engine/constants.py` | Modify | Add `DI_SPREAD_STEEPNESS` to `SIGMOID_PARAMS` |
| `backend/app/engine/traditional.py` | Modify | Changes 1, 2, 4: continuous DI, uniform flow dampening, squeeze direction |
| `backend/app/engine/combiner.py` | Modify | Change 3: remove `direction` param from `compute_llm_contribution` |
| `backend/app/main.py` | Modify | Change 3: update caller sites for prompt + LLM contribution |
| `backend/app/prompts/signal_analysis.txt` | Modify | Change 3: remove direction anchoring |
| `backend/tests/engine/test_traditional.py` | Modify | Update/add tests for changes 1, 2, 4 |
| `backend/tests/engine/test_combiner.py` | Modify | Update LLM contribution tests for change 3 |
| `backend/tests/engine/test_llm.py` | Modify | Remove stale `direction=` kwarg from `render_prompt` call |
| `backend/tests/test_pipeline_ml.py` | Modify | Remove stale `direction=` kwarg from `render_prompt` calls |

---

## Task 1: Squeeze Direction from Dominant Thesis (Change 4)

Smallest, most isolated change. Squeeze currently follows `mean_rev_score` sign; should follow `trend_score + mean_rev_score` sign.

**Files:**
- Modify: `backend/app/engine/traditional.py:322-323`
- Test: `backend/tests/engine/test_traditional.py:676-688`

- [ ] **Step 1: Update the failing test**

In `test_traditional.py`, rename and rewrite `test_squeeze_sign_matches_mean_rev_sign` (line 676). The test needs `trend_score` exposed in the indicators dict to directly verify the dominant thesis logic. We'll expose `trend_score` in Step 3 alongside the implementation change.

Replace the test with:

```python
def test_squeeze_sign_matches_dominant_thesis(self):
    """Squeeze score sign matches trend_score + mean_rev_score, not just MR."""
    for direction in ("up", "down"):
        df = _make_candles(80, direction)
        result = compute_technical_score(df)
        indicators = result["indicators"]
        trend = indicators["trend_score"]
        mr = indicators["mean_rev_score"]
        sq = indicators["squeeze_score"]
        directional_sum = trend + mr
        if directional_sum > 0:
            assert sq >= 0, f"{direction}: squeeze should be >= 0 when dominant thesis is bullish"
        elif directional_sum < 0:
            assert sq <= 0, f"{direction}: squeeze should be <= 0 when dominant thesis is bearish"
        else:
            assert sq == 0, f"{direction}: squeeze must be 0 when dominant thesis is neutral"
```

- [ ] **Step 2: Run the updated test to verify it fails**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestUnifiedMeanReversion::test_squeeze_sign_matches_dominant_thesis -v
```

Expected: FAIL — `trend_score` key not in indicators (KeyError), or if the indicators exposure is skipped, the sign assertion fails for cases where trend opposes MR.

- [ ] **Step 3: Implement squeeze direction change + expose trend_score**

In `backend/app/engine/traditional.py`:

**Line 322-323** — replace:
```python
mean_rev_sign = 1 if mean_rev_score > 0 else (-1 if mean_rev_score < 0 else 0)
squeeze_score = mean_rev_sign * sigmoid_scale(50 - bb_width_pct, center=0, steepness=sq_steep) * caps["squeeze_cap"]
```

With:
```python
directional_sum = trend_score + mean_rev_score
directional_sign = 1 if directional_sum > 0 else (-1 if directional_sum < 0 else 0)
squeeze_score = directional_sign * sigmoid_scale(50 - bb_width_pct, center=0, steepness=sq_steep) * caps["squeeze_cap"]
```

**Line 354+ (indicators dict)** — add after `"squeeze_score"`:
```python
"trend_score": round(trend_score, 2),
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestUnifiedMeanReversion::test_squeeze_sign_matches_dominant_thesis -v
```

Expected: PASS

- [ ] **Step 5: Run the full test_traditional.py suite to check for regressions**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v
```

Expected: All pass. The other squeeze/MR tests in `TestUnifiedMeanReversion` should still pass since in clear up/down trends, `trend_score + mean_rev_score` has the same sign as `mean_rev_score` alone (trend dominates).

---

## Task 2: Continuous DI Direction (Change 1)

Replace binary DI direction switch with continuous sigmoid mapping. This is the core change.

**Files:**
- Modify: `backend/app/engine/constants.py:19-27` — add `DI_SPREAD_STEEPNESS`
- Modify: `backend/app/engine/traditional.py:313-314` — continuous DI in `compute_technical_score`
- Modify: `backend/app/engine/traditional.py:41` — continuous DI in `compute_trend_conviction`
- Test: `backend/tests/engine/test_traditional.py`

### Step 2a: Add constant and write sigmoid_score unit tests

- [ ] **Step 1: Add DI_SPREAD_STEEPNESS constant and parameter description**

In `backend/app/engine/constants.py`, add to the `SIGMOID_PARAMS` dict (line 19-27):

```python
"di_spread_steepness": 3.0,
```

Also add a description entry in the parameter descriptions dict (after `volume_ratio_steepness`, around line 237):

```python
"di_spread_steepness": {
    "description": "Sigmoid steepness for continuous DI direction mapping. Controls how DI+/DI- spread maps to directional strength [-1, +1]. Higher = sharper transition near equal DI",
    "pipeline_stage": "Technical Scoring -> Trend",
    "range": "1.0-6.0",
},
```

- [ ] **Step 2: Write unit tests for sigmoid_score with DI spread values**

Add a new test class at the end of `test_traditional.py`:

```python
class TestContinuousDIDirection:
    """Tests for continuous DI direction via sigmoid_score."""

    def test_sigmoid_score_strong_bullish(self):
        """DI+=35, DI-=10 -> spread=0.56 -> sigmoid ~0.88."""
        from app.engine.scoring import sigmoid_score
        di_spread = (35 - 10) / (35 + 10)  # 0.5556
        result = sigmoid_score(di_spread, center=0, steepness=3.0)
        assert 0.80 <= result <= 0.95

    def test_sigmoid_score_moderate_bullish(self):
        """DI+=22, DI-=15 -> spread=0.19 -> sigmoid ~0.47."""
        from app.engine.scoring import sigmoid_score
        di_spread = (22 - 15) / (22 + 15)  # 0.1892
        result = sigmoid_score(di_spread, center=0, steepness=3.0)
        assert 0.35 <= result <= 0.60

    def test_sigmoid_score_weak_bullish(self):
        """DI+=16, DI-=15 -> spread=0.03 -> sigmoid ~0.09."""
        from app.engine.scoring import sigmoid_score
        di_spread = (16 - 15) / (16 + 15)  # 0.0323
        result = sigmoid_score(di_spread, center=0, steepness=3.0)
        assert 0.0 <= result <= 0.20

    def test_sigmoid_score_strong_bearish(self):
        """DI+=10, DI-=30 -> spread=-0.50 -> sigmoid ~-0.85."""
        from app.engine.scoring import sigmoid_score
        di_spread = (10 - 30) / (10 + 30)  # -0.50
        result = sigmoid_score(di_spread, center=0, steepness=3.0)
        assert -0.95 <= result <= -0.75

    def test_sigmoid_score_symmetry(self):
        """Positive and negative spreads are symmetric."""
        from app.engine.scoring import sigmoid_score
        pos = sigmoid_score(0.3, center=0, steepness=3.0)
        neg = sigmoid_score(-0.3, center=0, steepness=3.0)
        assert abs(pos + neg) < 1e-10

    def test_sigmoid_score_zero_spread(self):
        """Equal DI -> spread=0 -> sigmoid=0."""
        from app.engine.scoring import sigmoid_score
        result = sigmoid_score(0.0, center=0, steepness=3.0)
        assert result == 0.0

    def test_di_sum_zero_returns_zero_direction(self):
        """When DI+ and DI- are both zero, direction should be 0."""
        # This tests the di_sum guard: di_sum=0 -> di_spread=0 -> sigmoid=0
        from app.engine.scoring import sigmoid_score
        di_plus, di_minus = 0.0, 0.0
        di_sum = di_plus + di_minus
        di_spread = (di_plus - di_minus) / di_sum if di_sum > 0 else 0.0
        result = sigmoid_score(di_spread, center=0, steepness=3.0)
        assert result == 0.0

    def test_strong_trend_produces_higher_score_than_flat(self):
        """Candles with strong trend should produce higher |score| than flat candles."""
        df_up = _make_candles(80, "up")
        df_flat = _make_candles(80, "flat")
        result_up = compute_technical_score(df_up)
        result_flat = compute_technical_score(df_flat)
        assert abs(result_up["score"]) > abs(result_flat["score"])
```

- [ ] **Step 3: Run the new tests to verify they fail**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestContinuousDIDirection -v
```

Expected: sigmoid_score tests PASS (they test the function directly), but `test_strong_trend_produces_higher_score_than_flat` may already pass. The key verification is that after implementation, the integration tests still pass with the new behavior.

### Step 2b: Implement continuous DI in compute_technical_score

- [ ] **Step 4: Implement continuous DI direction**

In `backend/app/engine/traditional.py`:

Add import at top (line 8, alongside existing constants import):
```python
from app.engine.constants import ORDER_FLOW, INDICATOR_PERIODS, MR_PRESSURE, VOL_MULTIPLIER, SIGMOID_PARAMS
```

**Line 313-314** — replace:
```python
di_sign = 1 if di_plus_val > di_minus_val else -1
trend_score = di_sign * sigmoid_scale(adx_val, center=15, steepness=sp.get("trend_score_steepness", 0.30)) * caps["trend_cap"]
```

With:
```python
di_sum = di_plus_val + di_minus_val
di_spread = (di_plus_val - di_minus_val) / di_sum if di_sum > 0 else 0.0
di_direction = sigmoid_score(di_spread, center=0, steepness=sp.get("di_spread_steepness", SIGMOID_PARAMS["di_spread_steepness"]))
trend_score = di_direction * sigmoid_scale(adx_val, center=15, steepness=sp.get("trend_score_steepness", 0.30)) * caps["trend_cap"]
```

**Add `di_direction` to the indicators dict** (after `trend_score` line in the indicators dict):
```python
"di_direction": round(di_direction, 4),
```

### Step 2c: Update compute_trend_conviction for continuous DI

- [ ] **Step 5: Update compute_trend_conviction to accept di_direction parameter**

In `backend/app/engine/traditional.py`, function `compute_trend_conviction` (line 25-67):

The function currently uses `direction = 1 if di_plus > di_minus else -1` (line 41). `compute_trend_conviction` is only called from one place — `compute_technical_score` — which already computes `di_direction` in Step 4. To avoid recomputing the DI spread and sigmoid, pass `di_direction` as a parameter.

**Update signature** (line 25-33) — add `di_direction` parameter, remove `di_plus` and `di_minus`:

Replace:
```python
def compute_trend_conviction(
    close: float,
    ema_9: float,
    ema_21: float,
    ema_50: float,
    adx: float,
    di_plus: float,
    di_minus: float,
    atr: float = 1.0,
) -> dict:
```

With:
```python
def compute_trend_conviction(
    close: float,
    ema_9: float,
    ema_21: float,
    ema_50: float,
    adx: float,
    di_direction: float,
    atr: float = 1.0,
) -> dict:
```

**Line 41** — replace:
```python
direction = 1 if di_plus > di_minus else -1
```

With:
```python
direction = 1 if di_direction > 0 else -1
```

When `di_direction <= 0` (including exactly equal DI where `di_direction == 0`), this defaults to -1, matching the current `1 if di_plus > di_minus else -1` behavior for equal values.

Note: The `direction` variable is used for sign comparisons (EMA alignment penalty at line 51, price confirmation at line 60). These comparisons need a discrete +1/-1 sign, so we extract the sign from the continuous value. Because `compute_trend_conviction` returns `direction` in its dict (line 67), and the only consumer is `compute_technical_score` (which stores `tc["conviction"]` but does NOT use `tc["direction"]`), the <=0 default choice has no downstream impact. The `test_equal_di_low_conviction` test (line 263) asserts `conviction < 0.4` which tests magnitude, not direction, so it will pass regardless.

**Update the call site** in `compute_technical_score` (line 274-280). The call currently passes `di_plus_val` and `di_minus_val` — replace those with `di_direction`:

Replace:
```python
tc = compute_trend_conviction(close_val, ema_9_val, ema_21_val, ema_50_val, adx_val, di_plus_val, di_minus_val, atr_val)
```

With:
```python
tc = compute_trend_conviction(close_val, ema_9_val, ema_21_val, ema_50_val, adx_val, di_direction, atr_val)
```

(The `di_direction` variable was computed just above in Step 4.)

**Update `test_traditional.py` conviction tests** that call `compute_trend_conviction` directly. Search for `compute_trend_conviction(` in the test file and replace `di_plus, di_minus` args with a precomputed `di_direction` value:

For tests using `di_plus=25, di_minus=15`: `di_direction = sigmoid_score((25-15)/(25+15), center=0, steepness=3.0)` ≈ +0.56
For tests using `di_plus=12, di_minus=25`: `di_direction = sigmoid_score((12-25)/(12+25), center=0, steepness=3.0)` ≈ -0.60
For tests using `di_plus=20, di_minus=20`: `di_direction = 0.0`
For tests using `di_plus=30, di_minus=10`: `di_direction = sigmoid_score((30-10)/(30+10), center=0, steepness=3.0)` ≈ +0.82

Each test should import `sigmoid_score` from `app.engine.scoring` and compute the `di_direction` inline, or use the approximate float directly.

**Line 387** — also update the confidence calculation that references `di_sign`. After this change, `di_sign` no longer exists in `compute_technical_score`. Replace:
```python
if final_sign != 0 and di_sign != final_sign:
```

With:
```python
di_sign = 1 if di_direction > 0 else (-1 if di_direction < 0 else 0)
if final_sign != 0 and di_sign != final_sign:
```

- [ ] **Step 6: Run tests to verify**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v
```

Expected: All tests pass. The conviction tests at lines 235 and 263 should still pass:
- `test_partial_alignment_moderate_conviction` (DI+=12, DI-=25): continuous direction is negative (same as binary), conviction range 0.3-0.7 should hold.
- `test_equal_di_low_conviction` (DI+=20, DI-=20): spread=0, `sigmoid_score(0)=0`, `direction` defaults to -1 (same as current `1 if 20 > 20 else -1`). Test asserts `conviction < 0.4` (magnitude only) — passes.
- `test_direction_from_di` (DI+=25, DI-=15): positive spread, direction=+1, unchanged.

---

## Task 3: Uniform Flow Dampening (Change 2)

Apply `final_mult` to the total flow score instead of selectively to funding and L/S only.

**Files:**
- Modify: `backend/app/engine/traditional.py:492-534` — `compute_order_flow_score`
- Test: `backend/tests/engine/test_traditional.py` — update 4 tests

> **Note:** After this change, sub-scores in `details` become pre-dampening (raw) values. `main.py:832` passes `order_flow=json.dumps(flow_result["details"])` to the LLM prompt, so the LLM will see raw sub-scores instead of dampened ones. This is intentional per the spec — raw values are more useful for factor analysis. The dampened total is still in `score`, and `final_mult` is in `details` for reconstruction.

- [ ] **Step 1: Update the four affected tests**

**Test 1: `test_oi_unaffected_by_regime`** (line 560). Currently asserts OI score is identical with/without regime. After fix, regime dampens the total, so OI contributes less. Replace:

```python
def test_oi_dampened_by_regime(self):
    """OI score is dampened via total when regime is trending."""
    regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
    metrics = {"open_interest_change_pct": 0.05, "price_direction": 1}
    result_with = compute_order_flow_score(metrics, regime=regime)
    result_without = compute_order_flow_score(metrics)
    # regime dampens the total score (final_mult < 1.0)
    assert abs(result_with["score"]) <= abs(result_without["score"])
```

**Test 2: `test_oi_unaffected_by_conviction`** (line 725). Currently asserts OI score identical at low/high conviction. Replace:

```python
def test_oi_dampened_by_conviction(self):
    """OI score is dampened via total when conviction is high."""
    metrics = {"open_interest_change_pct": 0.05, "price_direction": 1}
    result_low = compute_order_flow_score(metrics, trend_conviction=0.0)
    result_high = compute_order_flow_score(metrics, trend_conviction=0.9)
    assert abs(result_low["score"]) >= abs(result_high["score"])
```

**Test 3: `test_cvd_not_affected_by_contrarian_mult`** (line 802). Currently asserts CVD sub-score is identical with/without trending regime. After fix, `details["cvd_score"]` stores the **pre-dampening** value, so the sub-score assertion should still pass. But verify the total score is dampened. Update to:

```python
def test_cvd_subscore_is_pre_dampening(self):
    """CVD sub-score in details is the raw pre-dampening value."""
    metrics = {"cvd_delta": 500.0, "avg_candle_volume": 1000.0}
    regime_trending = {"trending": 0.8, "ranging": 0.1, "volatile": 0.05, "steady": 0.05}
    result_trending = compute_order_flow_score(metrics, regime=regime_trending)
    result_no_regime = compute_order_flow_score(metrics)
    # sub-scores are pre-dampening, so raw CVD should be the same
    assert result_trending["details"]["cvd_score"] == result_no_regime["details"]["cvd_score"]
    # but the total score is dampened by final_mult
    assert abs(result_trending["score"]) < abs(result_no_regime["score"])
```

**Test 4: `test_trending_regime_reduces_contrarian`** (line 539). Currently asserts `0.25 <= ratio <= 0.40` for the trending/ranging score ratio. After moving dampening from individual scores to total, this ratio will change because funding and L/S are no longer pre-dampened before summing. The ratio may shift since all 5 sub-scores now contribute at full strength before the single `final_mult` application. Run the test after implementation and update the range to match the new behavior:

```python
def test_trending_regime_reduces_contrarian(self):
    """Pure trending regime (trending=1) reduces total flow score."""
    regime_trending = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
    regime_ranging = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0, "steady": 0.0}
    metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
    score_trending = abs(compute_order_flow_score(metrics, regime=regime_trending)["score"])
    score_ranging = abs(compute_order_flow_score(metrics, regime=regime_ranging)["score"])
    ratio = score_trending / score_ranging
    # uniform dampening: final_mult applies to total, so ratio = final_mult for trending regime
    # contrarian_mult for trending=1.0 is ~0.3, so ratio should be in that range
    assert 0.20 <= ratio <= 0.50, f"Expected dampened ratio, got {ratio:.2f}"
```

Note: The exact ratio range may need adjustment after implementation. Run the test, observe the actual ratio, and tighten the bounds accordingly.

- [ ] **Step 2: Run the updated tests to verify they fail**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestRegimeContrarian::test_oi_dampened_by_regime tests/engine/test_traditional.py::TestOrderFlowTrendConviction::test_oi_dampened_by_conviction tests/engine/test_traditional.py::TestCVDScoring::test_cvd_subscore_is_pre_dampening tests/engine/test_traditional.py::TestOrderFlowRegimeScaling::test_trending_regime_reduces_contrarian -v
```

Expected: `test_oi_dampened_by_regime` passes (it's a weaker assertion), `test_cvd_subscore_is_pre_dampening` fails on the `abs(result_trending["score"]) < abs(result_no_regime["score"])` assertion since currently the total isn't dampened uniformly.

- [ ] **Step 3: Implement uniform flow dampening**

In `backend/app/engine/traditional.py`, function `compute_order_flow_score` (starting at line 492):

**Lines 495-508** — remove `* final_mult` from individual funding and LS scores:

Replace line 495:
```python
funding_score = sigmoid_score(-funding, center=0, steepness=funding_steepness) * FUNDING_MAX * final_mult
```
With:
```python
funding_score = sigmoid_score(-funding, center=0, steepness=funding_steepness) * FUNDING_MAX
```

Replace line 508:
```python
ls_score = sigmoid_score(1.0 - ls, center=0, steepness=ls_steepness) * LS_MAX * final_mult
```
With:
```python
ls_score = sigmoid_score(1.0 - ls, center=0, steepness=ls_steepness) * LS_MAX
```

**Lines 534-535** — apply `final_mult` to total:

Replace:
```python
total = funding_score + oi_score + ls_score + cvd_score + book_score
score = max(min(round(total), 100), -100)
```
With:
```python
total = (funding_score + oi_score + ls_score + cvd_score + book_score) * final_mult
score = max(min(round(total), 100), -100)
```

**Details dict (lines 537-557):** The sub-scores stored in `details` are now pre-dampening values (the raw contribution before `final_mult`). This is the intended behavior per the spec — more useful for debugging. No change needed to the details dict assignments since `funding_score`, `oi_score`, etc. now hold raw values.

- [ ] **Step 4: Run the four updated tests to verify they pass**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestRegimeContrarian::test_oi_dampened_by_regime tests/engine/test_traditional.py::TestOrderFlowTrendConviction::test_oi_dampened_by_conviction tests/engine/test_traditional.py::TestCVDScoring::test_cvd_subscore_is_pre_dampening tests/engine/test_traditional.py::TestOrderFlowRegimeScaling::test_trending_regime_reduces_contrarian -v
```

Expected: PASS

- [ ] **Step 5: Run the full test_traditional.py suite**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v
```

Expected: All pass. Check that `TestRegimeContrarian` tests still pass — `test_trending_reduces_contrarian` and `test_mixed_regime_interpolates` should work since they test relative magnitudes, and uniform dampening preserves the ordering.

---

## Task 4: Direction-Independent LLM (Change 3)

Three-part change: prompt template, combiner function signature, caller in main.py.

**Files:**
- Modify: `backend/app/prompts/signal_analysis.txt:22,30`
- Modify: `backend/app/engine/combiner.py:96-111`
- Modify: `backend/app/main.py:813,838,855,858`
- Test: `backend/tests/engine/test_combiner.py:160-227`

### Step 4a: Update combiner tests (8 tests)

- [ ] **Step 1: Update all 8 `compute_llm_contribution` tests**

In `backend/tests/engine/test_combiner.py`:

**`test_llm_contribution_single_aligned_factor`** (line 160): Remove `"LONG"` arg. Bullish factor always produces positive contribution.
```python
def test_llm_contribution_single_bullish_factor():
    """Single bullish factor = positive contribution."""
    factors = [LLMFactor(type="rsi_divergence", direction="bullish", strength=2, reason="test")]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == round(7.0 * 2)
```

**`test_llm_contribution_single_opposing_factor`** (line 167): Remove `"LONG"` arg. Bearish factor always produces negative contribution.
```python
def test_llm_contribution_single_bearish_factor():
    """Bearish factor = negative contribution."""
    factors = [LLMFactor(type="rsi_divergence", direction="bearish", strength=2, reason="test")]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == round(-7.0 * 2)
```

**`test_llm_contribution_short_direction`** (line 174): Remove `"SHORT"` arg. Bearish factor now always produces negative (not positive). Rename and update expected value.
```python
def test_llm_contribution_bearish_always_negative():
    """Bearish factor always produces negative contribution regardless of context."""
    factors = [LLMFactor(type="funding_extreme", direction="bearish", strength=3, reason="test")]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == round(-5.0 * 3)
```

**`test_llm_contribution_multiple_factors`** (line 181): Remove `"LONG"` arg. Expected value unchanged (bullish aligned, bearish opposed — same math).
```python
def test_llm_contribution_multiple_factors():
    """Multiple factors sum their contributions."""
    factors = [
        LLMFactor(type="level_breakout", direction="bullish", strength=3, reason="broke key"),
        LLMFactor(type="rsi_divergence", direction="bullish", strength=1, reason="mild div"),
        LLMFactor(type="funding_extreme", direction="bearish", strength=2, reason="elevated"),
    ]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    expected = round((8.0 * 3) + (7.0 * 1) + (-5.0 * 2))  # 24 + 7 - 10 = 21
    assert result == expected
```

**`test_llm_contribution_capped_positive`** (line 193): Remove `"LONG"` arg.
```python
def test_llm_contribution_capped_positive():
    """Total capped at +total_cap."""
    factors = [
        LLMFactor(type="level_breakout", direction="bullish", strength=3, reason="a"),
        LLMFactor(type="htf_alignment", direction="bullish", strength=3, reason="b"),
        LLMFactor(type="rsi_divergence", direction="bullish", strength=3, reason="c"),
    ]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == 35
```

**`test_llm_contribution_capped_negative`** (line 205): Remove `"LONG"` arg.
```python
def test_llm_contribution_capped_negative():
    """Total capped at -total_cap."""
    factors = [
        LLMFactor(type="level_breakout", direction="bearish", strength=3, reason="a"),
        LLMFactor(type="htf_alignment", direction="bearish", strength=3, reason="b"),
        LLMFactor(type="rsi_divergence", direction="bearish", strength=3, reason="c"),
    ]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == -35
```

**`test_llm_contribution_empty_factors`** (line 216): Remove `"LONG"` arg.
```python
def test_llm_contribution_empty_factors():
    """Empty factor list returns 0."""
    result = compute_llm_contribution([], DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == 0
```

**`test_llm_contribution_custom_weights`** (line 222): Remove `"LONG"` arg.
```python
def test_llm_contribution_custom_weights():
    """Custom weight dict overrides defaults."""
    custom = {"rsi_divergence": 10.0}
    factors = [LLMFactor(type="rsi_divergence", direction="bullish", strength=2, reason="test")]
    result = compute_llm_contribution(factors, custom, 35.0)
    assert result == 20
```

- [ ] **Step 2: Run the updated combiner tests to verify they fail**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -k "llm_contribution" -v
```

Expected: FAIL — `compute_llm_contribution` still expects 4 positional args, tests now pass 3.

### Step 4b: Update combiner implementation

- [ ] **Step 3: Update `compute_llm_contribution` signature**

In `backend/app/engine/combiner.py`, replace lines 96-111:

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

- [ ] **Step 4: Run combiner tests to verify they pass**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -v
```

Expected: All PASS

### Step 4c: Update prompt template

- [ ] **Step 5: Update signal_analysis.txt**

In `backend/app/prompts/signal_analysis.txt`:

**Line 22** — replace:
```
Preliminary Indicator Score: {preliminary_score} (Direction: {direction})
```
With:
```
Preliminary Indicator Score: {preliminary_score} (positive = bullish, negative = bearish)
```

**Line 30** — replace:
```
The quantitative signals produced a {direction} bias with score {blended_score}. Your job is to independently evaluate whether the data supports this direction, or if factors suggest caution or contradiction.
```
With:
```
The quantitative signals produced a blended score of {blended_score} (positive = bullish, negative = bearish). Your job is to evaluate the evidence and determine which direction it supports. Assess factors for BOTH long and short scenarios — do not assume one direction.
```

### Step 4d: Update main.py caller

- [ ] **Step 6: Update main.py pipeline**

In `backend/app/main.py`:

**Line 813**: Delete `direction_label = "LONG" if blended > 0 else "SHORT"` (the one inside the `if should_call_llm` block).

**Line 838**: Remove `direction=direction_label,` from the `render_prompt` call. The template no longer uses `{direction}`.

**Lines 855-861**: Replace:
```python
direction_label = "LONG" if blended > 0 else "SHORT"
llm_contribution = compute_llm_contribution(
    llm_result.response.factors,
    direction_label,
    settings.llm_factor_weights,
    settings.llm_factor_total_cap,
)
```
With:
```python
llm_contribution = compute_llm_contribution(
    llm_result.response.factors,
    settings.llm_factor_weights,
    settings.llm_factor_total_cap,
)
```

### Step 4e: Update render_prompt callers in other test files

- [ ] **Step 7: Remove stale `direction=` kwargs from test files**

After removing `{direction}` from the prompt template, `render_prompt` callers that still pass `direction=` won't error (Python's `str.format()` silently ignores extra kwargs), but the dead args should be removed for clarity.

**`backend/tests/engine/test_llm.py:66`** — remove `direction="LONG",` from the `render_prompt()` call.

**`backend/tests/test_pipeline_ml.py:258`** — remove `direction="LONG",` from the first `render_prompt()` call in `test_prompt_includes_ml_context_when_available`.

**`backend/tests/test_pipeline_ml.py:287`** — remove `direction="LONG",` from the second `render_prompt()` call in `test_prompt_omits_ml_when_unavailable`.

Also check if any of these tests assert on rendered prompt content containing "Direction:" or "LONG" — if so, update those assertions to match the new template text.

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 grep -rn "direction" tests/engine/test_llm.py tests/test_pipeline_ml.py | grep -i "render_prompt\|Direction:"
```

- [ ] **Step 8: Run full engine test suite**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/ -v
```

Expected: All PASS

---

## Task 5: Full Test Suite Verification

- [ ] **Step 1: Run the complete backend test suite**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v
```

Expected: All pass. If any API-level tests fail (tests that mock the pipeline), they likely reference `direction_label` in mock setups — fix those call sites.

- [ ] **Step 2: Verify no remaining references to removed code**

Check that no code still passes `direction` to `compute_llm_contribution`, `render_prompt`, or uses `direction_label`:

```bash
grep -rn "direction_label" backend/app/ backend/tests/
grep -rn "compute_llm_contribution.*direction" backend/
grep -rn "render_prompt.*direction=" backend/
```

Expected: No matches in source code (only in this plan and the spec).

- [ ] **Step 3: Quick smoke test — start the container and verify no import errors**

```bash
cd backend && docker compose restart api
docker logs krypton-api-1 --tail 20
```

Expected: API starts without errors. No `ImportError`, `TypeError`, or `KeyError` in logs.
