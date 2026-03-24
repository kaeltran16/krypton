# Signal Engine v2 — Scoring Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recalibrate scoring sigmoids, improve regime detection with smoothing and per-pair ADX, and add confidence-weighted blending across all scoring sources.

**Architecture:** Three layered changes — (1) fix sigmoid activation ranges so scoring functions produce gradual rather than binary output, (2) add EMA smoothing to regime mix and per-pair ADX calibration, (3) attach confidence metadata to every scoring source and use it to modulate outer blend weights before combining scores. The Signal model gains a `confidence_tier` field exposed to the frontend.

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.0 async, Alembic, pytest, React/TypeScript/Tailwind

**Spec:** `docs/superpowers/specs/2026-03-24-signal-engine-v2-design.md` (Sections 1, 2, 3)

**Depends on:** Nothing (this is the foundation plan)

**Blocks:** Plans 2-5 all depend on confidence-weighted blending from this plan.

---

## File Structure

### Modified Files

| File | Responsibility |
|------|---------------|
| `backend/app/engine/constants.py` | Add order flow sigmoid recalibrated defaults, BB width window update, new confidence constants |
| `backend/app/engine/traditional.py` | Fix funding/OI sigmoids, continuous EMA alignment, add `confidence` key to tech and flow return dicts |
| `backend/app/engine/regime.py` | EMA smoothing on regime mix, per-pair ADX center support |
| `backend/app/engine/onchain_scorer.py` | Change return type from `int` to `dict` with `score` and `confidence` |
| `backend/app/engine/patterns.py` | Change `compute_pattern_score` return from `int` to `dict` with `score` and `confidence` |
| `backend/app/engine/combiner.py` | Update `compute_preliminary_score` with confidence parameters (backward-compatible defaults), add `compute_confidence_tier` |
| `backend/app/engine/backtester.py` | Update `compute_pattern_score` caller for dict return type |
| `backend/app/engine/param_groups.py` | Update sigmoid bounds for recalibrated defaults |
| `backend/app/db/models.py` | Add `confidence_tier` to Signal, `adx_center` to RegimeWeights |
| `backend/app/main.py` | Wire smoothed regime state, update on-chain/pattern callers for dict returns, pass confidence to combiner |
| `web/src/features/signals/types.ts` | Add `confidence_tier` field to Signal type |
| `web/src/features/signals/components/SignalCard.tsx` | Display confidence tier badge |
| `web/src/features/signals/components/SignalDetail.tsx` | Display confidence tier in detail view |

### Test Files

| File | What it covers |
|------|---------------|
| `backend/tests/engine/test_sigmoid_recalibration.py` | Sigmoid activation ranges for funding, OI, EMA alignment |
| `backend/tests/engine/test_regime_smoothing.py` | EMA smoothing, cold start, per-pair ADX center |
| `backend/tests/engine/test_confidence_blending.py` | Source confidence emission, combiner formula, tier computation |
| `backend/tests/engine/test_onchain_scorer.py` | Update existing tests for dict return type (10 call sites) |
| `backend/tests/engine/test_patterns.py` | Update existing tests for dict return type (24 call sites) |

---

## Task 1: Recalibrate Order Flow Sigmoids in Constants

**Files:**
- Modify: `backend/app/engine/constants.py:30-39`
- Test: `backend/tests/engine/test_sigmoid_recalibration.py`

- [ ] **Step 1: Write the failing test for sigmoid activation ranges**

```python
# backend/tests/engine/test_sigmoid_recalibration.py
import math

from app.engine.scoring import sigmoid_score
from app.engine.constants import ORDER_FLOW


def test_funding_rate_sigmoid_activates_in_normal_range():
    """Funding rate sigmoid should produce gradual scores in ±0.01% to ±0.05% range."""
    steepness = ORDER_FLOW["sigmoid_steepnesses"]["funding"]
    # At 0.01% funding rate, should produce non-trivial output (not near 0)
    score_low = abs(sigmoid_score(-0.0001, center=0, steepness=steepness))
    # At 0.05% funding rate, should be substantially higher
    score_high = abs(sigmoid_score(-0.0005, center=0, steepness=steepness))

    assert score_low > 0.05, f"Funding sigmoid too flat at 0.01%: {score_low}"
    assert score_high > 0.30, f"Funding sigmoid too flat at 0.05%: {score_high}"
    assert score_high > score_low, "Should increase with larger funding rate"


def test_oi_change_sigmoid_activates_in_normal_range():
    """OI change sigmoid should respond to 2-10% changes."""
    steepness = ORDER_FLOW["sigmoid_steepnesses"]["oi"]
    # 2% OI change should produce visible score
    score_2pct = abs(sigmoid_score(2.0, center=0, steepness=steepness))
    # 10% OI change should be near saturation
    score_10pct = abs(sigmoid_score(10.0, center=0, steepness=steepness))

    assert score_2pct > 0.10, f"OI sigmoid too flat at 2%: {score_2pct}"
    assert score_10pct > 0.70, f"OI sigmoid too flat at 10%: {score_10pct}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_sigmoid_recalibration.py -v`
Expected: FAIL — current steepness 8000 for funding only activates at extremes, and 65 for OI is too steep.

- [ ] **Step 3: Update constants with recalibrated sigmoid values**

In `backend/app/engine/constants.py`, change `ORDER_FLOW["sigmoid_steepnesses"]`:
```python
"sigmoid_steepnesses": {"funding": 400, "oi": 20, "ls_ratio": 6},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_sigmoid_recalibration.py -v`
Expected: PASS

- [ ] **Step 5: Run existing order flow tests to check for regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v -k "flow"`
Expected: PASS (existing tests should still pass — they test score bounds, not exact values)

---

## Task 2: Wire Recalibrated Sigmoids in Order Flow Scoring

**Files:**
- Modify: `backend/app/engine/traditional.py:407-421`
- Test: `backend/tests/engine/test_sigmoid_recalibration.py`

The `compute_order_flow_score` function currently hardcodes steepness values (8000 for funding at line 409, 65 for OI at line 417). These need to read from `ORDER_FLOW["sigmoid_steepnesses"]`.

- [ ] **Step 1: Write test verifying steepness reads from constants**

Add to `test_sigmoid_recalibration.py`:
```python
from unittest.mock import patch

from app.engine.traditional import compute_order_flow_score


