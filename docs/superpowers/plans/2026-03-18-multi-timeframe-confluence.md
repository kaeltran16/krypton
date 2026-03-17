# Multi-Timeframe Confluence Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a confluence scoring component (±15 points) that boosts signals aligned with the parent timeframe's trend and penalizes signals that conflict with it.

**Architecture:** Each timeframe caches its ADX/DI indicators to Redis after scoring. Child timeframes read the parent's cache and compute a confluence adjustment applied to the technical score before blending. 1D candle ingestion is added as a confluence-only timeframe (no signal emission) to serve as the parent for 4h.

**Tech Stack:** Python, FastAPI, Redis (caching), SQLAlchemy/Postgres (backtester queries), existing `sigmoid_scale` from `scoring.py`

**Spec:** `docs/superpowers/specs/2026-03-18-multi-timeframe-confluence-design.md`

---

## Chunk 1: Core Confluence Function + Config

### Task 1: `compute_confluence_score()` Unit Tests + Implementation

**Files:**
- Create: `backend/app/engine/confluence.py`
- Create: `backend/tests/engine/test_confluence.py`

- [ ] **Step 1: Write the test file**

```python
# backend/tests/engine/test_confluence.py
import pytest

from app.engine.confluence import compute_confluence_score


class TestConfluenceNoneParent:
    def test_none_returns_zero(self):
        assert compute_confluence_score(1, None) == 0

    def test_none_negative_direction(self):
        assert compute_confluence_score(-1, None) == 0


class TestConfluenceEqualDI:
    def test_equal_di_returns_zero(self):
        indicators = {"adx": 30, "di_plus": 25, "di_minus": 25}
        assert compute_confluence_score(1, indicators) == 0


class TestConfluenceAligned:
    def test_strong_trend_aligned(self):
        """ADX 40 + aligned → near max score."""
        score = compute_confluence_score(1, {"adx": 40, "di_plus": 30, "di_minus": 10})
        assert 13 <= score <= 15

    def test_moderate_trend_aligned(self):
        """ADX 25 + aligned → moderate score."""
        score = compute_confluence_score(1, {"adx": 25, "di_plus": 30, "di_minus": 10})
        assert 9 <= score <= 13

    def test_weak_trend_aligned(self):
        """ADX 10 + aligned → small score."""
        score = compute_confluence_score(1, {"adx": 10, "di_plus": 30, "di_minus": 10})
        assert 1 <= score <= 5


class TestConfluenceConflicting:
    def test_strong_trend_conflicting(self):
        """ADX 40 + conflicting → near negative max."""
        score = compute_confluence_score(-1, {"adx": 40, "di_plus": 30, "di_minus": 10})
        assert -15 <= score <= -13

    def test_weak_trend_conflicting(self):
        """ADX 10 + conflicting → small negative."""
        score = compute_confluence_score(-1, {"adx": 10, "di_plus": 30, "di_minus": 10})
        assert -5 <= score <= -1


class TestConfluenceClamping:
    def test_clamped_to_custom_max(self):
        score = compute_confluence_score(1, {"adx": 100, "di_plus": 50, "di_minus": 5}, max_score=10)
        assert score <= 10

    def test_clamped_to_custom_neg_max(self):
        score = compute_confluence_score(-1, {"adx": 100, "di_plus": 50, "di_minus": 5}, max_score=10)
        assert score >= -10


class TestConfluenceShortParent:
    def test_short_child_aligned_with_short_parent(self):
        """Child SHORT, parent SHORT (DI- > DI+) → positive boost."""
        score = compute_confluence_score(-1, {"adx": 35, "di_plus": 10, "di_minus": 30})
        assert score > 10

    def test_long_child_conflicting_with_short_parent(self):
        """Child LONG, parent SHORT → negative penalty."""
        score = compute_confluence_score(1, {"adx": 35, "di_plus": 10, "di_minus": 30})
        assert score < -10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_confluence.py -v`
Expected: ImportError — `app.engine.confluence` does not exist yet.

- [ ] **Step 3: Implement `confluence.py`**

