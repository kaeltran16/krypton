# Data Ingestion Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix reliability bugs in the data ingestion layer, add CVD and order book depth as new signal sources, and build a data freshness watchdog.

**Architecture:** TDD approach across 10 tasks in 3 commit batches. Bug fixes first (stable WS connection needed before adding channels), then reliability (liquidation Redis persistence, freshness watchdog), then new data sources (CVD trades collection + scoring, order book depth collection + scoring integration). Each task is independently testable. Commits are batched: bug fixes (Tasks 1-3), reliability (Tasks 4-5), new data sources (Tasks 6-10).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, Redis, websockets, Alembic, pytest

**Spec:** `docs/superpowers/specs/2026-03-25-data-ingestion-hardening.md`

**Task dependencies:** Tasks 1-3 are independent. Task 4 must complete before Task 5 (Task 5 modifies the LiquidationCollector that Task 4 rewrites). Tasks 6-7 depend on Task 1 (ping fix needed before adding new WS channels). Task 8 depends on Task 7. Tasks 9-10 depend on Task 6.

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `backend/app/collector/freshness.py` | Shared freshness computation: checks staleness of candles, order flow, on-chain, liquidation data |
| `backend/app/collector/watchdog.py` | Background coroutine (30s) that calls `compute_freshness()` and logs warnings |
| `backend/tests/collector/test_freshness.py` | Tests for freshness computation |
| `backend/tests/collector/test_watchdog.py` | Tests for watchdog logging behavior |
| `backend/tests/collector/test_cvd.py` | Tests for CVD trade parsing and accumulation |
| `backend/tests/collector/test_depth.py` | Tests for books5 parsing and depth state storage |
| Alembic migration | Adds `cvd_delta` nullable float column to `order_flow_snapshots` |

### Modified Files
| File | Changes |
|------|---------|
| `backend/app/collector/ws_client.py` | Add `ping_interval=20`, trades/books5 channel subscriptions + parsers, new callbacks |
| `backend/app/collector/liquidation.py` | Add Redis persistence (RPUSH/LRANGE) and startup reload |
| `backend/app/collector/onchain.py` | Compute `addr_trend_pct` from existing history |
| `backend/app/main.py` | Order flow preloading, CVD/depth handlers, watchdog startup, snapshot cvd_delta, pipeline depth wiring |
| `backend/app/engine/traditional.py` | CVD scoring component, dynamic confidence denominator |
| `backend/app/engine/constants.py` | CVD constants, rebalanced ORDER_FLOW max_scores |
| `backend/app/engine/liquidation_scorer.py` | Optional `depth` parameter with [0.7, 1.3] modifier |
| `backend/app/engine/structure.py` | Optional `depth` parameter for level strength modulation |
| `backend/app/db/models.py` | `cvd_delta` column on `OrderFlowSnapshot` |
| `backend/app/api/system.py` | Use shared `compute_freshness()` instead of ad-hoc logic |
| `backend/tests/collector/test_ws_client.py` | Tests for ping_interval, trades/books5 parsing |
| `backend/tests/collector/test_liquidation_collector.py` | Tests for Redis persistence + reload |
| `backend/tests/engine/test_traditional.py` | CVD scoring + dynamic confidence tests |
| `backend/tests/engine/test_liquidation_scorer.py` | Depth modifier tests |
| `backend/tests/engine/test_structure.py` | Depth modulation tests |
| `backend/tests/engine/test_onchain_scorer.py` | addr_trend_pct test |
| `backend/tests/test_pipeline.py` | Order flow preloading + log level tests |

---

## Task 1: WebSocket Ping Interval + Snapshot Log Level

Bug fixes 1.1 and 1.4 from the spec. Both are single-line changes.

**Files:**
- Modify: `backend/app/collector/ws_client.py:153`
- Modify: `backend/app/main.py:438`
- Test: `backend/tests/collector/test_ws_client.py`
- Test: `backend/tests/test_pipeline.py`

- [ ] **Step 1: Write failing test for ping_interval**

In `backend/tests/collector/test_ws_client.py`, add:

```python
from unittest.mock import patch, AsyncMock, MagicMock
import pytest

@pytest.mark.asyncio
async def test_run_loop_sets_ping_interval():
    from app.collector.ws_client import OKXWebSocketClient

    client = OKXWebSocketClient(pairs=["BTC-USDT-SWAP"], timeframes=["15m"])

    mock_ws = AsyncMock()
    mock_ws.__aiter__ = MagicMock(return_value=iter([]))
    mock_ws.send = AsyncMock()

    with patch("app.collector.ws_client.websockets.connect") as mock_connect:
        mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_connect.return_value.__aexit__ = AsyncMock(return_value=False)

        # Stop after first connection attempt
        async def stop_after_connect(*args, **kwargs):
            client._running = False

        mock_ws.__aiter__ = MagicMock(side_effect=stop_after_connect)

        client._running = True
        await client._run_loop("wss://example.com", [{"channel": "test"}], "test")

        mock_connect.assert_called_once()
        _, kwargs = mock_connect.call_args
        assert kwargs.get("ping_interval") == 20 or mock_connect.call_args[1].get("ping_interval") == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_ws_client.py::test_run_loop_sets_ping_interval -v`
Expected: FAIL — current code does not pass `ping_interval`

- [ ] **Step 3: Add ping_interval=20 to ws_client.py**

In `backend/app/collector/ws_client.py`, line 153, change:
```python
# OLD
async with websockets.connect(url) as ws:
# NEW
async with websockets.connect(url, ping_interval=20) as ws:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_ws_client.py::test_run_loop_sets_ping_interval -v`
Expected: PASS

- [ ] **Step 5: Fix snapshot log level**

In `backend/app/main.py`, line 438, change:
```python
# OLD
logger.debug(f"Order flow snapshot save skipped: {e}")
# NEW
logger.warning(f"Order flow snapshot save skipped: {e}")
```

- [ ] **Step 6: Run all existing tests to verify no regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_ws_client.py tests/test_pipeline.py -v`
Expected: All PASS

---

## Task 2: Order Flow Preloading on Startup

Bug fixes 1.2 and 1.3 from the spec. Seeds `app.state.order_flow` from the last `OrderFlowSnapshot` per pair so the first candle after restart has meaningful OI delta.

**Files:**
- Modify: `backend/app/main.py` (lifespan function, ~line 1191)
- Test: `backend/tests/test_pipeline.py`

- [ ] **Step 1: Write failing test for order flow preloading**

In `backend/tests/test_pipeline.py`, add:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_order_flow_preloaded_from_db():
    """After lifespan init, order_flow should be seeded from latest snapshots."""
    from app.db.models import OrderFlowSnapshot

    mock_snap = MagicMock(spec=OrderFlowSnapshot)
    mock_snap.pair = "BTC-USDT-SWAP"
    mock_snap.funding_rate = 0.0003
    mock_snap.open_interest = 150000.0
    mock_snap.long_short_ratio = 1.2

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_snap]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    order_flow = {}
    await _seed_order_flow(order_flow, mock_session)

    assert "BTC-USDT-SWAP" in order_flow
    assert order_flow["BTC-USDT-SWAP"]["funding_rate"] == 0.0003
    assert order_flow["BTC-USDT-SWAP"]["open_interest"] == 150000.0
    assert order_flow["BTC-USDT-SWAP"]["long_short_ratio"] == 1.2
```

Also test that bug 1.3 is fixed — first OI delta uses the seeded value:

```python
@pytest.mark.asyncio
async def test_first_oi_delta_uses_seeded_value():
    """After preloading, handle_open_interest should compute delta from seeded OI, not self."""
    from app.main import handle_open_interest

    app = MagicMock()
    app.state.order_flow = {"BTC-USDT-SWAP": {"open_interest": 150000.0}}

    await handle_open_interest(app, {"pair": "BTC-USDT-SWAP", "open_interest": 160000.0})

    flow = app.state.order_flow["BTC-USDT-SWAP"]
    expected_pct = (160000.0 - 150000.0) / 150000.0
    assert abs(flow["open_interest_change_pct"] - expected_pct) < 0.0001
```