def test_order_flow_uses_constant_steepness():
    """Order flow scoring should use steepness from ORDER_FLOW constants, not hardcoded."""
    metrics = {"funding_rate": 0.0003, "open_interest_change_pct": 5.0, "price_direction": 1}
    result = compute_order_flow_score(metrics)
    # With steepness=400, funding=0.0003 should produce a visible funding_score
    assert abs(result["details"]["funding_score"]) > 1.0, "Funding score too small with recalibrated sigmoid"
    # With steepness=20, OI=5% should produce moderate score
    assert abs(result["details"]["oi_score"]) > 2.0, "OI score too small with recalibrated sigmoid"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_sigmoid_recalibration.py::test_order_flow_uses_constant_steepness -v`
Expected: FAIL — hardcoded steepness 8000 in traditional.py still overrides the constant

- [ ] **Step 3: Replace hardcoded steepness with constant references**

In `backend/app/engine/traditional.py`, add constants after line 342:
```python
FUNDING_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["funding"]
OI_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["oi"]
LS_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["ls_ratio"]
```

Replace line 409:
```python
funding_score = sigmoid_score(-funding, center=0, steepness=FUNDING_STEEPNESS) * 35 * final_mult
```

Replace line 417:
```python
oi_score = price_dir * sigmoid_score(oi_change, center=0, steepness=OI_STEEPNESS) * 20
```

Replace line 421:
```python
ls_score = sigmoid_score(1.0 - ls, center=0, steepness=LS_STEEPNESS) * 35 * final_mult
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_sigmoid_recalibration.py -v`
Expected: PASS

---

## Task 3: Continuous EMA Alignment

**Files:**
- Modify: `backend/app/engine/traditional.py:12-52`
- Test: `backend/tests/engine/test_sigmoid_recalibration.py`

Replace the discrete 3-step EMA alignment (0/0.5/1.0) with a continuous measure: `(ema8 - ema21) / ATR` through a sigmoid. The function `compute_trend_conviction` currently uses a 3-step approach (lines 29-37).

- [ ] **Step 1: Write test for continuous EMA alignment**

Add to `test_sigmoid_recalibration.py`:
```python
from app.engine.traditional import compute_trend_conviction


def test_ema_alignment_is_continuous():
    """EMA alignment should produce continuous values, not discrete 0/0.5/1.0 steps."""
    base = dict(adx=25.0, di_plus=30.0, di_minus=15.0)

    # Strong bullish alignment (ema_9 >> ema_21 >> ema_50)
    r1 = compute_trend_conviction(close=110, ema_9=108, ema_21=105, ema_50=100, atr=2.0, **base)
    # Mild bullish alignment (ema_9 slightly > ema_21)
    r2 = compute_trend_conviction(close=101, ema_9=100.5, ema_21=100.0, ema_50=99.0, atr=2.0, **base)

    # Both bullish direction
    assert r1["direction"] == 1
    assert r2["direction"] == 1
    # Strong should have higher conviction
    assert r1["conviction"] > r2["conviction"]
    # Mild should NOT be exactly 0.5/3 — should be a continuous value between 0 and 1
    # (The old code would give both the same ema_alignment=1.0 since both are fully aligned)
    assert r1["conviction"] != r2["conviction"]


def test_ema_alignment_preserves_direction():
    """Bearish EMA alignment should produce negative direction."""
    r = compute_trend_conviction(
        close=95, ema_9=96, ema_21=98, ema_50=100, atr=2.0,
        adx=25.0, di_plus=12.0, di_minus=28.0,
    )
    assert r["direction"] == -1
    assert r["conviction"] > 0.3  # should show meaningful bearish conviction


def test_ema_alignment_atr_zero_no_crash():
    """ATR=0 should not cause division error — ema_spread defaults to 0."""
    r = compute_trend_conviction(
        close=105, ema_9=104, ema_21=102, ema_50=100, atr=0.0,
        adx=25.0, di_plus=30.0, di_minus=15.0,
    )
    assert r["direction"] == 1
    assert 0.0 <= r["conviction"] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_sigmoid_recalibration.py::test_ema_alignment_is_continuous -v`
Expected: FAIL — current discrete implementation gives same alignment for strong and mild cases

- [ ] **Step 3: Implement continuous EMA alignment**

Note: The function signature must add `atr` parameter. Update `compute_trend_conviction`:

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
    direction = 1 if di_plus > di_minus else -1

    # continuous EMA alignment: normalized distance between EMA pairs through sigmoid
    if atr > 0:
        ema_spread = (ema_9 - ema_21) / atr
    else:
        ema_spread = 0.0
    # sigmoid maps spread to 0-1 range; magnitude-sensitive
    ema_alignment = sigmoid_scale(abs(ema_spread), center=0.5, steepness=2.0)
    # direction consistency: check if spread direction matches DI direction
    spread_dir = 1 if ema_spread >= 0 else -1
    if spread_dir != direction:
        ema_alignment *= 0.3  # penalize conflicting EMA/DI direction

    # ADX strength
    adx_strength = sigmoid_scale(adx, center=20, steepness=0.25)

    # Price confirmation
    above_all = close > ema_9 and close > ema_21 and close > ema_50
    below_all = close < ema_9 and close < ema_21 and close < ema_50
    if (direction == 1 and above_all) or (direction == -1 and below_all):
        price_confirm = 1.0
    else:
        price_confirm = 0.0

    conviction = (ema_alignment + adx_strength + price_confirm) / 3.0
    return {"conviction": conviction, "direction": direction}
```

- [ ] **Step 4: Update callers to pass ATR**

In `backend/app/engine/traditional.py`, find the call to `compute_trend_conviction` (around line 259) and add `atr=atr_val`:
```python
tc = compute_trend_conviction(
    close=close_val,
    ema_9=ema_9_val, ema_21=ema_21_val, ema_50=ema_50_val,
    adx=adx_val, di_plus=di_plus_val, di_minus=di_minus_val,
    atr=atr_val,
)
```

