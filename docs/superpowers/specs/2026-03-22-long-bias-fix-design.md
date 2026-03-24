# Long Bias Fix — Design Spec

## Problem

The signal pipeline generates disproportionately more LONG signals than SHORT. Investigation identified four sources of directional asymmetry, ranging from structural pattern detection bugs to subtle LLM prompt framing.

## Root Causes

### 1. Missing Bearish Single-Candle Patterns (HIGH)

`backend/app/engine/patterns.py` detects 5 unique bullish pattern types vs 4 bearish. Hammer (strength 12) and Inverted Hammer (strength 10) are always classified as bullish regardless of prior trend context. Their bearish counterparts — Hanging Man and Shooting Star — are absent.

In traditional candlestick analysis, the same candle shape has opposite meaning depending on where it appears:
- Long lower shadow after a downtrend = Hammer (bullish reversal)
- Long lower shadow after an uptrend = Hanging Man (bearish reversal)
- Long upper shadow after a downtrend = Inverted Hammer (bullish reversal)
- Long upper shadow after an uptrend = Shooting Star (bearish reversal)

The net effect is +10 to +12 points of unearned bullish pattern score whenever these shapes appear at swing highs.

### 2. LLM System Prompt Suppresses Bearish Reasoning (MEDIUM)

`backend/app/engine/llm.py` line 18: *"not vague concerns about volatility or risk"* discourages exactly the kind of reasoning that supports SHORT signals — exhaustion, overheating, liquidation risk.

### 3. LLM User Prompt Anchors to Direction (MEDIUM)

`backend/app/prompts/signal_analysis.txt` line 30: *"The quantitative signals already flagged a {direction} setup"* anchors the LLM to confirm rather than independently evaluate. In a bull market where more setups arrive as LONG, this compounds confirmation bias.

### 4. Doji Candle OI Classification (LOW)

`backend/app/main.py` line 394: `close >= open` maps doji candles (close == open) to price_direction = +1 (bullish). This feeds a small bullish bias into the OI score component (capped at +/-20).

## Changes

### 1. Add Hanging Man and Shooting Star patterns

**File:** `backend/app/engine/patterns.py`

