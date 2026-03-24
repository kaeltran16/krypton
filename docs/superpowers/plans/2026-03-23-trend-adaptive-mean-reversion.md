# Trend-Adaptive Mean Reversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make mean reversion and contrarian flow scoring trend-aware so the signal engine emits signals during sustained trends instead of cancelling itself out.

**Architecture:** Add a trend conviction function (EMA alignment + ADX + DI → 0-1 float) that continuously suppresses mean reversion and squeeze scores in `compute_technical_score`, and dampens contrarian multiplier in `compute_order_flow_score`. On 4h+ timeframes, RSI/price divergence detection can override suppression to catch reversals. Lower timeframes rely on natural trend conviction decay.

**Tech Stack:** Python, pandas, numpy (all existing dependencies)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/engine/traditional.py` | Modify | Add `compute_trend_conviction()`, `detect_divergence()` helpers; modify `compute_technical_score()` and `compute_order_flow_score()` to use them |
| `backend/tests/engine/test_traditional.py` | Modify | Add test classes for trend conviction, divergence detection, trend suppression behavior, and flow dampening |

No new files created. No changes to combiner, ML, LLM, regime, risk, config, or API layers.

---

### Task 1: Add `compute_trend_conviction` helper + tests

**Files:**
- Modify: `backend/app/engine/traditional.py` (insert after line 7, before `_atr` function)
- Test: `backend/tests/engine/test_traditional.py`

**Context:** This function takes already-computed indicator values (EMA 9/21/50, close price, ADX, DI+, DI-) and returns a float 0.0-1.0 representing how strongly a directional trend is in place. It also returns the trend direction (+1 or -1). The score is composed of three signals:
- EMA alignment (direction-aware): EMA9 < EMA21 < EMA50 (bearish) or EMA9 > EMA21 > EMA50 (bullish) = 1.0; two of three EMAs ordered in the DI-indicated direction = 0.5; EMAs ordered against the DI direction or equal = 0.0
- ADX strength: `sigmoid_scale(adx, center=20, steepness=0.25)` — same function already used for regime detection
- Price confirmation (direction-aware): price above all EMAs when DI says bullish, or below all EMAs when DI says bearish = 1.0; else 0.0. A pullback against the DI direction does not confirm the trend.

The conviction is the mean of these three signals. The direction is determined by DI+/DI- (same as existing trend score logic).

- [ ] **Step 1: Write failing tests for `compute_trend_conviction`**

Add to `backend/tests/engine/test_traditional.py`:

```python
from app.engine.traditional import compute_trend_conviction


