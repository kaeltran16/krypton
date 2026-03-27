# Candlestick Pattern Scoring Improvements

## Overview

Fix bugs and improve the candlestick pattern scoring algorithm in `engine/patterns.py`. Nine changes total: 3 bug fixes, 2 scoring improvements, 4 pattern detection improvements. Core changes in `patterns.py`, `main.py` (wiring), `constants.py` (defaults), and `param_groups.py` (optimizer group). Supporting changes in `backtester.py` (boost routing), `db/models.py` + migration (PipelineSettings column).

## Goals

- Fix known bugs (strength overrides not wired, naive trend detection, broken confidence)
- Improve scoring accuracy with continuous curves and regime awareness
- Make pattern detection strength-proportional rather than binary
- Expose new scoring constants to the optimizer for self-tuning

## Non-Goals

- Adding new pattern types
- Multi-timeframe confirmation
- Changing the combiner interface or score range
- Pattern clustering or grouping

---

## Section 1: Bug Fixes

### 1.1 Wire strength overrides in production pipeline

**File:** `main.py` (line ~551)

**Problem:** `compute_pattern_score()` is called without `strength_overrides`, so optimizer-learned pattern strengths from DE sweep never apply in production signals. The backtester correctly routes overrides, but the live pipeline ignores them.

**Fix:** Load promoted pattern strengths from `PipelineSettings` (same path as other promoted params) and pass to `compute_pattern_score()`:

```python
# main.py, pattern detection section
detected_patterns = detect_candlestick_patterns(df, indicator_ctx)
pat_result = compute_pattern_score(
    detected_patterns, indicator_ctx,
    strength_overrides=pattern_strength_overrides,  # from PipelineSettings
    regime_trending=regime_mix.get("trending", 0),
)
```

The `pattern_strength_overrides` dict is extracted from PipelineSettings at startup and when the optimizer promotes a proposal, matching the existing pattern for other promoted params.

### 1.2 Replace naive trend detection for hammer family

**File:** `patterns.py`, `detect_candlestick_patterns()`

**Problem:** Hammer vs Hanging Man (and Inverted Hammer vs Shooting Star) is decided by `close[-1] - close[-6]` -- a raw 5-candle price delta. A short squeeze in a ranging market (ADX 12) can trigger a false "trend" classification.

**Fix:** Change `detect_candlestick_patterns` signature to accept `indicator_ctx`:

```python
def detect_candlestick_patterns(candles: pd.DataFrame, indicator_ctx: dict | None = None) -> list[dict]:
```

When `indicator_ctx` is provided, derive trend direction from ADX/DI:
- `di_plus > di_minus` and ADX >= 15 -> uptrend -> Hanging Man / Shooting Star
- `di_minus > di_plus` and ADX >= 15 -> downtrend -> Hammer / Inverted Hammer
- ADX < 15 -> suppress all four hammer-family patterns

When `indicator_ctx=None` (backward compat for existing tests), fall back to current 5-candle delta logic.

**Affected patterns:** Hammer, Hanging Man, Inverted Hammer, Shooting Star (4 of 15).

### 1.3 Directional confidence model

**File:** `patterns.py`, `compute_pattern_score()`

**Problem:** `confidence = min(non_neutral_count / 3.0, 1.0)` treats 2 bullish + 1 bearish the same as 3 bullish. Contradictory patterns inflate confidence, which inflates pattern's effective weight in the combiner.

**Fix:**

```python
bull_count = sum(1 for p in patterns if p.get("bias") == "bullish")
bear_count = sum(1 for p in patterns if p.get("bias") == "bearish")
non_neutral = bull_count + bear_count
if non_neutral == 0:
    confidence = 0.0
else:
    agreement = max(bull_count, bear_count) / non_neutral  # 1.0 unanimous, 0.5 split
    confidence = round(min(non_neutral / 3.0, 1.0) * agreement, 4)
```

Examples:
- 2 bullish, 0 bearish -> agreement 1.0, confidence 0.67
- 3 bullish, 0 bearish -> agreement 1.0, confidence 1.0
- 2 bullish, 1 bearish -> agreement 0.67, confidence 0.67 (was 1.0)

---

## Section 2: Scoring Improvements

### 2.1 Continuous volume boost curve

**File:** `patterns.py`, `compute_pattern_score()`

**Problem:** Hard thresholds at vol_ratio 1.2 (1.15x) and 1.5 (1.3x) create discontinuities -- a 1.3% volume change at the boundary produces a 13% boost jump.

**Fix:** Replace with sigmoid curve using `sigmoid_scale` (unipolar [0,1] mapper from `engine/scoring.py` -- needs adding to the existing `sigmoid_score` import in patterns.py):

