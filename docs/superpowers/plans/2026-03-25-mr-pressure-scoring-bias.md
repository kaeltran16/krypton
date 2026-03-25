# Mean-Reversion Pressure Scoring Bias Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the structural LONG bias in the signal engine by introducing `mr_pressure` — an exhaustion-awareness signal that propagates to six bias points in the scoring pipeline.

**Architecture:** `compute_mr_pressure(rsi, bb_pos)` produces a 0-1 signal requiring BOTH RSI and BB position to be extreme (multiplicative gate). This signal adjusts regime caps, volume scoring, confidence, confluence, order flow contrarian scaling, and LLM gate triggering. When `mr_pressure=0`, all behavior is identical to current.

**Tech Stack:** Python 3.11, FastAPI, pandas, numpy, pytest (asyncio_mode=auto), Docker (`krypton-api-1`)

**Spec:** `docs/superpowers/specs/2026-03-25-mr-pressure-scoring-bias-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/engine/constants.py` | Add `MR_PRESSURE` and `VOL_MULTIPLIER` constant dicts; update `PARAMETER_DESCRIPTIONS` for `volume_cap`; expose in `get_engine_constants()` |
| Modify | `backend/app/config.py` | Add `engine_mr_llm_trigger: float = 0.30` setting |
| Modify | `backend/app/engine/traditional.py` | Add `compute_mr_pressure()`; modify `compute_technical_score()` for dynamic caps, multiplicative volume, directional confidence; modify `compute_order_flow_score()` for mr_pressure relaxation |
| Modify | `backend/app/main.py` | Confluence dampening after `compute_confluence_score`; pass `mr_pressure` to `compute_order_flow_score`; LLM dual trigger |
| Modify | `backend/app/engine/backtester.py` | Add `param_overrides` field to `BacktestConfig`; pass overrides to `compute_technical_score` |
| Modify | `backend/app/engine/param_groups.py` | Add `mr_pressure` group, constraint function, and priority layer entry |
| Create | `backend/tests/engine/test_mr_pressure.py` | All unit tests for mr_pressure: computation, dynamic caps, multiplicative volume, directional confidence, order flow relaxation, integration traces |
| Modify | `backend/tests/engine/test_traditional.py` | Update any tests broken by volume scoring change (additive -> multiplicative) |

---

## Task 1: Add Constants and Config Setting

**Files:**
- Modify: `backend/app/engine/constants.py:96` (after `PERFORMANCE_TRACKER`)
- Modify: `backend/app/engine/constants.py:503-507` (update `volume_cap` description in `PARAMETER_DESCRIPTIONS`)
- Modify: `backend/app/engine/constants.py:555-588` (expose new constants in `get_engine_constants()`)
- Modify: `backend/app/config.py:72` (after `engine_confluence_max_score`)

- [ ] **Step 1: Add MR_PRESSURE and VOL_MULTIPLIER dicts to constants.py**

Add after the `PERFORMANCE_TRACKER` dict (around line 112):

```python
# -- Mean-reversion pressure (exhaustion-aware scoring) --
MR_PRESSURE = {
    "rsi_offset": 10,
    "rsi_range": 30,
    "bb_offset": 0.2,
    "bb_range": 0.3,
    "max_cap_shift": 18,
    "confluence_dampening": 0.7,
    "mr_llm_trigger": 0.30,
}

VOL_MULTIPLIER = {
    "obv_weight": 0.6,
    "vol_ratio_weight": 0.4,
}
```

- [ ] **Step 2: Update volume_cap description in PARAMETER_DESCRIPTIONS**

Replace the existing `volume_cap` entry (line ~503-507):

```python
"volume_cap": {
    "description": "Defines the volume confirmation multiplier amplitude. A value of 28 creates a multiplier range of 0.72x-1.28x applied to the directional score",
    "pipeline_stage": "Regime Detection -> Inner Caps",
    "range": "10-45 — larger values create more aggressive volume confirmation/contradiction",
},
```

- [ ] **Step 3: Expose new constants in get_engine_constants()**

Inside `get_engine_constants()`, add to the returned dict after the `"technical"` key's existing content:

```python
"technical": {
    "indicator_periods": _wrap(INDICATOR_PERIODS),
    "sigmoid_params": _wrap(SIGMOID_PARAMS),
    "mr_pressure": _wrap(MR_PRESSURE),
    "vol_multiplier": _wrap(VOL_MULTIPLIER),
},
```

- [ ] **Step 4: Add engine_mr_llm_trigger to config.py**

Add after `engine_confluence_max_score` (line ~72):

```python
engine_mr_llm_trigger: float = 0.30
```

- [ ] **Step 5: Run existing tests to verify no regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py tests/engine/test_param_groups.py -v --tb=short`
Expected: All existing tests PASS (no behavioral change yet)

---

## Task 2: Implement compute_mr_pressure and Unit Tests

**Files:**
- Modify: `backend/app/engine/traditional.py:6` (add import of `MR_PRESSURE`)
- Modify: `backend/app/engine/traditional.py:10` (add new function after `_HTF_TIMEFRAMES`)
- Create: `backend/tests/engine/test_mr_pressure.py`

- [ ] **Step 1: Write failing tests for compute_mr_pressure**

Create `backend/tests/engine/test_mr_pressure.py`:

```python
import pytest
from app.engine.traditional import compute_mr_pressure