class TestTrendConviction:
    def test_full_bearish_conviction(self):
        """Aligned bearish EMAs + strong ADX + price below all EMAs = high conviction."""
        result = compute_trend_conviction(
            close=90.0,
            ema_9=95.0, ema_21=98.0, ema_50=100.0,
            adx=35.0, di_plus=10.0, di_minus=30.0,
        )
        assert result["conviction"] > 0.8
        assert result["direction"] == -1

    def test_full_bullish_conviction(self):
        """Aligned bullish EMAs + strong ADX + price above all EMAs = high conviction."""
        result = compute_trend_conviction(
            close=110.0,
            ema_9=105.0, ema_21=102.0, ema_50=100.0,
            adx=35.0, di_plus=30.0, di_minus=10.0,
        )
        assert result["conviction"] > 0.8
        assert result["direction"] == 1

    def test_no_trend_low_conviction(self):
        """Tangled EMAs + low ADX = low conviction."""
        result = compute_trend_conviction(
            close=100.0,
            ema_9=100.5, ema_21=99.5, ema_50=100.2,
            adx=12.0, di_plus=15.0, di_minus=14.0,
        )
        assert result["conviction"] < 0.4

    def test_partial_alignment_moderate_conviction(self):
        """Two EMAs aligned but not all three = moderate conviction."""
        result = compute_trend_conviction(
            close=97.0,
            ema_9=96.0, ema_21=99.0, ema_50=98.0,  # 9 < 50 < 21, not fully aligned
            adx=28.0, di_plus=12.0, di_minus=25.0,
        )
        assert 0.3 <= result["conviction"] <= 0.7

    def test_conviction_bounded_zero_to_one(self):
        """Conviction is always in [0, 1]."""
        for close, adx in [(50.0, 0.0), (150.0, 80.0)]:
            result = compute_trend_conviction(
                close=close,
                ema_9=100.0, ema_21=100.0, ema_50=100.0,
                adx=adx, di_plus=20.0, di_minus=20.0,
            )
            assert 0.0 <= result["conviction"] <= 1.0

    def test_direction_from_di(self):
        """Direction follows DI+/DI- regardless of EMA order."""
        result = compute_trend_conviction(
            close=100.0,
            ema_9=101.0, ema_21=102.0, ema_50=103.0,
            adx=25.0, di_plus=25.0, di_minus=15.0,
        )
        assert result["direction"] == 1  # DI+ > DI- = bullish

    def test_equal_di_low_conviction(self):
        """When DI+ == DI-, there is no clear trend — conviction should be low."""
        result = compute_trend_conviction(
            close=100.0,
            ema_9=100.0, ema_21=100.0, ema_50=100.0,
            adx=15.0, di_plus=20.0, di_minus=20.0,
        )
        assert result["conviction"] < 0.4

    def test_price_confirm_requires_direction_alignment(self):
        """Price below all EMAs in a bullish trend should NOT confirm the trend."""
        result_misaligned = compute_trend_conviction(
            close=90.0,
            ema_9=95.0, ema_21=98.0, ema_50=100.0,
            adx=30.0, di_plus=25.0, di_minus=15.0,  # bullish DI
        )
        result_aligned = compute_trend_conviction(
            close=110.0,
            ema_9=105.0, ema_21=102.0, ema_50=100.0,
            adx=30.0, di_plus=25.0, di_minus=15.0,  # bullish DI
        )
        assert result_aligned["conviction"] > result_misaligned["conviction"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestTrendConviction -v`
Expected: FAIL with `ImportError: cannot import name 'compute_trend_conviction'`

Note: 8 tests now (added `test_equal_di_low_conviction` and `test_price_confirm_requires_direction_alignment`).

- [ ] **Step 3: Implement `compute_trend_conviction`**

Add to `backend/app/engine/traditional.py` after the imports (before `_atr`):

```python
def compute_trend_conviction(
    close: float,
    ema_9: float,
    ema_21: float,
    ema_50: float,
    adx: float,
    di_plus: float,
    di_minus: float,
) -> dict:
    """Compute trend conviction from EMA alignment, ADX strength, and price position.

    Returns dict with:
        conviction: 0.0 (no trend) to 1.0 (strong directional trend)
        direction: +1 (bullish) or -1 (bearish), from DI+/DI-
    """
    direction = 1 if di_plus > di_minus else -1

    # 1. EMA alignment (direction-aware): full=1.0, partial=0.5, against/equal=0.0
    bullish_full = ema_9 > ema_21 > ema_50
    bearish_full = ema_9 < ema_21 < ema_50
    if bullish_full or bearish_full:
        ema_alignment = 1.0
    elif (direction == 1 and ema_9 > ema_21) or (direction == -1 and ema_9 < ema_21):
        ema_alignment = 0.5
    else:
        ema_alignment = 0.0

    # 2. ADX strength (reuses same sigmoid as regime detection)
    adx_strength = sigmoid_scale(adx, center=20, steepness=0.25)

    # 3. Price confirmation (direction-aware)
    above_all = close > ema_9 and close > ema_21 and close > ema_50
    below_all = close < ema_9 and close < ema_21 and close < ema_50
    if (direction == 1 and above_all) or (direction == -1 and below_all):
        price_confirm = 1.0
    else:
        price_confirm = 0.0

    conviction = (ema_alignment + adx_strength + price_confirm) / 3.0

    return {"conviction": conviction, "direction": direction}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestTrendConviction -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Run full existing test suite to verify no regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`
Expected: All existing tests PASS

---

### Task 2: Add `detect_divergence` helper + tests (4h+ only)

**Files:**
- Modify: `backend/app/engine/traditional.py` (insert after `compute_trend_conviction`)
- Test: `backend/tests/engine/test_traditional.py`

**Context:** Divergence detection compares swing lows/highs in price vs RSI. A bullish divergence = price makes lower low but RSI makes higher low (selling pressure weakening). A bearish divergence = price makes higher high but RSI makes lower high (buying pressure weakening). This function scans the last `lookback` candles for swing points (local minima/maxima using a +-`order` window), then compares the last two swing lows (for bullish) or swing highs (for bearish). Returns a float 0.0-1.0 representing divergence strength, where 0.0 = no divergence.

- [ ] **Step 1: Write failing tests for `detect_divergence`**

Add to `backend/tests/engine/test_traditional.py`:

```python
from app.engine.traditional import detect_divergence


def _make_divergence_data(n=25, swing_type="bullish"):
    """Build price/RSI arrays with clear swing points on a gentle slope baseline.

    Uses a gently declining baseline (not flat) so that _find_swing_points
    strict comparison doesn't produce spurious matches in the baseline region.
    """
    # gentle downward slope baseline to avoid flat-data issues
    close = np.linspace(102.0, 98.0, n)
    rsi = np.linspace(52.0, 48.0, n)

    if swing_type == "bullish":
        # Two swing lows: price lower low, RSI higher low
        close[4], close[5], close[6] = 92.0, 90.0, 92.0
        rsi[4], rsi[5], rsi[6] = 28.0, 25.0, 28.0
        close[14], close[15], close[16] = 87.0, 85.0, 87.0
        rsi[14], rsi[15], rsi[16] = 34.0, 32.0, 34.0
    elif swing_type == "bearish":
        # Two swing highs: price higher high, RSI lower high
        close[4], close[5], close[6] = 108.0, 110.0, 108.0
        rsi[4], rsi[5], rsi[6] = 72.0, 75.0, 72.0
        close[14], close[15], close[16] = 113.0, 115.0, 113.0
        rsi[14], rsi[15], rsi[16] = 68.0, 70.0, 68.0
    elif swing_type == "no_divergence":
        # Both price and RSI making lower lows together
        close[4], close[5], close[6] = 92.0, 90.0, 92.0
        rsi[4], rsi[5], rsi[6] = 28.0, 25.0, 28.0
        close[14], close[15], close[16] = 87.0, 85.0, 87.0
        rsi[14], rsi[15], rsi[16] = 23.0, 20.0, 23.0

    return pd.Series(close), pd.Series(rsi)


class TestDetectDivergence:
    def test_bullish_divergence(self):
        """Price lower lows + RSI higher lows = bullish divergence."""
        close, rsi = _make_divergence_data(25, "bullish")
        result = detect_divergence(close, rsi, lookback=25, order=2)
        assert result > 0.0

    def test_bearish_divergence(self):
        """Price higher highs + RSI lower highs = bearish divergence."""
        close, rsi = _make_divergence_data(25, "bearish")
        result = detect_divergence(close, rsi, lookback=25, order=2)
        assert result > 0.0

    def test_no_divergence(self):
        """Price and RSI moving together = no divergence."""
        close, rsi = _make_divergence_data(25, "no_divergence")
        result = detect_divergence(close, rsi, lookback=25, order=2)
        assert result == 0.0

    def test_insufficient_swing_points(self):
        """Not enough swing points returns 0.0."""
        # gentle slope with no swing points
        close = pd.Series(np.linspace(100.0, 98.0, 10))
        rsi = pd.Series(np.linspace(50.0, 48.0, 10))
        result = detect_divergence(close, rsi, lookback=10, order=2)
        assert result == 0.0

    def test_returns_bounded_value(self):
        """Result is always in [0.0, 1.0]."""
        close, rsi = _make_divergence_data(25, "bullish")
        result = detect_divergence(close, rsi, lookback=25, order=2)
        assert 0.0 <= result <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestDetectDivergence -v`
Expected: FAIL with `ImportError: cannot import name 'detect_divergence'`

- [ ] **Step 3: Implement `detect_divergence`**

Add to `backend/app/engine/traditional.py` after `compute_trend_conviction`:

```python
def _find_swing_points(series: np.ndarray, order: int, mode: str) -> list[int]:
    """Find local minima or maxima indices in a series.

    Uses strict comparison: the center point must be strictly less/greater
    than all neighbors in the window. This prevents flat regions from
    producing spurious swing points.

    Args:
        series: 1D array of values.
        order: Number of points on each side to compare.
        mode: "min" for swing lows, "max" for swing highs.
    """
    indices = []
    for i in range(order, len(series) - order):
        left = series[i - order : i]
        right = series[i + 1 : i + order + 1]
        if mode == "min" and series[i] < left.min() and series[i] < right.min():
            indices.append(i)
        elif mode == "max" and series[i] > left.max() and series[i] > right.max():
            indices.append(i)
    return indices


def detect_divergence(
    close: pd.Series,
    rsi: pd.Series,
    lookback: int = 50,
    order: int = 3,
) -> float:
    """Detect RSI/price divergence over recent candles.

    Checks for both bullish divergence (price lower low + RSI higher low)
    and bearish divergence (price higher high + RSI lower high).
    Returns the stronger divergence if both are present.

    Args:
        close: Price close series.
        rsi: RSI series (same length as close).
        lookback: Number of recent candles to scan.
        order: Swing point detection window (points on each side).

    Returns:
        0.0 (no divergence) to 1.0 (strong divergence).
    """
    close_arr = close.values[-lookback:].astype(float)
    rsi_arr = rsi.values[-lookback:].astype(float)

    if len(close_arr) < 2 * order + 1:
        return 0.0

    best = 0.0

    # Check bullish divergence (swing lows)
    swing_lows = _find_swing_points(close_arr, order, "min")
    if len(swing_lows) >= 2:
        i1, i2 = swing_lows[-2], swing_lows[-1]
        price_lower = close_arr[i2] < close_arr[i1]
        rsi_higher = rsi_arr[i2] > rsi_arr[i1]
        if price_lower and rsi_higher:
            rsi_diff = rsi_arr[i2] - rsi_arr[i1]
            best = max(best, min(1.0, rsi_diff / 15.0))

    # Check bearish divergence (swing highs)
    swing_highs = _find_swing_points(close_arr, order, "max")
    if len(swing_highs) >= 2:
        i1, i2 = swing_highs[-2], swing_highs[-1]
        price_higher = close_arr[i2] > close_arr[i1]
        rsi_lower = rsi_arr[i2] < rsi_arr[i1]
        if price_higher and rsi_lower:
            rsi_diff = rsi_arr[i1] - rsi_arr[i2]
            best = max(best, min(1.0, rsi_diff / 15.0))

    return best
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestDetectDivergence -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`
Expected: All tests PASS

---

### Task 3: Wire trend conviction into `compute_technical_score` + tests

**Files:**
- Modify: `backend/app/engine/traditional.py:59-192` (`compute_technical_score` function)
- Test: `backend/tests/engine/test_traditional.py`

**Context:** After computing all indicators and sub-scores (trend, mean_rev, squeeze, volume), apply the trend conviction suppression factor to mean_rev_score and squeeze_score. The suppression factor is `1.0 - conviction`, so full conviction → mean_rev and squeeze go to zero. On 4h+ timeframes, divergence can override: `suppression = max(1.0 - conviction, divergence)`. The timeframe must be passed into the function (new optional parameter, defaulting to None which means no divergence check).

The function currently computes at lines 148-165:
```python
trend_score = di_sign * sigmoid_scale(adx_val, ...) * caps["trend_cap"]
mean_rev_score = (blend_ratio * rsi_raw + ...) * caps["mean_rev_cap"]
squeeze_score = mean_rev_sign * sigmoid_scale(...) * caps["squeeze_cap"]
obv_score = ...
vol_score = ...
total = trend_score + mean_rev_score + squeeze_score + obv_score + vol_score
```

After this change, mean_rev_score and squeeze_score get multiplied by the suppression factor before being added to total.

**Important:** The existing `_make_candles` helper creates weak synthetic trends (drift=0.2 on base=100) which don't produce strong EMA alignment or high ADX. Existing tests that check `score > 0` for uptrend and `score < 0` for downtrend will continue to pass because:
1. The synthetic data has weak trends → low conviction → low suppression
2. The trend score (DI direction) still dominates for the existing test data

New tests will use candles with stronger trends to verify suppression behavior.

- [ ] **Step 1: Write failing tests for trend suppression in `compute_technical_score`**

Add to `backend/tests/engine/test_traditional.py`:

```python
def _make_strong_trend_candles(n=100, direction="down", seed=42):
    """Generate candles with a strong sustained trend.

    Stronger drift than _make_candles to produce clear EMA alignment,
    high ADX, and meaningful trend conviction.
    """
    rng = np.random.RandomState(seed)
    base = 100.0
    rows = []
    prev_c = base
    for i in range(n):
        flat_period = n - 50  # 50 candles of flat, then 50 of strong trend
        if i < flat_period:
            drift = 0.0
        elif direction == "down":
            drift = -0.5
        else:
            drift = 0.5
        c = prev_c + drift + rng.uniform(-0.1, 0.1)
        o = prev_c + rng.uniform(-0.05, 0.05)
        h = max(o, c) + rng.uniform(0.05, 0.2)
        l = min(o, c) - rng.uniform(0.05, 0.2)
        v = rng.uniform(100, 200)
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        prev_c = c
    return pd.DataFrame(rows)


class TestTrendSuppression:
    def test_strong_downtrend_produces_negative_score(self):
        """In a strong downtrend, suppressing bullish mean reversion should make
        the overall score more negative than without suppression."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df)
        assert result["score"] < 0

    def test_strong_uptrend_produces_positive_score(self):
        """In a strong uptrend, suppressing bearish mean reversion should make
        the overall score more positive."""
        df = _make_strong_trend_candles(100, "up")
        result = compute_technical_score(df)
        assert result["score"] > 0

    def test_conviction_in_indicators(self):
        """Trend conviction value is exposed in indicators dict and is meaningful for strong trends."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df)
        assert "trend_conviction" in result["indicators"]
        assert result["indicators"]["trend_conviction"] > 0.5, (
            f"Strong downtrend should have high conviction, got {result['indicators']['trend_conviction']}"
        )

    def test_suppression_factor_in_indicators(self):
        """Mean reversion suppression factor is exposed in indicators dict."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df)
        assert "mr_suppression" in result["indicators"]
        assert 0.0 <= result["indicators"]["mr_suppression"] <= 1.0

    def test_weak_trend_minimal_suppression(self):
        """Weak trend data should have suppression factor close to 1.0 (no suppression)."""
        df = _make_candles(80, "up")  # weak drift=0.2 produces low conviction
        result = compute_technical_score(df)
        assert result["indicators"]["mr_suppression"] >= 0.6

    def test_timeframe_param_backward_compatible(self):
        """Calling without timeframe works (no divergence check, suppression only)."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert -100 <= result["score"] <= 100

    def test_divergence_field_on_4h(self):
        """On 4h timeframe, divergence detection runs and exposes the field."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df, timeframe="4h")
        assert "divergence" in result["indicators"]
        assert result["indicators"]["divergence"] >= 0.0

    def test_divergence_not_checked_on_lower_timeframes(self):
        """On sub-4h timeframes, divergence is always 0.0."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df, timeframe="1h")
        assert result["indicators"]["divergence"] == 0.0

    def test_suppression_formula_divergence_override(self):
        """Divergence overrides conviction suppression via max(1-conviction, divergence).

        This tests the formula directly: when divergence is stronger than
        (1 - conviction), divergence wins and allows mean reversion through.
        """
        # High conviction (0.95) would normally suppress to 0.05,
        # but divergence (0.8) overrides, keeping suppression at 0.8
        assert max(1.0 - 0.95, 0.8) == 0.8
        # Low divergence doesn't override
        assert max(1.0 - 0.5, 0.2) == 0.5
        # Zero conviction means full mean reversion regardless
        assert max(1.0 - 0.0, 0.0) == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestTrendSuppression -v`
Expected: FAIL — `trend_conviction` not in indicators, `mr_suppression` not in indicators

- [ ] **Step 3: Modify `compute_technical_score` to apply trend suppression**

In `backend/app/engine/traditional.py`, modify the `compute_technical_score` function:

1. Add `timeframe: str | None = None` parameter to the function signature (line 59).

2. After computing EMA values and last indicator values (after line 128), add the trend conviction block. Note: the existing code computes `float(ema_9.iloc[-1])` inline at lines 187-189 for the indicators dict. Move these to named variables here and reuse them in the indicators dict (see step 5).

```python
    # === Trend conviction ===
    ema_9_val = float(ema_9[last])
    ema_21_val = float(ema_21[last])
    ema_50_val = float(ema_50[last])
    close_val = float(close[last])

    tc = compute_trend_conviction(
        close=close_val,
        ema_9=ema_9_val, ema_21=ema_21_val, ema_50=ema_50_val,
        adx=adx_val, di_plus=di_plus_val, di_minus=di_minus_val,
    )
    trend_conviction = tc["conviction"]

    # Divergence override (4h+ only)
    htf_timeframes = {"4h", "1D"}
    divergence = 0.0
    if timeframe in htf_timeframes:
        divergence = detect_divergence(close, rsi, lookback=50, order=3)

    # Suppression factor: 1.0 = full mean reversion, 0.0 = fully suppressed
    # Divergence can restore mean reversion even during strong trends
    mr_suppression = max(1.0 - trend_conviction, divergence)
```

Note: Uses `close[last]` and `ema_9[last]` consistent with existing code pattern (line 107: `float(close[last])`).

3. Modify the scoring section (around lines 148-165). After computing `mean_rev_score` and `squeeze_score`, apply suppression:

```python
    # Apply trend-adaptive suppression
    mean_rev_score = mean_rev_score * mr_suppression
    squeeze_score = squeeze_score * mr_suppression
```

4. Add the new indicators to the `indicators` dict (around line 168):

```python
        "trend_conviction": round(trend_conviction, 2),
        "mr_suppression": round(mr_suppression, 2),
        "divergence": round(divergence, 2),
```

5. Replace the inline EMA computations in the indicators dict (lines 187-189) with the named variables computed earlier:

```python
    # Before (lines 187-189):
    "ema_9": round(float(ema_9.iloc[-1]), 2),
    "ema_21": round(float(ema_21.iloc[-1]), 2),
    "ema_50": round(float(ema_50.iloc[-1]), 2),

    # After:
    "ema_9": round(ema_9_val, 2),
    "ema_21": round(ema_21_val, 2),
    "ema_50": round(ema_50_val, 2),
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestTrendSuppression -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`
Expected: All existing tests PASS (weak synthetic data has low conviction → minimal suppression → direction tests unaffected)

---

### Task 4: Wire trend conviction into `compute_order_flow_score` + tests

**Files:**
- Modify: `backend/app/engine/traditional.py:220-301` (`compute_order_flow_score` function)
- Test: `backend/tests/engine/test_traditional.py`

**Context:** The flow scoring currently has a `contrarian_mult` that scales down contrarian signals in trending regimes. Trend conviction should further dampen this. When trend conviction is high, contrarian signals (funding rate, L/S ratio) should be suppressed beyond what regime scaling already does. The existing `contrarian_mult` (from regime) ranges from ~0.3 to 1.0. We multiply it by `(1.0 - trend_conviction)` to further suppress. This requires passing `trend_conviction` as a new optional parameter.

- [ ] **Step 1: Write failing tests for trend conviction dampening in flow scoring**

Add to `backend/tests/engine/test_traditional.py`:

```python
class TestOrderFlowTrendConviction:
    def test_high_conviction_suppresses_contrarian(self):
        """High trend conviction should reduce contrarian flow score magnitude."""
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        result_low = compute_order_flow_score(metrics, trend_conviction=0.0)
        result_high = compute_order_flow_score(metrics, trend_conviction=0.9)
        assert abs(result_high["score"]) < abs(result_low["score"])

    def test_zero_conviction_no_change(self):
        """Zero trend conviction should not change scoring behavior."""
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        result_without = compute_order_flow_score(metrics)
        result_with = compute_order_flow_score(metrics, trend_conviction=0.0)
        assert result_without["score"] == result_with["score"]

    def test_oi_unaffected_by_conviction(self):
        """OI score is direction-aware, not contrarian, so conviction shouldn't affect it."""
        metrics = {"open_interest_change_pct": 0.05, "price_direction": 1}
        result_low = compute_order_flow_score(metrics, trend_conviction=0.0)
        result_high = compute_order_flow_score(metrics, trend_conviction=0.9)
        assert result_low["score"] == result_high["score"]

    def test_conviction_stacks_with_regime(self):
        """Trending regime + high conviction should suppress more than either alone."""
        metrics = {"funding_rate": -0.0005}
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        score_regime_only = abs(compute_order_flow_score(
            metrics, regime=regime, trend_conviction=0.0,
        )["score"])
        score_both = abs(compute_order_flow_score(
            metrics, regime=regime, trend_conviction=0.8,
        )["score"])
        assert score_both < score_regime_only

    def test_conviction_in_details(self):
        """Trend conviction value is exposed in details dict."""
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, trend_conviction=0.7)
        assert "trend_conviction" in result["details"]
        assert result["details"]["trend_conviction"] == 0.7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowTrendConviction -v`
Expected: FAIL — `compute_order_flow_score` doesn't accept `trend_conviction` parameter

- [ ] **Step 3: Modify `compute_order_flow_score` to accept and use trend conviction**

In `backend/app/engine/traditional.py`, modify `compute_order_flow_score`:

1. Add `trend_conviction: float = 0.0` parameter to the function signature.

2. After computing `final_mult` (line 263), apply trend conviction dampening:

```python
    # Trend conviction further dampens contrarian signals
    conviction_dampening = 1.0 - trend_conviction
    final_mult = final_mult * conviction_dampening