- [ ] **Step 5: Run all sigmoid recalibration tests + existing traditional tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_sigmoid_recalibration.py tests/engine/test_traditional.py -v`
Expected: PASS

---

## Task 4: Update param_groups.py Bounds for Recalibrated Sigmoids

**Files:**
- Modify: `backend/app/engine/param_groups.py`
- Test: `backend/tests/engine/test_sigmoid_recalibration.py`

The `order_flow` param group has bounds for sigmoid steepnesses that need updating to match the recalibrated defaults (funding 400 instead of 8000, OI 20 instead of 65).

- [ ] **Step 1: Verify current bounds in param_groups.py**

Read `param_groups.py` and find the `order_flow` group's steepness bounds. Update the bounds so the recalibrated defaults (400, 20) are centered within the ranges. For example:
- `funding_steepness`: old range probably `3000-15000`, new range `200-800`
- `oi_steepness`: old range probably `30-120`, new range `10-40`

Also update `PARAMETER_DESCRIPTIONS` in `constants.py` to match the new ranges:
```python
"funding_steepness": {
    "description": "Sigmoid steepness for funding rate scoring. Higher = more sensitive to funding extremes",
    "pipeline_stage": "Order Flow Scoring",
    "range": "200-800",
},
"oi_steepness": {
    "description": "Sigmoid steepness for open interest change scoring",
    "pipeline_stage": "Order Flow Scoring",
    "range": "10-40",
},
```

- [ ] **Step 2: Write test verifying defaults are within bounds**

Add to `test_sigmoid_recalibration.py`:
```python
from app.engine.param_groups import PARAM_GROUPS
from app.engine.constants import ORDER_FLOW


def test_recalibrated_defaults_within_param_group_bounds():
    """Recalibrated sigmoid defaults must fall within optimizer sweep bounds."""
    flow_group = PARAM_GROUPS["order_flow"]
    params = flow_group["params"]

    for key in ["funding_steepness", "oi_steepness", "ls_ratio_steepness"]:
        if key in params:
            p = params[key]
            default = ORDER_FLOW["sigmoid_steepnesses"][key.replace("_steepness", "")]
            assert p["min"] <= default <= p["max"], (
                f"{key} default {default} outside bounds [{p['min']}, {p['max']}]"
            )
```

- [ ] **Step 3: Run test**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_sigmoid_recalibration.py::test_recalibrated_defaults_within_param_group_bounds -v`
Expected: PASS after bounds update

---

## Task 5: Wire BB Width Percentile Window Constant

**Files:**
- Modify: `backend/app/engine/traditional.py:229-234`
- Modify: `backend/app/engine/constants.py:16`
- Test: `backend/tests/engine/test_regime_smoothing.py`

The spec says to expand `bb_width_percentile_window` from 50 to 100. First verify whether `traditional.py` reads the constant or hardcodes 50.

- [ ] **Step 1: Verify hardcoded vs constant usage**

Read `traditional.py:229-234`. The code currently hardcodes `50`:
```python
if len(bb_widths) >= 50:
    recent_widths = bb_widths[-50:]
```

This does NOT read `INDICATOR_PERIODS["bb_width_percentile_window"]`.

- [ ] **Step 2: Write failing test**

```python
# backend/tests/engine/test_regime_smoothing.py
from app.engine.constants import INDICATOR_PERIODS


def test_bb_width_percentile_window_is_100():
    """BB width percentile window should be 100 candles for stable volatility context."""
    assert INDICATOR_PERIODS["bb_width_percentile_window"] == 100
```

- [ ] **Step 3: Wire the constant in traditional.py and update the value**

In `backend/app/engine/traditional.py`, add import at top:
```python
from app.engine.constants import INDICATOR_PERIODS
```

Replace lines 229-234:
```python
    bb_pct_window = INDICATOR_PERIODS["bb_width_percentile_window"]
    bb_widths = bb_width.dropna().values
    if len(bb_widths) >= bb_pct_window:
        recent_widths = bb_widths[-bb_pct_window:]
        current_width = bb_widths[-1]
        bb_width_pct = float(np.sum(recent_widths < current_width) / len(recent_widths) * 100)
    else:
        bb_width_pct = 50.0
```

In `backend/app/engine/constants.py`, update line 16:
```python
"bb_width_percentile_window": 100,
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_regime_smoothing.py::test_bb_width_percentile_window_is_100 tests/engine/test_traditional.py -v`
Expected: PASS

---

## Task 6: EMA Smoothing on Regime Mix

**Files:**
- Modify: `backend/app/engine/regime.py`
- Modify: `backend/app/main.py` (lifespan initialization)
- Test: `backend/tests/engine/test_regime_smoothing.py`

Apply EMA (alpha=0.3) to the 4 regime components across consecutive candles. Smoothed state stored in `app.state.smoothed_regime` keyed by `(pair, timeframe)`.

- [ ] **Step 1: Write test for regime smoothing**

Add to `test_regime_smoothing.py`:
```python
from app.engine.regime import compute_regime_mix, smooth_regime_mix


def test_regime_smoothing_prevents_single_candle_flip():
    """Smoothed regime should not flip from trending to ranging on a single candle."""
    smoothed_state = {}

    # Start with strong trending regime
    raw_trending = compute_regime_mix(trend_strength=0.9, vol_expansion=0.8)
    s1 = smooth_regime_mix(raw_trending, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)
    # First call: cold start, should equal raw
    assert abs(s1["trending"] - raw_trending["trending"]) < 0.01

    # Single candle flips to ranging
    raw_ranging = compute_regime_mix(trend_strength=0.1, vol_expansion=0.1)
    s2 = smooth_regime_mix(raw_ranging, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)
    # Should NOT have fully flipped — trending should still be dominant
    assert s2["trending"] > s2["ranging"], "Single candle should not flip regime"


def test_regime_smoothing_cold_start_uses_raw():
    """On cold start (no prior state), smoothed regime should equal raw values."""
    smoothed_state = {}
    raw = compute_regime_mix(trend_strength=0.5, vol_expansion=0.5)
    result = smooth_regime_mix(raw, smoothed_state, "ETH-USDT-SWAP", "15m", alpha=0.3)
    for key in ["trending", "ranging", "volatile", "steady"]:
        assert abs(result[key] - raw[key]) < 0.001


def test_regime_smoothing_converges_after_several_candles():
    """After 5+ consistent candles, smoothed regime should approach the new raw regime."""
    smoothed_state = {}
    # Initialize with trending
    raw_trending = compute_regime_mix(trend_strength=0.9, vol_expansion=0.8)
    smooth_regime_mix(raw_trending, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)

    # Apply 10 candles of ranging regime
    raw_ranging = compute_regime_mix(trend_strength=0.1, vol_expansion=0.1)
    for _ in range(10):
        result = smooth_regime_mix(raw_ranging, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)

    # Should have converged close to ranging
    assert result["ranging"] > 0.6, f"Should have converged to ranging: {result}"


def test_regime_smoothing_isolates_pairs():
    """Different pairs sharing the same state dict should not cross-pollinate."""
    smoothed_state = {}

    # BTC starts trending
    raw_trending = compute_regime_mix(trend_strength=0.9, vol_expansion=0.8)
    smooth_regime_mix(raw_trending, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)

    # ETH starts ranging
    raw_ranging = compute_regime_mix(trend_strength=0.1, vol_expansion=0.1)
    smooth_regime_mix(raw_ranging, smoothed_state, "ETH-USDT-SWAP", "1h", alpha=0.3)

    # Now feed ranging to BTC — should blend with prior trending state
    s_btc = smooth_regime_mix(raw_ranging, smoothed_state, "BTC-USDT-SWAP", "1h", alpha=0.3)
    # Feed trending to ETH — should blend with prior ranging state
    s_eth = smooth_regime_mix(raw_trending, smoothed_state, "ETH-USDT-SWAP", "1h", alpha=0.3)

    # BTC's smoothed trending should still be higher than ETH's (different history)
    assert s_btc["trending"] > s_eth["trending"], (
        f"BTC trending={s_btc['trending']}, ETH trending={s_eth['trending']} — state leaked"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_regime_smoothing.py::test_regime_smoothing_prevents_single_candle_flip -v`