Also test that NULL-valued snapshots don't inject None into the dict:

```python
@pytest.mark.asyncio
async def test_seed_order_flow_skips_null_fields():
    """Snapshot with NULL open_interest should not inject None into order_flow."""
    from app.db.models import OrderFlowSnapshot

    mock_snap = MagicMock(spec=OrderFlowSnapshot)
    mock_snap.pair = "ETH-USDT-SWAP"
    mock_snap.funding_rate = 0.0001
    mock_snap.open_interest = None
    mock_snap.long_short_ratio = None

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_snap]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    order_flow = {}
    await _seed_order_flow(order_flow, mock_session)

    assert "ETH-USDT-SWAP" in order_flow
    assert order_flow["ETH-USDT-SWAP"]["funding_rate"] == 0.0001
    assert "open_interest" not in order_flow["ETH-USDT-SWAP"]
    assert "long_short_ratio" not in order_flow["ETH-USDT-SWAP"]
```

Note: these tests import `_seed_order_flow` and `handle_open_interest` which don't exist yet / won't have the right behavior, so they will fail.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/test_pipeline.py::test_order_flow_preloaded_from_db -v`
Expected: FAIL — `_seed_order_flow` not found

- [ ] **Step 3: Implement `_seed_order_flow` in main.py**

Add near the top of `backend/app/main.py` (after imports, before handler functions):

```python
async def _seed_order_flow(order_flow: dict, session):
    """Seed order_flow dict from latest OrderFlowSnapshot per pair."""
    from sqlalchemy import select, func
    from app.db.models import OrderFlowSnapshot

    subq = (
        select(
            OrderFlowSnapshot.pair,
            func.max(OrderFlowSnapshot.id).label("max_id"),
        )
        .group_by(OrderFlowSnapshot.pair)
        .subquery()
    )
    stmt = select(OrderFlowSnapshot).join(
        subq,
        (OrderFlowSnapshot.pair == subq.c.pair)
        & (OrderFlowSnapshot.id == subq.c.max_id),
    )
    result = await session.execute(stmt)
    for snap in result.scalars().all():
        entry = {}
        if snap.funding_rate is not None:
            entry["funding_rate"] = snap.funding_rate
        if snap.open_interest is not None:
            entry["open_interest"] = snap.open_interest
        if snap.long_short_ratio is not None:
            entry["long_short_ratio"] = snap.long_short_ratio
        if entry:
            order_flow[snap.pair] = entry
```

Then in the lifespan function, after `app.state.order_flow = {}` (line 1191), add:

```python
try:
    async with db.session_factory() as session:
        await _seed_order_flow(app.state.order_flow, session)
    logger.info("Seeded order flow for %d pairs", len(app.state.order_flow))