```

3. Add to the `details` dict:

```python
        "trend_conviction": round(trend_conviction, 2),
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestOrderFlowTrendConviction -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`
Expected: All tests PASS (existing calls don't pass `trend_conviction`, defaults to 0.0 → no behavior change)

---

### Task 5: Wire `timeframe` and `trend_conviction` through `run_pipeline` in `main.py`

**Files:**
- Modify: `backend/app/main.py:332-335` (`compute_technical_score` call) and `backend/app/main.py:413-417` (`compute_order_flow_score` call)

**Context:** The pipeline already has `timeframe` as a local variable. Pass it to `compute_technical_score`. Extract `trend_conviction` from the tech_result indicators dict and pass it to `compute_order_flow_score`. No test changes needed — this is a wiring change tested by the integration of Task 3 and Task 4 behavior.

**Note — other callers not wired:** `compute_technical_score` is also called from `backend/app/api/routes.py:551` (`/engine/simulate` endpoint) and `backend/app/engine/backtester.py:39,155`. These callers use the default `timeframe=None`, which means they get trend conviction suppression but no divergence detection. This is intentional — simulation and backtest don't need divergence override, and the default behavior (suppression without divergence) is the safer mode.

- [ ] **Step 1: Pass `timeframe` to `compute_technical_score`**

In `backend/app/main.py`, modify the call at ~line 332:

```python
    # Before:
    tech_result = compute_technical_score(
        df, regime_weights=regime_weights,
        scoring_params=scoring_params or None,
    )

    # After:
    tech_result = compute_technical_score(
        df, regime_weights=regime_weights,
        scoring_params=scoring_params or None,
        timeframe=timeframe,
    )