```python
# backend/app/engine/confluence.py
"""Multi-timeframe confluence scoring and constants."""

from app.engine.scoring import sigmoid_scale

TIMEFRAME_PARENT = {"15m": "1h", "1h": "4h", "4h": "1D"}

CONFLUENCE_ONLY_TIMEFRAMES = {"1D"}

# TTL = 2x the timeframe period in seconds
TIMEFRAME_CACHE_TTL = {"15m": 1800, "1h": 7200, "4h": 28800, "1D": 172800}


def compute_confluence_score(
    child_direction: int,
    parent_indicators: dict | None,
    max_score: int = 15,
) -> int:
    """Score alignment between child and parent timeframe trends.

    Args:
        child_direction: +1 if child DI+ > DI-, -1 otherwise.
        parent_indicators: Dict with adx, di_plus, di_minus from parent TF, or None.
        max_score: Maximum absolute score.

    Returns:
        Integer in [-max_score, +max_score]. 0 if parent data unavailable.
    """
    if parent_indicators is None:
        return 0

    di_plus = parent_indicators.get("di_plus", 0)
    di_minus = parent_indicators.get("di_minus", 0)

    if di_plus == di_minus:
        return 0

    parent_direction = 1 if di_plus > di_minus else -1
    adx = parent_indicators.get("adx", 0)
    parent_strength = sigmoid_scale(adx, center=15, steepness=0.30)

    if child_direction == parent_direction:
        raw = max_score * parent_strength
    else:
        raw = -max_score * parent_strength

    return round(max(min(raw, max_score), -max_score))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_confluence.py -v`
Expected: All 12 tests PASS.

---

### Task 2: Config + 1D Ingestion Changes

**Files:**
- Modify: `backend/app/config.py:51` — add `"1D"` to default timeframes list
- Modify: `backend/app/config.py:59` — add `engine_confluence_max_score`
- Modify: `backend/app/collector/ws_client.py:14-18` — add 1D to channel map
- Modify: `backend/app/main.py:742` — add 1D to `OKX_BAR_MAP`

- [ ] **Step 5a: Add `"1D"` to the default timeframes list**

In `backend/app/config.py`, change line 51 from:

```python
    timeframes: list[str] = ["15m", "1h", "4h"]
```

to:

```python
    timeframes: list[str] = ["15m", "1h", "4h", "1D"]
```

Without this, the OKX WebSocket client won't subscribe to the 1D channel and `backfill_candles()` will skip 1D. If the user has a `PipelineSettings` row in the DB that overrides `timeframes`, they'll also need to add `"1D"` there via the settings API.

- [ ] **Step 5b: Add `engine_confluence_max_score` to config**

In `backend/app/config.py`, after line 65 (`engine_pattern_weight`), add:

```python
    engine_confluence_max_score: int = 15
```

- [ ] **Step 6: Add 1D to `TIMEFRAME_CHANNEL_MAP`**

In `backend/app/collector/ws_client.py`, change lines 14-18 from:

```python
TIMEFRAME_CHANNEL_MAP = {
    "15m": "candle15m",
    "1h": "candle1H",
    "4h": "candle4H",
}
```

to:

```python
TIMEFRAME_CHANNEL_MAP = {
    "15m": "candle15m",
    "1h": "candle1H",
    "4h": "candle4H",
    "1D": "candle1Dutc",
}
```

- [ ] **Step 7: Add 1D to `OKX_BAR_MAP`**

In `backend/app/main.py`, change line 742 from:

```python
OKX_BAR_MAP = {"15m": "15m", "1h": "1H", "4h": "4H"}
```

to:

```python
OKX_BAR_MAP = {"15m": "15m", "1h": "1H", "4h": "4H", "1D": "1Dutc"}
```

