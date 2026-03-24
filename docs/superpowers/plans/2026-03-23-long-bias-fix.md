# Long Bias Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the pipeline's structural long bias by fixing four sources of directional asymmetry and adding direction-split diagnostic logging.

**Architecture:** Trend-aware candlestick pattern detection (Hanging Man, Shooting Star), neutralized LLM prompts, corrected doji OI classification, and lightweight direction-split counters. All changes are backend-only, confined to the engine and pipeline orchestration layers.

**Tech Stack:** Python 3.11, FastAPI, Pandas, pytest (asyncio_mode=auto)

**Spec:** `docs/superpowers/specs/2026-03-22-long-bias-fix-design.md`

---

### Task 1: Add Hanging Man and Shooting Star patterns

**Files:**
- Modify: `backend/app/engine/patterns.py:39-54` (hammer/inverted hammer detectors)
- Modify: `backend/app/engine/patterns.py:162-209` (`detect_candlestick_patterns`)
- Test: `backend/tests/engine/test_patterns.py`

- [ ] **Step 1: Write failing tests for trend-aware hammer patterns**

Add a new test class at the bottom of `backend/tests/engine/test_patterns.py`:

```python
class TestTrendAwarePatterns:
    """Hammer/Inverted Hammer shape → different name depending on prior trend."""

    def _downtrend_candles(self, final: dict) -> pd.DataFrame:
        """10 padding candles forming a downtrend, then the final candle."""
        rows = [
            {"open": 110 - i * 2, "high": 111 - i * 2, "low": 108 - i * 2,
             "close": 109 - i * 2, "volume": 50}
            for i in range(10)
        ]
        rows.append(final)
        return pd.DataFrame(rows)

    def _uptrend_candles(self, final: dict) -> pd.DataFrame:
        """10 padding candles forming an uptrend, then the final candle."""
        rows = [
            {"open": 90 + i * 2, "high": 91 + i * 2, "low": 88 + i * 2,
             "close": 89 + i * 2, "volume": 50}
            for i in range(10)
        ]
        rows.append(final)
        return pd.DataFrame(rows)

    def _flat_candles(self, final: dict) -> pd.DataFrame:
        """10 padding candles with identical close, then the final candle."""
        rows = [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 50}
            for _ in range(10)
        ]
        rows.append(final)
        return pd.DataFrame(rows)

    # -- Hammer shape (long lower shadow, small body at top, no upper shadow)
    HAMMER_SHAPE = {"open": 100.3, "high": 100.5, "low": 90, "close": 100.5, "volume": 50}

    # -- Inverted Hammer shape (long upper shadow, small body at bottom, no lower shadow)
    INV_HAMMER_SHAPE = {"open": 100, "high": 110, "low": 100, "close": 100.2, "volume": 50}

    def test_hammer_after_downtrend(self):
        candles = self._downtrend_candles(self.HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Hammer" in names
        hammer = next(p for p in patterns if p["name"] == "Hammer")
        assert hammer["bias"] == "bullish"
        assert hammer["strength"] == 12

    def test_hanging_man_after_uptrend(self):
        candles = self._uptrend_candles(self.HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Hanging Man" in names
        hm = next(p for p in patterns if p["name"] == "Hanging Man")
        assert hm["bias"] == "bearish"
        assert hm["strength"] == 12

    def test_inverted_hammer_after_downtrend(self):
        candles = self._downtrend_candles(self.INV_HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Inverted Hammer" in names
        ih = next(p for p in patterns if p["name"] == "Inverted Hammer")
        assert ih["bias"] == "bullish"
        assert ih["strength"] == 10

    def test_shooting_star_after_uptrend(self):
        candles = self._uptrend_candles(self.INV_HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Shooting Star" in names
        ss = next(p for p in patterns if p["name"] == "Shooting Star")
        assert ss["bias"] == "bearish"
        assert ss["strength"] == 10

    def test_hammer_shape_flat_market_suppressed(self):
        candles = self._flat_candles(self.HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Hammer" not in names
        assert "Hanging Man" not in names

    def test_inverted_hammer_shape_flat_market_suppressed(self):
        candles = self._flat_candles(self.INV_HAMMER_SHAPE)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Inverted Hammer" not in names
        assert "Shooting Star" not in names

    def test_insufficient_lookback_suppressed(self):
        """Fewer than 6 candles total → can't determine trend → no hammer patterns."""
        rows = [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 50}
            for _ in range(2)
        ]
        rows.append(self.HAMMER_SHAPE)
        candles = pd.DataFrame(rows)
        patterns = detect_candlestick_patterns(candles)
        names = [p["name"] for p in patterns]
        assert "Hammer" not in names
        assert "Hanging Man" not in names
        assert "Inverted Hammer" not in names
        assert "Shooting Star" not in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py::TestTrendAwarePatterns -v`