Expected: FAIL — `smooth_regime_mix` function doesn't exist yet

- [ ] **Step 3: Implement smooth_regime_mix in regime.py**

Add to `backend/app/engine/regime.py`:
```python
REGIME_EMA_ALPHA = 0.3


def smooth_regime_mix(
    raw: dict,
    state: dict,
    pair: str,
    timeframe: str,
    alpha: float = REGIME_EMA_ALPHA,
) -> dict:
    """Apply EMA smoothing to regime mix across consecutive candles.

    Args:
        raw: Raw regime mix from compute_regime_mix().
        state: Mutable dict keyed by (pair, timeframe), storing previous smoothed values.
        pair: Trading pair identifier.
        timeframe: Candle timeframe.
        alpha: EMA smoothing factor (0.3 = adapts within 3-5 candles).

    Returns:
        Smoothed regime dict (trending/ranging/volatile/steady summing to ~1.0).
    """
    key = (pair, timeframe)
    prev = state.get(key)
    if prev is None:
        # cold start: use raw values
        smoothed = dict(raw)
    else:
        smoothed = {
            k: alpha * raw[k] + (1 - alpha) * prev[k]
            for k in REGIMES
        }
    # renormalize to sum to 1.0
    total = sum(smoothed.values())
    if total > 0:
        smoothed = {k: v / total for k, v in smoothed.items()}
    state[key] = smoothed
    return smoothed
```

- [ ] **Step 4: Run regime smoothing tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_regime_smoothing.py -v`
Expected: PASS

---

## Task 7: Wire Regime Smoothing in Main Pipeline

**Files:**
- Modify: `backend/app/main.py` (lifespan + run_pipeline)

- [ ] **Step 1: Initialize smoothed regime state in lifespan**

In `backend/app/main.py` lifespan function (around line 1123 where `app.state.order_flow = {}` is set), add:
```python
app.state.smoothed_regime = {}
```

- [ ] **Step 2: Wire smoothing into run_pipeline**

In `run_pipeline`, after the regime is computed from `tech_result` (around line 459), add smoothing:
```python
from app.engine.regime import smooth_regime_mix

regime = tech_result.get("regime")
if regime:
    regime = smooth_regime_mix(regime, app.state.smoothed_regime, pair, timeframe)
```

This replaces the raw regime with the smoothed version before it's used for outer weight blending.

- [ ] **Step 3: Run existing pipeline tests to verify no regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/ -v`
Expected: PASS

---

## Task 8: Per-Pair ADX Center

**Files:**
- Modify: `backend/app/db/models.py:339-394` (RegimeWeights — add `adx_center`)
- Modify: `backend/app/engine/regime.py`
- Modify: `backend/app/engine/traditional.py:270`
- Test: `backend/tests/engine/test_regime_smoothing.py`

Add a learned `adx_center` per (pair, timeframe) to RegimeWeights. Default 20. Used by `compute_regime_mix` as the center for the trend_strength sigmoid.

- [ ] **Step 1: Write test for per-pair ADX center**

Add to `test_regime_smoothing.py`:
```python
from app.engine.scoring import sigmoid_scale


def test_per_pair_adx_center_affects_regime():
    """Different ADX centers should produce different regime mixes for the same ADX value."""
    adx_val = 30.0

    # Default center=20: ADX 30 is above center, strong trend
    ts_default = sigmoid_scale(adx_val, center=20.0, steepness=0.25)
    # Higher center=35 (e.g., WIF): ADX 30 is below center, weak trend
    ts_high = sigmoid_scale(adx_val, center=35.0, steepness=0.25)

    regime_default = compute_regime_mix(ts_default, vol_expansion=0.5)
    regime_high = compute_regime_mix(ts_high, vol_expansion=0.5)

    assert regime_default["trending"] > regime_high["trending"], (
        "Higher ADX center should reduce trending component for same ADX"
    )
```

- [ ] **Step 2: Add adx_center column to RegimeWeights model**

In `backend/app/db/models.py`, add after line 394 (before `updated_at`):
```python
adx_center: Mapped[float] = mapped_column(
    Float, nullable=False, default=20.0, server_default="20.0"
)
```

- [ ] **Step 3: Update compute_technical_score to use per-pair ADX center**

In `backend/app/engine/traditional.py`, modify the trend_strength computation (line 270). The `regime_weights` parameter already passes the RegimeWeights DB row. Read `adx_center` from it:

```python
adx_center = 20.0
if regime_weights is not None and hasattr(regime_weights, "adx_center"):
    adx_center = regime_weights.adx_center
trend_strength = sigmoid_scale(adx_val, center=adx_center, steepness=0.25)
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_regime_smoothing.py tests/engine/test_traditional.py -v`
Expected: PASS

---

## Task 9: Technical Score Confidence Emission

**Files:**
- Modify: `backend/app/engine/traditional.py:179-330`
- Test: `backend/tests/engine/test_confidence_blending.py`

Add a `confidence` key (0.0-1.0) to the `compute_technical_score` return dict. Derived from candle count and indicator agreement.

- [ ] **Step 1: Write test**