- [ ] **Step 8: Run existing tests to verify no regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/collector/test_ws_client.py tests/test_config.py -v`
Expected: All existing tests still pass.

---

## Chunk 2: Pipeline + Backtester Integration

### Task 3: Pipeline Integration (Redis Caching + Confluence Scoring + 1D Early Return)

**Files:**
- Modify: `backend/app/main.py:234-554` — `run_pipeline()` changes

This task modifies `run_pipeline()` in three places:

1. After `compute_technical_score()` (line 260): cache own indicators to Redis
2. After cache write: early return for confluence-only timeframes (1D)
3. Before continuing pipeline: read parent cache, compute confluence, adjust tech score
4. In `raw_indicators` dict (line 537): add confluence fields

- [ ] **Step 9: Add import for confluence module**

In `backend/app/main.py`, after the existing engine imports (line 32-36 area), add:

```python
from app.engine.confluence import (
    TIMEFRAME_PARENT, CONFLUENCE_ONLY_TIMEFRAMES,
    TIMEFRAME_CACHE_TTL, compute_confluence_score,
)
```

- [ ] **Step 10: Add HTF indicator cache write + confluence scoring after `compute_technical_score()`**

In `backend/app/main.py`, after the tech_result try/except block (after line 263), insert the following block **before** the indicator alert evaluation (line 265):

```python
    # ── HTF indicator caching ──
    indicators = tech_result["indicators"]
    htf_cache = json.dumps({
        "adx": indicators["adx"],
        "di_plus": indicators["di_plus"],
        "di_minus": indicators["di_minus"],
        "timestamp": candle["timestamp"].isoformat()
        if hasattr(candle["timestamp"], "isoformat")
        else candle["timestamp"],
    })
    htf_key = f"htf_indicators:{pair}:{timeframe}"
    ttl = TIMEFRAME_CACHE_TTL.get(timeframe, 7200)
    try:
        await redis.set(htf_key, htf_cache, ex=ttl)
    except Exception as e:
        logger.warning(f"HTF indicator cache write failed for {pair}:{timeframe}: {e}")

    # 1D is confluence-only — cache indicators, skip signal emission
    if timeframe in CONFLUENCE_ONLY_TIMEFRAMES:
        return

    # ── Confluence scoring ──
    confluence_score = 0
    parent_tf = TIMEFRAME_PARENT.get(timeframe)
    parent_indicators = None
    if parent_tf:
        try:
            raw_parent = await redis.get(f"htf_indicators:{pair}:{parent_tf}")
            if raw_parent:
                parent_indicators = json.loads(raw_parent)
        except Exception as e:
            logger.warning(f"HTF cache read failed for {pair}:{parent_tf}: {e}")

        child_direction = 1 if indicators["di_plus"] > indicators["di_minus"] else -1
        confluence_score = compute_confluence_score(
            child_direction, parent_indicators,
            max_score=settings.engine_confluence_max_score,
        )
        tech_result["score"] = max(min(tech_result["score"] + confluence_score, 100), -100)
```

- [ ] **Step 11: Add confluence fields to `raw_indicators` in signal emission**

In `backend/app/main.py`, inside the `raw_indicators` dict (around line 537-550), add after the `"levels_source"` line:

```python
            "confluence_score": confluence_score,
            "parent_tf": parent_tf,
            "parent_adx": parent_indicators["adx"] if parent_indicators else None,
            "parent_di_plus": parent_indicators["di_plus"] if parent_indicators else None,
            "parent_di_minus": parent_indicators["di_minus"] if parent_indicators else None,
```

- [ ] **Step 12: Run full test suite to verify no regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All tests pass. The pipeline tests in `tests/test_pipeline.py` call scoring functions directly (no Redis), so they're unaffected by the new Redis caching code.

---

### Task 4: Confluence Constants + Caching Pattern Unit Tests

**Files:**
- Create: `backend/tests/engine/test_confluence_caching.py`

These tests verify the confluence constants (timeframe hierarchy, cache TTLs, confluence-only set) and the cache key/serialization patterns that `run_pipeline()` uses. They use `AsyncMock` to validate the expected Redis interaction contract — they do **not** exercise the pipeline code itself.

- [ ] **Step 13: Write caching pattern + constants tests**

```python
# backend/tests/engine/test_confluence_caching.py
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app.engine.confluence import (
    TIMEFRAME_CACHE_TTL, TIMEFRAME_PARENT,
    CONFLUENCE_ONLY_TIMEFRAMES, compute_confluence_score,
)
from app.main import run_pipeline


class TestHTFCacheKeyContract:
    @pytest.mark.asyncio
    async def test_cache_key_format_and_ttl(self):
        """Verify the key/TTL contract that run_pipeline must follow."""
        redis = AsyncMock()
        pair, timeframe = "BTC-USDT-SWAP", "1h"

        # Replicate the serialization run_pipeline uses
        indicators = {"adx": 28.5, "di_plus": 32.1, "di_minus": 18.7}
        htf_cache = json.dumps({
            "adx": indicators["adx"],
            "di_plus": indicators["di_plus"],
            "di_minus": indicators["di_minus"],
            "timestamp": "2025-01-01T01:00:00+00:00",
        })
        htf_key = f"htf_indicators:{pair}:{timeframe}"
        ttl = TIMEFRAME_CACHE_TTL[timeframe]
        await redis.set(htf_key, htf_cache, ex=ttl)

        redis.set.assert_called_once_with(htf_key, htf_cache, ex=7200)
        cached = json.loads(redis.set.call_args[0][1])
        assert cached["adx"] == 28.5
        assert cached["di_plus"] == 32.1
        assert cached["di_minus"] == 18.7