Expected: FAIL — `test_hanging_man_after_uptrend`, `test_shooting_star_after_uptrend`, `test_*_flat_market_suppressed`, and `test_insufficient_lookback_suppressed` fail. `test_hammer_after_downtrend` and `test_inverted_hammer_after_downtrend` may pass since the padding creates a downtrend context accidentally matching existing behavior.

- [ ] **Step 3: Make hammer/inverted hammer detectors trend-aware**

Modify `backend/app/engine/patterns.py`. Replace `_detect_hammer` (lines 39-45) and `_detect_inverted_hammer` (lines 48-54) with trend-aware versions that take a `trend_dir` parameter:

```python
def _detect_hammer(c, avg_b: float, trend_dir: int) -> dict | None:
    body = _body(c)
    lower = _lower_shadow(c)
    upper = _upper_shadow(c)
    if body < avg_b * 0.5 and lower >= body * 2 and upper < body * 0.5:
        if trend_dir == 0:
            return None
        if trend_dir < 0:
            return {"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}
        return {"name": "Hanging Man", "type": "candlestick", "bias": "bearish", "strength": 12}
    return None


def _detect_inverted_hammer(c, avg_b: float, trend_dir: int) -> dict | None:
    body = _body(c)
    upper = _upper_shadow(c)
    lower = _lower_shadow(c)
    if body < avg_b * 0.5 and upper >= body * 2 and lower < body * 0.5:
        if trend_dir == 0:
            return None
        if trend_dir < 0:
            return {"name": "Inverted Hammer", "type": "candlestick", "bias": "bullish", "strength": 10}
        return {"name": "Shooting Star", "type": "candlestick", "bias": "bearish", "strength": 10}
    return None
```

- [ ] **Step 4: Update `detect_candlestick_patterns` to compute trend direction and call detectors separately**

In `detect_candlestick_patterns` (starting at line 162), add trend direction computation after the `avg_b` calculation, and pull hammer/inverted hammer out of the uniform single-candle loop:

```python
    avg_b = _avg_body(df)
    patterns: list[dict] = []

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    third = df.iloc[-3] if len(df) >= 3 else None

    # Compute trend direction for hammer-family patterns
    if len(df) >= 6:
        trend_change = float(df.iloc[-1]["close"]) - float(df.iloc[-6]["close"])
        if trend_change > 0:
            trend_dir = 1
        elif trend_change < 0:
            trend_dir = -1
        else:
            trend_dir = 0
    else:
        trend_dir = 0  # Insufficient lookback

    # Trend-aware single-candle (hammer family)
    for detector in (_detect_hammer, _detect_inverted_hammer):
        result = detector(curr, avg_b, trend_dir)
        if result:
            patterns.append(result)

    # Uniform single-candle (no trend context needed)
    for detector in (_detect_doji, _detect_spinning_top, _detect_marubozu):
        result = detector(curr, avg_b)
        if result:
            patterns.append(result)
```

The two-candle and three-candle sections remain unchanged.

- [ ] **Step 5: Fix existing hammer/inverted hammer tests**

The existing `_make_candles` helper pads with `close=102`. The existing hammer test candle has `close=100.5` and inverted hammer has `close=100.2`. Since `close[-1] < close[-6]`, this is a downtrend → still Hammer/Inverted Hammer (bullish). Existing tests should still pass without changes.

Verify: `docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py -v`
Expected: ALL tests pass, including the old `test_hammer_detected` and `test_inverted_hammer_detected`.

- [ ] **Step 6: Run full test suite to verify no regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_patterns.py -v`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/engine/patterns.py backend/tests/engine/test_patterns.py
git commit -m "feat: add Hanging Man and Shooting Star patterns with trend context"
```

---

### Task 2: Add pattern strengths to constants registry

**Files:**
- Modify: `backend/app/engine/constants.py:80-94` (`PATTERN_STRENGTHS` dict)

- [ ] **Step 1: Add `hanging_man` and `shooting_star` entries**

In `backend/app/engine/constants.py`, add two entries to `PATTERN_STRENGTHS` after `hammer`:

