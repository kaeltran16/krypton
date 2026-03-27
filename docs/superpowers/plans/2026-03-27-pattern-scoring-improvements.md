# Pattern Scoring Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 3 bugs, add 2 scoring improvements, and add 4 detection improvements to the candlestick pattern scoring pipeline, with optimizer integration.

**Architecture:** All scoring/detection changes are in `engine/patterns.py`. New constants in `engine/constants.py`. Optimizer wiring in `engine/param_groups.py` + `engine/backtester.py`. Production wiring in `main.py`. DB migration adds JSONB columns to `PipelineSettings` for promoted overrides.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Alembic, pytest (async), Docker

**Spec:** `docs/superpowers/specs/2026-03-27-pattern-scoring-improvements-design.md`

**Test command prefix** (all tasks use this):
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest
```

---

### Task 1: Add pattern boost constants

**Files:**
- Modify: `backend/app/engine/constants.py:87-103` (after PATTERN_STRENGTHS)
- Modify: `backend/app/engine/constants.py:637-639` (get_engine_constants patterns section)

- [ ] **Step 1: Add PATTERN_BOOST_DEFAULTS dict after PATTERN_STRENGTHS**

In `backend/app/engine/constants.py`, after the `PATTERN_STRENGTHS` dict (line ~103), add:

```python
PATTERN_BOOST_DEFAULTS = {
    "vol_center": 1.35,
    "vol_steepness": 8.0,
    "reversal_boost": 0.3,
    "continuation_boost": 0.2,
}
```

- [ ] **Step 2: Expose boosts in get_engine_constants**

In the `get_engine_constants()` function, update the `"patterns"` section from:

```python
"patterns": {
    "strengths": _wrap(PATTERN_STRENGTHS),
},
```

to:

```python
"patterns": {
    "strengths": _wrap(PATTERN_STRENGTHS),
    "boosts": _wrap(PATTERN_BOOST_DEFAULTS),
},
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py -v`

Expected: All existing tests PASS (no behavior change, just new constants).

---

### Task 2: Continuous volume boost curve (spec 2.1)

**Files:**
- Modify: `backend/app/engine/patterns.py:7` (import)
- Modify: `backend/app/engine/patterns.py:242-246` (signature)
- Modify: `backend/app/engine/patterns.py:295-300` (volume boost logic)
- Test: `backend/tests/engine/test_patterns.py`

- [ ] **Step 1: Write failing tests for continuous volume boost**

Add to `backend/tests/engine/test_patterns.py`:

```python
class TestContinuousVolumeBoost:
    def test_continuous_curve_no_jump(self):
        """Small vol_ratio change across old threshold should produce small score change."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx_130 = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.30, "bb_pos": 0.5, "close": 100}
        ctx_140 = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.40, "bb_pos": 0.5, "close": 100}
        score_130 = compute_pattern_score(patterns, ctx_130)["score"]
        score_140 = compute_pattern_score(patterns, ctx_140)["score"]
        # continuous curve: nearby ratios produce different but close scores
        assert score_140 > score_130

    def test_low_volume_minimal_boost(self):
        """vol_ratio 1.0 should give negligible boost."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)["score"]
        assert score == 12

    def test_high_volume_approaches_max(self):
        """vol_ratio 2.0+ should give near-max boost (~1.3x)."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 2.5, "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx)["score"]
        assert 15 <= score <= 16  # 12 * ~1.3 = ~15.6

    def test_boost_overrides_vol_params(self):
        """boost_overrides can shift the volume sigmoid center."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.2, "bb_pos": 0.5, "close": 100}
        score_default = compute_pattern_score(patterns, ctx)["score"]
        # shift center down so 1.2 is well above center → bigger boost
        score_shifted = compute_pattern_score(
            patterns, ctx, boost_overrides={"vol_center": 1.0, "vol_steepness": 10.0}
        )["score"]
        assert score_shifted > score_default
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestContinuousVolumeBoost -v`

Expected: FAIL — `test_continuous_curve_no_jump` fails (current hard thresholds give same score at 1.30 and 1.40), `test_boost_overrides_vol_params` fails (boost_overrides param doesn't exist).

- [ ] **Step 3: Add sigmoid_scale import**

In `backend/app/engine/patterns.py`, change line 7 from:

```python
from app.engine.scoring import sigmoid_score
```

to:

```python
from app.engine.scoring import sigmoid_score, sigmoid_scale
```

- [ ] **Step 4: Add boost_overrides param and implement continuous volume boost**

In `backend/app/engine/patterns.py`, update the `compute_pattern_score` signature and volume boost logic.

Change the signature (line 242-246) from:

```python
def compute_pattern_score(
    patterns: list[dict],
    indicator_ctx: dict | None = None,
    strength_overrides: dict[str, int | float] | None = None,
) -> dict:
```

to:

```python
def compute_pattern_score(
    patterns: list[dict],
    indicator_ctx: dict | None = None,
    strength_overrides: dict[str, int | float] | None = None,
    regime_trending: float | None = None,
    boost_overrides: dict[str, float] | None = None,
) -> dict:
```

Add boost resolution after the `indicator_ctx` defaults block (after line 262):

```python
    from app.engine.constants import PATTERN_BOOST_DEFAULTS
    _boosts = {**PATTERN_BOOST_DEFAULTS, **(boost_overrides or {})}
```

Replace the volume boost block (lines 295-300) from:

```python
        # Volume confirmation boost
        vol_boost = 1.0
        if vol_ratio > 1.5:
            vol_boost = 1.3
        elif vol_ratio > 1.2:
            vol_boost = 1.15