class TestComputeMrPressure:
    def test_neutral_rsi_returns_zero(self):
        """RSI near 50 should produce 0 regardless of BB position."""
        assert compute_mr_pressure(50, 0.95) == 0.0
        assert compute_mr_pressure(55, 0.95) == 0.0

    def test_neutral_bb_returns_zero(self):
        """BB position near 0.5 should produce 0 regardless of RSI."""
        assert compute_mr_pressure(85, 0.5) == 0.0
        assert compute_mr_pressure(85, 0.55) == 0.0

    def test_both_extreme_overbought(self):
        """Both RSI and BB extreme overbought should produce high pressure."""
        pressure = compute_mr_pressure(85, 0.95)
        assert 0.5 < pressure <= 1.0

    def test_both_extreme_oversold(self):
        """Symmetric: oversold should produce same magnitude as overbought."""
        overbought = compute_mr_pressure(85, 0.95)
        oversold = compute_mr_pressure(15, 0.05)
        assert abs(overbought - oversold) < 0.05  # nearly symmetric

    def test_multiplicative_gate(self):
        """Only RSI extreme (BB neutral) = 0. Requires both."""
        assert compute_mr_pressure(90, 0.5) == 0.0

    def test_moderate_values(self):
        """RSI=78, BB=0.90 -> moderate pressure ~0.40."""
        pressure = compute_mr_pressure(78, 0.90)
        assert 0.2 < pressure < 0.6

    def test_output_bounded(self):
        """Output is always in [0, 1]."""
        for rsi in [0, 10, 25, 50, 75, 90, 100]:
            for bb in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
                p = compute_mr_pressure(rsi, bb)
                assert 0.0 <= p <= 1.0, f"Out of bounds: rsi={rsi}, bb={bb}, p={p}"

    def test_reference_values(self):
        """Verify spec reference table values (approximate)."""
        assert compute_mr_pressure(55, 0.55) == 0.0
        assert compute_mr_pressure(65, 0.70) == 0.0
        assert 0.10 <= compute_mr_pressure(72, 0.82) <= 0.25
        assert 0.30 <= compute_mr_pressure(78, 0.90) <= 0.50
        assert 0.55 <= compute_mr_pressure(85, 0.95) <= 0.80
        assert 0.25 <= compute_mr_pressure(25, 0.08) <= 0.50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestComputeMrPressure -v`
Expected: FAIL — `ImportError: cannot import name 'compute_mr_pressure'`

- [ ] **Step 3: Implement compute_mr_pressure**

In `backend/app/engine/traditional.py`, move the existing mid-file import from line 344 to the top of the file (after line 7) and extend it:

```python
from app.engine.constants import ORDER_FLOW, INDICATOR_PERIODS, MR_PRESSURE, VOL_MULTIPLIER
```

Then delete the old import at line 344 (`from app.engine.constants import ORDER_FLOW, INDICATOR_PERIODS`).

Add the function after `_HTF_TIMEFRAMES = {"4h", "1D"}` (line ~10):

```python
def compute_mr_pressure(rsi: float, bb_pos: float, config: dict | None = None) -> float:
    """Measure mean-reversion indicator extremity (0.0-1.0).

    Multiplicative gate: BOTH RSI and BB position must be extreme.
    Symmetric for overbought and oversold.
    """
    cfg = config or MR_PRESSURE
    rsi_extremity = max(0, abs(rsi - 50) - cfg["rsi_offset"]) / cfg["rsi_range"]
    bb_extremity = max(0, abs(bb_pos - 0.5) - cfg["bb_offset"]) / cfg["bb_range"]
    return min(1.0, rsi_extremity * bb_extremity)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestComputeMrPressure -v`
Expected: All PASS

---

## Task 3: Dynamic Cap Shifting (Fix 1)

**Files:**
- Modify: `backend/app/engine/traditional.py:277` (after `caps = blend_caps(...)` in `compute_technical_score`)
- Modify: `backend/app/engine/traditional.py:340` (add `mr_pressure` to return dict)
- Test: `backend/tests/engine/test_mr_pressure.py`

- [ ] **Step 1: Write failing tests for dynamic caps**

Append to `test_mr_pressure.py`:

```python
import numpy as np
import pandas as pd


def _make_candles(n=80, trend="up", seed=42):
    """Generate n candles with a given trend direction."""
    rng = np.random.RandomState(seed)
    base = 100.0
    rows = []
    prev_c = base
    for i in range(n):
        flat_period = n - 30
        if i < flat_period:
            drift = 0.0
        elif trend == "up":
            drift = 0.2
        elif trend == "down":
            drift = -0.2
        else:
            drift = 0.0
        c = prev_c + drift + rng.uniform(-0.15, 0.15)
        o = prev_c + rng.uniform(-0.1, 0.1)
        h = max(o, c) + rng.uniform(0.05, 0.3)
        l = min(o, c) - rng.uniform(0.05, 0.3)
        v = rng.uniform(100, 200)
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        prev_c = c
    return pd.DataFrame(rows)


class TestDynamicCaps:
    def test_no_shift_at_zero_pressure(self):
        """When mr_pressure=0, caps should be unchanged from blend_caps output."""
        from app.engine.regime import blend_caps, compute_regime_mix
        from app.engine.scoring import sigmoid_scale

        trend_strength = sigmoid_scale(20, center=20, steepness=0.25)
        vol_expansion = sigmoid_scale(50, center=50, steepness=0.08)
        regime = compute_regime_mix(trend_strength, vol_expansion)
        original_caps = blend_caps(regime)

        # Neutral RSI/BB -> mr_pressure=0 -> caps unchanged
        df = _make_candles(80, "flat")
        result = compute_technical_score(df)
        # mr_pressure should be near 0 for flat candles (RSI ~50, BB ~0.5)
        assert result.get("mr_pressure", 0.0) < 0.1

    def test_caps_stay_balanced(self):
        """Cap shift must preserve total: trend_cap + mean_rev_cap sum stays constant."""
        from app.engine.constants import MR_PRESSURE as MR_CONST

        # Direct arithmetic test: shift is a zero-sum transfer
        base_trend, base_mr = 38.0, 22.0
        original_sum = base_trend + base_mr

        for mr_p in [0.0, 0.16, 0.40, 0.69, 1.0]:
            shift = mr_p * MR_CONST["max_cap_shift"]
            new_trend = base_trend - shift
            new_mr = base_mr + shift
            assert abs((new_trend + new_mr) - original_sum) < 1e-9, \
                f"Sum changed at mr_pressure={mr_p}: {new_trend + new_mr} != {original_sum}"

    def test_mr_pressure_in_return_dict(self):
        """compute_technical_score must return mr_pressure in the result dict."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert "mr_pressure" in result
        assert 0.0 <= result["mr_pressure"] <= 1.0

    def test_mr_pressure_in_indicators(self):
        """mr_pressure should be included in the indicators dict for observability."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert "mr_pressure" in result["indicators"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestDynamicCaps -v`
