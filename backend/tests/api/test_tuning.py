import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import create_router
from tests.conftest import make_test_jwt


def _mock_db():
    db = MagicMock()
    session = AsyncMock()
    db.session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
    db.session_factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return db, session


@pytest.fixture
def app_with_routes():
    app = FastAPI()
    settings = MagicMock()
    settings.jwt_secret = "test-jwt-secret"
    app.state.settings = settings
    db, session = _mock_db()
    app.state.db = db
    app.state.session = session
    router = create_router()
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_get_tuning_returns_all_rows(app_with_routes):
    session = app_with_routes.state.session
    row = MagicMock()
    row.pair = "BTC-USDT-SWAP"
    row.timeframe = "1h"
    row.current_sl_atr = 1.8
    row.current_tp1_atr = 2.5
    row.current_tp2_atr = 4.0
    row.last_optimized_at = None
    row.last_optimized_count = 0
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = [row]

    async with AsyncClient(
        transport=ASGITransport(app=app_with_routes), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/engine/tuning",
            cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["pair"] == "BTC-USDT-SWAP"
    assert data[0]["current_sl_atr"] == 1.8


@pytest.mark.asyncio
async def test_get_tuning_requires_auth(app_with_routes):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_routes), base_url="http://test"
    ) as client:
        resp = await client.get("/api/engine/tuning")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_reset_tuning(app_with_routes):
    session = app_with_routes.state.session
    row = MagicMock()
    row.current_sl_atr = 1.8
    row.current_tp1_atr = 2.5
    row.current_tp2_atr = 4.0
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = row

    async with AsyncClient(
        transport=ASGITransport(app=app_with_routes), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/engine/tuning/reset",
            cookies={"krypton_token": make_test_jwt()},
            json={"pair": "BTC-USDT-SWAP", "timeframe": "1h"},
        )
    assert resp.status_code == 200
    from app.engine.performance_tracker import DEFAULT_SL, DEFAULT_TP1, DEFAULT_TP2
    assert row.current_sl_atr == DEFAULT_SL
    assert row.current_tp1_atr == DEFAULT_TP1
    assert row.current_tp2_atr == DEFAULT_TP2