except Exception as e:
    logger.warning("Order flow preload failed: %s", e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/test_pipeline.py::test_order_flow_preloaded_from_db -v`
Expected: PASS

- [ ] **Step 5: Run existing tests for regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=30`
Expected: All PASS

---

## Task 3: Wire addr_trend_pct From Existing History

Bug fix 1.5. The on-chain scorer already reads `addr_trend_pct` from Redis if present (`onchain_scorer.py:72`). The collector already stores `active_addresses` history in Redis. This task only adds the collector-level computation that populates the `addr_trend_pct` key.

**Files:**
- Modify: `backend/app/collector/onchain.py:192`
- Test: `backend/tests/engine/test_onchain_scorer.py`

- [ ] **Step 1: Write failing test**

In `backend/tests/engine/test_onchain_scorer.py`, add:

```python
@pytest.mark.asyncio
async def test_addr_trend_pct_scores_positive(mock_redis):
    _setup_redis(mock_redis, "BTC-USDT-SWAP", {"addr_trend_pct": 0.05})
    result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
    assert result["score"] > 0


@pytest.mark.asyncio
async def test_addr_trend_pct_scores_negative(mock_redis):
    _setup_redis(mock_redis, "BTC-USDT-SWAP", {"addr_trend_pct": -0.05})
    result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
    # addr_trend negative combined with no other metrics
    assert result["score"] < 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_onchain_scorer.py::test_addr_trend_pct_scores_positive tests/engine/test_onchain_scorer.py::test_addr_trend_pct_scores_negative -v`
Expected: FAIL — mock returns `addr_trend_pct` but the existing `_setup_redis` pattern should handle this. If tests pass already (scorer already reads from Redis when key exists), that means the scorer logic works but the collector never provides the key. In that case, write a collector-level test instead:

```python
# In backend/tests/collector/test_onchain_collector.py (new or extend)
@pytest.mark.asyncio
async def test_addr_trend_pct_computed_from_history():
    """After _append_history stores active_addresses, addr_trend_pct should be set."""
    from app.collector.onchain import OnChainCollector
    import json

    mock_redis = AsyncMock()

    history = [
        json.dumps({"v": 800000, "ts": "2026-03-25T00:00:00Z"}),
        json.dumps({"v": 850000, "ts": "2026-03-25T01:00:00Z"}),
        json.dumps({"v": 900000, "ts": "2026-03-25T02:00:00Z"}),
    ]
    mock_redis.lrange = AsyncMock(return_value=history)
    mock_redis.rpush = AsyncMock()
    mock_redis.ltrim = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.set = AsyncMock()

    collector = OnChainCollector(pairs=["BTC-USDT-SWAP"], redis=mock_redis)
    await collector._append_history("BTC-USDT-SWAP", "active_addresses", 900000)

    # Should have called redis.set with addr_trend_pct key
    set_calls = [c for c in mock_redis.set.call_args_list if "addr_trend_pct" in str(c)]
    assert len(set_calls) >= 1
```

- [ ] **Step 3: Implement addr_trend_pct computation**

In `backend/app/collector/onchain.py`, modify `_append_history` (line 231) to compute trend when the metric is `active_addresses`:

```python
async def _append_history(self, pair: str, metric: str, value: float):
    """Store rolling 24h history for trend calculation."""
    hist_key = f"onchain_hist:{pair}:{metric}"
    entry = json.dumps({"v": value, "ts": datetime.now(timezone.utc).isoformat()})
    await self.redis.rpush(hist_key, entry)
    await self.redis.ltrim(hist_key, -288, -1)
    await self.redis.expire(hist_key, 86400)

    if metric == "active_addresses":
        await self._compute_addr_trend(pair, hist_key)

async def _compute_addr_trend(self, pair: str, hist_key: str):
    """Compute addr_trend_pct from active_addresses rolling history."""
    try:
        raw_list = await self.redis.lrange(hist_key, 0, -1)
        if len(raw_list) < 2:
            return
        oldest = json.loads(raw_list[0])["v"]
        latest = json.loads(raw_list[-1])["v"]
        if oldest > 0:
            trend_pct = (latest - oldest) / oldest
            key = _redis_key(pair, "addr_trend_pct")
            await self.redis.set(key, json.dumps({
                "value": trend_pct,
                "ts": datetime.now(timezone.utc).isoformat(),
            }), ex=REDIS_TTL)
    except Exception as e:
        logger.warning(f"addr_trend_pct computation failed for {pair}: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_onchain_scorer.py tests/collector/ -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite for bug fix regression check**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=30`
Expected: All PASS

- [ ] **Step 6: Commit bug fix batch (Tasks 1-3)**

```
fix(collector): WS ping keepalive, order flow preloading, addr_trend_pct, snapshot log level

Bug 1.1: Add ping_interval=20 to websockets.connect() in ws_client._run_loop
to prevent silent connection drops after ~5min of inactivity.

Bug 1.2/1.3: Seed app.state.order_flow from last OrderFlowSnapshot per pair
on startup so first OI delta is meaningful. NULL-safe: skips None fields.

Bug 1.4: Change OrderFlowSnapshot DB write failure from logger.debug to
logger.warning so production failures are visible.

Bug 1.5: Compute addr_trend_pct from active_addresses rolling Redis history.
Gives BTC 4/5 on-chain metrics instead of 3/5.
```

---

## Task 4: Liquidation Redis Persistence

Reliability fix 2.2. Persist liquidation events to Redis so they survive restarts.

**Files:**
- Modify: `backend/app/collector/liquidation.py`
- Modify: `backend/app/main.py` (pass redis to collector)
- Test: `backend/tests/collector/test_liquidation_collector.py`

- [ ] **Step 1: Write failing tests for Redis persistence**

In `backend/tests/collector/test_liquidation_collector.py`, add:

```python
import json
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_events_persisted_to_redis():
    mock_client = AsyncMock()
    mock_client.get_liquidation_orders.return_value = [
        {"bkPx": "50000", "sz": "100", "side": "buy", "ts": "0"},
    ]
    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[])

    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"], redis=mock_redis)
    await collector._poll()

    mock_redis.rpush.assert_called()
    call_args = mock_redis.rpush.call_args
    assert call_args[0][0] == "liq_events:BTC-USDT-SWAP"
    event = json.loads(call_args[0][1])
    assert event["price"] == 50000.0


@pytest.mark.asyncio
async def test_events_reloaded_from_redis_on_init():
    mock_client = AsyncMock()
    now = datetime.now(timezone.utc)
    stored = json.dumps({
        "price": 49000.0, "volume": 200.0,
        "timestamp": now.isoformat(), "side": "sell",
    })
    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[stored])

    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"], redis=mock_redis)
    await collector.load_from_redis()

    assert len(collector.events["BTC-USDT-SWAP"]) == 1
    assert collector.events["BTC-USDT-SWAP"][0]["price"] == 49000.0


@pytest.mark.asyncio
async def test_old_events_pruned_from_redis():
    mock_client = AsyncMock()
    mock_client.get_liquidation_orders.return_value = []
    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.delete = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[])

    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"], redis=mock_redis)

    old_event = {
        "price": 48000.0, "volume": 50.0,
        "timestamp": datetime.now(timezone.utc) - timedelta(hours=25),
        "side": "buy",
    }
    collector._events["BTC-USDT-SWAP"].append(old_event)
    await collector._poll()

    assert len(collector.events["BTC-USDT-SWAP"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_liquidation_collector.py::test_events_persisted_to_redis tests/collector/test_liquidation_collector.py::test_events_reloaded_from_redis_on_init tests/collector/test_liquidation_collector.py::test_old_events_pruned_from_redis -v`
Expected: FAIL — constructor doesn't accept `redis` param, `load_from_redis` doesn't exist

- [ ] **Step 3: Implement Redis persistence in liquidation.py**

Replace `backend/app/collector/liquidation.py`:

```python
"""Polls OKX liquidation endpoint every 5 minutes, maintains rolling 24h window."""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 300  # 5 minutes
WINDOW_HOURS = 24


class LiquidationCollector:
    def __init__(self, okx_client, pairs: list[str], redis=None):
        self._client = okx_client
        self._pairs = pairs
        self._events: dict[str, list[dict]] = {p: [] for p in pairs}
        self._redis = redis
        self._task = None
        self._last_poll_ts = None

    @property
    def events(self) -> dict[str, list[dict]]:
        return self._events

    async def load_from_redis(self):
        """Reload events from Redis on startup."""
        if not self._redis:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        for pair in self._pairs:
            try:
                raw_list = await self._redis.lrange(f"liq_events:{pair}", 0, -1)
                for raw in raw_list:
                    event = json.loads(raw)
                    event["timestamp"] = datetime.fromisoformat(event["timestamp"])
                    if event["timestamp"] > cutoff:
                        self._events[pair].append(event)
                logger.info("Loaded %d liquidation events for %s from Redis", len(self._events[pair]), pair)
            except Exception as e:
                logger.warning("Failed to load liquidation events for %s: %s", pair, e)

    async def start(self):
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _poll_loop(self):
        while True:
            try:
                await self._poll()
            except Exception as e:
                logger.warning("Liquidation poll error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _poll(self):
        self._last_poll_ts = time.time()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        for pair in self._pairs:
            try:
                raw = await self._client.get_liquidation_orders(pair)
                if raw:
                    for item in raw:
                        event = {
                            "price": float(item.get("bkPx", 0)),
                            "volume": float(item.get("sz", 0)),
                            "timestamp": datetime.now(timezone.utc),
                            "side": item.get("side", ""),
                        }
                        self._events[pair].append(event)
                        await self._persist_event(pair, event)
            except Exception as e:
                logger.debug("Liquidation poll for %s failed: %s", pair, e)
            finally:
                self._events[pair] = [
                    e for e in self._events[pair] if e["timestamp"] > cutoff
                ]

    async def _persist_event(self, pair: str, event: dict):
        if not self._redis:
            return
        try:
            data = {
                "price": event["price"],
                "volume": event["volume"],
                "timestamp": event["timestamp"].isoformat(),
                "side": event["side"],
            }
            await self._redis.rpush(f"liq_events:{pair}", json.dumps(data))
            await self._redis.expire(f"liq_events:{pair}", 86400)
        except Exception as e:
            logger.debug("Failed to persist liquidation event: %s", e)
```

- [ ] **Step 4: Update main.py to pass redis to LiquidationCollector**

In the lifespan function where `LiquidationCollector` is created (~line 1346), add `redis=app.state.redis`:

```python
# OLD
liq_collector = LiquidationCollector(okx_client, settings.pairs)
# NEW
liq_collector = LiquidationCollector(okx_client, settings.pairs, redis=app.state.redis)
await liq_collector.load_from_redis()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_liquidation_collector.py -v`
Expected: All PASS

---

## Task 5: Data Freshness Module + Watchdog

Reliability fix 2.1. Shared freshness computation used by both the watchdog and the health endpoint.

**Requires:** Task 4 completed (for `LiquidationCollector._last_poll_ts`).

**Files:**
- Create: `backend/app/collector/freshness.py`
- Create: `backend/app/collector/watchdog.py`
- Modify: `backend/app/main.py` (start watchdog in lifespan)
- Test: `backend/tests/collector/test_freshness.py`
- Test: `backend/tests/collector/test_watchdog.py`

- [ ] **Step 1: Write failing test for compute_freshness**

Create `backend/tests/collector/test_freshness.py`:

```python
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_candle_stale_when_old():
    from app.collector.freshness import compute_freshness

    old_ts = time.time() - 2400  # 40 min ago
    candle_json = json.dumps({"timestamp": old_ts})

    mock_redis = AsyncMock()
    mock_redis.lindex = AsyncMock(return_value=candle_json)
    mock_redis.exists = AsyncMock(return_value=1)

    app_state = MagicMock()
    app_state.redis = mock_redis
    app_state.settings = MagicMock()
    app_state.settings.pairs = ["BTC-USDT-SWAP"]
    app_state.settings.timeframes = ["15m"]
    app_state.order_flow = {"BTC-USDT-SWAP": {"_last_updated": time.time()}}
    app_state.liquidation_collector = MagicMock()
    app_state.liquidation_collector._last_poll_ts = time.time()

    result = await compute_freshness(app_state)

    btc_candle = result["candles"].get("BTC-USDT-SWAP:15m", {})
    assert btc_candle.get("stale") is True


@pytest.mark.asyncio
async def test_all_fresh():
    from app.collector.freshness import compute_freshness

    now = time.time()
    candle_json = json.dumps({"timestamp": now - 60})

    mock_redis = AsyncMock()
    mock_redis.lindex = AsyncMock(return_value=candle_json)
    mock_redis.exists = AsyncMock(return_value=1)

    app_state = MagicMock()
    app_state.redis = mock_redis
    app_state.settings = MagicMock()
    app_state.settings.pairs = ["BTC-USDT-SWAP"]
    app_state.settings.timeframes = ["15m"]
    app_state.order_flow = {"BTC-USDT-SWAP": {"_last_updated": now}}
    app_state.liquidation_collector = MagicMock()
    app_state.liquidation_collector._last_poll_ts = now

    result = await compute_freshness(app_state)

    btc_candle = result["candles"].get("BTC-USDT-SWAP:15m", {})
    assert btc_candle.get("stale") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_freshness.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement freshness.py**

Create `backend/app/collector/freshness.py`:

```python
"""Shared data freshness computation for watchdog and health endpoint."""

import json
import logging
import time

logger = logging.getLogger(__name__)

TIMEFRAME_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1D": 86400}
ORDER_FLOW_MAX_AGE = 600       # 10 minutes
ONCHAIN_MAX_AGE = 900          # 15 minutes
LIQUIDATION_MAX_AGE = 600      # 10 minutes


async def compute_freshness(app_state) -> dict:
    """Check staleness of all data sources. Returns structured freshness report."""
    redis = app_state.redis
    pairs = app_state.settings.pairs
    timeframes = getattr(app_state.settings, "timeframes", ["15m"])
    now = time.time()

    result = {"candles": {}, "order_flow": {}, "onchain": {}, "liquidation": {}}

    # candle freshness
    for pair in pairs:
        for tf in timeframes:
            key = f"candles:{pair}:{tf}"
            max_age = TIMEFRAME_SECONDS.get(tf, 900) * 2
            age = await _redis_list_age(redis, key, now)
            result["candles"][f"{pair}:{tf}"] = {
                "seconds_ago": age,
                "stale": age is None or age > max_age,
            }

    # order flow freshness
    for pair in pairs:
        flow = app_state.order_flow.get(pair, {})
        updated = flow.get("_last_updated")
        age = (now - updated) if updated else None
        result["order_flow"][pair] = {
            "seconds_ago": round(age) if age is not None else None,
            "stale": age is None or age > ORDER_FLOW_MAX_AGE,
        }

    # on-chain freshness
    onchain_metrics = ["exchange_netflow", "active_addresses"]
    for pair in pairs:
        present = 0
        for metric in onchain_metrics:
            exists = await redis.exists(f"onchain:{pair}:{metric}")
            if exists:
                present += 1
        result["onchain"][pair] = {
            "metrics_present": present,
            "metrics_total": len(onchain_metrics),
            "stale": present == 0,
        }

    # liquidation freshness
    liq = getattr(app_state, "liquidation_collector", None)
    if liq:
        poll_ts = getattr(liq, "_last_poll_ts", None)
        age = (now - poll_ts) if poll_ts else None
        result["liquidation"] = {
            "seconds_ago": round(age) if age is not None else None,
            "stale": age is None or age > LIQUIDATION_MAX_AGE,
        }

    return result


async def _redis_list_age(redis, key: str, now: float) -> int | None:
    """Seconds since the last entry in a Redis list."""
    try:
        raw = await redis.lindex(key, -1)
        if not raw:
            return None
        data = json.loads(raw)
        ts = data.get("timestamp")
        if ts is None:
            return None
        if isinstance(ts, str):
            from datetime import datetime
            ts = datetime.fromisoformat(ts).timestamp()
        return max(0, round(now - float(ts)))
    except Exception:
        return None
```

- [ ] **Step 4: Run freshness tests**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_freshness.py -v`
Expected: PASS

- [ ] **Step 5: Write watchdog test**

Create `backend/tests/collector/test_watchdog.py`:

```python
import logging
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_watchdog_logs_warning_on_stale_data():
    from app.collector.watchdog import _check_once

    stale_result = {
        "candles": {"BTC-USDT-SWAP:15m": {"seconds_ago": 3000, "stale": True}},
        "order_flow": {},
        "onchain": {},
        "liquidation": {"seconds_ago": None, "stale": True},
    }

    with patch("app.collector.watchdog.compute_freshness", new_callable=AsyncMock, return_value=stale_result):
        with patch("app.collector.watchdog.logger") as mock_logger:
            app_state = MagicMock()
            await _check_once(app_state)
            mock_logger.warning.assert_called()


@pytest.mark.asyncio
async def test_watchdog_silent_when_fresh():
    from app.collector.watchdog import _check_once

    fresh_result = {
        "candles": {"BTC-USDT-SWAP:15m": {"seconds_ago": 60, "stale": False}},
        "order_flow": {"BTC-USDT-SWAP": {"seconds_ago": 30, "stale": False}},
        "onchain": {"BTC-USDT-SWAP": {"metrics_present": 2, "stale": False}},
        "liquidation": {"seconds_ago": 120, "stale": False},
    }

    with patch("app.collector.watchdog.compute_freshness", new_callable=AsyncMock, return_value=fresh_result):
        with patch("app.collector.watchdog.logger") as mock_logger:
            app_state = MagicMock()
            await _check_once(app_state)
            mock_logger.warning.assert_not_called()
```

- [ ] **Step 6: Implement watchdog.py**

Create `backend/app/collector/watchdog.py`:

```python
"""Background data freshness watchdog — logs warnings when sources go stale."""

import asyncio
import logging

from app.collector.freshness import compute_freshness

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30


async def _check_once(app_state):
    report = await compute_freshness(app_state)

    for key, info in report.get("candles", {}).items():
        if info.get("stale"):
            logger.warning("Candle data stale: %s (age=%s)", key, info.get("seconds_ago"))

    for pair, info in report.get("order_flow", {}).items():
        if info.get("stale"):
            logger.warning("Order flow stale: %s (age=%s)", pair, info.get("seconds_ago"))

    for pair, info in report.get("onchain", {}).items():
        if info.get("stale"):
            logger.warning("On-chain data stale: %s (present=%s/%s)", pair, info.get("metrics_present"), info.get("metrics_total"))

    liq = report.get("liquidation", {})
    if isinstance(liq, dict) and liq.get("stale"):
        logger.warning("Liquidation data stale (age=%s)", liq.get("seconds_ago"))


async def run_watchdog(app_state):
    """Background loop checking data freshness every 30 seconds."""
    while True:
        try:
            await _check_once(app_state)
        except Exception as e:
            logger.error("Watchdog check failed: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)
```

- [ ] **Step 7: Run watchdog tests**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_watchdog.py -v`
Expected: PASS

- [ ] **Step 8: Wire watchdog into main.py lifespan**

In `backend/app/main.py`, in the lifespan function after other background tasks are started, add:

```python
from app.collector.watchdog import run_watchdog
watchdog_task = asyncio.create_task(run_watchdog(app.state))
```

And in the shutdown section:
```python
watchdog_task.cancel()
```

- [ ] **Step 9: Add `_last_updated` to order flow updates**

Note: `_last_poll_ts` was already added to LiquidationCollector in Task 4.

In `backend/app/main.py`, in `handle_funding_rate`, `handle_open_interest`, and `handle_long_short_data`, add after `flow = app.state.order_flow.setdefault(...)`:
```python
flow["_last_updated"] = time.time()
```

- [ ] **Step 10: Wire compute_freshness into health endpoint**

In `backend/app/api/system.py`, replace the ad-hoc `_get_freshness()` helper and its usage in `system_health()` with a call to the shared `compute_freshness()`:

```python
from app.collector.freshness import compute_freshness

# In system_health(), replace the ad-hoc freshness section with:
freshness_report = await compute_freshness(request.app.state)

# Then build the response freshness dict from the report:
# Map candles → technicals_seconds_ago, order_flow → order_flow_seconds_ago, etc.
```

Remove the now-unused `_get_freshness()` function. The health endpoint response shape should remain the same for frontend compatibility — only the internal implementation changes.

- [ ] **Step 11: Run all tests**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/ tests/api/ -v`
Expected: All PASS

- [ ] **Step 12: Commit reliability batch (Tasks 4-5)**

```
feat(collector): liquidation Redis persistence and data freshness watchdog

Liquidation events survive server restarts via RPUSH to liq_events:{pair}
with 24h expiry. load_from_redis() rehydrates on startup.

Shared compute_freshness() checks staleness of candles, order flow,
on-chain, and liquidation sources. Watchdog background task (30s) logs
warnings when thresholds exceeded. Health endpoint now uses shared
freshness module instead of ad-hoc logic.
```

---

## Task 6: CVD Collection via OKX Trades Channel

New data source 3.1 part 1. Subscribe to OKX trades channel, parse trade messages, accumulate CVD in `app.state.cvd`.

**Files:**
- Modify: `backend/app/collector/ws_client.py` (add trades subscription + parser + callback)
- Modify: `backend/app/main.py` (add `handle_trade` callback, init `app.state.cvd`)
- Test: `backend/tests/collector/test_ws_client.py` (parse_trade_message tests)
- Create: `backend/tests/collector/test_cvd.py` (CVD accumulation tests)

- [ ] **Step 1: Write failing test for parse_trade_message**

In `backend/tests/collector/test_ws_client.py`, add:

```python
from app.collector.ws_client import parse_trade_message


def test_parse_trade_message_buy():
    raw = {
        "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
        "data": [{"px": "67000.5", "sz": "10.5", "side": "buy", "ts": "1709042400000"}],
    }
    result = parse_trade_message(raw)
    assert result is not None
    assert result["pair"] == "BTC-USDT-SWAP"
    assert result["size"] == 10.5
    assert result["side"] == "buy"
    assert result["price"] == 67000.5


def test_parse_trade_message_sell():
    raw = {
        "arg": {"channel": "trades", "instId": "ETH-USDT-SWAP"},
        "data": [{"px": "3500.0", "sz": "50.0", "side": "sell", "ts": "1709042400000"}],
    }
    result = parse_trade_message(raw)
    assert result["side"] == "sell"
    assert result["size"] == 50.0


def test_parse_trade_message_invalid():
    assert parse_trade_message({"arg": {}, "data": []}) is None
    assert parse_trade_message({"arg": {"channel": "funding-rate"}, "data": [{}]}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_ws_client.py::test_parse_trade_message_buy tests/collector/test_ws_client.py::test_parse_trade_message_sell tests/collector/test_ws_client.py::test_parse_trade_message_invalid -v`
Expected: FAIL — `parse_trade_message` not found

- [ ] **Step 3: Implement parse_trade_message in ws_client.py**

In `backend/app/collector/ws_client.py`, after `parse_open_interest_message` (~line 107), add:

```python
def parse_trade_message(msg: dict) -> dict | None:
    """Parse an OKX trades channel message."""
    arg = msg.get("arg")
    data = msg.get("data")
    if not arg or not data:
        return None

    if arg.get("channel") != "trades":
        return None

    row = data[0]
    size = _parse_float(row.get("sz"))
    price = _parse_float(row.get("px"))
    if size is None or price is None:
        return None

    return {
        "pair": arg["instId"],
        "price": price,
        "size": size,
        "side": row.get("side", ""),
        "timestamp": datetime.fromtimestamp(int(row["ts"]) / 1000, tz=timezone.utc),
    }
```

- [ ] **Step 4: Run parse tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_ws_client.py::test_parse_trade_message_buy tests/collector/test_ws_client.py::test_parse_trade_message_sell tests/collector/test_ws_client.py::test_parse_trade_message_invalid -v`
Expected: PASS

- [ ] **Step 5: Write CVD accumulation test**

Create `backend/tests/collector/test_cvd.py`:

```python
import time
import pytest


def test_cvd_accumulates_buys():
    """Buy trades should increase candle_delta."""
    cvd = {"cumulative": 0.0, "candle_delta": 0.0, "_last_updated": 0}
    from app.main import _update_cvd
    _update_cvd(cvd, size=10.0, side="buy")
    assert cvd["candle_delta"] == 10.0
    assert cvd["cumulative"] == 10.0


def test_cvd_accumulates_sells():
    """Sell trades should decrease candle_delta."""
    cvd = {"cumulative": 0.0, "candle_delta": 0.0, "_last_updated": 0}
    from app.main import _update_cvd
    _update_cvd(cvd, size=5.0, side="sell")
    assert cvd["candle_delta"] == -5.0
    assert cvd["cumulative"] == -5.0


def test_cvd_multiple_trades():
    """Multiple trades accumulate correctly."""
    cvd = {"cumulative": 0.0, "candle_delta": 0.0, "_last_updated": 0}
    from app.main import _update_cvd
    _update_cvd(cvd, size=10.0, side="buy")
    _update_cvd(cvd, size=3.0, side="sell")
    _update_cvd(cvd, size=7.0, side="buy")
    assert cvd["candle_delta"] == 14.0  # 10 - 3 + 7
    assert cvd["cumulative"] == 14.0
```

- [ ] **Step 6: Implement CVD state management in main.py**

In `backend/app/main.py`, add the CVD helper and handler:

```python
import time

def _update_cvd(cvd: dict, size: float, side: str):
    """Update CVD accumulator with a single trade."""
    delta = size if side == "buy" else -size
    cvd["cumulative"] += delta
    cvd["candle_delta"] += delta
    cvd["_last_updated"] = time.time()
```

Add the handler function:

```python
async def handle_trade(app: FastAPI, data: dict):
    """Handle incoming trade from OKX trades channel."""
    pair = data["pair"]
    cvd = app.state.cvd.setdefault(pair, {
        "cumulative": 0.0, "candle_delta": 0.0, "_last_updated": 0,
    })
    _update_cvd(cvd, data["size"], data["side"])
```

In lifespan, initialize:
```python
app.state.cvd = {}
```

- [ ] **Step 7: Add trades channel to ws_client.py**

In `_build_public_args` (~line 135), add the trades channel:

```python
def _build_public_args(self) -> list[dict]:
    args = []
    for pair in self.pairs:
        args.append({"channel": "funding-rate", "instId": pair})
        args.append({"channel": "open-interest", "instId": pair})
        args.append({"channel": "trades", "instId": pair})
    return args
```

Add `on_trade` callback to the constructor:

```python
def __init__(
    self,
    pairs: list[str],
    timeframes: list[str],
    on_candle: Callable[[dict], Coroutine] | None = None,
    on_funding_rate: Callable[[dict], Coroutine] | None = None,
    on_open_interest: Callable[[dict], Coroutine] | None = None,
    on_trade: Callable[[dict], Coroutine] | None = None,
):
    # ... existing ...
    self.on_trade = on_trade
```

In `_listen`, after the OI block (~line 188), add:

```python
trade = parse_trade_message(msg)
if trade and self.on_trade:
    await self.on_trade(trade)
    continue
```

- [ ] **Step 8: Wire callback in main.py lifespan**

In the `OKXWebSocketClient` construction, add:

```python
on_trade=lambda d: handle_trade(app, d),
```

- [ ] **Step 9: Run all CVD tests**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_cvd.py tests/collector/test_ws_client.py -v`
Expected: All PASS

---

## Task 7: CVD Scoring Integration

New data source 3.1 part 2. Add CVD component to `compute_order_flow_score`, rebalance max_scores, implement dynamic confidence.

**Files:**
- Modify: `backend/app/engine/constants.py:30-39`
- Modify: `backend/app/engine/traditional.py:371-465`
- Test: `backend/tests/engine/test_traditional.py`

- [ ] **Step 1: Write failing tests for CVD scoring**

In `backend/tests/engine/test_traditional.py`, add:

```python
class TestCVDScoring:
    def test_positive_cvd_scores_positive(self):
        metrics = {"cvd_delta": 500.0, "avg_candle_volume": 1000.0}
        result = compute_order_flow_score(metrics)
        assert result["score"] > 0
        assert result["details"]["cvd_score"] > 0

    def test_negative_cvd_scores_negative(self):
        metrics = {"cvd_delta": -500.0, "avg_candle_volume": 1000.0}
        result = compute_order_flow_score(metrics)
        assert result["score"] < 0
        assert result["details"]["cvd_score"] < 0

    def test_cvd_not_affected_by_contrarian_mult(self):
        metrics = {"cvd_delta": 500.0, "avg_candle_volume": 1000.0}
        regime_trending = {"trending": 0.8, "ranging": 0.1, "volatile": 0.05, "steady": 0.05}
        result_trending = compute_order_flow_score(metrics, regime=regime_trending)
        result_no_regime = compute_order_flow_score(metrics)
        # CVD score should be same regardless of regime
        assert result_trending["details"]["cvd_score"] == result_no_regime["details"]["cvd_score"]

    def test_cvd_max_bounded_to_20(self):
        metrics = {"cvd_delta": 99999.0, "avg_candle_volume": 1.0}
        result = compute_order_flow_score(metrics)
        assert abs(result["details"]["cvd_score"]) <= 20.1  # rounding tolerance

    def test_cvd_absent_scores_zero(self):
        metrics = {"funding_rate": 0.001}
        result = compute_order_flow_score(metrics)
        assert result["details"]["cvd_score"] == 0.0

    def test_max_scores_rebalanced(self):
        """Total max scores should now be 100 (30+20+30+20)."""
        from app.engine.constants import ORDER_FLOW
        total = sum(ORDER_FLOW["max_scores"].values())
        assert total == 100


class TestDynamicConfidence:
    def test_three_legacy_sources_full_confidence(self):
        metrics = {"funding_rate": 0.001, "open_interest_change_pct": 0.05,
                   "long_short_ratio": 1.5, "price_direction": 1}
        result = compute_order_flow_score(metrics)
        assert result["confidence"] == 1.0

    def test_three_legacy_plus_cvd_full_confidence(self):
        metrics = {"funding_rate": 0.001, "open_interest_change_pct": 0.05,
                   "long_short_ratio": 1.5, "price_direction": 1,
                   "cvd_delta": 100.0, "avg_candle_volume": 1000.0}
        result = compute_order_flow_score(metrics)
        assert result["confidence"] == 1.0

    def test_cvd_unavailable_no_regression(self):
        """When CVD is absent, confidence should be same as pre-CVD (3/3=1.0)."""
        metrics = {"funding_rate": 0.001, "open_interest_change_pct": 0.05,
                   "long_short_ratio": 1.5, "price_direction": 1}
        result = compute_order_flow_score(metrics)
        assert result["confidence"] == 1.0  # 3 present / 3 available = 1.0

    def test_only_funding_partial_confidence(self):
        """With only funding present, confidence = 1/3 (not 1/1)."""
        metrics = {"funding_rate": 0.001}
        result = compute_order_flow_score(metrics)
        assert abs(result["confidence"] - 1 / 3) < 0.01

    def test_sparse_data_does_not_inflate_confidence(self):
        """Confidence must not reach 1.0 when only one source has data."""
        metrics = {"funding_rate": 0.001}
        result = compute_order_flow_score(metrics)
        assert result["confidence"] < 0.5  # 1/3 ≈ 0.33

    def test_cvd_present_raises_denominator(self):
        """When CVD flows, denominator is 4 not 3."""
        metrics = {"funding_rate": 0.001, "cvd_delta": 100.0, "avg_candle_volume": 1000.0}
        result = compute_order_flow_score(metrics)
        # 2 inputs present (funding + cvd) / 4 sources available = 0.5
        assert abs(result["confidence"] - 0.5) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestCVDScoring tests/engine/test_traditional.py::TestDynamicConfidence -v`
Expected: FAIL — no `cvd_score` in details, no CVD constants

- [ ] **Step 3: Update constants.py**

In `backend/app/engine/constants.py`, update the ORDER_FLOW dict (lines 30-39):

```python
ORDER_FLOW = {
    "max_scores": {"funding": 30, "oi": 20, "ls_ratio": 30, "cvd": 20},
    "sigmoid_steepnesses": {"funding": 400, "oi": 20, "ls_ratio": 6, "cvd": 3},
    "trending_floor": 0.3,
    "recent_window": 3,
    "baseline_window": 7,
    "roc_threshold": 0.0005,
    "roc_steepness": 8000,
    "ls_roc_scale": 0.003,
}
```

Also add CVD parameter descriptions (after `ls_ratio_steepness` in PARAMETER_DESCRIPTIONS):

```python
"cvd_max": {
    "description": "Maximum score contribution from cumulative volume delta",
    "pipeline_stage": "Order Flow Scoring",
    "range": "10-30",
},
"cvd_steepness": {
    "description": "Sigmoid steepness for CVD delta scoring. Higher = more sensitive to volume imbalance",
    "pipeline_stage": "Order Flow Scoring",
    "range": "1-8",
},
```

- [ ] **Step 4: Update compute_order_flow_score in traditional.py**

In `backend/app/engine/traditional.py`, update the constants import section (~line 344) to add:

```python
CVD_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["cvd"]
```

Then update `compute_order_flow_score` (~line 371). After the ls_score computation (line 434), add the CVD component:

```python
    # CVD — directional, NOT affected by contrarian or regime (max +/-20)
    cvd_delta = metrics.get("cvd_delta")
    avg_vol = metrics.get("avg_candle_volume", 0)
    if cvd_delta is not None and avg_vol > 0:
        cvd_normalized = cvd_delta / avg_vol
        cvd_score = sigmoid_score(cvd_normalized, center=0, steepness=CVD_STEEPNESS) * 20
    else:
        cvd_score = 0.0
```

Update the total (line 436):
```python
    total = funding_score + oi_score + ls_score + cvd_score
    score = max(min(round(total), 100), -100)
```

Add `cvd_score` to details dict:
```python
        "cvd_score": round(cvd_score, 1),
```

Replace the confidence calculation (lines 457-463) with dynamic denominator:
```python
    # dynamic confidence: inputs_present / sources_available
    # Legacy 3 sources (funding, OI, L/S) are always counted as available.
    # CVD only counted when data is flowing. This prevents confidence inflation
    # when sparse data arrives (e.g., only funding → 1/3 not 1/1).
    inputs_present = sum([
        funding != 0.0,
        oi_change != 0.0 and price_dir != 0,
        ls != 1.0,
        cvd_delta is not None and avg_vol > 0 and cvd_delta != 0.0,
    ])
    sources_available = 3 + (1 if cvd_delta is not None else 0)
    flow_confidence = round(inputs_present / max(sources_available, 1), 4)
```

Also update the funding_score max from 35 to 30, and ls_score max from 35 to 30:

```python
    # Funding rate — contrarian (max +/-30)
    funding_score = sigmoid_score(-funding, center=0, steepness=FUNDING_STEEPNESS) * 30 * final_mult

    # OI change — direction-aware (max +/-20), NOT affected by regime/RoC
    # (unchanged)

    # L/S ratio — contrarian (max +/-30)
    ls_score = sigmoid_score(1.0 - ls, center=0, steepness=LS_STEEPNESS) * 30 * final_mult
```

- [ ] **Step 5: Pre-check — run existing order flow tests with ONLY the max_scores change**

Before adding CVD scoring code, temporarily apply only the max_scores rebalance (funding 35→30, ls 35→30) and run:
Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`

If any tests fail due to the score magnitude reduction (~14%), fix those test assertions first (they should use directional checks like `> 0` not magnitude thresholds). This prevents discovering breakage after all CVD code is interleaved.

- [ ] **Step 6: Run full test suite with CVD scoring**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`
Expected: All PASS (new CVD tests + existing tests including TestOrderFlowBounds, TestOrderFlowContinuity)

---

## Task 8: CVD Persistence (Migration + Snapshot)

New data source 3.1 part 3. Add `cvd_delta` column to `OrderFlowSnapshot` and save it in the pipeline.

**Files:**
- Modify: `backend/app/db/models.py:222-237`
- Modify: `backend/app/main.py` (snapshot creation + candle_delta reset)
- New Alembic migration

- [ ] **Step 1: Add cvd_delta column to OrderFlowSnapshot model**

In `backend/app/db/models.py`, add after `long_short_ratio` (~line 235):

```python
    cvd_delta: Mapped[float | None] = mapped_column(Float)
```

- [ ] **Step 2: Create Alembic migration**

Run: `docker exec krypton-api-1 alembic revision --autogenerate -m "add cvd_delta to order_flow_snapshots"`
Then verify the generated migration adds the column.

- [ ] **Step 3: Run migration**

Run: `docker exec krypton-api-1 alembic upgrade head`
Expected: Migration applies successfully

- [ ] **Step 4: Update run_pipeline to inject CVD and snapshot it**

In `backend/app/main.py`, in `run_pipeline`, the flow is:
1. `flow_metrics` is built from `app.state.order_flow[pair]` (~line 410)
2. `compute_order_flow_score(flow_metrics, ...)` is called (~line 417)
3. `OrderFlowSnapshot(...)` is created (~line 429)

Insert CVD injection BETWEEN step 1 and step 2 (~line 415).

**Important:** Read and reset `candle_delta` atomically (adjacent, no awaits between) to minimize the race window where trades for the next candle could arrive and then be wiped by the reset. Python's GIL protects dict mutations within a single bytecode operation, and there are no `await` points between read and reset, so this is safe. Trades arriving during the subsequent `await session.flush()` will correctly accumulate into the next candle's delta.

```python
# inject CVD into flow_metrics before scoring — read+reset adjacent
cvd_state = app.state.cvd.get(pair) if hasattr(app.state, "cvd") else None
cvd_delta_val = None
if cvd_state:
    cvd_delta_val = cvd_state["candle_delta"]
    cvd_state["candle_delta"] = 0.0  # reset immediately after read, before any awaits
    flow_metrics["cvd_delta"] = cvd_delta_val
    flow_metrics["avg_candle_volume"] = float(candle.get("volume", 0))
```

Then update the OrderFlowSnapshot creation (~line 429) to include `cvd_delta`:

```python
snap = OrderFlowSnapshot(
    pair=pair,
    funding_rate=flow_metrics.get("funding_rate"),
    open_interest=flow_metrics.get("open_interest"),
    oi_change_pct=flow_metrics.get("open_interest_change_pct"),
    long_short_ratio=flow_metrics.get("long_short_ratio"),
    cvd_delta=cvd_delta_val,
)
```

- [ ] **Step 5: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=30`
Expected: All PASS

---

## Task 9: Order Book Depth Collection

New data source 3.2 part 1. Subscribe to OKX books5 channel, parse depth data, store in `app.state.order_book`.

**Files:**
- Modify: `backend/app/collector/ws_client.py` (add books5 subscription + parser + callback)
- Modify: `backend/app/main.py` (add handler, init state)
- Test: `backend/tests/collector/test_ws_client.py`
- Create: `backend/tests/collector/test_depth.py`

- [ ] **Step 1: Write failing tests for parse_books5_message**

In `backend/tests/collector/test_ws_client.py`, add:

```python
from app.collector.ws_client import parse_books5_message


def test_parse_books5_message():
    raw = {
        "arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"},
        "data": [{
            "bids": [["67000", "10", "0", "3"], ["66990", "20", "0", "5"]],
            "asks": [["67010", "15", "0", "4"], ["67020", "8", "0", "2"]],
            "ts": "1709042400000",
        }],
    }
    result = parse_books5_message(raw)
    assert result is not None
    assert result["pair"] == "BTC-USDT-SWAP"
    assert len(result["bids"]) == 2
    assert result["bids"][0] == (67000.0, 10.0)
    assert len(result["asks"]) == 2
    assert result["asks"][0] == (67010.0, 15.0)