```python
PATTERN_STRENGTHS = {
    "bullish_engulfing": 15,
    "bearish_engulfing": 15,
    "morning_star": 15,
    "evening_star": 15,
    "three_white_soldiers": 15,
    "three_black_crows": 15,
    "marubozu": 13,
    "hammer": 12,
    "hanging_man": 12,
    "piercing_line": 12,
    "dark_cloud_cover": 12,
    "inverted_hammer": 10,
    "shooting_star": 10,
    "doji": 8,
    "spinning_top": 5,
}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/engine/constants.py
git commit -m "feat: register Hanging Man and Shooting Star in pattern strengths"
```

---

### Task 3: Neutralize LLM system prompt

**Files:**
- Modify: `backend/app/engine/llm.py:13-19` (`SYSTEM_PROMPT`)

- [ ] **Step 1: Replace `SYSTEM_PROMPT`**

In `backend/app/engine/llm.py`, replace lines 13-19:

```python
SYSTEM_PROMPT = (
    "You are a decisive crypto futures trader with 10 years of experience. "
    "You analyze quantitative data and identify specific factors that support "
    "or undermine a trade setup. You focus on concrete evidence — divergences, "
    "key levels, exhaustion signals, positioning extremes. "
    "Apply equal scrutiny to both long and short setups."
)
```

Changes: removed `"not vague concerns about volatility or risk"`, added `"Apply equal scrutiny to both long and short setups."`.

- [ ] **Step 2: Commit**

```bash
git add backend/app/engine/llm.py
git commit -m "fix: neutralize LLM system prompt — remove anti-bearish bias"
```

---

### Task 4: Neutralize LLM user prompt anchoring

**Files:**
- Modify: `backend/app/prompts/signal_analysis.txt:30,64`

- [ ] **Step 1: Replace anchoring language on line 30**

In `backend/app/prompts/signal_analysis.txt`, replace line 30:

```
# Before:
The quantitative signals already flagged a {direction} setup. Your job is to identify specific factors that support or undermine this trade.

# After:
The quantitative signals produced a {direction} bias with score {blended_score}. Your job is to independently evaluate whether the data supports this direction, or if factors suggest caution or contradiction.
```

- [ ] **Step 2: Replace confirmation-bias language on line 64**

In `backend/app/prompts/signal_analysis.txt`, replace line 64:

```
# Before:
Only report factors you actually see evidence for in the data. Do not invent factors. If you see no clear factors against the trade, report supporting factors only.

# After:
Only report factors you actually see evidence for in the data. Do not invent factors. Report all factors you see evidence for, whether they support or undermine the setup.
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/prompts/signal_analysis.txt
git commit -m "fix: neutralize LLM user prompt — remove confirmation-bias anchoring"
```

---

### Task 5: Fix doji price direction classification

**Files:**
- Modify: `backend/app/main.py:394`

- [ ] **Step 1: Replace the price_direction ternary**

In `backend/app/main.py`, replace line 394:

```python
# Before:
flow_metrics = {**flow_metrics, "price_direction": 1 if candle["close"] >= candle["open"] else -1}

# After:
flow_metrics = {**flow_metrics, "price_direction": 1 if candle["close"] > candle["open"] else (-1 if candle["close"] < candle["open"] else 0)}
```

Doji candles (close == open) now get `price_direction = 0`, which `compute_order_flow_score` already handles by producing `oi_score = 0.0`.

- [ ] **Step 2: Commit**

```bash
git add backend/app/main.py
git commit -m "fix: classify doji candles as neutral price direction for OI scoring"
```

---

### Task 6: Add direction split diagnostic logging

**Files:**
- Modify: `backend/app/main.py` (module-level counters + `_log_pipeline_evaluation` body)

- [ ] **Step 1: Add module-level counters**

Near the top of `backend/app/main.py`, after the existing imports and logging setup (around line 12, after `logging.basicConfig`), add:

```python
_direction_counts = {"LONG": 0, "SHORT": 0}
_direction_lifetime = {"LONG": 0, "SHORT": 0}
```

- [ ] **Step 2: Add direction tracking to `_log_pipeline_evaluation`**

At the end of the `_log_pipeline_evaluation` function (after the existing `logger.info` call on line 770), add:

```python
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

- [ ] **Step 3: Run full backend test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: add direction split diagnostic logging every 20 emitted signals"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full test suite one more time**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v`
Expected: All tests PASS, no regressions.

- [ ] **Step 2: Squash into a single commit**

Per project convention (no small incremental commits), squash the task commits into a single feature commit:

```bash
git reset --soft HEAD~6
git commit -m "fix: eliminate long bias — trend-aware patterns, neutral LLM prompts, doji fix, direction logging"
```