class TestHTFCacheReadPattern:
    @pytest.mark.asyncio
    async def test_child_reads_parent_cache_and_scores(self):
        """15m pipeline reads cached 1h indicators and produces non-zero confluence."""
        redis = AsyncMock()
        parent_data = json.dumps({"adx": 30, "di_plus": 28, "di_minus": 15})
        redis.get.return_value = parent_data

        pair, timeframe = "BTC-USDT-SWAP", "15m"
        parent_tf = TIMEFRAME_PARENT[timeframe]
        raw_parent = await redis.get(f"htf_indicators:{pair}:{parent_tf}")
        parent_indicators = json.loads(raw_parent)

        child_direction = 1  # child is bullish
        score = compute_confluence_score(child_direction, parent_indicators)

        # Parent is bullish (DI+ > DI-) and child is bullish → positive boost
        assert score > 0
        redis.get.assert_called_once_with(f"htf_indicators:{pair}:1h")

    @pytest.mark.asyncio
    async def test_cold_start_cache_miss_returns_zero(self):
        """No cache → confluence = 0, no crash."""
        redis = AsyncMock()
        redis.get.return_value = None

        raw_parent = await redis.get("htf_indicators:BTC-USDT-SWAP:1h")
        parent_indicators = json.loads(raw_parent) if raw_parent else None

        score = compute_confluence_score(1, parent_indicators)
        assert score == 0


class TestConfluenceOnlyTimeframes:
    def test_1d_is_confluence_only(self):
        """1D should be in CONFLUENCE_ONLY_TIMEFRAMES."""
        assert "1D" in CONFLUENCE_ONLY_TIMEFRAMES

    def test_signal_timeframes_are_not_confluence_only(self):
        """15m, 1h, 4h should emit signals normally."""
        for tf in ["15m", "1h", "4h"]:
            assert tf not in CONFLUENCE_ONLY_TIMEFRAMES

    def test_all_signal_timeframes_have_parents(self):
        """Every signal-emitting timeframe should have a parent for confluence."""
        for tf in ["15m", "1h", "4h"]:
            assert tf in TIMEFRAME_PARENT

    def test_cache_ttl_covers_all_timeframes(self):
        """Every timeframe (signal + confluence-only) should have a cache TTL."""
        all_tfs = set(TIMEFRAME_PARENT.keys()) | CONFLUENCE_ONLY_TIMEFRAMES
        for tf in all_tfs:
            assert tf in TIMEFRAME_CACHE_TTL


def _mock_db():
    mock_session = AsyncMock()
    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db, mock_session


class TestPipeline1DEarlyReturn:
    @pytest.mark.asyncio
    async def test_1d_caches_indicators_but_skips_signal_emission(self):
        """run_pipeline for 1D should write HTF cache then return without emitting."""
        app = FastAPI()
        app.state.settings = MagicMock()
        app.state.settings.engine_confluence_max_score = 15
        app.state.redis = AsyncMock()
        mock_db, mock_session = _mock_db()
        app.state.db = mock_db
        app.state.order_flow = {}
        app.state.prompt_template = ""
        app.state.manager = MagicMock()

        # 200 candles so we pass the minimum count check
        raw_candles = [
            json.dumps({
                "timestamp": f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00",
                "open": 67000 + i * 10, "high": 67100 + i * 10,
                "low": 66900 + i * 10, "close": 67050 + i * 10,
                "volume": 100,
            })
            for i in range(200)
        ]
        app.state.redis.lrange = AsyncMock(return_value=raw_candles)

        candle = {
            "pair": "BTC-USDT-SWAP", "timeframe": "1D",
            "timestamp": datetime(2026, 2, 27, tzinfo=timezone.utc),
            "open": 67000, "high": 67100, "low": 66900, "close": 67050,
            "volume": 100,
        }

        await run_pipeline(app, candle)

        # HTF cache should have been written (redis.set called)
        app.state.redis.set.assert_called_once()
        call_args = app.state.redis.set.call_args
        assert "htf_indicators:BTC-USDT-SWAP:1D" in call_args[0]

        # No signal should have been emitted
        app.state.manager.broadcast.assert_not_called()
        mock_session.add.assert_not_called()