Compute trend direction in `detect_candlestick_patterns()` by comparing `close[-1]` vs `close[-6]` (current vs 5 candles back). If fewer than 6 candles are available, fall back to `trend_dir = 0` (suppress hammer/inverted hammer entirely — same as flat market handling, since we can't determine a reliable trend context). Pass `trend_dir` (+1 for uptrend, -1 for downtrend, 0 for flat) as a parameter to `_detect_hammer` and `_detect_inverted_hammer`. Pull these two detectors out of the uniform single-candle loop since they need the extra parameter.

When `trend_dir == 0` (close == close[-5], flat/sideways market, or insufficient lookback data), suppress the pattern entirely (return None) since the reversal interpretation requires a clear prior trend.

Behavior:
- Hammer shape + prior downtrend (trend_dir = -1) → Hammer (bullish, strength 12) — unchanged
- Hammer shape + prior uptrend (trend_dir = +1) → Hanging Man (bearish, strength 12) — new
- Inverted Hammer shape + prior downtrend (trend_dir = -1) → Inverted Hammer (bullish, strength 10) — unchanged
- Inverted Hammer shape + prior uptrend (trend_dir = +1) → Shooting Star (bearish, strength 10) — new

**File:** `backend/app/engine/constants.py`

Add `hanging_man: 12` and `shooting_star: 10` to `PATTERN_STRENGTHS`. Note: `PATTERN_STRENGTHS` is a display-only registry consumed by `get_engine_constants()` for the API parameters endpoint — the actual strength values come from the detector return dicts in `patterns.py`, not from this dict.

**Tests:**

Add tests verifying:
- Hammer shape after 5 declining candles → Hammer (bullish)
- Hammer shape after 5 rising candles → Hanging Man (bearish)
- Inverted Hammer shape after 5 declining candles → Inverted Hammer (bullish)
- Inverted Hammer shape after 5 rising candles → Shooting Star (bearish)
- Hammer/Inverted Hammer shape with flat prior (close == close[-5]) → no pattern detected
- Hammer/Inverted Hammer shape with fewer than 6 candles → no pattern detected (insufficient lookback)

Review existing Hammer/Inverted Hammer tests — ensure padding candle data creates a valid downtrend context so tests still pass with the new trend-aware logic.

### 2. Neutralize LLM system prompt

**File:** `backend/app/engine/llm.py`

Replace SYSTEM_PROMPT with:

```
You are a decisive crypto futures trader with 10 years of experience. You analyze quantitative data and identify specific factors that support or undermine a trade setup. You focus on concrete evidence — divergences, key levels, exhaustion signals, positioning extremes. Apply equal scrutiny to both long and short setups.
```

Change: removed *"not vague concerns about volatility or risk"*, added *"Apply equal scrutiny to both long and short setups."*

### 3. Neutralize LLM user prompt anchoring

**File:** `backend/app/prompts/signal_analysis.txt`

Replace line 30:

```
# Before
The quantitative signals already flagged a {direction} setup. Your job is to identify specific factors that support or undermine this trade.

# After
The quantitative signals produced a {direction} bias with score {blended_score}. Your job is to independently evaluate whether the data supports this direction, or if factors suggest caution or contradiction.
```

Change: removed confirmatory framing ("already flagged"), added independence framing ("independently evaluate"), included score magnitude for context. The `{blended_score}` placeholder is already passed in `render_prompt()` at `main.py:572`.

Also replace line 64:

```
# Before
If you see no clear factors against the trade, report supporting factors only.

# After
Report all factors you see evidence for, whether they support or undermine the setup.
```

Change: removed permission to omit contrary evidence, replaced with balanced instruction.

### 4. Fix doji price direction

**File:** `backend/app/main.py`

Replace line 394:

```python
# Before
"price_direction": 1 if candle["close"] >= candle["open"] else -1

# After
"price_direction": 1 if candle["close"] > candle["open"] else (-1 if candle["close"] < candle["open"] else 0)
```

The OI scoring in `compute_order_flow_score` already handles `price_dir == 0` → `oi_score = 0.0`.

No unit test needed — this is a one-liner ternary with obvious correctness, and the logic is inline in `run_pipeline` (not in a separately testable function). Extracting it would be over-engineering.

### 5. Add direction split diagnostic logging

**File:** `backend/app/main.py`

Add a module-level counter dict. Inside `_log_pipeline_evaluation`, when `emitted=True`, increment the direction counter and log the split every 20 emitted signals. The counter resets on process restart and is per-worker — this is intentional for a lightweight diagnostic, not a metrics system.

```python
_direction_counts = {"LONG": 0, "SHORT": 0}
_direction_lifetime = {"LONG": 0, "SHORT": 0}

# Inside _log_pipeline_evaluation, at the end:
if emitted:
    direction = "LONG" if final_score > 0 else "SHORT"
    _direction_counts[direction] += 1
    _direction_lifetime[direction] += 1
    total = _direction_counts["LONG"] + _direction_counts["SHORT"]
    if total >= 20:
        l, s = _direction_counts["LONG"], _direction_counts["SHORT"]
        lt_l, lt_s = _direction_lifetime["LONG"], _direction_lifetime["SHORT"]
        lt_total = lt_l + lt_s
        logger.info(f"Direction split (last {total}): LONG={l} ({round(l*100/total)}%) SHORT={s} ({round(s*100/total)}%)")
        logger.info(f"Direction split (lifetime {lt_total}): LONG={lt_l} ({round(lt_l*100/lt_total)}%) SHORT={lt_s} ({round(lt_s*100/lt_total)}%)")
        _direction_counts["LONG"] = 0
        _direction_counts["SHORT"] = 0
```

## Files Changed

| File | Change |
|------|--------|
| `backend/app/engine/patterns.py` | Add Hanging Man, Shooting Star with trend context; pull hammer detectors out of uniform loop |
| `backend/app/engine/constants.py` | Add `hanging_man` and `shooting_star` to PATTERN_STRENGTHS |
| `backend/app/engine/llm.py` | Neutralize system prompt |
| `backend/app/prompts/signal_analysis.txt` | Neutralize user prompt anchoring; remove confirmation-bias language |
| `backend/app/main.py` | Fix doji price_direction; add direction split logging |
| `backend/tests/` | Tests for new patterns (incl. flat market edge case) and doji fix; review existing hammer tests |

## Not Changed

- Technical scoring (RSI, ADX, BB, OBV) — confirmed symmetric
- Order flow scoring (funding, L/S ratio) — confirmed symmetric
- ML pipeline — symmetric architecture with class weight balancing
- Combiner, risk, outcome resolver, performance tracker — all confirmed symmetric
- On-chain scoring — confirmed symmetric
- Level calculation — confirmed symmetric