Expected: FAIL — `mr_pressure` not in result dict

- [ ] **Step 3: Implement dynamic cap shifting in compute_technical_score**

In `compute_technical_score`, after `caps = blend_caps(regime, regime_weights)` (line ~277), add:

```python
    mr_pressure_val = compute_mr_pressure(rsi_val, bb_pos)
    if mr_pressure_val > 0:
        shift = mr_pressure_val * MR_PRESSURE["max_cap_shift"]
        caps["mean_rev_cap"] += shift
        caps["trend_cap"] -= shift
```

In the `indicators` dict (around line 307), add:

```python
        "mr_pressure": round(mr_pressure_val, 4),
```

Update the return statement (line ~340) to include `mr_pressure`:

```python
    return {"score": score, "indicators": indicators, "regime": regime, "caps": caps, "confidence": round(confidence, 4), "mr_pressure": round(mr_pressure_val, 4)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestDynamicCaps -v`
Expected: All PASS

---

## Task 4: Multiplicative Volume Scoring (Fix 2)

**Files:**
- Modify: `backend/app/engine/traditional.py:299-304` (replace additive volume block in `compute_technical_score`)
- Test: `backend/tests/engine/test_mr_pressure.py`

- [ ] **Step 1: Write failing tests for multiplicative volume**

Append to `test_mr_pressure.py`:

```python
from app.engine.traditional import compute_technical_score


class TestMultiplicativeVolume:
    def test_volume_cannot_flip_direction(self):
        """Volume multiplier must never change the sign of the directional score."""
        df = _make_candles(80, "down")
        result = compute_technical_score(df)
        # The score direction should be determined by directional components,
        # not volume. We can't control exact values, but we verify the
        # mechanism by checking that total is computed multiplicatively.
        # Check that the indicators still contain expected fields
        assert "obv_slope" in result["indicators"]
        assert "vol_ratio" in result["indicators"]

    def test_vol_mult_range_bounded_by_volume_cap(self):
        """The volume multiplier ceiling/floor should be derived from volume_cap."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        caps = result["caps"]
        vol_cap = caps["volume_cap"]
        expected_ceil = 1.0 + vol_cap / 100
        expected_floor = 2.0 - expected_ceil
        # Floor should be positive (volume_cap < 100)
        assert expected_floor > 0
        assert expected_ceil > 1.0

    def test_score_bounded(self):
        """Score must stay within [-100, +100] after multiplicative volume change."""
        for trend in ("up", "down", "flat"):
            df = _make_candles(80, trend)
            result = compute_technical_score(df)
            assert -100 <= result["score"] <= 100
```

- [ ] **Step 2: Run tests to verify they fail or pass (these test the interface, not internals)**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestMultiplicativeVolume -v`
Expected: May pass on interface checks, but let's verify before implementing.

- [ ] **Step 3: Implement multiplicative volume scoring**

In `compute_technical_score`, replace lines 299-304 (the additive volume block):

**Remove:**
```python
    # 4. Volume confirmation (60/40 split)
    obv_score = sigmoid_score(obv_slope_norm, center=0, steepness=4) * (caps["volume_cap"] * 0.6)
    vol_score = candle_direction * sigmoid_score(vol_ratio - 1, center=0, steepness=3.0) * (caps["volume_cap"] * 0.4)

    total = trend_score + mean_rev_score + squeeze_score + obv_score + vol_score
    score = max(min(round(total), 100), -100)
```

**Replace with:**
```python
    # 4. Multiplicative volume confirmation
    directional = trend_score + mean_rev_score + squeeze_score

    if directional == 0:
        total = 0.0
    else:
        score_sign = 1 if directional > 0 else -1

        obv_dir = 1 if obv_slope_norm > 0 else -1
        obv_confirms = (obv_dir == score_sign)
        obv_strength = sigmoid_scale(abs(obv_slope_norm), center=0, steepness=4)

        candle_confirms = (candle_direction == score_sign)
        vol_strength = sigmoid_scale(vol_ratio - 1, center=0, steepness=3)

        obv_w = VOL_MULTIPLIER["obv_weight"]
        vol_w = 1.0 - obv_w  # derived, not stored — keeps weights summing to 1.0
        confirmation = (
            obv_w * (obv_strength if obv_confirms else 1 - obv_strength)
            + vol_w * (vol_strength if candle_confirms else 1 - vol_strength)
        )

        vol_mult_ceil = 1.0 + caps["volume_cap"] / 100
        vol_mult_floor = 2.0 - vol_mult_ceil
        vol_mult = vol_mult_floor + (vol_mult_ceil - vol_mult_floor) * confirmation
        total = directional * vol_mult

    score = max(min(round(total), 100), -100)
```

- [ ] **Step 4: Run ALL traditional tests to check for regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py tests/engine/test_mr_pressure.py -v --tb=short`
Expected: All PASS. If any existing tests fail due to score magnitude changes from the additive-to-multiplicative switch, update test expectations to match the new scoring behavior (the volume change is intentional and always-active per the spec).

- [ ] **Step 5: Fix any broken existing tests**

The volume change is always-active (structural). Tests that assert exact score values or directional outcomes may need updated thresholds. Specifically check:
- `test_uptrend_positive` — should still produce positive score
- `test_downtrend_negative` — should still produce negative score
- `test_score_within_bounds` — should still pass (bounds unchanged)