```python
# backend/tests/engine/test_confidence_blending.py
import numpy as np
import pandas as pd


def _make_candles(n: int) -> pd.DataFrame:
    """Generate n synthetic candles for testing."""
    np.random.seed(42)
    close = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": close - np.random.rand(n) * 0.3,
        "high": close + np.abs(np.random.randn(n) * 0.5),
        "low": close - np.abs(np.random.randn(n) * 0.5),
        "close": close,
        "volume": np.random.rand(n) * 1000 + 500,
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="1h"),
    })


def test_technical_confidence_scales_with_candle_count():
    """Tech confidence should ramp from 0.5 at 70 candles to 1.0 at 150+."""
    from app.engine.traditional import compute_technical_score

    df_70 = _make_candles(70)
    df_150 = _make_candles(150)

    r70 = compute_technical_score(df_70)
    r150 = compute_technical_score(df_150)

    assert "confidence" in r70, "Tech result must include 'confidence' key"
    assert 0.4 <= r70["confidence"] <= 0.7, f"70 candles should give ~0.5 confidence: {r70['confidence']}"
    assert r150["confidence"] >= 0.8, f"150+ candles should give high confidence: {r150['confidence']}"
    assert r150["confidence"] > r70["confidence"]


def test_technical_confidence_floors_at_zero():
    """Tech confidence should not go negative even with very few candles."""
    from app.engine.traditional import compute_technical_score

    df_30 = _make_candles(70)  # minimum required by pipeline
    r30 = compute_technical_score(df_30)
    assert r30["confidence"] >= 0.0, f"Confidence must not be negative: {r30['confidence']}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_confidence_blending.py::test_technical_confidence_scales_with_candle_count -v`
Expected: FAIL — no `confidence` key in return dict

- [ ] **Step 3: Add confidence computation to compute_technical_score**

At the end of `compute_technical_score` in `traditional.py`, before the `return` statement (line 330), add:
```python
    # confidence: candle count ramp (0.5 at 70 to 1.0 at 150+), clamped to [0, 1]
    candle_confidence = max(0.0, min(1.0, 0.5 + 0.5 * (len(df) - 70) / 80))

    # indicator agreement: trend and volume aligned = higher confidence
    trend_vol_aligned = (trend_score > 0 and (obv_score + vol_score) > 0) or \
                        (trend_score < 0 and (obv_score + vol_score) < 0)
    agreement_boost = 0.1 if trend_vol_aligned else 0.0

    confidence = min(1.0, candle_confidence + agreement_boost)

    return {"score": score, "indicators": indicators, "regime": regime, "caps": caps, "confidence": confidence}
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_confidence_blending.py tests/engine/test_traditional.py -v`
Expected: PASS

---

## Task 10: Order Flow Confidence Emission

**Files:**
- Modify: `backend/app/engine/traditional.py:358-444`
- Test: `backend/tests/engine/test_confidence_blending.py`

Add `confidence` key to `compute_order_flow_score` return dict. Based on data freshness and completeness (all 3 metrics present = 1.0).

- [ ] **Step 1: Write test**

Add to `test_confidence_blending.py`:
```python
from app.engine.traditional import compute_order_flow_score


def test_flow_confidence_full_data():
    """Full flow data (all 3 metrics present) should give high confidence."""
    metrics = {
        "funding_rate": 0.0001,
        "open_interest_change_pct": 3.0,
        "long_short_ratio": 1.2,
        "price_direction": 1,
    }
    result = compute_order_flow_score(metrics)
    assert "confidence" in result, "Flow result must include 'confidence' key"
    assert result["confidence"] >= 0.8


def test_flow_confidence_missing_metrics():
    """Missing flow metrics should reduce confidence proportionally."""
    # Only funding rate provided
    metrics = {"funding_rate": 0.0001}
    result = compute_order_flow_score(metrics)
    assert result["confidence"] < 0.5, "Partial data should give low confidence"


def test_flow_confidence_empty_metrics():
    """Empty metrics dict should give 0 confidence."""
    result = compute_order_flow_score({})
    assert result["confidence"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_confidence_blending.py::test_flow_confidence_full_data -v`
Expected: FAIL

- [ ] **Step 3: Add confidence to compute_order_flow_score**

At the end of `compute_order_flow_score` (before the return), add:
```python
    # confidence based on data completeness and freshness
    present = sum([
        _is_finite(metrics.get("funding_rate")),
        _is_finite(metrics.get("open_interest_change_pct")),
        _is_finite(metrics.get("long_short_ratio")),
    ])
    completeness = present / 3.0

    # data freshness: decay if snapshot is old (caller can pass timestamp)
    freshness = 1.0
    snapshot_age_seconds = metrics.get("_snapshot_age_seconds")
    if snapshot_age_seconds is not None and snapshot_age_seconds > 300:
        # decay linearly from 1.0 at 5min to 0.3 at 30min
        freshness = max(0.3, 1.0 - (snapshot_age_seconds - 300) / 1500)

    confidence = completeness * freshness

    return {"score": score, "details": details, "confidence": confidence}
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_confidence_blending.py -v -k "flow"`
Expected: PASS

---

## Task 11: On-Chain Confidence Emission (Return Type Change)

**Files:**
- Modify: `backend/app/engine/onchain_scorer.py`
- Test: `backend/tests/engine/test_confidence_blending.py`

Change `compute_onchain_score` from returning `int` to returning `{"score": int, "confidence": float}`. Confidence based on number of available metrics. Unsupported pairs return `{"score": 0, "confidence": 0.0}`.

- [ ] **Step 1: Write test**

Add to `test_confidence_blending.py`:
```python
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_onchain_returns_dict_with_confidence():
    """compute_onchain_score should return dict with score and confidence."""
    from app.engine.onchain_scorer import compute_onchain_score

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)  # no data available

    result = await compute_onchain_score("BTC-USDT-SWAP", redis)
    assert isinstance(result, dict), "Must return dict, not int"
    assert "score" in result
    assert "confidence" in result


@pytest.mark.asyncio
async def test_onchain_unsupported_pair_zero_confidence():
    """Unsupported pairs should return confidence=0.0."""
    from app.engine.onchain_scorer import compute_onchain_score

    redis = AsyncMock()
    result = await compute_onchain_score("WIF-USDT-SWAP", redis)
    assert result["score"] == 0
    assert result["confidence"] == 0.0


@pytest.mark.asyncio
async def test_onchain_partial_data_reduces_confidence():
    """Having only some metrics available should reduce confidence."""
    from app.engine.onchain_scorer import compute_onchain_score

    redis = AsyncMock()
    # Only exchange_netflow available (1 of 5 BTC metrics)
    async def mock_get(key):
        if "exchange_netflow" in key:
            return "1000.0"
        return None
    redis.get = mock_get

    result = await compute_onchain_score("BTC-USDT-SWAP", redis)
    assert 0.0 < result["confidence"] < 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_confidence_blending.py::test_onchain_returns_dict_with_confidence -v`
Expected: FAIL — currently returns `int`

- [ ] **Step 3: Update compute_onchain_score to return dict**