```

- [ ] **Step 14: Run caching pattern + constants tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_confluence_caching.py -v`
Expected: All 8 tests PASS (these test against the already-implemented confluence module + mock Redis).

---

### Task 5: Backtester Confluence Integration

**Files:**
- Modify: `backend/app/engine/backtester.py:1-17` — add imports
- Modify: `backend/app/engine/backtester.py:22-34` — add `confluence_max_score` to `BacktestConfig`
- Modify: `backend/app/engine/backtester.py:54-60` — add `parent_candles` parameter
- Add: new functions `precompute_parent_indicators()` and `_lookup_parent_indicators()`
- Add: confluence scoring inside the iteration loop
- Create: `backend/tests/engine/test_confluence_backtest.py`

- [ ] **Step 15: Write backtester confluence tests**

```python
# backend/tests/engine/test_confluence_backtest.py
from datetime import datetime, timezone, timedelta

from app.engine.backtester import run_backtest, BacktestConfig
from app.engine.confluence import compute_confluence_score


def _make_candle_series(n=100, base_price=67000, trend=10, start_minutes_offset=0, minutes_per_candle=15):
    """Generate a synthetic candle series."""
    candles = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=start_minutes_offset)
    for i in range(n):
        o = base_price + i * trend
        candles.append({
            "timestamp": (start + timedelta(minutes=minutes_per_candle * i)).isoformat(),
            "open": o, "high": o + 50, "low": o - 30, "close": o + 20, "volume": 100 + i,
        })
    return candles


class TestPrecomputeParentIndicators:
    def test_returns_snapshots_after_min_candles(self):
        from app.engine.backtester import precompute_parent_indicators
        parent_candles = _make_candle_series(n=100, minutes_per_candle=60)
        timestamps, indicators = precompute_parent_indicators(parent_candles)
        # Should have snapshots for candles 70..99 = 30 snapshots
        assert len(timestamps) == 30
        assert len(indicators) == 30
        assert all("adx" in ind for ind in indicators)
        assert all("di_plus" in ind for ind in indicators)
        assert all("di_minus" in ind for ind in indicators)

    def test_too_few_candles_returns_empty(self):
        from app.engine.backtester import precompute_parent_indicators
        parent_candles = _make_candle_series(n=50, minutes_per_candle=60)
        timestamps, indicators = precompute_parent_indicators(parent_candles)
        assert timestamps == []
        assert indicators == []

    def test_timestamps_are_sorted(self):
        from app.engine.backtester import precompute_parent_indicators
        parent_candles = _make_candle_series(n=100, minutes_per_candle=60)
        timestamps, _ = precompute_parent_indicators(parent_candles)
        assert timestamps == sorted(timestamps)


class TestLookupParentIndicators:
    def test_finds_most_recent_before_child(self):
        from app.engine.backtester import _lookup_parent_indicators
        timestamps = ["2025-01-01T01:00:00", "2025-01-01T02:00:00", "2025-01-01T03:00:00"]
        indicators = [{"adx": 10}, {"adx": 20}, {"adx": 30}]
        # Child at 02:30 should get the 02:00 snapshot
        result = _lookup_parent_indicators("2025-01-01T02:30:00", timestamps, indicators)
        assert result["adx"] == 20

    def test_returns_none_before_first_snapshot(self):
        from app.engine.backtester import _lookup_parent_indicators
        timestamps = ["2025-01-01T02:00:00"]
        indicators = [{"adx": 10}]
        result = _lookup_parent_indicators("2025-01-01T01:00:00", timestamps, indicators)
        assert result is None

    def test_returns_none_for_empty(self):
        from app.engine.backtester import _lookup_parent_indicators
        result = _lookup_parent_indicators("2025-01-01T01:00:00", [], [])
        assert result is None

    def test_exact_match_uses_that_snapshot(self):
        from app.engine.backtester import _lookup_parent_indicators
        timestamps = ["2025-01-01T01:00:00", "2025-01-01T02:00:00"]
        indicators = [{"adx": 10}, {"adx": 20}]
        result = _lookup_parent_indicators("2025-01-01T02:00:00", timestamps, indicators)
        assert result["adx"] == 20

    def test_never_returns_future_data(self):
        from app.engine.backtester import _lookup_parent_indicators
        timestamps = ["2025-01-01T03:00:00", "2025-01-01T04:00:00"]
        indicators = [{"adx": 30}, {"adx": 40}]
        result = _lookup_parent_indicators("2025-01-01T02:00:00", timestamps, indicators)
        assert result is None


class TestBacktestWithConfluence:
    def test_with_parent_candles_produces_different_scores(self):
        """Backtest with parent candles should produce different results than without."""
        child_candles = _make_candle_series(n=120, base_price=67000, trend=10)
        parent_candles = _make_candle_series(n=100, base_price=67000, trend=10, minutes_per_candle=60)
        config = BacktestConfig(signal_threshold=20, max_concurrent_positions=5)

        result_without = run_backtest(child_candles, "BTC-USDT-SWAP", config)
        result_with = run_backtest(child_candles, "BTC-USDT-SWAP", config, parent_candles=parent_candles)

        # Both should run successfully
        assert "stats" in result_without
        assert "stats" in result_with

    def test_without_parent_candles_runs_normally(self):
        """Backtest without parent candles should work identically to before."""
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(signal_threshold=20)
        result = run_backtest(candles, "BTC-USDT-SWAP", config, parent_candles=None)
        assert "stats" in result
        assert "trades" in result
```

