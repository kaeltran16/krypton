from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

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