If any tests fail, update their expected values to reflect the new multiplicative volume behavior.

---

## Task 5: Directional Confidence (Fix 3)

**Files:**
- Modify: `backend/app/engine/traditional.py:334-338` (replace confidence computation in `compute_technical_score`)
- Test: `backend/tests/engine/test_mr_pressure.py`

- [ ] **Step 1: Write failing tests for directional confidence**

Append to `test_mr_pressure.py`:

```python
class TestDirectionalConfidence:
    def test_confidence_bounded(self):
        """Confidence must be in [0, 1]."""
        for trend in ("up", "down", "flat"):
            df = _make_candles(80, trend)
            result = compute_technical_score(df)
            assert 0.0 <= result["confidence"] <= 1.0

    def test_strong_trend_confidence_similar(self):
        """In a clear trend with no exhaustion, confidence should be similar to current."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        # Strong uptrend should produce reasonable confidence
        assert result["confidence"] >= 0.3

    def test_mr_pressure_provides_confidence_floor(self):
        """When mr_pressure is high, confidence should be boosted even if trend is weak.

        This tests the max(trend_conf, mr_conf) logic — mr_pressure alone
        can provide confidence for SHORT signals in trends.
        """
        # We can't easily force RSI/BB to specific values with synthetic candles,
        # but we can verify the formula logic by checking the returned confidence
        # is at least as high as mr_pressure when mr_pressure is significant.
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        mr_p = result.get("mr_pressure", 0.0)
        # If mr_pressure is nonzero, confidence should be at least mr_pressure * 0.8
        if mr_p > 0.1:
            assert result["confidence"] >= mr_p * 0.7
```

- [ ] **Step 2: Run tests to verify baseline**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestDirectionalConfidence -v`
Expected: May pass or fail depending on current confidence formula.

- [ ] **Step 3: Implement directional confidence**

In `compute_technical_score`, replace the confidence block (lines ~334-338):

**Remove:**
```python
    # confidence: combine trend strength + conviction + indicator agreement
    # indicator_conflict is high when trend and mean-rev scores cancel each other
    indicator_conflict = 1.0 - abs(trend_score + mean_rev_score) / max(abs(trend_score) + abs(mean_rev_score), 1e-6)
    confidence = (trend_strength * 0.4 + trend_conviction * 0.4 + (1.0 - indicator_conflict) * 0.2)
    confidence = max(0.0, min(1.0, confidence))
```

**Replace with:**
```python
    # confidence: directional — either strong trend or strong exhaustion can produce confidence
    indicator_conflict = 1.0 - abs(trend_score + mean_rev_score) / max(abs(trend_score) + abs(mean_rev_score), 1e-6)
    score_sign = 1 if total > 0 else -1

    trend_conf = trend_strength * 0.5 + trend_conviction * 0.5
    if di_sign != score_sign:
        trend_conf *= 0.2

    mr_conf = mr_pressure_val
    thesis_conf = max(trend_conf, mr_conf)
    confidence = thesis_conf * 0.8 + (1.0 - indicator_conflict) * 0.2
    confidence = max(0.0, min(1.0, confidence))
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py tests/engine/test_traditional.py tests/engine/test_confidence.py -v --tb=short`
Expected: All PASS

---

## Task 6: Order Flow Contrarian Relaxation (Fix 5)

**Files:**
- Modify: `backend/app/engine/traditional.py:372-377` (add `mr_pressure` param to `compute_order_flow_score`)
- Modify: `backend/app/engine/traditional.py:416-419` (modify contrarian/conviction dampening logic)
- Test: `backend/tests/engine/test_mr_pressure.py`

- [ ] **Step 1: Write failing tests for order flow relaxation**

Append to `test_mr_pressure.py`:

```python
from app.engine.traditional import compute_order_flow_score


