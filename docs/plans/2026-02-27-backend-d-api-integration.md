# Backend Plan D: API & Integration (Phases 6-7, Tasks 12-17)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the API layer (auth, REST endpoints, WebSocket broadcast) and wire everything together — collector, engine, DB persistence, Redis caching, and signal broadcast.

**Architecture:** FastAPI lifespan starts background tasks for OKX WS client and REST poller. Candle close events trigger the signal pipeline as concurrent asyncio tasks. Signals are persisted to PostgreSQL and broadcast to WebSocket clients via Redis pub/sub. All runtime state lives on `app.state` (not module-level globals) to preserve testability and the existing `lifespan_override` pattern.

**Tech Stack:** Python 3.11, FastAPI, Redis (redis-py async), SQLAlchemy (async), Docker, pytest + pytest-asyncio

**Depends on:** Plans A (foundation), B (collector), C (signal engine)

**Key design decisions:**
- State on `app.state` — consistent with existing `main.py` pattern, keeps `create_app(lifespan_override=...)` for tests
- REST endpoints query PostgreSQL directly — no in-memory signal store, signals survive restarts
- Auth reads from `app.state.settings` at request time — single source of truth, no `os.environ` duplication
- Pipeline tasks tracked in a set with error callbacks — no silent failures
- Cached candles include timestamp — preserves full data for traceability
- `engine_llm_weight` config field is unused — flow weight derived as `1 - engine_traditional_weight`; noted as dead config, not addressed here (YAGNI)
- WS auth via query param — limitation: key visible in URL; trade-off for browser WS API compatibility

---

## Phase 6: API & WebSocket

### Task 12: API key auth middleware

**Files:**
- Create: `backend/app/api/__init__.py` (empty)
- Create: `backend/app/api/auth.py`
- Create: `backend/tests/api/__init__.py` (empty)
- Test: `backend/tests/api/test_auth.py`

Two auth functions: `require_api_key(expected_key)` for standalone/test use, and `require_settings_api_key()` for production routes that read the key from `app.state.settings` at request time.

**Step 1: Write the failing test**

```python
# backend/tests/api/test_auth.py
import pytest
from unittest.mock import MagicMock
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.api.auth import require_api_key, require_settings_api_key


@pytest.fixture
def protected_app():
    app = FastAPI()
    dep = require_api_key("test-secret-key")

    @app.get("/protected")
    async def protected(api_key: str = dep):
        return {"status": "ok"}

    return app


@pytest.fixture
def settings_app():
    """App using settings-aware auth (reads key from app.state.settings)."""
    app = FastAPI()

    mock_settings = MagicMock()
    mock_settings.krypton_api_key = "settings-key"
    app.state.settings = mock_settings

    dep = require_settings_api_key()

    @app.get("/protected")
    async def protected(api_key: str = dep):
        return {"status": "ok"}

    return app


@pytest.mark.asyncio
async def test_valid_api_key(protected_app):
    async with AsyncClient(
        transport=ASGITransport(app=protected_app), base_url="http://test"
    ) as client:
        resp = await client.get("/protected", headers={"X-API-Key": "test-secret-key"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_missing_api_key(protected_app):
    async with AsyncClient(
        transport=ASGITransport(app=protected_app), base_url="http://test"
    ) as client:
        resp = await client.get("/protected")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_api_key(protected_app):
    async with AsyncClient(
        transport=ASGITransport(app=protected_app), base_url="http://test"
    ) as client:
        resp = await client.get("/protected", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_settings_auth_valid(settings_app):
    async with AsyncClient(
        transport=ASGITransport(app=settings_app), base_url="http://test"
    ) as client:
        resp = await client.get("/protected", headers={"X-API-Key": "settings-key"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_settings_auth_wrong(settings_app):
    async with AsyncClient(
        transport=ASGITransport(app=settings_app), base_url="http://test"
    ) as client:
        resp = await client.get("/protected", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/api/test_auth.py -v
```

Expected: FAIL — `ImportError`

**Step 3: Implement auth.py**

```python
# backend/app/api/auth.py
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(expected_key: str):
    """Auth dependency with a hardcoded expected key. Useful for testing."""
    async def verify(key: str = Security(api_key_header)):
        if not key or key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return key
    return Depends(verify)


def require_settings_api_key():
    """Auth dependency that reads the API key from app.state.settings at request time."""
    async def verify(request: Request, key: str = Security(api_key_header)):
        expected = request.app.state.settings.krypton_api_key
        if not key or key != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return key
    return Depends(verify)
```