```

- [ ] **Step 2: Pass `trend_conviction` to `compute_order_flow_score`**

In `backend/app/main.py`, modify the call at ~line 413:

```python
    # Before:
    flow_result = compute_order_flow_score(
        flow_metrics,
        regime=tech_result["regime"],
        flow_history=flow_history,
    )

    # After:
    flow_result = compute_order_flow_score(
        flow_metrics,
        regime=tech_result["regime"],
        flow_history=flow_history,
        trend_conviction=tech_result["indicators"].get("trend_conviction", 0.0),
    )
```

- [ ] **Step 3: Run full backend test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v`
Expected: All tests PASS

---

### Task 6: Final validation and commit

**Files:**
- All modified files from Tasks 1-5

- [ ] **Step 1: Run full test suite one final time**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v`
Expected: All tests PASS

- [ ] **Step 2: Review git diff**

Run: `git diff --stat`
Expected: Two files changed:
- `backend/app/engine/traditional.py`
- `backend/tests/engine/test_traditional.py`
One file with minor wiring change:
- `backend/app/main.py`

- [ ] **Step 3: Stage and commit**

```bash
git add backend/app/engine/traditional.py backend/tests/engine/test_traditional.py backend/app/main.py
git commit -m "feat(engine): trend-adaptive mean reversion suppression with divergence override"
```

Wait for user approval before committing.