- [ ] **Step 16: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_confluence_backtest.py -v`
Expected: ImportError or AttributeError — `precompute_parent_indicators` and `_lookup_parent_indicators` don't exist yet.

- [ ] **Step 17: Add imports and `confluence_max_score` to `BacktestConfig`**

In `backend/app/engine/backtester.py`, add `bisect` to imports (line 1 area):

```python
import bisect
```

Add import for confluence (after existing engine imports around line 14):

```python
from app.engine.confluence import compute_confluence_score
```

Add to `BacktestConfig` dataclass (after `ml_confidence_threshold` on line 33):

```python
    confluence_max_score: int = 15
```

- [ ] **Step 18: Add `precompute_parent_indicators()` and `_lookup_parent_indicators()`**

In `backend/app/engine/backtester.py`, add after the `MIN_CANDLES` constant (after line 18):

```python
def precompute_parent_indicators(parent_candles: list[dict]) -> tuple[list[str], list[dict]]:
    """Pre-compute ADX/DI indicators for each parent candle.

    Returns (sorted_timestamps, indicators_list) for bisect lookup.
    """
    if len(parent_candles) < MIN_CANDLES:
        return [], []

    timestamps: list[str] = []
    indicators: list[dict] = []

    for i in range(MIN_CANDLES, len(parent_candles)):
        window = parent_candles[max(0, i - 199) : i + 1]
        df = pd.DataFrame(window)
        try:
            result = compute_technical_score(df)
            ts = parent_candles[i]["timestamp"]
            if isinstance(ts, datetime):
                ts = ts.isoformat()
            timestamps.append(ts)
            indicators.append({
                "adx": result["indicators"]["adx"],
                "di_plus": result["indicators"]["di_plus"],
                "di_minus": result["indicators"]["di_minus"],
            })
        except Exception:
            continue

    return timestamps, indicators


def _lookup_parent_indicators(
    child_timestamp: str,
    parent_timestamps: list[str],
    parent_indicators: list[dict],
) -> dict | None:
    """Find the most recent parent snapshot at or before child_timestamp."""
    if not parent_timestamps:
        return None
    idx = bisect.bisect_right(parent_timestamps, child_timestamp) - 1
    if idx < 0:
        return None
    return parent_indicators[idx]
```

- [ ] **Step 19: Add `parent_candles` parameter and confluence logic to `run_backtest()`**

In `backend/app/engine/backtester.py`, modify the `run_backtest` signature (line 54) to add `parent_candles`:

```python
def run_backtest(
    candles: list[dict],
    pair: str,
    config: BacktestConfig | None = None,
    cancel_flag: dict | None = None,
    ml_predictor=None,
    parent_candles: list[dict] | None = None,
) -> dict:
```

After `config = BacktestConfig()` (line 74), add parent precomputation:

```python
    # Pre-compute parent TF indicators for confluence scoring
    parent_timestamps: list[str] = []
    parent_indicators_list: list[dict] = []
    if parent_candles:
        parent_timestamps, parent_indicators_list = precompute_parent_indicators(parent_candles)