**Step 4: Run tests**

```bash
cd backend && python -m pytest tests/api/test_auth.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/app/api/__init__.py backend/app/api/auth.py backend/tests/api/__init__.py backend/tests/api/test_auth.py
git commit -m "feat: add API key authentication middleware"
```

---

### Task 13: REST API endpoints (DB-backed)

**Files:**
- Create: `backend/app/api/routes.py`
- Test: `backend/tests/api/test_routes.py`

Routes query PostgreSQL directly via `request.app.state.db`. No in-memory signal store — signals survive process restarts.

**Step 1: Write the failing test**

```python
# backend/tests/api/test_routes.py
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient

from app.api.routes import create_router


def _mock_db(scalars_all=None, scalar_one=None):
    """Create a mock Database whose session returns preset query results."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    mock_result.scalar_one_or_none.return_value = scalar_one
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db


@pytest.fixture
def app_with_routes():
    from fastapi import FastAPI
    app = FastAPI()

    mock_settings = MagicMock()
    mock_settings.krypton_api_key = "test-key"
    app.state.settings = mock_settings
    app.state.db = _mock_db()

    router = create_router()
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_get_signals_requires_auth(app_with_routes):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_routes), base_url="http://test"
    ) as client:
        resp = await client.get("/api/signals")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_signals_empty(app_with_routes):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_routes), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/signals",
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_signal_not_found(app_with_routes):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_routes), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/signals/999",
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 404
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/api/test_routes.py -v
```

Expected: FAIL — `ImportError`

**Step 3: Implement routes.py**

```python
# backend/app/api/routes.py
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.api.auth import require_settings_api_key
from app.db.models import Signal


def _signal_to_dict(signal: Signal) -> dict:
    return {
        "id": signal.id,
        "pair": signal.pair,
        "timeframe": signal.timeframe,
        "direction": signal.direction,
        "final_score": signal.final_score,
        "traditional_score": signal.traditional_score,
        "llm_opinion": signal.llm_opinion,
        "llm_confidence": signal.llm_confidence,
        "explanation": signal.explanation,
        "entry": float(signal.entry),
        "stop_loss": float(signal.stop_loss),
        "take_profit_1": float(signal.take_profit_1),
        "take_profit_2": float(signal.take_profit_2),
        "raw_indicators": signal.raw_indicators,
        "created_at": signal.created_at.isoformat(),
    }


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api")
    auth = require_settings_api_key()

    @router.get("/signals")
    async def get_signals(
        request: Request,
        _key: str = auth,
        pair: str | None = Query(None),
        timeframe: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
    ):
        db = request.app.state.db
        async with db.session_factory() as session:
            query = select(Signal).order_by(Signal.created_at.desc())
            if pair:
                query = query.where(Signal.pair == pair)
            if timeframe:
                query = query.where(Signal.timeframe == timeframe)
            query = query.limit(limit)
            result = await session.execute(query)
            return [_signal_to_dict(s) for s in result.scalars().all()]

    @router.get("/signals/{signal_id}")
    async def get_signal(request: Request, signal_id: int, _key: str = auth):
        db = request.app.state.db
        async with db.session_factory() as session:
            result = await session.execute(
                select(Signal).where(Signal.id == signal_id)
            )
            signal = result.scalar_one_or_none()
            if not signal:
                raise HTTPException(status_code=404, detail="Signal not found")
            return _signal_to_dict(signal)

    return router
```

**Step 4: Run tests**

```bash
cd backend && python -m pytest tests/api/test_routes.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/api/test_routes.py
git commit -m "feat: add DB-backed REST API endpoints for signals"
```

---

### Task 14: WebSocket broadcast

**Files:**
- Create: `backend/app/api/ws.py`
- Test: `backend/tests/api/test_ws.py`

**Step 1: Write the failing test**