```python
from app.engine.scoring import sigmoid_score, sigmoid_scale  # add sigmoid_scale

vol_boost = 1.0 + 0.3 * sigmoid_scale(vol_ratio, center=VOL_BOOST_CENTER, steepness=VOL_BOOST_STEEPNESS)
```

Note: `sigmoid_score` (bipolar, [-1,1]) is already imported and used for level proximity boost. `sigmoid_scale` (unipolar, [0,1]) is the correct choice here since we need a 0-1 magnitude multiplier.

Default constants (in `constants.py`):
- `VOL_BOOST_CENTER = 1.35`
- `VOL_BOOST_STEEPNESS = 8.0`

Behavior:
- vol_ratio 1.0 -> ~1.02x
- vol_ratio 1.2 -> ~1.09x
- vol_ratio 1.35 -> ~1.15x
- vol_ratio 1.5 -> ~1.21x
- vol_ratio 2.0 -> ~1.30x

### 2.2 Regime-aware trend boost

**File:** `patterns.py`, `compute_pattern_score()`

**Problem:** Trend boost is binary (ADX >= 15 -> 1.3x reversal, ADX >= 30 -> 1.2x continuation). A barely-trending market (ADX 16) gets the same boost as a strong trend (ADX 45).

**Fix:** Accept `regime_trending` float (0-1) and scale continuously:

```python
def compute_pattern_score(
    patterns, indicator_ctx=None, strength_overrides=None, regime_trending=None,
) -> dict:
```

When `regime_trending` is provided:

```python
pattern_bullish = (bias == "bullish")
adx_bullish = (di_plus > di_minus)

if pattern_bullish != adx_bullish:
    # reversal signal
    trend_boost = 1.0 + REVERSAL_BOOST_BASE * regime_trending
else:
    # continuation signal
    trend_boost = 1.0 + CONTINUATION_BOOST_BASE * regime_trending
```

Default constants (in `constants.py`):
- `REVERSAL_BOOST_BASE = 0.3`
- `CONTINUATION_BOOST_BASE = 0.2`

When `regime_trending=None` (backward compat), fall back to current ADX threshold logic.

---

## Section 3: Pattern Detection Improvements

### 3.1 Engulfing magnitude scaling

**File:** `patterns.py`, `_detect_bullish_engulfing()`, `_detect_bearish_engulfing()`

**Problem:** A barely-engulfing candle (1.01x prior body) gets the same strength 15 as a dominant one (3x). Engulfing ratio is a strong quality signal.

**Fix:** Scale strength by engulfing ratio:

```python
ratio = min(_body(curr) / _body(prev), 2.5)
strength = round(base_strength * (0.6 + 0.4 * ratio / 2.5))
```

- Barely engulfing (1.01x) -> strength ~9
- Moderate (1.5x) -> strength ~12
- Dominant (2.5x+) -> strength 15 (full base)

The `base_strength` (15) remains the value the optimizer overrides. The scaling adjusts the *detected* strength before it reaches the optimizer's override layer.

### 3.2 Piercing Line / Dark Cloud Cover penetration depth

**File:** `patterns.py`, `_detect_piercing_line()`, `_detect_dark_cloud_cover()`

**Problem:** Binary midpoint check -- closing at 51% vs 90% of the prior body produces the same strength.

**Fix:** Scale by penetration depth past midpoint:

```python
prev_body = abs(prev["open"] - prev["close"])
half_body = prev_body / 2
if half_body > 0:
    penetration = min(abs(curr["close"] - midpoint) / half_body, 1.0)
else:
    penetration = 1.0
strength = round(base_strength * (0.6 + 0.4 * penetration))
```

- Just past midpoint -> strength ~8
- Deep penetration (90%) -> strength ~12 (full base)

### 3.3 Three White Soldiers / Black Crows exhaustion detection

**File:** `patterns.py`, `_detect_three_white_soldiers()`, `_detect_three_black_crows()`

**Problem:** No check for diminishing bodies or growing shadows -- classic exhaustion signals that contradict the continuation interpretation.

**Fix:** After confirming the base pattern, check for exhaustion:

```python
bodies = [_body(c1), _body(c2), _body(c3)]
shrinking = bodies[2] < bodies[0] * 0.8  # last body < 80% of first

# for 3WS: growing upper shadows; for 3BC: growing lower shadows
if three_white_soldiers:
    shadow = _upper_shadow(c3)
else:
    shadow = _lower_shadow(c3)
shadow_growth = shadow > bodies[2] * 0.5

if shrinking or shadow_growth:
    strength = round(base_strength * 0.6)  # 15 -> 9
```

Healthy continuation (stable/growing bodies, small shadows) keeps full strength.

