from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app.api.push import router as push_router


def _make_push_app():
    """Create a minimal FastAPI app with just push routes and mock session."""
    app = FastAPI()
    app.include_router(push_router)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield mock_session

    app.state.session_factory = factory
    return app, mock_session


@pytest.mark.asyncio
async def test_subscribe_creates_subscription():
    from httpx import ASGITransport, AsyncClient

    app, mock_session = _make_push_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/push/subscribe",
            json={
                "endpoint": "https://push.example.com/abc",
                "keys": {"p256dh": "key123", "auth": "auth456"},
                "pairs": ["BTC-USDT-SWAP"],
                "timeframes": ["1h"],
                "threshold": 60,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "subscribed"
    mock_session.execute.assert_called_once()
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_upserts_on_duplicate_endpoint():
    from httpx import ASGITransport, AsyncClient

    app, mock_session = _make_push_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "endpoint": "https://push.example.com/abc",
            "keys": {"p256dh": "key123", "auth": "auth456"},
            "pairs": ["BTC-USDT-SWAP"],
            "timeframes": ["1h"],
            "threshold": 60,
        }
        resp1 = await client.post("/api/push/subscribe", json=payload)
        assert resp1.status_code == 200

        payload["threshold"] = 80
        resp2 = await client.post("/api/push/subscribe", json=payload)
        assert resp2.status_code == 200

    assert mock_session.execute.call_count == 2
    assert mock_session.add.call_count == 2


@pytest.mark.asyncio
async def test_unsubscribe_removes_subscription():
    from httpx import ASGITransport, AsyncClient

    app, mock_session = _make_push_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/push/unsubscribe",
            json={"endpoint": "https://push.example.com/abc"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "unsubscribed"
    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()
