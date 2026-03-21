from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import create_router
from tests.conftest import make_test_jwt


def _mock_db(scalars_all=None, scalar_one=None):
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
    app = FastAPI()

    mock_settings = MagicMock()
    mock_settings.jwt_secret = "test-jwt-secret"
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
            cookies={"krypton_token": make_test_jwt()},
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
            cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 404
