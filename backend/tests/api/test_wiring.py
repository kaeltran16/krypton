import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app.main import (
    persist_candle,
    persist_signal,
    handle_candle,
    handle_funding_rate,
    handle_open_interest,
    handle_long_short_data,
    _pipeline_done_callback,
)
from app.api.connections import ConnectionManager


def _mock_db():
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
        "timestamp": datetime(2026, 2, 27, tzinfo=timezone.utc),
        "open": 67000,
        "high": 67100,
        "low": 66900,
        "close": 67050,
        "volume": 100,
    }
    await handle_candle(app, candle)

    app.state.redis.rpush.assert_called_once()
    app.state.redis.ltrim.assert_called_once()

    assert len(app.state.pipeline_tasks) <= 1

    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_handle_funding_rate():
    app = FastAPI()
    app.state.order_flow = {}
    await handle_funding_rate(app, {"pair": "BTC-USDT-SWAP", "funding_rate": 0.0003})
    assert app.state.order_flow["BTC-USDT-SWAP"]["funding_rate"] == 0.0003


@pytest.mark.asyncio
async def test_handle_open_interest_computes_change_pct():
    app = FastAPI()
    app.state.order_flow = {"BTC-USDT-SWAP": {"open_interest": 1000}}
    await handle_open_interest(app, {"pair": "BTC-USDT-SWAP", "open_interest": 1100})
    assert app.state.order_flow["BTC-USDT-SWAP"]["open_interest"] == 1100
    assert abs(app.state.order_flow["BTC-USDT-SWAP"]["open_interest_change_pct"] - 0.1) < 0.001


@pytest.mark.asyncio
async def test_handle_long_short_data():
    app = FastAPI()
    app.state.order_flow = {}
    await handle_long_short_data(app, {"pair": "BTC-USDT-SWAP", "long_short_ratio": 1.3})
    assert app.state.order_flow["BTC-USDT-SWAP"]["long_short_ratio"] == 1.3


def test_pipeline_done_callback_logs_error():
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