def test_parse_books5_message_invalid():
    assert parse_books5_message({"arg": {}, "data": []}) is None
    assert parse_books5_message({"arg": {"channel": "trades"}, "data": [{}]}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_ws_client.py::test_parse_books5_message tests/collector/test_ws_client.py::test_parse_books5_message_invalid -v`
Expected: FAIL — `parse_books5_message` not found

- [ ] **Step 3: Implement parse_books5_message in ws_client.py**

In `backend/app/collector/ws_client.py`, after `parse_trade_message`, add:

```python
def parse_books5_message(msg: dict) -> dict | None:
    """Parse an OKX books5 channel message (top 5 bid/ask levels)."""
    arg = msg.get("arg")
    data = msg.get("data")
    if not arg or not data:
        return None

    if arg.get("channel") != "books5":
        return None

    row = data[0]
    raw_bids = row.get("bids", [])
    raw_asks = row.get("asks", [])
    if not raw_bids and not raw_asks:
        return None

    bids = [(_parse_float(b[0]), _parse_float(b[1])) for b in raw_bids if len(b) >= 2]
    asks = [(_parse_float(a[0]), _parse_float(a[1])) for a in raw_asks if len(a) >= 2]
    bids = [(p, s) for p, s in bids if p is not None and s is not None]
    asks = [(p, s) for p, s in asks if p is not None and s is not None]

    return {
        "pair": arg["instId"],
        "bids": bids,
        "asks": asks,
    }
```

- [ ] **Step 4: Run parse tests**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_ws_client.py::test_parse_books5_message tests/collector/test_ws_client.py::test_parse_books5_message_invalid -v`
Expected: PASS

- [ ] **Step 5: Write depth state test**

Create `backend/tests/collector/test_depth.py`:

```python
import time
import pytest


def test_depth_state_stored():
    """books5 data should be stored in app.state.order_book with correct structure."""
    from app.main import handle_depth
    from unittest.mock import MagicMock

    app = MagicMock()
    app.state.order_book = {}

    import asyncio
    asyncio.get_event_loop().run_until_complete(
        handle_depth(app, {
            "pair": "BTC-USDT-SWAP",
            "bids": [(67000.0, 10.0), (66990.0, 20.0)],
            "asks": [(67010.0, 15.0), (67020.0, 8.0)],
        })
    )

    assert "BTC-USDT-SWAP" in app.state.order_book
    assert len(app.state.order_book["BTC-USDT-SWAP"]["bids"]) == 2
    assert len(app.state.order_book["BTC-USDT-SWAP"]["asks"]) == 2
    assert "_last_updated" in app.state.order_book["BTC-USDT-SWAP"]
```

- [ ] **Step 6: Implement depth handling in main.py**

Note: No `_compute_depth_imbalance` helper — the downstream scorers (liquidation_scorer, structure) compute their own depth logic directly from raw bids/asks.

```python
async def handle_depth(app: FastAPI, data: dict):
    """Handle incoming order book depth from OKX books5 channel."""
    pair = data["pair"]
    app.state.order_book[pair] = {
        "bids": data["bids"],
        "asks": data["asks"],
        "_last_updated": time.time(),
    }
```

In lifespan, initialize:
```python
app.state.order_book = {}
```

- [ ] **Step 7: Add books5 channel to ws_client.py**

In `_build_public_args`, add:
```python
args.append({"channel": "books5", "instId": pair})
```

Add `on_depth` callback to constructor and `_listen`:

Constructor:
```python
on_depth: Callable[[dict], Coroutine] | None = None,
```

In `_listen`, after the trade block:
```python
depth = parse_books5_message(msg)
if depth and self.on_depth:
    await self.on_depth(depth)
    continue
```

Wire in lifespan:
```python
on_depth=lambda d: handle_depth(app, d),
```

- [ ] **Step 8: Run all depth tests**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_depth.py tests/collector/test_ws_client.py -v`
Expected: All PASS

---

## Task 10: Depth Scoring Integration

New data source 3.2 parts 2-3. Add depth modifier to liquidation scorer and structure level strength. Wire depth through the pipeline.

**Files:**
- Modify: `backend/app/engine/liquidation_scorer.py`
- Modify: `backend/app/engine/structure.py`
- Modify: `backend/app/main.py` (pass depth to scorers)
- Test: `backend/tests/engine/test_liquidation_scorer.py`
- Test: `backend/tests/engine/test_structure.py`

- [ ] **Step 1: Write failing tests for liquidation depth modifier**

In `backend/tests/engine/test_liquidation_scorer.py`, add:

```python
from datetime import datetime, timezone


def _make_events(price, volume, count=5):
    now = datetime.now(timezone.utc)
    return [{"price": price, "volume": volume, "timestamp": now, "side": "buy"} for _ in range(count)]


def test_depth_none_unchanged():
    events = _make_events(50200.0, 500.0)
    r1 = compute_liquidation_score(events, current_price=50000.0, atr=200.0)
    r2 = compute_liquidation_score(events, current_price=50000.0, atr=200.0, depth=None)
    assert r1["score"] == r2["score"]


def test_depth_thin_asks_amplifies_bullish_cluster():
    events = _make_events(50200.0, 500.0)  # cluster above price
    thin_asks = {
        "bids": [(49900, 100), (49800, 100)],
        "asks": [(50100, 5), (50200, 3)],  # thin asks near cluster
    }
    r_no_depth = compute_liquidation_score(events, 50000.0, 200.0)
    r_thin = compute_liquidation_score(events, 50000.0, 200.0, depth=thin_asks)
    assert abs(r_thin["score"]) >= abs(r_no_depth["score"])


def test_depth_thick_asks_dampens_bullish_cluster():
    events = _make_events(50200.0, 500.0)  # cluster above price
    thick_asks = {
        "bids": [(49900, 100), (49800, 100)],
        "asks": [(50100, 5000), (50200, 3000)],  # thick asks
    }
    r_no_depth = compute_liquidation_score(events, 50000.0, 200.0)
    r_thick = compute_liquidation_score(events, 50000.0, 200.0, depth=thick_asks)
    assert abs(r_thick["score"]) <= abs(r_no_depth["score"])


def test_depth_modifier_bounded():
    events = _make_events(50200.0, 500.0)
    extreme_depth = {
        "bids": [(49900, 1)],
        "asks": [(50100, 999999)],
    }
    result = compute_liquidation_score(events, 50000.0, 200.0, depth=extreme_depth)
    assert -100 <= result["score"] <= 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_liquidation_scorer.py::test_depth_none_unchanged tests/engine/test_liquidation_scorer.py::test_depth_thin_asks_amplifies_bullish_cluster -v`
Expected: FAIL — `depth` parameter not accepted

- [ ] **Step 3: Add depth modifier to liquidation_scorer.py**

In `backend/app/engine/liquidation_scorer.py`, update `compute_liquidation_score` signature:

```python
def compute_liquidation_score(
    events: list[dict],
    current_price: float,
    atr: float,
    depth: dict | None = None,
) -> dict:
```

Add a helper function before `compute_liquidation_score`:

```python
def _depth_modifier(cluster_center: float, current_price: float, atr: float, depth: dict | None) -> float:
    """Compute depth-based modifier for a liquidation cluster. Returns [0.7, 1.3]."""
    if not depth:
        return 1.0

    is_above = cluster_center > current_price
    levels = depth.get("asks", []) if is_above else depth.get("bids", [])

    if not levels:
        return 1.0

    # check if any levels fall within 0.5 ATR of cluster center
    nearby_vol = sum(size for price, size in levels if abs(price - cluster_center) <= 0.5 * atr)

    if nearby_vol == 0:
        return 1.0

    all_vols = [size for _, size in levels]
    avg_vol = sum(all_vols) / len(all_vols) if all_vols else 1.0

    if avg_vol <= 0:
        return 1.0

    ratio = nearby_vol / avg_vol
    if ratio < 0.5:
        modifier = 1.3  # thin = amplify
    elif ratio > 2.0:
        modifier = 0.7  # thick = dampen
    else:
        modifier = 1.0 + 0.3 * (1.0 - ratio)  # linear interpolation

    return max(0.7, min(1.3, modifier))
```

In the scoring loop inside `compute_liquidation_score`, after computing `proximity` and `density`, apply the modifier:

```python
        mod = _depth_modifier(cluster["center"], current_price, atr, depth)
        score += direction * proximity * min(density / density_norm, 1.0) * 30 * mod
```

- [ ] **Step 4: Run liquidation tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_liquidation_scorer.py -v`
Expected: All PASS

- [ ] **Step 5: Write failing tests for structure depth modulation**

In `backend/tests/engine/test_structure.py`, add:

```python
import pandas as pd
import numpy as np


def _make_simple_candles(n=50, base=100.0):
    """Create minimal candles for structure detection."""
    data = {
        "open": [base] * n,
        "high": [base + 2] * n,
        "low": [base - 2] * n,
        "close": [base] * n,
        "volume": [1000.0] * n,
    }
    return pd.DataFrame(data)


def test_depth_none_unchanged():
    from app.engine.structure import collect_structure_levels
    candles = _make_simple_candles()
    indicators = {"bb_upper": 105.0, "bb_lower": 95.0}
    r1 = collect_structure_levels(candles, indicators, atr=2.0)
    r2 = collect_structure_levels(candles, indicators, atr=2.0, depth=None)
    assert r1 == r2


def test_support_strength_amplified_by_heavy_bids():
    from app.engine.structure import collect_structure_levels
    candles = _make_simple_candles(50, base=100.0)
    indicators = {"bb_upper": 105.0, "bb_lower": 95.0}
    heavy_bids = {
        "bids": [(95.0, 5000), (94.0, 100), (93.0, 100)],
        "asks": [(105.0, 100), (106.0, 100)],
    }
    r_no_depth = collect_structure_levels(candles, indicators, atr=2.0)
    r_depth = collect_structure_levels(candles, indicators, atr=2.0, depth=heavy_bids)

    # Find bb_lower level in both results
    bb_lower_no = next((l for l in r_no_depth if l["label"] == "bb_lower"), None)
    bb_lower_d = next((l for l in r_depth if l["label"] == "bb_lower"), None)

    assert bb_lower_no is not None and bb_lower_d is not None
    assert bb_lower_d["strength"] >= bb_lower_no["strength"]
```

- [ ] **Step 6: Add depth modulation to structure.py**

In `backend/app/engine/structure.py`, update `collect_structure_levels` signature:

```python
def collect_structure_levels(
    candles: pd.DataFrame,
    indicators: dict,
    atr: float,
    liquidation_clusters: list[dict] | None = None,
    depth: dict | None = None,
) -> list[dict]:
```

After building the levels list and before the final sort, add depth modulation:

```python
    # 5. Depth modulation — amplify levels near heavy bid/ask resting orders
    if depth and atr > 0:
        current_price = float(candles["close"].iloc[-1])
        all_depth_vols = [s for _, s in depth.get("bids", []) + depth.get("asks", [])]
        avg_depth_vol = sum(all_depth_vols) / len(all_depth_vols) if all_depth_vols else 0

        if avg_depth_vol > 0:
            for level in levels:
                is_support = level["price"] < current_price
                side_levels = depth.get("bids", []) if is_support else depth.get("asks", [])

                nearby_vol = sum(s for p, s in side_levels if abs(p - level["price"]) <= 0.5 * atr)

                if nearby_vol > 2 * avg_depth_vol:
                    mult = min(1.5, 1.0 + (nearby_vol / avg_depth_vol - 2) * 0.25)
                    level["strength"] = int(level["strength"] * mult)

    levels.sort(key=lambda lv: lv["price"])
    return levels
```

- [ ] **Step 7: Wire depth into pipeline (main.py)**

In `backend/app/main.py`, in `run_pipeline`:

Near the top of the function, extract depth:
```python
order_book = getattr(app.state, "order_book", {})
depth = order_book.get(pair)
```

Update the `compute_liquidation_score` call (~line 475):
```python
liq_result = compute_liquidation_score(
    events=liq_collector.events.get(pair, []),
    current_price=current_price,
    atr=liq_atr,
    depth=depth,
)
```

Update the `collect_structure_levels` call (~line 832):
```python
structure = collect_structure_levels(
    df, tech_result["indicators"], atr,
    liquidation_clusters=liq_clusters,
    depth=depth,
)
```

- [ ] **Step 8: Run all tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_liquidation_scorer.py tests/engine/test_structure.py -v`
Expected: All PASS

- [ ] **Step 9: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=30`
Expected: All PASS

- [ ] **Step 10: Commit new data sources batch (Tasks 6-10)**

```
feat(engine): add CVD and order book depth as new signal sources

CVD (Cumulative Volume Delta) from OKX trades channel:
- Subscribe to trades channel, accumulate buy-sell aggressor delta per candle
- New scoring component in compute_order_flow_score (max +/-20, directional)
- Rebalance ORDER_FLOW max_scores: funding=30, oi=20, ls=30, cvd=20
- Dynamic confidence denominator: legacy 3 always counted, CVD when flowing
- Alembic migration adds cvd_delta column to OrderFlowSnapshot
- Atomic read+reset of candle_delta to prevent race on candle boundary

Order book depth from OKX books5 channel:
- Subscribe to books5 for top 5 bid/ask levels, store in app.state.order_book
- Liquidation scorer: depth modifier [0.7, 1.3] amplifies thin-book clusters
- Structure levels: heavy bid/ask near S/R zones amplify strength up to 1.5x
- Both accept optional depth=None for backward compatibility
```