```

After `tech_result = compute_technical_score(df)` (inside the try block around line 98), add confluence scoring:

```python
        # Confluence scoring
        confluence_score = 0
        if parent_timestamps:
            ts = current["timestamp"]
            if isinstance(ts, datetime):
                ts = ts.isoformat()
            parent_ind = _lookup_parent_indicators(ts, parent_timestamps, parent_indicators_list)
            child_dir = 1 if tech_result["indicators"]["di_plus"] > tech_result["indicators"]["di_minus"] else -1
            confluence_score = compute_confluence_score(
                child_dir, parent_ind, max_score=config.confluence_max_score,
            )
            tech_result["score"] = max(min(tech_result["score"] + confluence_score, 100), -100)
```

This block goes right after `tech_result = compute_technical_score(df)` and before the pattern scoring block.

- [ ] **Step 20: Run backtester tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_confluence_backtest.py tests/engine/test_backtester.py -v`
Expected: All new and existing backtester tests pass.

---

### Task 6: Backtest API Parent Candle Fetching

**Files:**
- Modify: `backend/app/api/backtest.py:145-201` — fetch parent candles and pass to `run_backtest()`

- [ ] **Step 21: Add parent candle fetching to backtest API**

In `backend/app/api/backtest.py`, add imports at top (after existing imports):

```python
from datetime import timedelta
from app.engine.confluence import TIMEFRAME_PARENT
```

(`datetime` is already imported but `timedelta` may need adding to the import — check if it's already in the `from datetime import ...` line.)

In the `_run()` async function inside `start_backtest()`, **before** the per-pair loop (around line 161, after `all_stats_parts = []`), add the parent date pre-warm calculation:

```python
            # Extend parent query range backwards to pre-warm indicator window.
            # precompute_parent_indicators needs MIN_CANDLES (70) parent candles
            # before producing its first snapshot. Without this, the first ~70
            # parent periods of every backtest would have zero confluence.
            _PARENT_PERIOD_HOURS = {"1h": 1, "4h": 4, "1D": 24}
            parent_tf = TIMEFRAME_PARENT.get(body.timeframe)
            parent_prewarm_from = date_from
            if parent_tf and parent_tf in _PARENT_PERIOD_HOURS:
                parent_prewarm_from = date_from - timedelta(
                    hours=_PARENT_PERIOD_HOURS[parent_tf] * 70
                )
```

Then inside the per-pair loop (around line 162-201), after loading child candles from Postgres and before calling `run_backtest`, add parent candle fetching using the pre-warmed date:

```python
                # Fetch parent timeframe candles for confluence scoring
                parent_candles_list = None
                if parent_tf:
                    async with db.session_factory() as session:
                        parent_result = await session.execute(
                            select(Candle)
                            .where(Candle.pair == pair)
                            .where(Candle.timeframe == parent_tf)
                            .where(Candle.timestamp >= parent_prewarm_from)
                            .where(Candle.timestamp <= date_to)
                            .order_by(Candle.timestamp)
                        )
                        parent_rows = parent_result.scalars().all()
                    if parent_rows:
                        parent_candles_list = [
                            {
                                "timestamp": c.timestamp.isoformat(),
                                "open": float(c.open),
                                "high": float(c.high),
                                "low": float(c.low),
                                "close": float(c.close),
                                "volume": float(c.volume),
                            }
                            for c in parent_rows
                        ]
```

Then modify the `run_backtest` call (around line 199-201) to pass parent candles:

```python
                result = await asyncio.to_thread(
                    run_backtest, candles, pair, bt_config, cancel_flags.get(run_id),
                    ml_predictor, parent_candles_list,
                )
```

- [ ] **Step 22: Run full test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All tests pass.

---

### Task 7: Commit

- [ ] **Step 23: Commit all changes**

```bash
git add backend/app/engine/confluence.py backend/tests/engine/test_confluence.py backend/tests/engine/test_confluence_caching.py backend/tests/engine/test_confluence_backtest.py backend/app/config.py backend/app/collector/ws_client.py backend/app/main.py backend/app/engine/backtester.py backend/app/api/backtest.py
git commit -m "feat: add multi-timeframe confluence scoring"
```