### 3.4 Doji / Spinning Top contextual bias

**File:** `patterns.py`, `_detect_doji()`, `_detect_spinning_top()`

**Problem:** Always return `bias: "neutral"`, and `compute_pattern_score` skips neutral patterns entirely. These are dead code in the scoring path.

**Fix:** When `indicator_ctx` is available in `detect_candlestick_patterns`:
- ADX >= 15 and `di_plus > di_minus` (uptrend) -> `bias: "bearish"` (potential reversal)
- ADX >= 15 and `di_minus > di_plus` (downtrend) -> `bias: "bullish"` (potential reversal)
- ADX < 15 -> stays `bias: "neutral"` (indecision in a range = no signal)

Strength values stay at 8 (Doji) and 5 (Spinning Top) -- the weakest directional signals. They contribute to confluence but cannot drive signals alone.

Implementation: `_detect_doji` and `_detect_spinning_top` gain an optional `trend_bias` parameter set by the caller based on `indicator_ctx`.

---

## Section 4: Optimizer Integration

### New param group: `pattern_boosts`

**File:** `param_groups.py`, `constants.py`

Four new tunable constants added to a `pattern_boosts` group:

| Param | Config path | Default | Sweep range |
|---|---|---|---|
| `pattern_vol_center` | `patterns.boosts.vol_center` | 1.35 | 1.1 - 2.0 |
| `pattern_vol_steepness` | `patterns.boosts.vol_steepness` | 8.0 | 3.0 - 15.0 |
| `pattern_reversal_boost` | `patterns.boosts.reversal_boost` | 0.3 | 0.1 - 0.5 |
| `pattern_continuation_boost` | `patterns.boosts.continuation_boost` | 0.2 | 0.1 - 0.4 |

Group sits in priority layer 2 alongside existing `pattern_strengths` and `sigmoid_curves`. Uses DE sweep method.

Constraint: all values positive.

These defaults live in `constants.py` under a `PATTERN_BOOST_DEFAULTS` dict. At runtime, `compute_pattern_score` reads overrides from PipelineSettings (same path as other promoted params), falling back to constants.

### PipelineSettings migration

`PipelineSettings` (`db/models.py`) has no column for pattern boost overrides. Add:

```python
pattern_boost_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
```

Alembic migration adds the nullable JSONB column. Follows the same pattern as `llm_factor_weights`. At startup in `main.py`, load into `app.state` alongside other promoted params; pass to `compute_pattern_score` via a `boost_overrides` kwarg.

### Backtester routing for pattern boosts

`backtester.py` (lines 150-164) routes `param_overrides` by matching keys against `_SIGMOID_KEYS` or `PATTERN_STRENGTHS`. The four new boost params match neither set and would fall through to `remaining_overrides`.

Fix: add a `_PATTERN_BOOST_KEYS` set (the four param names) and route matches to a `boost_overrides` dict passed to `compute_pattern_score` alongside `strength_overrides`. This lets DE sweep evaluate boost param candidates via backtest.

---

## Section 5: Files Changed

| File | Changes |
|---|---|
| `engine/patterns.py` | All detection and scoring changes (sections 1.2, 1.3, 2.1, 2.2, 3.1-3.4) |
| `engine/constants.py` | Add `PATTERN_BOOST_DEFAULTS` dict with 4 constants |
| `engine/param_groups.py` | Add `pattern_boosts` group definition |
| `engine/backtester.py` | Add `_PATTERN_BOOST_KEYS` routing, pass `boost_overrides` to `compute_pattern_score` |
| `db/models.py` | Add `pattern_boost_overrides` JSONB column to `PipelineSettings` |
| `main.py` | Wire `indicator_ctx` to detection, wire `strength_overrides` + `boost_overrides` + `regime_trending` to scoring; load boost overrides from PipelineSettings at startup |
| `tests/engine/test_patterns.py` | Update existing tests, add tests for new behavior |
| `tests/engine/test_de_sweep.py` | Add tests for new param group |
| `alembic/versions/` | Migration adding `pattern_boost_overrides` column |

### What doesn't change

- Return types: `list[dict]` from detection, `dict{score, confidence}` from scoring
- Combiner interface (`compute_preliminary_score` signature)
- Score range: -100 to +100
- Existing `pattern_strengths` optimizer group
- Regime outer weight system
- Backtester pattern strength override routing (existing `strength_overrides` path unchanged)

### Backward compatibility

All new parameters are optional with defaults matching current behavior:
- `detect_candlestick_patterns(candles, indicator_ctx=None)` -- `None` uses current 5-candle delta
- `compute_pattern_score(..., regime_trending=None)` -- `None` uses current ADX thresholds
- Existing tests pass without modification