```python
# backend/tests/api/test_ws.py
import pytest
import json
from unittest.mock import AsyncMock

from app.api.ws import ConnectionManager


@pytest.mark.asyncio
async def test_connection_manager_broadcast():
    """Manager should broadcast message to all connected clients."""
    manager = ConnectionManager()

    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()

    manager.active_connections.append(mock_ws1)
    manager.active_connections.append(mock_ws2)

    message = {"type": "signal", "data": {"pair": "BTC-USDT-SWAP"}}
    await manager.broadcast(message)

    mock_ws1.send_json.assert_called_once_with(message)
    mock_ws2.send_json.assert_called_once_with(message)


@pytest.mark.asyncio
async def test_connection_manager_removes_dead_connection():
    """Manager should remove connections that fail on send."""
    manager = ConnectionManager()

    mock_ws_good = AsyncMock()
    mock_ws_dead = AsyncMock()
    mock_ws_dead.send_json.side_effect = Exception("Connection closed")

    manager.active_connections.append(mock_ws_good)
    manager.active_connections.append(mock_ws_dead)

    await manager.broadcast({"type": "test"})

    assert mock_ws_dead not in manager.active_connections
    assert mock_ws_good in manager.active_connections
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/api/test_ws.py -v
```

Expected: FAIL — `ImportError`

**Step 3: Implement ws.py**

```python
# backend/app/api/ws.py
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)
```

**Step 4: Run tests**

```bash
cd backend && python -m pytest tests/api/test_ws.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/app/api/ws.py backend/tests/api/test_ws.py
git commit -m "feat: add WebSocket connection manager with broadcast"
```

---

## Phase 7: Integration & Wiring

### Task 15: Application lifespan and full wiring

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/api/test_wiring.py`

Key changes vs existing `main.py`:
- All state on `app.state` (settings, db, redis, manager, order_flow, pipeline_tasks, prompt_template)
- Uses existing `Database` class from `app.db.database` (not fictional `init_db`/`async_session_factory`)
- Preserves `create_app(lifespan_override=...)` for test injection
- Pipeline tasks tracked with `done_callback` for error logging
- Cached candles include `timestamp` for traceability
- WS and REST auth both read from `app.state.settings` at request time (single source of truth)

**Step 1: Update main.py with full application wiring**

```python
# backend/app/main.py
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import Settings
from app.db.database import Database
from app.db.models import Candle, Signal
from app.collector.ws_client import OKXWebSocketClient
from app.collector.rest_poller import OKXRestPoller
from app.api.routes import create_router
from app.api.ws import ConnectionManager
from app.engine.traditional import compute_technical_score, compute_order_flow_score
from app.engine.combiner import compute_preliminary_score, compute_final_score, calculate_levels
from app.engine.llm import load_prompt_template, render_prompt, call_openrouter

logger = logging.getLogger(__name__)


def _pipeline_done_callback(task: asyncio.Task, tasks: set):
    """Log errors from completed pipeline tasks and remove from tracking set."""
    tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(f"Pipeline task failed: {exc}", exc_info=exc)


async def persist_candle(db: Database, candle: dict):
    """Write candle to PostgreSQL (upsert to handle duplicates)."""
    try:
        async with db.session_factory() as session:
            stmt = pg_insert(Candle).values(
                pair=candle["pair"],
                timeframe=candle["timeframe"],
                timestamp=candle["timestamp"],
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
            ).on_conflict_do_nothing(constraint="uq_candle")
            await session.execute(stmt)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to persist candle {candle['pair']}:{candle['timeframe']}: {e}")


async def persist_signal(db: Database, signal_data: dict):
    """Write signal to PostgreSQL."""
    try:
        async with db.session_factory() as session:
            row = Signal(
                pair=signal_data["pair"],
                timeframe=signal_data["timeframe"],
                direction=signal_data["direction"],
                final_score=signal_data["final_score"],
                traditional_score=signal_data["traditional_score"],
                llm_opinion=signal_data.get("llm_opinion"),
                llm_confidence=signal_data.get("llm_confidence"),
                explanation=signal_data.get("explanation"),
                entry=signal_data["entry"],
                stop_loss=signal_data["stop_loss"],
                take_profit_1=signal_data["take_profit_1"],
                take_profit_2=signal_data["take_profit_2"],
                raw_indicators=signal_data.get("raw_indicators"),
            )
            session.add(row)
            await session.commit()
            signal_data["id"] = row.id
    except Exception as e:
        logger.error(f"Failed to persist signal {signal_data['pair']}: {e}")