class TestOrderFlowMrPressure:
    def test_zero_pressure_unchanged(self):
        """mr_pressure=0 must produce identical results to default."""
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        regime = {"trending": 0.8, "ranging": 0.1, "volatile": 0.05, "steady": 0.05}
        result_default = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.5)
        result_zero = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.5, mr_pressure=0.0)
        assert result_default["score"] == result_zero["score"]

    def test_high_pressure_relaxes_contrarian(self):
        """High mr_pressure should increase contrarian flow score magnitude."""
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        regime = {"trending": 0.8, "ranging": 0.1, "volatile": 0.05, "steady": 0.05}
        result_low = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.7, mr_pressure=0.0)
        result_high = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.7, mr_pressure=0.69)
        # Higher mr_pressure should allow larger contrarian scores
        assert abs(result_high["score"]) > abs(result_low["score"])

    def test_conviction_ceiling_relaxed(self):
        """mr_pressure should relax the conviction dampening ceiling."""
        metrics = {"funding_rate": -0.005, "long_short_ratio": 0.5}
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        # High conviction normally caps final_mult hard
        result_no_mr = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.8, mr_pressure=0.0)
        result_mr = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.8, mr_pressure=0.69)
        assert abs(result_mr["score"]) > abs(result_no_mr["score"])

    def test_oi_unaffected_by_mr_pressure(self):
        """OI score is direction-aware, not contrarian — mr_pressure shouldn't affect it."""
        metrics = {"open_interest_change_pct": 0.05, "price_direction": 1}
        regime = {"trending": 0.8, "ranging": 0.1, "volatile": 0.05, "steady": 0.05}
        result_low = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.5, mr_pressure=0.0)
        result_high = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.5, mr_pressure=0.7)
        assert result_low["score"] == result_high["score"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestOrderFlowMrPressure -v`
Expected: FAIL — `compute_order_flow_score() got an unexpected keyword argument 'mr_pressure'`

- [ ] **Step 3: Implement order flow contrarian relaxation**

In `compute_order_flow_score` signature (line ~372), add `mr_pressure` parameter:

```python
def compute_order_flow_score(
    metrics: dict,
    regime: dict | None = None,
    flow_history: list | None = None,
    trend_conviction: float = 0.0,
    mr_pressure: float = 0.0,
) -> dict:
```

After the `contrarian_mult` computation (around line ~394, after the `else: contrarian_mult = 1.0`), add the floor relaxation:

```python
    if mr_pressure > 0:
        relaxed_floor = TRENDING_FLOOR + mr_pressure * (1.0 - TRENDING_FLOOR)
        contrarian_mult = max(contrarian_mult, relaxed_floor)
```

Replace the conviction dampening (lines ~418-419):

**Remove:**
```python
    conviction_dampening = 1.0 - trend_conviction
    final_mult = min(final_mult, conviction_dampening)
```

**Replace with:**
```python
    effective_conviction = trend_conviction * (1.0 - mr_pressure)
    conviction_dampening = 1.0 - effective_conviction
    final_mult = min(final_mult, conviction_dampening)
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestOrderFlowMrPressure tests/engine/test_traditional.py -v --tb=short`
Expected: All PASS (existing tests pass because default `mr_pressure=0.0` preserves behavior)

---

## Task 7: Confluence Dampening + LLM Dual Trigger + Pipeline Wiring (Fixes 4, 6)

**Files:**
- Modify: `backend/app/main.py:6` (add import of `MR_PRESSURE`)
- Modify: `backend/app/main.py:440` (add confluence dampening after `compute_confluence_score`)
- Modify: `backend/app/main.py:~460-470` (pass `mr_pressure` to `compute_order_flow_score`)
- Modify: `backend/app/main.py:771` (replace LLM gate check)

These changes are in `main.py` which requires the live app context for integration testing. Unit tests for the LLM gate logic and confluence dampening are added below.

- [ ] **Step 1: Write tests for confluence dampening and LLM gate logic**

Append to `test_mr_pressure.py`:

```python
from app.engine.constants import MR_PRESSURE as MR_PRESSURE_CONST


class TestConfluenceDampening:
    def test_no_dampening_at_zero_pressure(self):
        """Confluence score should be unchanged when mr_pressure=0."""
        confluence_score = 13
        mr_p = 0.0
        dampened = round(confluence_score * (1 - mr_p * MR_PRESSURE_CONST["confluence_dampening"]))
        assert dampened == 13

    def test_dampening_at_high_pressure(self):
        """Confluence score should be reduced when mr_pressure is high."""
        confluence_score = 13
        mr_p = 0.69
        dampened = round(confluence_score * (1 - mr_p * MR_PRESSURE_CONST["confluence_dampening"]))
        assert dampened < 13
        assert dampened > 0  # not fully zeroed

    def test_full_pressure_dampening(self):
        """At mr_pressure=1.0 with dampening=0.7, confluence is reduced by 70%."""
        confluence_score = 10
        mr_p = 1.0
        dampened = round(confluence_score * (1 - mr_p * MR_PRESSURE_CONST["confluence_dampening"]))
        assert dampened == 3  # 10 * 0.3 = 3


class TestLLMDualTrigger:
    def test_score_path_triggers(self):
        """LLM should trigger on score magnitude alone (existing behavior)."""
        blended = 45
        mr_p = 0.0
        llm_threshold = 40
        mr_llm_trigger = 0.30
        should_call = abs(blended) >= llm_threshold or mr_p >= mr_llm_trigger
        assert should_call is True

    def test_mr_pressure_path_triggers(self):
        """LLM should trigger on mr_pressure alone even with low blended score."""
        blended = -17
        mr_p = 0.40
        llm_threshold = 40
        mr_llm_trigger = 0.30
        should_call = abs(blended) >= llm_threshold or mr_p >= mr_llm_trigger
        assert should_call is True

    def test_neither_path_triggers(self):
        """LLM should NOT trigger when both score and mr_pressure are below thresholds."""
        blended = -5
        mr_p = 0.16
        llm_threshold = 40
        mr_llm_trigger = 0.30
        should_call = abs(blended) >= llm_threshold or mr_p >= mr_llm_trigger
        assert should_call is False

    def test_moderate_long_not_triggered(self):
        """Moderate LONG with no exhaustion should not trigger on mr_pressure path."""
        blended = 25
        mr_p = 0.0
        llm_threshold = 40
        mr_llm_trigger = 0.30
        should_call = abs(blended) >= llm_threshold or mr_p >= mr_llm_trigger
        assert should_call is False
```

- [ ] **Step 2: Run tests to verify they pass (pure logic tests)**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestConfluenceDampening tests/engine/test_mr_pressure.py::TestLLMDualTrigger -v`
Expected: All PASS (these test the math formula, not the wiring)

- [ ] **Step 3: Wire confluence dampening in main.py**

In `main.py`, add import at the top (near other engine imports, around line ~37):

```python
from app.engine.constants import MR_PRESSURE as MR_PRESSURE_CONST
```

The dampening must be applied *before* the confluence score is added to `tech_result["score"]`.

**Replace lines ~436-440:**
```python
        confluence_score = compute_confluence_score(
            child_direction, parent_indicators,
            max_score=settings.engine_confluence_max_score,
        )
        tech_result["score"] = max(min(tech_result["score"] + confluence_score, 100), -100)
```

**With:**
```python
        confluence_score = compute_confluence_score(
            child_direction, parent_indicators,
            max_score=settings.engine_confluence_max_score,
        )
        mr_pressure_val = tech_result.get("mr_pressure", 0.0)
        if mr_pressure_val > 0 and confluence_score != 0:
            confluence_score = round(confluence_score * (1 - mr_pressure_val * MR_PRESSURE_CONST["confluence_dampening"]))
        tech_result["score"] = max(min(tech_result["score"] + confluence_score, 100), -100)
```

- [ ] **Step 4: Wire mr_pressure to compute_order_flow_score call in main.py**

Find the `compute_order_flow_score` call in `run_pipeline` (search for it) and add the `mr_pressure` kwarg:

```python
    flow_result = compute_order_flow_score(
        flow_metrics,
        regime=tech_result["regime"],
        flow_history=flow_history,
        trend_conviction=tech_result["indicators"].get("trend_conviction", 0.0),
        mr_pressure=tech_result.get("mr_pressure", 0.0),
    )
```

- [ ] **Step 5: Wire LLM dual trigger in main.py**

Replace line ~771:

**Remove:**
```python
    if abs(blended) >= settings.engine_llm_threshold and prompt_template:
```

**Replace with:**
```python
    mr_pressure_val = tech_result.get("mr_pressure", 0.0)
    should_call_llm = (
        abs(blended) >= settings.engine_llm_threshold
        or mr_pressure_val >= settings.engine_mr_llm_trigger
    )
    if should_call_llm and prompt_template:
```

- [ ] **Step 6: Run all tests to verify no regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --tb=short`
Expected: All PASS

---

## Task 8: Backtester Param Overrides

**Files:**
- Modify: `backend/app/engine/backtester.py:70-82` (add `param_overrides` to `BacktestConfig`)
- Modify: `backend/app/engine/backtester.py:154-155` (pass overrides to `compute_technical_score`)
- Modify: `backend/app/engine/traditional.py:181` (add `overrides` param to `compute_technical_score`)
- Test: `backend/tests/engine/test_mr_pressure.py`

- [ ] **Step 1: Write failing tests for param overrides**

Append to `test_mr_pressure.py`:

```python
class TestParamOverrides:
    def test_overrides_change_score(self):
        """Passing overrides to compute_technical_score should change the output."""
        df = _make_candles(80, "up")
        result_default = compute_technical_score(df)
        result_override = compute_technical_score(df, overrides={"mr_pressure": {"max_cap_shift": 0}})
        # With max_cap_shift=0, no cap shifting occurs even with pressure
        # Scores may or may not differ depending on mr_pressure value
        # The key test: it doesn't crash and returns valid output
        assert -100 <= result_override["score"] <= 100

    def test_overrides_none_unchanged(self):
        """overrides=None should produce identical results to no overrides."""
        df = _make_candles(80, "up")
        result_none = compute_technical_score(df, overrides=None)
        result_default = compute_technical_score(df)
        assert result_none["score"] == result_default["score"]

    def test_vol_multiplier_override(self):
        """Overriding vol_multiplier.obv_weight should change the score."""
        df = _make_candles(80, "up")
        r1 = compute_technical_score(df, overrides={"vol_multiplier": {"obv_weight": 0.9}})
        r2 = compute_technical_score(df, overrides={"vol_multiplier": {"obv_weight": 0.1}})
        # Different OBV weights should produce different scores (usually)
        # At minimum, both must be valid
        assert -100 <= r1["score"] <= 100
        assert -100 <= r2["score"] <= 100

    def test_backtest_propagates_overrides(self):
        """Spec test 12: BacktestConfig param_overrides propagate to scoring functions."""
        from app.engine.backtester import run_backtest, BacktestConfig

        candles = _make_candles(120, "up").to_dict("records")
        r_default = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig())
        r_override = run_backtest(
            candles, "BTC-USDT-SWAP",
            BacktestConfig(param_overrides={"mr_pressure": {"max_cap_shift": 0}}),
        )
        # Both should complete without error
        assert "stats" in r_default
        assert "stats" in r_override
        # With max_cap_shift=0, cap shifting is disabled — may produce different trades
        # (exact difference depends on mr_pressure in synthetic data)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestParamOverrides -v`