In `backend/app/engine/onchain_scorer.py`, replace the function body:
```python
async def compute_onchain_score(pair: str, redis) -> dict:
    """Compute on-chain score for a given pair using asset-specific profile.

    Returns dict with 'score' (int, -100 to +100) and 'confidence' (float, 0.0-1.0).
    Unknown/unsupported pairs return {"score": 0, "confidence": 0.0}.
    """
    asset = pair.split("-")[0].upper()
    profile = _PROFILES.get(asset)
    if profile is None:
        return {"score": 0, "confidence": 0.0}

    score = 0.0
    total_metrics = len(profile["metrics"])
    available_metrics = 0

    # Exchange netflow (±35)
    netflow = await _get_metric(redis, pair, "exchange_netflow")
    if netflow is not None:
        available_metrics += 1
        score += sigmoid_score(-netflow / profile["netflow_norm"], center=0, steepness=1.5) * 35

    # Whale activity (±20)
    whale_count = await _get_metric(redis, pair, "whale_tx_count")
    if whale_count is not None:
        available_metrics += 1
        score += sigmoid_score(profile["whale_baseline"] - whale_count, center=0, steepness=0.3) * 20

    # Active addresses trend (±15)
    addr_trend = await _get_metric(redis, pair, "addr_trend_pct")
    if addr_trend is not None:
        available_metrics += 1
        score += sigmoid_score(addr_trend, center=0, steepness=8) * 15

    if asset == "BTC":
        nupl = await _get_metric(redis, pair, "nupl")
        if nupl is not None:
            available_metrics += 1
            score += sigmoid_score(0.5 - nupl, center=0, steepness=3) * 15
        hashrate = await _get_metric(redis, pair, "hashrate_change_pct")
        if hashrate is not None:
            available_metrics += 1
            score += sigmoid_score(hashrate, center=0, steepness=10) * 15
    elif asset == "ETH":
        staking = await _get_metric(redis, pair, "staking_flow")
        if staking is not None:
            available_metrics += 1
            score += sigmoid_score(-staking, center=0, steepness=1) * 15
        gas_trend = await _get_metric(redis, pair, "gas_trend_pct")
        if gas_trend is not None:
            available_metrics += 1
            score += sigmoid_score(gas_trend, center=0, steepness=5) * 15

    confidence = available_metrics / total_metrics if total_metrics > 0 else 0.0
    return {"score": max(min(round(score), 100), -100), "confidence": confidence}
```

- [ ] **Step 4: Update existing on-chain tests for dict return**

In `backend/tests/engine/test_onchain_scorer.py`, all 10 test cases assign `score = await compute_onchain_score(...)` and compare as int. Change all to:
```python
result = await compute_onchain_score(...)
score = result["score"]
```
Then keep existing assertions on `score`. Also add `assert "confidence" in result` to at least one test.

- [ ] **Step 5: Run all on-chain tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_confidence_blending.py tests/engine/test_onchain_scorer.py -v`
Expected: PASS

---

## Task 12: Pattern Confidence Emission

**Files:**
- Modify: `backend/app/engine/patterns.py`
- Test: `backend/tests/engine/test_confidence_blending.py`

Change `compute_pattern_score` from returning `int` to `{"score": int, "confidence": float}`. Confidence based on number of confirming patterns and volume confirmation.

- [ ] **Step 1: Write test**

Add to `test_confidence_blending.py`:
```python
from app.engine.patterns import compute_pattern_score