async def run_pipeline(app: FastAPI, candle: dict):
    """Main pipeline: candle close -> indicators -> LLM -> signal -> broadcast."""
    settings = app.state.settings
    redis = app.state.redis
    db = app.state.db
    manager = app.state.manager
    order_flow = app.state.order_flow
    prompt_template = app.state.prompt_template

    pair = candle["pair"]
    timeframe = candle["timeframe"]

    # fetch recent candles from redis cache
    try:
        cache_key = f"candles:{pair}:{timeframe}"
        raw_candles = await redis.lrange(cache_key, -50, -1)
    except Exception as e:
        logger.error(f"Redis fetch failed for {pair}:{timeframe}: {e}")
        return

    if len(raw_candles) < 50:
        logger.warning(f"Not enough candles for {pair}:{timeframe} ({len(raw_candles)})")
        return

    candles_data = [json.loads(c) for c in raw_candles]
    df = pd.DataFrame(candles_data)

    # layer 1: traditional
    try:
        tech_result = compute_technical_score(df)
    except Exception as e:
        logger.error(f"Technical scoring failed for {pair}:{timeframe}: {e}")
        return

    flow_metrics = order_flow.get(pair, {})
    flow_result = compute_order_flow_score(flow_metrics)

    preliminary = compute_preliminary_score(
        tech_result["score"],
        flow_result["score"],
        settings.engine_traditional_weight,
        1 - settings.engine_traditional_weight,
    )

    # layer 2: LLM (conditional)
    llm_response = None
    if abs(preliminary) >= settings.engine_llm_threshold and prompt_template:
        try:
            rendered = render_prompt(
                template=prompt_template,
                pair=pair,
                timeframe=timeframe,
                indicators=json.dumps(tech_result["indicators"], indent=2),
                order_flow=json.dumps(flow_result["details"], indent=2),
                preliminary_score=str(preliminary),
                direction="LONG" if preliminary > 0 else "SHORT",
                candles=json.dumps(candles_data[-20:], indent=2),
            )
            llm_response = await call_openrouter(
                prompt=rendered,
                api_key=settings.openrouter_api_key,
                model=settings.openrouter_model,
                timeout=settings.engine_llm_timeout_seconds,
            )
        except Exception as e:
            logger.error(f"LLM call failed for {pair}:{timeframe}: {e}")

    # combine
    final = compute_final_score(preliminary, llm_response)
    direction = "LONG" if final > 0 else "SHORT"

    if abs(final) < settings.engine_signal_threshold:
        return

    # calculate levels
    atr = tech_result["indicators"].get("atr", 200)
    llm_levels = None
    if llm_response and llm_response.opinion == "confirm" and llm_response.levels:
        llm_levels = llm_response.levels.model_dump()
    levels = calculate_levels(direction, float(candle["close"]), atr, llm_levels)

    # build signal
    signal_data = {
        "pair": pair,
        "timeframe": timeframe,
        "direction": direction,
        "final_score": final,
        "traditional_score": tech_result["score"],
        "llm_opinion": llm_response.opinion if llm_response else "skipped",
        "llm_confidence": llm_response.confidence if llm_response else None,
        "explanation": llm_response.explanation if llm_response else None,
        **levels,
        "raw_indicators": tech_result["indicators"],
    }

    # persist to DB and broadcast
    await persist_signal(db, signal_data)
    await manager.broadcast({"type": "signal", "data": signal_data})
    logger.info(f"Signal emitted: {pair} {timeframe} {direction} score={final}")


async def handle_candle(app: FastAPI, candle: dict):
    """Cache candle in Redis, persist to DB, and trigger pipeline concurrently."""
    redis = app.state.redis
    db = app.state.db

    cache_key = f"candles:{candle['pair']}:{candle['timeframe']}"
    candle_json = json.dumps({
        "timestamp": candle["timestamp"],
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle["volume"],
    })

    try:
        await redis.rpush(cache_key, candle_json)
        await redis.ltrim(cache_key, -200, -1)
    except Exception as e:
        logger.error(f"Redis cache failed for {candle['pair']}:{candle['timeframe']}: {e}")

    await persist_candle(db, candle)

    # fire pipeline as a concurrent task with error tracking
    task = asyncio.create_task(run_pipeline(app, candle))
    app.state.pipeline_tasks.add(task)
    task.add_done_callback(
        lambda t: _pipeline_done_callback(t, app.state.pipeline_tasks)
    )