```

to:

```python
        # Volume confirmation boost (continuous sigmoid curve)
        vol_boost = 1.0 + 0.3 * sigmoid_scale(
            vol_ratio, center=_boosts["vol_center"], steepness=_boosts["vol_steepness"]
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestContinuousVolumeBoost tests/engine/test_patterns.py::TestVolumeConfirmationBoost tests/engine/test_patterns.py::TestPatternScoring -v`

Expected: All PASS — new tests verify continuous behavior, existing volume and scoring tests still pass.

---

### Task 3: Regime-aware trend boost (spec 2.2)

**Files:**
- Modify: `backend/app/engine/patterns.py:284-293` (trend boost logic)
- Test: `backend/tests/engine/test_patterns.py`

- [ ] **Step 1: Write failing tests for regime-aware trend boost**

Add to `backend/tests/engine/test_patterns.py`:

```python
class TestRegimeAwareTrendBoost:
    def test_regime_trending_scales_reversal_boost(self):
        """Higher regime_trending gives larger reversal boost."""
        patterns = [{"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15}]
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score_low = compute_pattern_score(patterns, ctx, regime_trending=0.2)["score"]
        score_high = compute_pattern_score(patterns, ctx, regime_trending=0.8)["score"]
        assert score_high > score_low

    def test_regime_trending_scales_continuation_boost(self):
        """Continuation boost also scales with regime_trending."""
        patterns = [{"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15}]
        # bullish pattern + bullish DI = continuation
        ctx = {"adx": 25, "di_plus": 30, "di_minus": 10, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score_low = compute_pattern_score(patterns, ctx, regime_trending=0.2)["score"]
        score_high = compute_pattern_score(patterns, ctx, regime_trending=0.8)["score"]
        assert score_high > score_low

    def test_regime_trending_zero_no_boost(self):
        """regime_trending=0 gives trend_boost 1.0 regardless of ADX."""
        patterns = [{"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15}]
        ctx = {"adx": 40, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx, regime_trending=0.0)["score"]
        assert score == 15  # no trend boost

    def test_regime_trending_none_fallback(self):
        """When regime_trending=None, use legacy ADX thresholds."""
        patterns = [{"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15}]
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score = compute_pattern_score(patterns, ctx, regime_trending=None)["score"]
        # legacy: reversal at adx >= 15 gives 1.3x -> round(15 * 1.3) = 20
        assert score == 20

    def test_boost_overrides_reversal_base(self):
        """boost_overrides can change the reversal boost base."""
        patterns = [{"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15}]
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 100}
        score_default = compute_pattern_score(patterns, ctx, regime_trending=1.0)["score"]
        score_boosted = compute_pattern_score(
            patterns, ctx, regime_trending=1.0,
            boost_overrides={"reversal_boost": 0.5},
        )["score"]
        assert score_boosted > score_default
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestRegimeAwareTrendBoost -v`

Expected: FAIL — regime_trending is accepted (added in Task 2 signature) but not used yet; score_low == score_high since the old ADX threshold logic ignores regime_trending.

- [ ] **Step 3: Replace ADX threshold trend boost with continuous regime scaling**

In `backend/app/engine/patterns.py`, replace the trend boost block (lines 284-293) from:

```python
        # Trend-alignment boost
        trend_boost = 1.0
        if adx >= 15:
            pattern_bullish = bias == "bullish"
            if pattern_bullish != adx_bullish:
                # Reversal signal
                trend_boost = 1.3
            elif adx >= 30:
                # Continuation with strong trend
                trend_boost = 1.2
```

to:

```python
        # Trend-alignment boost
        trend_boost = 1.0
        pattern_bullish = bias == "bullish"
        if regime_trending is not None:
            if pattern_bullish != adx_bullish:
                trend_boost = 1.0 + _boosts["reversal_boost"] * regime_trending
            else:
                trend_boost = 1.0 + _boosts["continuation_boost"] * regime_trending
        elif adx >= 15:
            if pattern_bullish != adx_bullish:
                trend_boost = 1.3
            elif adx >= 30:
                trend_boost = 1.2
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestRegimeAwareTrendBoost tests/engine/test_patterns.py::TestTrendAlignmentBoost -v`

Expected: All PASS — new regime tests verify continuous scaling, existing trend tests pass via the `regime_trending=None` fallback.

---

### Task 4: Directional confidence model (spec 1.3)

**Files:**
- Modify: `backend/app/engine/patterns.py:315-317` (confidence calculation)
- Test: `backend/tests/engine/test_patterns.py`

- [ ] **Step 1: Write failing tests for directional confidence**

Add to `backend/tests/engine/test_patterns.py`:

```python
class TestDirectionalConfidence:
    def test_contradictory_patterns_reduce_confidence(self):
        """2 bull + 1 bear has lower confidence than 3 bull (same count)."""
        unanimous = [
            {"name": "A", "type": "c", "bias": "bullish", "strength": 10},
            {"name": "B", "type": "c", "bias": "bullish", "strength": 10},
            {"name": "C", "type": "c", "bias": "bullish", "strength": 10},
        ]
        mixed = [
            {"name": "A", "type": "c", "bias": "bullish", "strength": 10},
            {"name": "B", "type": "c", "bias": "bullish", "strength": 10},
            {"name": "C", "type": "c", "bias": "bearish", "strength": 10},
        ]
        conf_unanimous = compute_pattern_score(unanimous)["confidence"]
        conf_mixed = compute_pattern_score(mixed)["confidence"]
        assert conf_unanimous > conf_mixed

    def test_evenly_split_half_confidence(self):
        """1 bull + 1 bear → agreement 0.5, count-based 0.67, product ~0.33."""
        patterns = [
            {"name": "A", "type": "c", "bias": "bullish", "strength": 10},
            {"name": "B", "type": "c", "bias": "bearish", "strength": 10},
        ]
        conf = compute_pattern_score(patterns)["confidence"]
        assert 0.30 <= conf <= 0.40

    def test_unanimous_full_confidence(self):
        """3 same-direction patterns → confidence 1.0."""
        patterns = [
            {"name": "A", "type": "c", "bias": "bearish", "strength": 10},
            {"name": "B", "type": "c", "bias": "bearish", "strength": 10},
            {"name": "C", "type": "c", "bias": "bearish", "strength": 10},
        ]
        conf = compute_pattern_score(patterns)["confidence"]
        assert conf == 1.0

    def test_single_pattern_confidence(self):
        """1 non-neutral pattern → agreement 1.0, count-based 0.33."""
        patterns = [{"name": "A", "type": "c", "bias": "bullish", "strength": 10}]
        conf = compute_pattern_score(patterns)["confidence"]
        assert 0.30 <= conf <= 0.40

    def test_all_neutral_patterns_zero_confidence(self):
        """Only neutral patterns → 0 non-neutral → confidence 0.0."""
        patterns = [
            {"name": "A", "type": "c", "bias": "neutral", "strength": 5},
            {"name": "B", "type": "c", "bias": "neutral", "strength": 5},
        ]
        conf = compute_pattern_score(patterns)["confidence"]
        assert conf == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestDirectionalConfidence -v`

Expected: FAIL — `test_contradictory_patterns_reduce_confidence` fails because current formula gives confidence 1.0 for both (3 non-neutral / 3 = 1.0 regardless of direction).

- [ ] **Step 3: Replace confidence calculation with agreement-weighted model**

In `backend/app/engine/patterns.py`, replace the confidence block (lines 315-317) from:

```python
    # confidence: based on number of non-neutral patterns detected (max ~3 meaningful)
    non_neutral = sum(1 for p in patterns if p.get("bias", "neutral") != "neutral")
    confidence = round(min(non_neutral / 3.0, 1.0), 4)
```

to:

```python
    bull_count = sum(1 for p in patterns if p.get("bias") == "bullish")
    bear_count = sum(1 for p in patterns if p.get("bias") == "bearish")
    non_neutral = bull_count + bear_count
    if non_neutral == 0:
        confidence = 0.0
    else:
        agreement = max(bull_count, bear_count) / non_neutral
        confidence = round(min(non_neutral / 3.0, 1.0) * agreement, 4)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestDirectionalConfidence tests/engine/test_patterns.py::TestPatternScoring -v`

Expected: All PASS.

---

### Task 5: Indicator-ctx-aware hammer family detection (spec 1.2)

**Files:**
- Modify: `backend/app/engine/patterns.py:170` (detect_candlestick_patterns signature)
- Modify: `backend/app/engine/patterns.py:195-211` (trend detection + hammer dispatch)
- Test: `backend/tests/engine/test_patterns.py`

- [ ] **Step 1: Write failing tests for ADX/DI-based hammer detection**

Add to `backend/tests/engine/test_patterns.py`:

```python
class TestIndicatorCtxHammerDetection:
    HAMMER_SHAPE = {"open": 100.3, "high": 100.5, "low": 90, "close": 100.5, "volume": 50}
    INV_HAMMER_SHAPE = {"open": 100, "high": 110, "low": 100, "close": 100.2, "volume": 50}

    def _uptrend_candles(self, final: dict) -> pd.DataFrame:
        rows = [
            {"open": 90 + i * 2, "high": 91 + i * 2, "low": 88 + i * 2,
             "close": 89 + i * 2, "volume": 50}
            for i in range(10)
        ]
        rows.append(final)
        return pd.DataFrame(rows)

    def test_adx_di_overrides_price_delta(self):
        """Price delta says uptrend but DI says downtrend -> Hammer (not Hanging Man)."""
        candles = self._uptrend_candles(self.HAMMER_SHAPE)
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        names = [p["name"] for p in patterns]
        assert "Hammer" in names
        assert "Hanging Man" not in names

    def test_low_adx_suppresses_hammer(self):
        """ADX < 15 with indicator_ctx suppresses all hammer family."""
        candles = self._uptrend_candles(self.HAMMER_SHAPE)
        ctx = {"adx": 10, "di_plus": 10, "di_minus": 30}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        names = [p["name"] for p in patterns]
        assert "Hammer" not in names
        assert "Hanging Man" not in names

    def test_no_ctx_uses_price_delta(self):
        """Without indicator_ctx, falls back to 5-candle delta (existing behavior)."""
        candles = self._uptrend_candles(self.HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Hanging Man" in names  # price delta says uptrend

    def test_shooting_star_in_uptrend_ctx(self):
        """Inverted hammer shape + uptrend DI -> Shooting Star."""
        candles = self._uptrend_candles(self.INV_HAMMER_SHAPE)
        ctx = {"adx": 25, "di_plus": 30, "di_minus": 10}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        names = [p["name"] for p in patterns]
        assert "Shooting Star" in names

    def test_empty_ctx_falls_back_to_price_delta(self):
        """Empty dict indicator_ctx behaves like None (price delta fallback)."""
        candles = self._uptrend_candles(self.HAMMER_SHAPE)
        patterns_none = detect_candlestick_patterns(candles)
        patterns_empty = detect_candlestick_patterns(candles, indicator_ctx={})
        names_none = [p["name"] for p in patterns_none]
        names_empty = [p["name"] for p in patterns_empty]
        assert names_none == names_empty
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestIndicatorCtxHammerDetection -v`

Expected: FAIL — `detect_candlestick_patterns` doesn't accept `indicator_ctx` kwarg -> TypeError.

- [ ] **Step 3: Add indicator_ctx param and ADX/DI-based trend detection**

In `backend/app/engine/patterns.py`, change the `detect_candlestick_patterns` signature (line 170) from:

```python
def detect_candlestick_patterns(candles: pd.DataFrame) -> list[dict]:
```

to:

```python
def detect_candlestick_patterns(candles: pd.DataFrame, indicator_ctx: dict | None = None) -> list[dict]:
```

Replace the trend detection block (lines 195-205) from:

```python
    # Compute trend direction for hammer-family patterns
    if len(df) >= 6:
        trend_change = curr["close"] - float(df.iloc[-6]["close"])
        if trend_change > 0:
            trend_dir = 1
        elif trend_change < 0:
            trend_dir = -1
        else:
            trend_dir = 0
    else:
        trend_dir = 0
```

to:

```python
    # Compute trend direction for hammer-family patterns
    _has_ctx = indicator_ctx and "adx" in indicator_ctx
    if _has_ctx and indicator_ctx["adx"] >= 15:
        di_plus = indicator_ctx.get("di_plus", 0)
        di_minus = indicator_ctx.get("di_minus", 0)
        if di_plus > di_minus:
            trend_dir = 1
        elif di_minus > di_plus:
            trend_dir = -1
        else:
            trend_dir = 0
    elif _has_ctx and indicator_ctx["adx"] < 15:
        trend_dir = 0  # low ADX with ctx: suppress hammer family
    elif len(df) >= 6:
        trend_change = curr["close"] - float(df.iloc[-6]["close"])
        if trend_change > 0:
            trend_dir = 1
        elif trend_change < 0:
            trend_dir = -1
        else:
            trend_dir = 0
    else:
        trend_dir = 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestIndicatorCtxHammerDetection tests/engine/test_patterns.py::TestTrendAwarePatterns tests/engine/test_patterns.py::TestSingleCandlePatterns -v`

Expected: All PASS — new ADX/DI tests pass, existing tests use no indicator_ctx so fall back to price delta.

---

### Task 6: Strength-proportional detection (specs 3.1, 3.2, 3.3)

**Backward compat note:** Engulfing strength changes from fixed 15 to variable 9-15. Piercing/dark cloud changes from fixed 12 to variable 7-12. Existing tests that use `compute_pattern_score` with hardcoded pattern dicts (e.g., `test_stacking_patterns` with `"strength": 15`) are unaffected because they provide strength directly. Existing detection tests (`TestTwoCandlePatterns`, `TestThreeCandlePatterns`) check pattern names, not strength values, so they also pass. No existing test checks exact detected-strength values.

**Files:**
- Modify: `backend/app/engine/patterns.py:98-111` (engulfing)
- Modify: `backend/app/engine/patterns.py:114-127` (piercing/dark cloud)
- Modify: `backend/app/engine/patterns.py:150-163` (3WS/3BC)
- Test: `backend/tests/engine/test_patterns.py`

- [ ] **Step 1: Write failing tests for engulfing magnitude scaling**

Add to `backend/tests/engine/test_patterns.py`:

```python
class TestStrengthProportionalDetection:
    # -- Engulfing (3.1) --
    def test_bullish_engulfing_scales_by_ratio(self):
        """Barely engulfing gets weaker strength than dominant engulfing."""
        barely = _make_candles([
            {"open": 105, "high": 106, "low": 99, "close": 100, "volume": 50},
            {"open": 99, "high": 106, "low": 98, "close": 105.1, "volume": 80},
        ])
        dominant = _make_candles([
            {"open": 102, "high": 103, "low": 99, "close": 100, "volume": 50},
            {"open": 99, "high": 108, "low": 98, "close": 107, "volume": 80},
        ])
        barely_eng = next(p for p in detect_candlestick_patterns(barely) if p["name"] == "Bullish Engulfing")
        dominant_eng = next(p for p in detect_candlestick_patterns(dominant) if p["name"] == "Bullish Engulfing")
        assert dominant_eng["strength"] > barely_eng["strength"]

    def test_bearish_engulfing_scales_by_ratio(self):
        """Same scaling applies to bearish engulfing."""
        barely = _make_candles([
            {"open": 100, "high": 106, "low": 99, "close": 105, "volume": 50},
            {"open": 106, "high": 107, "low": 99.5, "close": 99.9, "volume": 80},
        ])
        dominant = _make_candles([
            {"open": 100, "high": 103, "low": 99, "close": 102, "volume": 50},
            {"open": 103, "high": 104, "low": 92, "close": 93, "volume": 80},
        ])
        barely_eng = next(p for p in detect_candlestick_patterns(barely) if p["name"] == "Bearish Engulfing")
        dominant_eng = next(p for p in detect_candlestick_patterns(dominant) if p["name"] == "Bearish Engulfing")
        assert dominant_eng["strength"] > barely_eng["strength"]

    # -- Piercing / Dark Cloud (3.2) --
    def test_piercing_line_scales_by_penetration(self):
        """Deep penetration gives higher strength than barely past midpoint."""
        shallow = _make_candles([
            {"open": 110, "high": 111, "low": 100, "close": 101, "volume": 50},
            {"open": 100, "high": 106.5, "low": 99, "close": 106, "volume": 60},
        ])
        deep = _make_candles([
            {"open": 110, "high": 111, "low": 100, "close": 101, "volume": 50},
            {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 60},
        ])
        shallow_pl = next(p for p in detect_candlestick_patterns(shallow) if p["name"] == "Piercing Line")
        deep_pl = next(p for p in detect_candlestick_patterns(deep) if p["name"] == "Piercing Line")
        assert deep_pl["strength"] > shallow_pl["strength"]

    def test_dark_cloud_scales_by_penetration(self):
        """Deep dark cloud penetration gives higher strength."""
        shallow = _make_candles([
            {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 50},
            {"open": 110, "high": 111, "low": 103.5, "close": 104, "volume": 60},
        ])
        deep = _make_candles([
            {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 50},
            {"open": 110, "high": 111, "low": 100, "close": 101, "volume": 60},
        ])
        shallow_dc = next(p for p in detect_candlestick_patterns(shallow) if p["name"] == "Dark Cloud Cover")
        deep_dc = next(p for p in detect_candlestick_patterns(deep) if p["name"] == "Dark Cloud Cover")
        assert deep_dc["strength"] > shallow_dc["strength"]

    # -- Three White Soldiers / Black Crows exhaustion (3.3) --
    def test_three_white_soldiers_exhaustion_reduces_strength(self):
        """Shrinking last body reduces strength."""
        healthy = _make_candles([
            {"open": 100, "high": 107, "low": 99, "close": 106, "volume": 50},
            {"open": 106, "high": 113, "low": 105, "close": 112, "volume": 55},
            {"open": 112, "high": 119, "low": 111, "close": 118, "volume": 60},
        ])
        exhausted = _make_candles([
            {"open": 100, "high": 110, "low": 99, "close": 109, "volume": 50},
            {"open": 109, "high": 118, "low": 108, "close": 117, "volume": 55},
            {"open": 117, "high": 120, "low": 116, "close": 119, "volume": 60},
        ])
        healthy_3ws = next(p for p in detect_candlestick_patterns(healthy) if p["name"] == "Three White Soldiers")
        exhausted_3ws = next(p for p in detect_candlestick_patterns(exhausted) if p["name"] == "Three White Soldiers")
        assert healthy_3ws["strength"] > exhausted_3ws["strength"]

    def test_three_black_crows_exhaustion_reduces_strength(self):
        """Growing lower shadow on last candle reduces strength."""
        healthy = _make_candles([
            {"open": 118, "high": 119, "low": 111, "close": 112, "volume": 50},
            {"open": 112, "high": 113, "low": 105, "close": 106, "volume": 55},
            {"open": 106, "high": 107, "low": 99, "close": 100, "volume": 60},
        ])
        exhausted = _make_candles([
            {"open": 118, "high": 119, "low": 111, "close": 112, "volume": 50},
            {"open": 112, "high": 113, "low": 105, "close": 106, "volume": 55},
            {"open": 106, "high": 107, "low": 96, "close": 103, "volume": 60},
        ])
        healthy_3bc = next(p for p in detect_candlestick_patterns(healthy) if p["name"] == "Three Black Crows")
        exhausted_3bc = next(p for p in detect_candlestick_patterns(exhausted) if p["name"] == "Three Black Crows")
        assert healthy_3bc["strength"] > exhausted_3bc["strength"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestStrengthProportionalDetection -v`

Expected: FAIL — all tests fail because current detection functions return fixed strength values.

- [ ] **Step 3: Implement engulfing magnitude scaling**

In `backend/app/engine/patterns.py`, replace `_detect_bullish_engulfing` (lines 98-103):

```python
def _detect_bullish_engulfing(prev, curr) -> dict | None:
    if _is_bearish(prev) and _is_bullish(curr):
        if curr["open"] <= prev["close"] and curr["close"] >= prev["open"]:
            if _body(curr) > _body(prev):
                ratio = min(_body(curr) / _body(prev), 2.5)
                strength = round(15 * (0.6 + 0.4 * ratio / 2.5))
                return {"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": strength}
    return None
```

Replace `_detect_bearish_engulfing` (lines 106-111):

```python
def _detect_bearish_engulfing(prev, curr) -> dict | None:
    if _is_bullish(prev) and _is_bearish(curr):
        if curr["open"] >= prev["close"] and curr["close"] <= prev["open"]:
            if _body(curr) > _body(prev):
                ratio = min(_body(curr) / _body(prev), 2.5)
                strength = round(15 * (0.6 + 0.4 * ratio / 2.5))
                return {"name": "Bearish Engulfing", "type": "candlestick", "bias": "bearish", "strength": strength}
    return None
```

- [ ] **Step 4: Implement piercing line / dark cloud penetration scaling**

Replace `_detect_piercing_line` (lines 114-119):

```python
def _detect_piercing_line(prev, curr) -> dict | None:
    if _is_bearish(prev) and _is_bullish(curr):
        midpoint = (prev["open"] + prev["close"]) / 2
        if curr["open"] < prev["close"] and curr["close"] > midpoint:
            prev_body = abs(prev["open"] - prev["close"])
            half_body = prev_body / 2
            penetration = min(abs(curr["close"] - midpoint) / half_body, 1.0) if half_body > 0 else 1.0
            strength = round(12 * (0.6 + 0.4 * penetration))
            return {"name": "Piercing Line", "type": "candlestick", "bias": "bullish", "strength": strength}
    return None
```

Replace `_detect_dark_cloud_cover` (lines 122-127):

```python
def _detect_dark_cloud_cover(prev, curr) -> dict | None:
    if _is_bullish(prev) and _is_bearish(curr):
        midpoint = (prev["open"] + prev["close"]) / 2
        if curr["open"] > prev["close"] and curr["close"] < midpoint:
            prev_body = abs(prev["open"] - prev["close"])
            half_body = prev_body / 2
            penetration = min(abs(curr["close"] - midpoint) / half_body, 1.0) if half_body > 0 else 1.0
            strength = round(12 * (0.6 + 0.4 * penetration))
            return {"name": "Dark Cloud Cover", "type": "candlestick", "bias": "bearish", "strength": strength}
    return None
```

- [ ] **Step 5: Implement three white soldiers / three black crows exhaustion**

Replace `_detect_three_white_soldiers` (lines 150-155):

```python
def _detect_three_white_soldiers(c1, c2, c3, avg_b: float) -> dict | None:
    if _is_bullish(c1) and _is_bullish(c2) and _is_bullish(c3):
        if c2["close"] > c1["close"] and c3["close"] > c2["close"]:
            if _body(c1) > avg_b * 0.5 and _body(c2) > avg_b * 0.5 and _body(c3) > avg_b * 0.5:
                strength = 15
                bodies = [_body(c1), _body(c2), _body(c3)]
                shrinking = bodies[2] < bodies[0] * 0.8
                shadow_growth = _upper_shadow(c3) > bodies[2] * 0.5
                if shrinking or shadow_growth:
                    strength = round(15 * 0.6)
                return {"name": "Three White Soldiers", "type": "candlestick", "bias": "bullish", "strength": strength}
    return None
```

Replace `_detect_three_black_crows` (lines 158-163):

```python
def _detect_three_black_crows(c1, c2, c3, avg_b: float) -> dict | None:
    if _is_bearish(c1) and _is_bearish(c2) and _is_bearish(c3):
        if c2["close"] < c1["close"] and c3["close"] < c2["close"]:
            if _body(c1) > avg_b * 0.5 and _body(c2) > avg_b * 0.5 and _body(c3) > avg_b * 0.5:
                strength = 15
                bodies = [_body(c1), _body(c2), _body(c3)]
                shrinking = bodies[2] < bodies[0] * 0.8
                shadow_growth = _lower_shadow(c3) > bodies[2] * 0.5
                if shrinking or shadow_growth:
                    strength = round(15 * 0.6)
                return {"name": "Three Black Crows", "type": "candlestick", "bias": "bearish", "strength": strength}
    return None
```

- [ ] **Step 6: Run all detection tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestStrengthProportionalDetection tests/engine/test_patterns.py::TestTwoCandlePatterns tests/engine/test_patterns.py::TestThreeCandlePatterns tests/engine/test_patterns.py::TestNoFalsePositives -v`

Expected: All PASS — new proportional tests pass, existing detection tests pass (they check pattern names, not strength values).

---

### Task 7: Doji / Spinning Top contextual bias (spec 3.4)

**Depends on:** Task 5 (indicator_ctx param on detect_candlestick_patterns)

**Files:**
- Modify: `backend/app/engine/patterns.py:65-80` (_detect_doji, _detect_spinning_top)
- Modify: `backend/app/engine/patterns.py:213-217` (dispatch in detect_candlestick_patterns)
- Test: `backend/tests/engine/test_patterns.py`

- [ ] **Step 1: Write failing tests for contextual doji/spinning top bias**

Add to `backend/tests/engine/test_patterns.py`:

```python
class TestDojiBiasContext:
    def test_doji_bearish_in_uptrend(self):
        """Doji in uptrend gets bearish bias (potential reversal)."""
        candles = _make_candles([
            {"open": 100, "high": 105, "low": 95, "close": 100.1, "volume": 50},
        ])
        ctx = {"adx": 25, "di_plus": 30, "di_minus": 10}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        doji = next((p for p in patterns if p["name"] == "Doji"), None)
        assert doji is not None
        assert doji["bias"] == "bearish"

    def test_doji_bullish_in_downtrend(self):
        """Doji in downtrend gets bullish bias."""
        candles = _make_candles([
            {"open": 100, "high": 105, "low": 95, "close": 100.1, "volume": 50},
        ])
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        doji = next((p for p in patterns if p["name"] == "Doji"), None)
        assert doji is not None
        assert doji["bias"] == "bullish"

    def test_doji_neutral_low_adx(self):
        """Doji stays neutral in ranging market (ADX < 15)."""
        candles = _make_candles([
            {"open": 100, "high": 105, "low": 95, "close": 100.1, "volume": 50},
        ])
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        doji = next((p for p in patterns if p["name"] == "Doji"), None)
        assert doji is not None
        assert doji["bias"] == "neutral"

    def test_doji_neutral_without_ctx(self):
        """Doji stays neutral without indicator_ctx (backward compat)."""
        candles = _make_candles([
            {"open": 100, "high": 105, "low": 95, "close": 100.1, "volume": 50},
        ])
        patterns = detect_candlestick_patterns(candles)
        doji = next((p for p in patterns if p["name"] == "Doji"), None)
        assert doji is not None
        assert doji["bias"] == "neutral"

    def test_spinning_top_bearish_in_uptrend(self):
        """Spinning Top in uptrend gets bearish bias."""
        candles = _make_candles([
            {"open": 100, "high": 106, "low": 94, "close": 100.5, "volume": 50},
        ])
        ctx = {"adx": 25, "di_plus": 30, "di_minus": 10}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        sp = next((p for p in patterns if p["name"] == "Spinning Top"), None)
        assert sp is not None
        assert sp["bias"] == "bearish"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestDojiBiasContext -v`

Expected: FAIL — `test_doji_bearish_in_uptrend` fails because `doji["bias"] == "neutral"` (always neutral currently).

- [ ] **Step 3: Add trend_bias param to _detect_doji and _detect_spinning_top**

In `backend/app/engine/patterns.py`, replace `_detect_doji` (lines 65-70):

```python
def _detect_doji(c, avg_b: float, trend_bias: str = "neutral") -> dict | None:
    body = _body(c)
    total = c["high"] - c["low"]
    if total > 0 and body / total < 0.1:
        return {"name": "Doji", "type": "candlestick", "bias": trend_bias, "strength": 8}
    return None
```

Replace `_detect_spinning_top` (lines 73-80):

```python
def _detect_spinning_top(c, avg_b: float, trend_bias: str = "neutral") -> dict | None:
    body = _body(c)
    upper = _upper_shadow(c)
    lower = _lower_shadow(c)
    if body < avg_b * 0.4 and upper > body * 0.5 and lower > body * 0.5:
        if body / (c["high"] - c["low"]) >= 0.1:
            return {"name": "Spinning Top", "type": "candlestick", "bias": trend_bias, "strength": 5}
    return None
```

- [ ] **Step 4: Wire trend_bias in detect_candlestick_patterns**

In `detect_candlestick_patterns`, replace the doji/spinning top dispatch block (lines 213-217) from:

```python
    # Uniform single-candle (no trend context needed)
    for detector in (_detect_doji, _detect_spinning_top, _detect_marubozu):
        result = detector(curr, avg_b)
        if result:
            patterns.append(result)
```

to:

```python
    # Derive contextual bias for indecision patterns
    _indecision_bias = "neutral"
    if _has_ctx and indicator_ctx["adx"] >= 15:
        if indicator_ctx.get("di_plus", 0) > indicator_ctx.get("di_minus", 0):
            _indecision_bias = "bearish"
        elif indicator_ctx.get("di_minus", 0) > indicator_ctx.get("di_plus", 0):
            _indecision_bias = "bullish"

    for detector in (_detect_doji, _detect_spinning_top):
        result = detector(curr, avg_b, trend_bias=_indecision_bias)
        if result:
            patterns.append(result)
    result = _detect_marubozu(curr, avg_b)
    if result:
        patterns.append(result)
```

- [ ] **Step 5: Run all tests to verify**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestDojiBiasContext tests/engine/test_patterns.py::TestSingleCandlePatterns tests/engine/test_patterns.py::TestPatternScoring -v`

Expected: All PASS — new bias tests pass, existing tests pass (no ctx → neutral bias → existing behavior preserved).

---

### Task 8: PipelineSettings migration

**Files:**
- Modify: `backend/app/db/models.py:211` (after llm_factor_total_cap)
- Create: `backend/alembic/versions/<auto>_add_pattern_override_columns.py`

- [ ] **Step 1: Add JSONB columns to PipelineSettings model**

In `backend/app/db/models.py`, after the `confluence_max_score` line (line 211), add:

```python
    pattern_strength_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pattern_boost_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

- [ ] **Step 2: Generate Alembic migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add pattern override columns to pipeline_settings"`

Expected: New migration file created in `alembic/versions/`.

- [ ] **Step 3: Apply migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head`

Expected: Migration applies successfully.

- [ ] **Step 4: Verify rollback safety**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic downgrade -1`

Expected: Downgrade succeeds (drops the two nullable JSONB columns).

Then re-apply: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head`

---

### Task 9: Param group + backtester routing

**Files:**
- Modify: `backend/app/engine/param_groups.py:21-27` (PRIORITY_LAYERS)
- Modify: `backend/app/engine/param_groups.py:362` (after onchain group, before _mr_pressure_ok)
- Modify: `backend/app/engine/backtester.py:17` (imports)
- Modify: `backend/app/engine/backtester.py:151-166` (override routing)
- Modify: `backend/app/engine/backtester.py:205-211` (compute_pattern_score call)
- Test: `backend/tests/engine/test_de_sweep.py`

- [ ] **Step 1: Write failing tests for pattern_boosts group and backtester routing**

Add to `backend/tests/engine/test_de_sweep.py`:

```python
class TestPatternBoostOverrides:
    def test_boost_override_changes_score(self):
        """Pattern boost overrides via boost_overrides change output score."""
        from app.engine.patterns import compute_pattern_score
        patterns = [
            {"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12},
        ]
        ctx = {"adx": 10, "di_plus": 20, "di_minus": 15, "vol_ratio": 1.5, "bb_pos": 0.5, "close": 50000}
        r_default = compute_pattern_score(patterns, ctx, regime_trending=0.5)
        r_override = compute_pattern_score(
            patterns, ctx, regime_trending=0.5,
            boost_overrides={"vol_center": 1.0, "vol_steepness": 12.0},
        )
        assert r_override["score"] != r_default["score"]

    def test_boost_override_via_backtest(self):
        """Boost param overrides route through backtester without error."""
        candles = _make_candles(120, "up").to_dict("records")
        r = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(
            signal_threshold=15,
            param_overrides={"vol_center": 1.0, "vol_steepness": 12.0},
        ))
        assert "profit_factor" in r["stats"]


class TestPatternBoostsParamGroup:
    def test_group_exists(self):
        """pattern_boosts group is defined in PARAM_GROUPS."""
        from app.engine.param_groups import PARAM_GROUPS
        assert "pattern_boosts" in PARAM_GROUPS

    def test_group_uses_de_sweep(self):
        from app.engine.param_groups import PARAM_GROUPS
        assert PARAM_GROUPS["pattern_boosts"]["sweep_method"] == "de"

    def test_group_constraint_rejects_negative(self):
        from app.engine.param_groups import validate_candidate
        assert not validate_candidate("pattern_boosts", {"vol_center": -1, "vol_steepness": 8, "reversal_boost": 0.3, "continuation_boost": 0.2})

    def test_group_constraint_accepts_valid(self):
        from app.engine.param_groups import validate_candidate
        assert validate_candidate("pattern_boosts", {"vol_center": 1.5, "vol_steepness": 8, "reversal_boost": 0.3, "continuation_boost": 0.2})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py::TestPatternBoostOverrides tests/engine/test_de_sweep.py::TestPatternBoostsParamGroup -v`

Expected: FAIL — `pattern_boosts` group doesn't exist, backtester doesn't route boost keys.

- [ ] **Step 3: Add pattern_boosts group to param_groups.py**

In `backend/app/engine/param_groups.py`, add import at line 16:

```python
from app.engine.constants import PATTERN_STRENGTHS, PATTERN_BOOST_DEFAULTS
```

(Change the existing `from app.engine.constants import PATTERN_STRENGTHS` to include `PATTERN_BOOST_DEFAULTS`.)

Add `"pattern_boosts"` to priority layer 2 (lines 24-26), changing:

```python
    {"sigmoid_curves", "order_flow", "pattern_strengths",
     "indicator_periods", "mean_reversion", "llm_factors", "onchain",
     "mr_pressure"},  # layer 2
```

to:

```python
    {"sigmoid_curves", "order_flow", "pattern_strengths", "pattern_boosts",
     "indicator_periods", "mean_reversion", "llm_factors", "onchain",
     "mr_pressure"},  # layer 2
```

After the `"onchain"` group definition (after line 361), add:

```python
    "pattern_boosts": {
        "params": {
            name: f"patterns.boosts.{name}"
            for name in PATTERN_BOOST_DEFAULTS
        },
        "sweep_method": "de",
        "sweep_ranges": {
            "vol_center": (1.1, 2.0, None),
            "vol_steepness": (3.0, 15.0, None),
            "reversal_boost": (0.1, 0.5, None),
            "continuation_boost": (0.1, 0.4, None),
        },
        "constraints": _positive_values,
        "priority": _priority_for("pattern_boosts"),
    },
```

- [ ] **Step 4: Update backtester to route pattern boost overrides**

In `backend/app/engine/backtester.py`, update the import line (line 17) from:

```python
from app.engine.constants import PATTERN_STRENGTHS
```

to:

```python
from app.engine.constants import PATTERN_STRENGTHS, PATTERN_BOOST_DEFAULTS
```

Update the override routing block (lines 151-166) from:

```python
    scoring_params: dict | None = None
    strength_overrides: dict | None = None
    remaining_overrides: dict | None = None
    if config.param_overrides:
        _sp, _so, _ro = {}, {}, {}
        for k, v in config.param_overrides.items():
            if k in _SIGMOID_KEYS:
                _sp[k] = v
            elif k in PATTERN_STRENGTHS:
                _so[k] = v
            else:
                _ro[k] = v
        scoring_params = _sp or None
        strength_overrides = _so or None
        remaining_overrides = _ro or None
```

to:

```python
    scoring_params: dict | None = None
    strength_overrides: dict | None = None
    boost_overrides: dict | None = None
    remaining_overrides: dict | None = None
    if config.param_overrides:
        _sp, _so, _bo, _ro = {}, {}, {}, {}
        for k, v in config.param_overrides.items():
            if k in _SIGMOID_KEYS:
                _sp[k] = v
            elif k in PATTERN_STRENGTHS:
                _so[k] = v
            elif k in PATTERN_BOOST_DEFAULTS:
                _bo[k] = v
            else:
                _ro[k] = v
        scoring_params = _sp or None
        strength_overrides = _so or None
        boost_overrides = _bo or None
        remaining_overrides = _ro or None
```

Update the compute_pattern_score call (lines 209-211) from:

```python
                pat_score = compute_pattern_score(detected, indicator_ctx, strength_overrides=strength_overrides)["score"]
```

to:

```python
                pat_score = compute_pattern_score(
                    detected, indicator_ctx,
                    strength_overrides=strength_overrides,
                    boost_overrides=boost_overrides,
                )["score"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_de_sweep.py -v`

Expected: All PASS — new and existing tests pass.

---

### Task 10: Main.py production wiring (spec 1.1)

**Files:**
- Modify: `backend/app/main.py:1322` (early app.state initialization)
- Modify: `backend/app/main.py:545-554` (pattern detection + scoring call)
- Modify: `backend/app/main.py:1364-1378` (PipelineSettings loading)
- Modify: `backend/tests/conftest.py` (add override attrs to _test_lifespan)
- Test: `backend/tests/engine/test_patterns.py`

- [ ] **Step 1: Initialize pattern override attrs early in lifespan**

In `backend/app/main.py`, after `app.state.last_pipeline_cycle = 0.0` (line 1323), add:

```python
        app.state.pattern_strength_overrides = None
        app.state.pattern_boost_overrides = None
```

This ensures the attributes exist even if PipelineSettings loading is skipped or fails.

- [ ] **Step 2: Load pattern overrides from PipelineSettings at startup**

In the PipelineSettings loading block (after line 1375 `_apply_pipeline_overrides(settings, ps)`), add:

```python
                app.state.pattern_strength_overrides = getattr(ps, "pattern_strength_overrides", None)
                app.state.pattern_boost_overrides = getattr(ps, "pattern_boost_overrides", None)
```

In the `else` branch (line 1377, no PipelineSettings row) and the `except` block (line 1380), add:

```python
                app.state.pattern_strength_overrides = None
                app.state.pattern_boost_overrides = None
```

- [ ] **Step 3: Wire indicator_ctx, strength_overrides, regime_trending, and boost_overrides in run_pipeline**

In `backend/app/main.py`, replace the pattern detection block (lines 545-554) from:

```python
    # Pattern detection
    detected_patterns = []
    pat_result = {"score": 0, "confidence": 0.0}
    try:
        detected_patterns = detect_candlestick_patterns(df)
        indicator_ctx = {**tech_result["indicators"], "close": float(df.iloc[-1]["close"])}
        pat_result = compute_pattern_score(detected_patterns, indicator_ctx)
    except Exception as e:
        logger.debug(f"Pattern detection skipped: {e}")
    pat_score = pat_result["score"]
```

to:

```python
    # Pattern detection
    detected_patterns = []
    pat_result = {"score": 0, "confidence": 0.0}
    try:
        indicator_ctx = {**tech_result["indicators"], "close": float(df.iloc[-1]["close"])}
        detected_patterns = detect_candlestick_patterns(df, indicator_ctx)
        regime_mix = tech_result.get("regime") or {}
        pat_result = compute_pattern_score(
            detected_patterns, indicator_ctx,
            strength_overrides=getattr(app.state, "pattern_strength_overrides", None),
            regime_trending=regime_mix.get("trending", 0),
            boost_overrides=getattr(app.state, "pattern_boost_overrides", None),
        )
    except Exception as e:
        logger.debug(f"Pattern detection skipped: {e}")
    pat_score = pat_result["score"]
```

- [ ] **Step 4: Update test lifespan stub**

In `backend/tests/conftest.py`, inside `_test_lifespan`, add after the existing `app.state` assignments:

```python
    app.state.pattern_strength_overrides = None
    app.state.pattern_boost_overrides = None
```

- [ ] **Step 5: Write integration tests for production wiring**

Add to `backend/tests/engine/test_patterns.py`:

```python
class TestProductionWiring:
    def test_detect_with_indicator_ctx_does_not_crash(self):
        """detect_candlestick_patterns accepts indicator_ctx without error."""
        candles = _make_candles([
            {"open": 100, "high": 105, "low": 95, "close": 102, "volume": 50},
        ])
        ctx = {"adx": 20, "di_plus": 25, "di_minus": 15, "vol_ratio": 1.3,
               "bb_pos": 0.5, "close": 102}
        patterns = detect_candlestick_patterns(candles, indicator_ctx=ctx)
        assert isinstance(patterns, list)

    def test_compute_score_full_params(self):
        """compute_pattern_score accepts all new params together."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 25, "di_plus": 10, "di_minus": 30, "vol_ratio": 1.5,
               "bb_pos": 0.5, "close": 100}
        result = compute_pattern_score(
            patterns, ctx,
            strength_overrides={"hammer": 14},
            regime_trending=0.6,
            boost_overrides={"vol_center": 1.2, "reversal_boost": 0.4},
        )
        assert "score" in result
        assert "confidence" in result
        assert result["score"] != 0

    def test_regime_none_and_boost_none_backward_compat(self):
        """Passing None for regime_trending and boost_overrides matches legacy behavior."""
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        ctx = {"adx": 10, "di_plus": 15, "di_minus": 10, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 100}
        legacy = compute_pattern_score(patterns, ctx)
        explicit_none = compute_pattern_score(
            patterns, ctx, regime_trending=None, boost_overrides=None,
        )
        assert legacy["score"] == explicit_none["score"]
        assert legacy["confidence"] == explicit_none["confidence"]
```

- [ ] **Step 6: Run full test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v --timeout=60`

Expected: All tests PASS.

---

### Task 11: Final verification

- [ ] **Step 1: Run full pattern test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py tests/engine/test_de_sweep.py tests/engine/test_confidence.py -v`

Expected: All PASS.

- [ ] **Step 2: Run full project test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v --timeout=60`

Expected: All PASS.

- [ ] **Step 3: Verify backward compatibility of existing tests**

Confirm these specific existing tests still produce the same results:
- `TestPatternScoring::test_stacking_patterns` → score == 27
- `TestPatternScoring::test_neutral_pattern_no_score` → score == 0
- `TestTrendAlignmentBoost::test_reversal_pattern_gets_boost` → score > 15
- `TestVolumeConfirmationBoost::test_normal_volume_no_boost` → score == 12
- `TestTrendAwarePatterns::test_hammer_after_downtrend` → Hammer detected
- `TestBacktestParamOverrides::test_pattern_override_via_backtest` → succeeds

- [ ] **Step 4: Verify new test classes all pass**

Confirm all new test classes added by this plan:
- `TestContinuousVolumeBoost` (4 tests)
- `TestRegimeAwareTrendBoost` (5 tests)
- `TestDirectionalConfidence` (5 tests, including all_neutral edge case)
- `TestIndicatorCtxHammerDetection` (5 tests, including empty_ctx fallback)
- `TestStrengthProportionalDetection` (6 tests)
- `TestDojiBiasContext` (5 tests)
- `TestPatternBoostOverrides` (2 tests)
- `TestPatternBoostsParamGroup` (4 tests)
- `TestProductionWiring` (3 tests)