def test_pattern_score_returns_dict_with_confidence():
    """compute_pattern_score should return dict with score and confidence."""
    patterns = [{"name": "hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
    result = compute_pattern_score(patterns)
    assert isinstance(result, dict), "Must return dict, not int"
    assert "score" in result
    assert "confidence" in result


def test_pattern_no_patterns_zero_confidence():
    result = compute_pattern_score([])
    assert result["score"] == 0
    assert result["confidence"] == 0.0


def test_pattern_multiple_confirming_patterns_higher_confidence():
    single = compute_pattern_score(
        [{"name": "hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
    )
    multi = compute_pattern_score([
        {"name": "hammer", "type": "candlestick", "bias": "bullish", "strength": 12},
        {"name": "bullish_engulfing", "type": "candlestick", "bias": "bullish", "strength": 15},
    ])
    assert multi["confidence"] > single["confidence"]


def test_pattern_confidence_with_none_context():
    """compute_pattern_score should handle indicator_ctx=None without crashing."""
    patterns = [{"name": "hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
    result = compute_pattern_score(patterns, None)
    assert isinstance(result, dict)
    assert 0.0 <= result["confidence"] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_confidence_blending.py::test_pattern_score_returns_dict_with_confidence -v`
Expected: FAIL

- [ ] **Step 3: Update compute_pattern_score to return dict**

In `backend/app/engine/patterns.py`, modify `compute_pattern_score` to wrap the return:

At the start of the function, handle empty case:
```python
if not patterns:
    return {"score": 0, "confidence": 0.0}
```

At the end, before returning the clamped score, add confidence computation:
```python
    # confidence: based on number of confirming patterns and volume
    n_confirming = sum(1 for p in patterns if p.get("bias") != "neutral")
    pattern_count_factor = min(1.0, n_confirming / 3.0)  # 3+ confirming patterns = full
    vol_factor = 0.5  # base; boosted if volume context present
    if indicator_ctx and indicator_ctx.get("vol_ratio", 1.0) > 1.2:
        vol_factor = 1.0
    confidence = min(1.0, (pattern_count_factor + vol_factor) / 2.0)

    return {"score": max(min(round(total_score), 100), -100), "confidence": confidence}
```

Replace the current `return max(min(round(total_score), 100), -100)` with the dict return above.

- [ ] **Step 4: Run pattern tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_confidence_blending.py -v -k "pattern" && docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py -v`
Expected: PASS — note existing pattern tests will need updating since return type changed from `int` to `dict`

- [ ] **Step 5: Update existing pattern tests for dict return**

In `backend/tests/engine/test_patterns.py`, there are **24 call sites** that assign `score = compute_pattern_score(...)` and compare as int (e.g., `assert score > 0`, `assert score == 27`). Apply this systematic change to all:
```python
# Before:
score = compute_pattern_score(patterns, ctx)
assert score > 0

# After:
result = compute_pattern_score(patterns, ctx)
assert result["score"] > 0
```

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py -v`
Expected: PASS

- [ ] **Step 6: Update backtester.py for dict return**

In `backend/app/engine/backtester.py:178`, change:
```python
# Before:
pat_score = compute_pattern_score(detected, indicator_ctx)

# After:
pat_score = compute_pattern_score(detected, indicator_ctx)["score"]
```

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester.py -v`
Expected: PASS

---

## Task 13: Update Main Pipeline Callers for New Return Types

**Files:**
- Modify: `backend/app/main.py:437-484`

The on-chain scorer now returns `dict`, pattern scorer returns `dict`. Update the callers in `run_pipeline`.

- [ ] **Step 1: Update on-chain caller**

In `main.py`, replace lines 447-456:
```python
    # On-chain scoring (if available)
    onchain_score = 0
    onchain_confidence = 0.0
    onchain_available = False
    if getattr(settings, "onchain_enabled", False):
        try:
            from app.engine.onchain_scorer import compute_onchain_score
            onchain_result = await compute_onchain_score(pair, redis)
            onchain_score = onchain_result["score"]
            onchain_confidence = onchain_result["confidence"]
            onchain_available = onchain_confidence > 0.0
        except Exception as e:
            logger.debug(f"On-chain scoring skipped: {e}")
```

- [ ] **Step 2: Update pattern caller**

In `main.py`, replace lines 437-445:
```python
    # Pattern detection
    detected_patterns = []
    pat_score = 0
    pat_confidence = 0.0
    try:
        detected_patterns = detect_candlestick_patterns(df)
        indicator_ctx = {**tech_result["indicators"], "close": float(df.iloc[-1]["close"])}
        pat_result = compute_pattern_score(detected_patterns, indicator_ctx)
        pat_score = pat_result["score"]
        pat_confidence = pat_result["confidence"]
    except Exception as e:
        logger.debug(f"Pattern detection skipped: {e}")
```

- [ ] **Step 3: Extract confidence from tech and flow results**

After the tech and flow scoring calls, extract their confidence values:
```python
tech_confidence = tech_result.get("confidence", 1.0)
flow_confidence = flow_result.get("confidence", 0.0) if flow_available else 0.0
```

- [ ] **Step 4: Run existing API tests to check for regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=60`
Expected: PASS

---

## Task 14: Confidence-Weighted Combiner Formula

**Files:**
- Modify: `backend/app/engine/combiner.py`
- Modify: `backend/app/main.py:462-484`
- Test: `backend/tests/engine/test_confidence_blending.py`

Update `compute_preliminary_score` to accept confidence values and apply the weighted formula.

- [ ] **Step 1: Write test for confidence-weighted blending**

Add to `test_confidence_blending.py`:
```python
from app.engine.combiner import compute_preliminary_score


def test_zero_confidence_source_drops_out():
    """A source with confidence=0 should not contribute to the blend."""
    # All scores positive, but onchain has 0 confidence
    score_with_onchain = compute_preliminary_score(
        technical_score=60, order_flow_score=40,
        onchain_score=80, pattern_score=30,
        tech_weight=0.40, flow_weight=0.22, onchain_weight=0.23, pattern_weight=0.15,
        tech_confidence=1.0, flow_confidence=1.0, onchain_confidence=0.0, pattern_confidence=1.0,
    )
    score_without_onchain = compute_preliminary_score(
        technical_score=60, order_flow_score=40,
        onchain_score=0, pattern_score=30,
        tech_weight=0.40, flow_weight=0.22, onchain_weight=0.0, pattern_weight=0.15,
        tech_confidence=1.0, flow_confidence=1.0, onchain_confidence=0.0, pattern_confidence=1.0,
    )
    # With confidence=0, onchain_score=80 should be ignored
    assert abs(score_with_onchain - score_without_onchain) < 2


def test_high_confidence_source_gets_more_weight():
    """High-confidence source should have more influence than low-confidence one."""
    # Tech high confidence, flow low confidence
    result1 = compute_preliminary_score(
        technical_score=80, order_flow_score=-60,
        tech_weight=0.5, flow_weight=0.5,
        tech_confidence=1.0, flow_confidence=0.2,
    )
    # Tech low confidence, flow high confidence
    result2 = compute_preliminary_score(
        technical_score=80, order_flow_score=-60,
        tech_weight=0.5, flow_weight=0.5,
        tech_confidence=0.2, flow_confidence=1.0,
    )
    # Result 1 should be more positive (tech-dominated)
    assert result1 > result2


def test_confidence_renormalization_preserves_scale():
    """Even with reduced confidences, output should remain in -100 to +100 range."""
    result = compute_preliminary_score(
        technical_score=100, order_flow_score=100,
        onchain_score=100, pattern_score=100,
        tech_weight=0.40, flow_weight=0.22, onchain_weight=0.23, pattern_weight=0.15,
        tech_confidence=0.5, flow_confidence=0.5, onchain_confidence=0.5, pattern_confidence=0.5,
    )
    assert -100 <= result <= 100


def test_all_zero_confidence_returns_zero():
    """When all sources have 0 confidence, result should be 0 (not NaN or error)."""
    result = compute_preliminary_score(
        technical_score=80, order_flow_score=60,
        onchain_score=40, pattern_score=50,
        tech_weight=0.40, flow_weight=0.22, onchain_weight=0.23, pattern_weight=0.15,
        tech_confidence=0.0, flow_confidence=0.0, onchain_confidence=0.0, pattern_confidence=0.0,
    )
    assert result == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_confidence_blending.py::test_zero_confidence_source_drops_out -v`
Expected: FAIL — `compute_preliminary_score` doesn't accept confidence params

- [ ] **Step 3: Update compute_preliminary_score with confidence weighting**

In `backend/app/engine/combiner.py`, update the function signature and body:
```python
def compute_preliminary_score(
    technical_score: int,
    order_flow_score: int,
    tech_weight: float = 0.40,
    flow_weight: float = 0.22,
    onchain_score: int = 0,
    onchain_weight: float = 0.23,
    pattern_score: int = 0,
    pattern_weight: float = 0.15,
    tech_confidence: float = 1.0,
    flow_confidence: float = 1.0,
    onchain_confidence: float = 1.0,
    pattern_confidence: float = 1.0,
) -> int:
    # apply confidence to base weights
    eff_tech = tech_weight * tech_confidence
    eff_flow = flow_weight * flow_confidence
    eff_onchain = onchain_weight * onchain_confidence
    eff_pattern = pattern_weight * pattern_confidence

    total = eff_tech + eff_flow + eff_onchain + eff_pattern
    if total <= 0:
        return 0
    # renormalize
    eff_tech /= total
    eff_flow /= total
    eff_onchain /= total
    eff_pattern /= total

    return round(
        technical_score * eff_tech
        + order_flow_score * eff_flow
        + onchain_score * eff_onchain
        + pattern_score * eff_pattern
    )
```

- [ ] **Step 4: Update main.py to pass confidence values**

In `main.py`, update the `compute_preliminary_score` call (around lines 475-484):
```python
    indicator_preliminary = compute_preliminary_score(
        tech_result["score"],
        flow_result["score"],
        tech_w,
        flow_w,
        onchain_score,
        onchain_w,
        pat_score,
        pattern_w,
        tech_confidence=tech_confidence,
        flow_confidence=flow_confidence,
        onchain_confidence=onchain_confidence,
        pattern_confidence=pat_confidence,
    )
```

Note: The availability masking (lines 462-473) should still zero out base weights for unavailable sources. Confidence provides a second layer of modulation on top of that.

- [ ] **Step 5: Run all confidence blending tests + combiner tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_confidence_blending.py tests/engine/test_combiner.py -v`
Expected: PASS

- [ ] **Step 6: Update existing combiner tests**

Existing tests in `test_combiner.py` call `compute_preliminary_score` without confidence params. These should still work since the new params have defaults of 1.0. Verify:

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -v`
Expected: PASS (backward-compatible defaults)

---

## Task 15: Signal Confidence Tier

**Files:**
- Modify: `backend/app/db/models.py:62-104` (Signal — add `confidence_tier`)
- Modify: `backend/app/main.py` (compute tier + add to signal_data)
- Test: `backend/tests/engine/test_confidence_blending.py`

Compute overall signal confidence from weighted average of source confidences. Map to `high`/`medium`/`low` tier. Store on Signal model.

- [ ] **Step 1: Write test**

Add to `test_confidence_blending.py`:
```python
def test_compute_signal_confidence_tier():
    """Signal confidence tier derived from weighted average of source confidences."""
    from app.engine.combiner import compute_confidence_tier

    # All high confidence
    assert compute_confidence_tier(
        confidences={"tech": 1.0, "flow": 0.9, "onchain": 0.8, "pattern": 0.7},
        weights={"tech": 0.4, "flow": 0.22, "onchain": 0.23, "pattern": 0.15},
    ) == "high"

    # Mixed
    assert compute_confidence_tier(
        confidences={"tech": 0.7, "flow": 0.3, "onchain": 0.0, "pattern": 0.5},
        weights={"tech": 0.5, "flow": 0.2, "onchain": 0.0, "pattern": 0.3},
    ) == "medium"

    # All low
    assert compute_confidence_tier(
        confidences={"tech": 0.5, "flow": 0.0, "onchain": 0.0, "pattern": 0.2},
        weights={"tech": 1.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0},
    ) == "low"
```

- [ ] **Step 2: Implement compute_confidence_tier in combiner.py**

Add to `backend/app/engine/combiner.py`:
```python
def compute_confidence_tier(
    confidences: dict[str, float],
    weights: dict[str, float],
) -> str:
    """Compute signal confidence tier from weighted source confidences.

    Returns 'high', 'medium', or 'low'.
    """
    all_keys = set(confidences) | set(weights)
    total_weight = sum(weights.get(k, 0.0) for k in all_keys)
    if total_weight <= 0:
        return "low"
    weighted_avg = sum(
        confidences.get(k, 0.0) * weights.get(k, 0.0)
        for k in all_keys
    ) / total_weight

    if weighted_avg >= 0.7:
        return "high"
    elif weighted_avg >= 0.4:
        return "medium"
    return "low"
```

- [ ] **Step 3: Add confidence_tier to Signal model**

In `backend/app/db/models.py`, add after `engine_snapshot` (line 100):
```python
confidence_tier: Mapped[str | None] = mapped_column(String(8), nullable=True)
```

- [ ] **Step 4: Wire confidence tier in main.py signal_data**

In `main.py`, after computing the final score and before building `signal_data`, compute the tier:
```python
from app.engine.combiner import compute_confidence_tier

confidence_tier = compute_confidence_tier(
    confidences={"tech": tech_confidence, "flow": flow_confidence,
                 "onchain": onchain_confidence, "pattern": pat_confidence},
    weights={"tech": tech_w, "flow": flow_w, "onchain": onchain_w, "pattern": pattern_w},
)
```

Add to `signal_data` dict:
```python
"confidence_tier": confidence_tier,
```

Also add confidences to `raw_indicators` for auditability:
```python
"tech_confidence": tech_confidence,
"flow_confidence": flow_confidence,
"onchain_confidence": onchain_confidence,
"pattern_confidence": pat_confidence,
```

- [ ] **Step 5: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_confidence_blending.py -v`
Expected: PASS

---

## Task 16: Alembic Migration

**Files:**
- Create: `backend/alembic/versions/XXXX_signal_engine_v2_foundation.py`

- [ ] **Step 1: Generate migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "signal engine v2 foundation"`

This should detect:
- `Signal.confidence_tier` — new nullable varchar(8)
- `RegimeWeights.adx_center` — new float column with default 20.0

- [ ] **Step 2: Review migration and apply**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head`
Expected: Migration applies successfully

---

## Task 17: Frontend — Display Confidence Tier

**Files:**
- Modify: `web/src/features/signals/types.ts`
- Modify: `web/src/features/signals/components/SignalCard.tsx`
- Modify: `web/src/features/signals/components/SignalDetail.tsx`

- [ ] **Step 1: Add confidence_tier to Signal type**

In `web/src/features/signals/types.ts`, add to the `Signal` interface:
```typescript
confidence_tier: 'high' | 'medium' | 'low' | null;
```

- [ ] **Step 2: Add confidence badge to SignalCard**

In `SignalCard.tsx`, add a badge next to the score or direction badge. Use the existing `Badge` component (already imported):

```tsx
{signal.confidence_tier && (
  <Badge
    color={signal.confidence_tier === 'high' ? 'long' : signal.confidence_tier === 'medium' ? 'accent' : 'muted'}
    pill
    weight="medium"
  >
    {signal.confidence_tier}
  </Badge>
)}
```

- [ ] **Step 3: Add confidence display to SignalDetail**

In `SignalDetail.tsx`, add a row in the signal details section showing the confidence tier.

- [ ] **Step 4: Build and test frontend**

Run: `cd web && pnpm build`
Expected: No TypeScript errors, build succeeds

---

## Task 18: Final Integration Test

- [ ] **Step 1: Run the full backend test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=120`
Expected: All tests pass

- [ ] **Step 2: Verify no regressions in existing scoring behavior**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py tests/engine/test_combiner.py tests/engine/test_regime.py tests/engine/test_patterns.py -v`
Expected: PASS