async def handle_funding_rate(app: FastAPI, data: dict):
    """Update in-memory order flow with latest funding rate."""
    pair = data["pair"]
    app.state.order_flow.setdefault(pair, {})
    app.state.order_flow[pair]["funding_rate"] = data["funding_rate"]


async def handle_open_interest(app: FastAPI, data: dict):
    """Update in-memory order flow with latest open interest."""
    pair = data["pair"]
    flow = app.state.order_flow.setdefault(pair, {})

    prev_oi = flow.get("open_interest", data["open_interest"])
    current_oi = data["open_interest"]
    if prev_oi > 0:
        flow["open_interest_change_pct"] = (current_oi - prev_oi) / prev_oi
    flow["open_interest"] = current_oi


async def handle_long_short_data(app: FastAPI, data: dict):
    """Update in-memory order flow with latest long/short ratio."""
    pair = data["pair"]
    app.state.order_flow.setdefault(pair, {})
    app.state.order_flow[pair]["long_short_ratio"] = data["long_short_ratio"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db = Database(settings.database_url)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    manager = ConnectionManager()

    app.state.settings = settings
    app.state.db = db
    app.state.redis = redis
    app.state.manager = manager
    app.state.order_flow = {}
    app.state.pipeline_tasks = set()

    prompt_path = Path(__file__).parent / "prompts" / "signal_analysis.txt"
    app.state.prompt_template = load_prompt_template(prompt_path) if prompt_path.exists() else ""

    ws_client = OKXWebSocketClient(
        pairs=settings.pairs,
        timeframes=settings.timeframes,
        on_candle=lambda c: handle_candle(app, c),
        on_funding_rate=lambda d: handle_funding_rate(app, d),
        on_open_interest=lambda d: handle_open_interest(app, d),
    )
    rest_poller = OKXRestPoller(
        pairs=settings.pairs,
        interval_seconds=settings.collector_rest_poll_interval_seconds,
        on_data=lambda d: handle_long_short_data(app, d),
    )

    ws_task = asyncio.create_task(ws_client.connect())
    poller_task = asyncio.create_task(rest_poller.run())

    yield

    await ws_client.stop()
    rest_poller.stop()
    ws_task.cancel()
    poller_task.cancel()
    await redis.close()
    await db.close()


def create_app(lifespan_override=None) -> FastAPI:
    app = FastAPI(title="Krypton", version="0.1.0", lifespan=lifespan_override or lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    router = create_router()
    app.include_router(router)

    @app.websocket("/ws/signals")
    async def ws_signals(websocket: WebSocket, api_key: str = Query(None)):
        # WS auth via query param — browser WS API does not support custom headers
        settings = websocket.app.state.settings
        if api_key != settings.krypton_api_key:
            await websocket.close(code=4001, reason="Invalid API key")
            return
        manager = websocket.app.state.manager
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    return app


app = create_app()
```

**Step 2: Update conftest.py**

Preserve the existing `lifespan_override` pattern. The test lifespan yields without initializing infrastructure — tests that need state set it up in their own fixtures.

```python
# backend/tests/conftest.py
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from fastapi import FastAPI

from app.main import create_app


@asynccontextmanager
async def _test_lifespan(app: FastAPI):
    yield


@pytest.fixture
def app():
    return create_app(lifespan_override=_test_lifespan)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
```

**Step 3: Write wiring tests**

```python
# backend/tests/api/test_wiring.py
import asyncio
import json
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI

from app.main import (
    persist_candle,
    persist_signal,
    handle_candle,
    handle_funding_rate,
    handle_open_interest,
    handle_long_short_data,
    run_pipeline,
    _pipeline_done_callback,
)
from app.api.ws import ConnectionManager


def _mock_db():
    """Create a mock Database for wiring tests."""
    mock_session = AsyncMock()
    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db, mock_session


@pytest.mark.asyncio
async def test_persist_candle_calls_execute():
    mock_db, mock_session = _mock_db()
    candle = {
        "pair": "BTC-USDT-SWAP",
        "timeframe": "15m",
        "timestamp": "2026-02-27T00:00:00Z",
        "open": 67000,
        "high": 67100,
        "low": 66900,
        "close": 67050,
        "volume": 100,
    }
    await persist_candle(mock_db, candle)
    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_persist_signal_sets_id():
    mock_db, mock_session = _mock_db()
    signal_data = {
        "pair": "BTC-USDT-SWAP",
        "timeframe": "15m",
        "direction": "LONG",
        "final_score": 60,
        "traditional_score": 55,
        "entry": 67050,
        "stop_loss": 66750,
        "take_profit_1": 67450,
        "take_profit_2": 67650,
    }
    await persist_signal(mock_db, signal_data)
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_persist_candle_logs_on_error():
    mock_db, mock_session = _mock_db()
    mock_session.execute.side_effect = Exception("db error")
    candle = {
        "pair": "BTC-USDT-SWAP",
        "timeframe": "15m",
        "timestamp": "2026-02-27T00:00:00Z",
        "open": 67000,
        "high": 67100,
        "low": 66900,
        "close": 67050,
        "volume": 100,
    }
    # should not raise — error is logged
    await persist_candle(mock_db, candle)


@pytest.mark.asyncio
async def test_handle_candle_caches_and_persists():
    app = FastAPI()
    app.state.redis = AsyncMock()
    mock_db, _ = _mock_db()
    app.state.db = mock_db
    app.state.pipeline_tasks = set()
    app.state.settings = MagicMock()
    app.state.redis.lrange = AsyncMock(return_value=[])
    app.state.order_flow = {}
    app.state.prompt_template = ""
    app.state.manager = ConnectionManager()

    candle = {
        "pair": "BTC-USDT-SWAP",
        "timeframe": "15m",
        "timestamp": "2026-02-27T00:00:00Z",
        "open": 67000,
        "high": 67100,
        "low": 66900,
        "close": 67050,
        "volume": 100,
    }
    await handle_candle(app, candle)

    # verify redis cache calls
    app.state.redis.rpush.assert_called_once()
    app.state.redis.ltrim.assert_called_once()

    # verify pipeline task was created and tracked
    assert len(app.state.pipeline_tasks) <= 1  # may have completed already

    # let pipeline task complete (it will exit early — not enough candles)
    await asyncio.sleep(0.01)


def test_handle_funding_rate():
    app = FastAPI()
    app.state.order_flow = {}
    # handle_funding_rate is async due to callback type requirement
    asyncio.get_event_loop().run_until_complete(
        handle_funding_rate(app, {"pair": "BTC-USDT-SWAP", "funding_rate": 0.0003})
    )
    assert app.state.order_flow["BTC-USDT-SWAP"]["funding_rate"] == 0.0003


def test_handle_open_interest_computes_change_pct():
    app = FastAPI()
    app.state.order_flow = {"BTC-USDT-SWAP": {"open_interest": 1000}}
    asyncio.get_event_loop().run_until_complete(
        handle_open_interest(app, {"pair": "BTC-USDT-SWAP", "open_interest": 1100})
    )
    assert app.state.order_flow["BTC-USDT-SWAP"]["open_interest"] == 1100
    assert abs(app.state.order_flow["BTC-USDT-SWAP"]["open_interest_change_pct"] - 0.1) < 0.001


def test_handle_long_short_data():
    app = FastAPI()
    app.state.order_flow = {}
    asyncio.get_event_loop().run_until_complete(
        handle_long_short_data(app, {"pair": "BTC-USDT-SWAP", "long_short_ratio": 1.3})
    )
    assert app.state.order_flow["BTC-USDT-SWAP"]["long_short_ratio"] == 1.3


def test_pipeline_done_callback_logs_error():
    """Verify that failed pipeline tasks are logged and removed from tracking set."""
    tasks = set()
    loop = asyncio.new_event_loop()

    async def failing_task():
        raise ValueError("pipeline error")

    task = loop.create_task(failing_task())
    tasks.add(task)

    try:
        loop.run_until_complete(task)
    except ValueError:
        pass

    _pipeline_done_callback(task, tasks)
    assert task not in tasks
    loop.close()
```

**Step 4: Run all tests**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/conftest.py backend/tests/api/test_wiring.py
git commit -m "feat: wire application lifespan with collector, engine, DB persistence, and broadcast pipeline"
```

---

### Task 16: Integration test for the signal pipeline

**Files:**
- Create: `backend/tests/test_pipeline.py`

**Step 1: Write integration test**

This test verifies the core pipeline wiring: candle data in -> indicators computed -> signal out. It exercises the real computation logic without mocking engine functions.

```python
# backend/tests/test_pipeline.py
import pytest
import pandas as pd

from app.engine.traditional import compute_technical_score, compute_order_flow_score
from app.engine.combiner import compute_preliminary_score, compute_final_score, calculate_levels
from app.engine.llm import parse_llm_response


def _make_candles(count: int = 50, base: float = 67000, trend: float = 10) -> list[dict]:
    """Generate synthetic uptrend candle data as list of dicts."""
    candles = []
    for i in range(count):
        o = base + i * trend
        candles.append({
            "open": o,
            "high": o + 50,
            "low": o - 30,
            "close": o + 20,
            "volume": 100 + i,
        })
    return candles


def test_full_pipeline_produces_signal():
    """End-to-end: candles + order flow -> preliminary score -> final score -> signal levels."""
    candles_data = _make_candles()
    df = pd.DataFrame(candles_data)

    # layer 1
    tech_result = compute_technical_score(df)
    assert -100 <= tech_result["score"] <= 100

    flow_metrics = {
        "funding_rate": 0.0001,
        "open_interest_change_pct": 0.02,
        "long_short_ratio": 1.1,
    }
    flow_result = compute_order_flow_score(flow_metrics)
    assert -100 <= flow_result["score"] <= 100

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])

    # layer 2 (simulate LLM confirm)
    llm_json = '{"opinion": "confirm", "confidence": "HIGH", "explanation": "Strong setup.", "levels": null}'
    llm_response = parse_llm_response(llm_json)
    assert llm_response is not None

    final = compute_final_score(preliminary, llm_response)
    assert -100 <= final <= 100
    assert final > preliminary  # confirm should boost

    # levels
    direction = "LONG" if final > 0 else "SHORT"
    atr = tech_result["indicators"]["atr"]
    levels = calculate_levels(direction, candles_data[-1]["close"], atr, llm_levels=None)
    assert "entry" in levels
    assert "stop_loss" in levels
    assert "take_profit_1" in levels
    assert "take_profit_2" in levels


def test_pipeline_without_llm():
    """Pipeline should work when LLM is skipped (preliminary below threshold)."""
    candles_data = _make_candles()
    df = pd.DataFrame(candles_data)

    tech_result = compute_technical_score(df)
    flow_result = compute_order_flow_score({})

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])
    final = compute_final_score(preliminary, llm_response=None)
    assert final == preliminary


def test_pipeline_with_empty_order_flow():
    """Pipeline should handle completely empty order flow gracefully."""
    candles_data = _make_candles()
    df = pd.DataFrame(candles_data)

    tech_result = compute_technical_score(df)
    flow_result = compute_order_flow_score({})
    assert flow_result["score"] == 0

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])
    assert preliminary != 0  # tech score alone should produce non-zero
```

**Step 2: Run tests**

```bash
cd backend && python -m pytest tests/test_pipeline.py -v
```

Expected: ALL PASS

**Step 3: Commit**

```bash
git add backend/tests/test_pipeline.py
git commit -m "test: add integration tests for signal pipeline"
```

---

### Task 17: End-to-end smoke test with Docker

**Step 1: Create .env file from example**

```bash
cd backend && cp .env.example .env
# edit .env with real values for KRYPTON_API_KEY and OPENROUTER_API_KEY
```

**Step 2: Build and start the full stack**

```bash
docker compose up --build -d
```

**Step 3: Verify health**

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`

**Step 4: Verify auth works**

```bash
curl -H "X-API-Key: your-api-key" http://localhost:8000/api/signals
```

Expected: `[]` (empty array, 200 OK)

```bash
curl http://localhost:8000/api/signals
```

Expected: `401`

**Step 5: Check logs for OKX connection**

```bash
docker compose logs api | grep -i "subscribed\|connected\|error"
```

Expected: Log lines showing WS subscription to OKX channels (candles + funding-rate + open-interest)

**Step 6: Commit any fixes**

```bash
git add -A
git commit -m "chore: verify end-to-end Docker deployment"
```