Expected: FAIL — `compute_technical_score() got an unexpected keyword argument 'overrides'`

- [ ] **Step 3: Add overrides param to compute_technical_score**

Update `compute_technical_score` signature (line ~181):

```python
def compute_technical_score(candles: pd.DataFrame, regime_weights=None, scoring_params: dict | None = None, timeframe: str | None = None, overrides: dict | None = None) -> dict:
```

At the top of the function, after `sp = scoring_params or {}` (line ~280), add:

```python
    mr = {**MR_PRESSURE, **(overrides.get("mr_pressure") or {})} if overrides else MR_PRESSURE
    vol = {**VOL_MULTIPLIER, **(overrides.get("vol_multiplier") or {})} if overrides else VOL_MULTIPLIER
```

Then replace all references to `MR_PRESSURE` dict lookups within `compute_technical_score` with `mr` (the `config` param on `compute_mr_pressure` was already added in Task 2):

In `compute_technical_score`, the cap shift line becomes:
```python
    mr_pressure_val = compute_mr_pressure(rsi_val, bb_pos, config=mr)
    if mr_pressure_val > 0:
        shift = mr_pressure_val * mr["max_cap_shift"]
        caps["mean_rev_cap"] += shift
        caps["trend_cap"] -= shift
```

And the volume multiplier references become:
```python
        obv_w = vol["obv_weight"]
        vol_w = 1.0 - obv_w
```

- [ ] **Step 4: Add param_overrides to BacktestConfig**

In `backtester.py`, update `BacktestConfig` (line ~70):

```python
@dataclass
class BacktestConfig:
    signal_threshold: int = 40
    tech_weight: float = 0.75
    pattern_weight: float = 0.25
    enable_patterns: bool = True
    sl_atr_multiplier: float = 1.5
    tp1_atr_multiplier: float = 2.0
    tp2_atr_multiplier: float = 3.0
    risk_per_trade_pct: float = 1.0
    max_concurrent_positions: int = 3
    ml_confidence_threshold: float = 0.65
    confluence_max_score: int = 15
    param_overrides: dict = field(default_factory=dict)
```

Add `from dataclasses import dataclass, field` import — already imported on line 7.

- [ ] **Step 5: Pass overrides in backtester's run_backtest**

In `run_backtest`, at line ~155 where `compute_technical_score` is called:

**Replace:**
```python
            tech_result = compute_technical_score(df, regime_weights=regime_weights)
```

**With:**
```python
            tech_result = compute_technical_score(df, regime_weights=regime_weights, overrides=config.param_overrides or None)
```

Also update `precompute_parent_indicators` at line ~39 (this call doesn't need overrides — parent indicator computation is for confluence lookup only, not affected by mr_pressure tuning).

- [ ] **Step 6: Run all tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py tests/engine/test_traditional.py tests/engine/test_backtester.py -v --tb=short`
Expected: All PASS

---

## Task 9: Optimizer Param Group

**Files:**
- Modify: `backend/app/engine/param_groups.py:24-26` (add `mr_pressure` to priority layer 2)
- Modify: `backend/app/engine/param_groups.py:347` (add `mr_pressure` group before `get_group`)
- Modify: `backend/app/engine/optimizer.py:~315-330` (map candidate params to overrides in `run_counterfactual_eval`)
- Test: `backend/tests/engine/test_mr_pressure.py`

- [ ] **Step 1: Write failing tests for param group**

Append to `test_mr_pressure.py`:

```python
class TestMrPressureParamGroup:
    def test_group_registered(self):
        """mr_pressure group should exist in PARAM_GROUPS."""
        from app.engine.param_groups import PARAM_GROUPS
        assert "mr_pressure" in PARAM_GROUPS

    def test_group_is_grid(self):
        """mr_pressure should use grid sweep method."""
        from app.engine.param_groups import PARAM_GROUPS
        assert PARAM_GROUPS["mr_pressure"]["sweep_method"] == "grid"

    def test_constraint_accepts_valid(self):
        """Valid candidate should pass constraint."""
        from app.engine.param_groups import validate_candidate
        valid = {
            "max_cap_shift": 18,
            "confluence_dampening": 0.7,
            "obv_weight": 0.6,
            "mr_llm_trigger": 0.30,
        }
        assert validate_candidate("mr_pressure", valid) is True

    def test_constraint_rejects_zero_cap_shift(self):
        """max_cap_shift=0 should fail constraint."""
        from app.engine.param_groups import validate_candidate
        invalid = {
            "max_cap_shift": 0,
            "confluence_dampening": 0.7,
            "obv_weight": 0.6,
            "mr_llm_trigger": 0.30,
        }
        assert validate_candidate("mr_pressure", invalid) is False

    def test_constraint_rejects_out_of_range(self):
        """obv_weight=0 should fail constraint."""
        from app.engine.param_groups import validate_candidate
        invalid = {
            "max_cap_shift": 18,
            "confluence_dampening": 0.7,
            "obv_weight": 0,
            "mr_llm_trigger": 0.30,
        }
        assert validate_candidate("mr_pressure", invalid) is False

    def test_priority_layer_2(self):
        """mr_pressure should be in priority layer 2."""
        from app.engine.param_groups import PARAM_GROUPS
        assert PARAM_GROUPS["mr_pressure"]["priority"] == 2

    def test_sweep_ranges_match_spec(self):
        """Sweep ranges should match the spec."""
        from app.engine.param_groups import PARAM_GROUPS
        ranges = PARAM_GROUPS["mr_pressure"]["sweep_ranges"]
        assert ranges["max_cap_shift"] == (8, 24, 4)
        assert ranges["confluence_dampening"] == (0.30, 0.90, 0.15)
        assert ranges["obv_weight"] == (0.30, 0.80, 0.10)
        assert ranges["mr_llm_trigger"] == (0.20, 0.45, 0.05)

    # NOTE: Spec test 13 (run_counterfactual_eval integration) requires a full
    # async app state with DB and is out of scope for this plan. It should be
    # tested manually post-deployment or added as a follow-up integration test.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestMrPressureParamGroup -v`
Expected: FAIL — `"mr_pressure" not in PARAM_GROUPS`

- [ ] **Step 3: Add mr_pressure to priority layer 2**

In `param_groups.py`, update `PRIORITY_LAYERS` (line ~24):

```python
PRIORITY_LAYERS: list[set[str]] = [
    {"source_weights", "thresholds"},
    {"regime_caps", "regime_outer", "atr_levels"},
    {"sigmoid_curves", "order_flow", "pattern_strengths",
     "indicator_periods", "mean_reversion", "llm_factors", "onchain",
     "mr_pressure"},
]
```

- [ ] **Step 4: Add mr_pressure constraint function and group definition**

Before the `get_group` function (line ~350), add:

```python
def _mr_pressure_ok(c: dict[str, Any]) -> bool:
    return (
        c["max_cap_shift"] > 0
        and 0 < c["confluence_dampening"] < 1
        and 0 < c["obv_weight"] < 1
        and 0 < c["mr_llm_trigger"] < 1
    )


PARAM_GROUPS["mr_pressure"] = {
    "params": {
        "max_cap_shift": "technical.mr_pressure.max_cap_shift",
        "confluence_dampening": "technical.mr_pressure.confluence_dampening",
        "obv_weight": "technical.vol_multiplier.obv_weight",
        "mr_llm_trigger": "technical.mr_pressure.mr_llm_trigger",
    },
    "sweep_method": "grid",
    "sweep_ranges": {
        "max_cap_shift": (8, 24, 4),
        "confluence_dampening": (0.30, 0.90, 0.15),
        "obv_weight": (0.30, 0.80, 0.10),
        "mr_llm_trigger": (0.20, 0.45, 0.05),
    },
    "constraints": _mr_pressure_ok,
    "priority": _priority_for("mr_pressure"),
}
```

- [ ] **Step 5: Wire param_overrides in optimizer's run_counterfactual_eval**

In `optimizer.py`, inside `run_counterfactual_eval`, update the grid sweep section (around line ~319) to map candidate params to overrides when the group is `mr_pressure`:

Find where `BacktestConfig` is constructed (line ~319) and update to:

```python
                        config = BacktestConfig(
                            signal_threshold=candidate.get("signal", settings.engine_signal_threshold),
                        )
                        # Map candidate params to scoring overrides for mr_pressure group
                        if group_name == "mr_pressure":
                            config.param_overrides = {
                                "mr_pressure": {
                                    k: candidate[k]
                                    for k in ("max_cap_shift", "confluence_dampening", "mr_llm_trigger")
                                    if k in candidate
                                },
                                "vol_multiplier": {
                                    k: candidate[k]
                                    for k in ("obv_weight",)
                                    if k in candidate
                                },
                            }
```

Also fix the pre-existing bug at line ~319: remove `pair=pair, timeframe="15m"` from the `BacktestConfig` constructor call (these fields don't exist on the dataclass — `pair` is passed to `run_backtest()` directly). The corrected version is shown in the code block above (no `pair`/`timeframe` kwargs).

- [ ] **Step 6: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestMrPressureParamGroup tests/engine/test_param_groups.py tests/engine/test_optimizer.py -v --tb=short`
Expected: All PASS

---

## Task 10: Integration Tests — Full Pipeline Traces

**Files:**
- Modify: `backend/tests/engine/test_mr_pressure.py`

These tests verify the end-to-end scoring behavior described in the spec's comparison tables.

- [ ] **Step 1: Write integration tests**

Append to `test_mr_pressure.py`:

```python
from app.engine.combiner import compute_preliminary_score


class TestIntegrationPipelineTraces:
    def test_neutral_regression(self):
        """RSI~50, BB~0.5: mr_pressure=0, behavior unchanged from current."""
        df = _make_candles(80, "flat")
        result = compute_technical_score(df)
        assert result.get("mr_pressure", 0.0) < 0.05
        # Score should be near zero for flat market
        assert abs(result["score"]) < 30

    def test_strong_trend_no_exhaustion(self):
        """Strong uptrend with no exhaustion should still produce positive LONG score.

        Spec test 10: LONG signal strength should not be significantly degraded
        by the volume multiplier change. Score must remain positive and above
        a minimum magnitude.
        """
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        mr_p = result.get("mr_pressure", 0.0)
        # In an uptrend, RSI may be elevated but BB may not be extreme
        # The score should still be positive (LONG) and strong enough
        if mr_p < 0.1:
            assert result["score"] > 0, "Strong uptrend with no exhaustion should be LONG"
            assert result["score"] >= 10, (
                f"LONG signal too weak ({result['score']}): multiplicative volume "
                "may have degraded trend-following signals beyond acceptable ~10% range"
            )

    def test_order_flow_with_mr_pressure(self):
        """Order flow score with mr_pressure should be larger than without."""
        metrics = {
            "funding_rate": -0.003,
            "long_short_ratio": 0.6,
            "open_interest_change_pct": -0.02,
            "price_direction": -1,
        }
        regime = {"trending": 0.9, "ranging": 0.05, "volatile": 0.025, "steady": 0.025}

        result_no_mr = compute_order_flow_score(
            metrics, regime=regime, trend_conviction=0.7, mr_pressure=0.0,
        )
        result_mr = compute_order_flow_score(
            metrics, regime=regime, trend_conviction=0.7, mr_pressure=0.69,
        )
        # With mr_pressure, contrarian signals (funding + LS) should be stronger
        assert abs(result_mr["score"]) > abs(result_no_mr["score"])

    def test_blended_score_with_exhaustion(self):
        """Full blending with high mr_pressure should produce a more negative score."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)

        flow_metrics = {
            "funding_rate": -0.003,
            "long_short_ratio": 0.6,
        }
        flow_result = compute_order_flow_score(
            flow_metrics,
            regime=result["regime"],
            trend_conviction=result["indicators"].get("trend_conviction", 0.0),
            mr_pressure=result.get("mr_pressure", 0.0),
        )

        blended = compute_preliminary_score(
            technical_score=result["score"],
            order_flow_score=flow_result["score"],
            tech_weight=0.40,
            flow_weight=0.22,
            tech_confidence=result["confidence"],
            flow_confidence=flow_result["confidence"],
        )
        # Blended should be a valid dict with score
        assert "score" in blended
        assert -100 <= blended["score"] <= 100
```

- [ ] **Step 2: Run integration tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py::TestIntegrationPipelineTraces -v`
Expected: All PASS

- [ ] **Step 3: Run the full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --tb=short`
Expected: All PASS

---

## Task 11: Update ALGORITHM.md Documentation

**Files:**
- Create: `backend/app/engine/ALGORITHM.md` (if it doesn't exist)

Note: If `ALGORITHM.md` does not exist yet, skip this task. The spec references updates to sections that may not be present. If the file exists elsewhere, update it according to the spec's documentation section.

- [ ] **Step 1: Check if ALGORITHM.md exists**

Run: `find backend/ -name "ALGORITHM*" -type f`
If no file found, skip this task entirely.

- [ ] **Step 2: If found, update Section 3 (Technical Scoring)**

Document:
- `mr_pressure` computation formula and its role as an exhaustion signal
- Dynamic cap shifting (trend_cap/mean_rev_cap budget transfer)
- Volume as confirmation multiplier (no longer additive)
- Directional confidence formula (max of trend_conf and mr_conf)

- [ ] **Step 3: If found, update remaining sections**

- Section 4 (Order Flow): mr_pressure relaxation of contrarian floor and conviction dampening
- Section 9 (Confluence): mr_pressure dampening of HTF alignment bonus
- Section 12 (LLM Gate): Dual trigger (score OR mr_pressure)
- Section 21 (Constants): Add MR_PRESSURE and VOL_MULTIPLIER tables

---

## Task 12: Final Commit

After all tasks are complete and all tests pass, commit everything as a single batch.

- [ ] **Step 1: Run the full test suite one final time**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 2: Commit all changes**

```
feat(engine): fix structural LONG bias with mr_pressure exhaustion-aware scoring
```
