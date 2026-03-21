"""Tests for alert API endpoints."""
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.api.alerts import router as alerts_router
from app.db.database import Database
from app.db.models import Alert, AlertHistory, AlertSettings
from sqlalchemy import delete
from tests.conftest import make_test_jwt

AUTH = {"krypton_token": make_test_jwt()}
_DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/krypton"
)


@pytest.fixture
async def alert_client():
    app = FastAPI()
    mock_settings = MagicMock()
    mock_settings.jwt_secret = "test-jwt-secret"
    mock_settings.pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    app.state.settings = mock_settings

    db = Database(_DB_URL)
    app.state.db = db
    mock_redis = MagicMock()
    mock_redis.delete = AsyncMock()
    app.state.redis = mock_redis
    app.include_router(alerts_router)

    # Clean up alert tables before each test
    async with db.session_factory() as session:
        await session.execute(delete(AlertHistory))
        await session.execute(delete(Alert))
        await session.execute(delete(AlertSettings))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    await db.close()


@pytest.mark.asyncio
async def test_create_price_alert(alert_client):
    resp = await alert_client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "crosses_above",
        "threshold": 70000,
        "urgency": "normal",
    }, cookies=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "price"
    assert data["is_one_shot"] is True  # crosses_above is always one-shot
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_create_alert_missing_threshold(alert_client):
    resp = await alert_client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "crosses_above",
    }, cookies=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_alert_requires_auth(alert_client):
    resp = await alert_client.post("/api/alerts", json={
        "type": "price",
        "condition": "crosses_above",
        "threshold": 70000,
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_alert_invalid_type(alert_client):
    resp = await alert_client.post("/api/alerts", json={
        "type": "invalid",
        "condition": "gt",
        "threshold": 70,
    }, cookies=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_alert_negative_price_threshold(alert_client):
    resp = await alert_client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "crosses_above",
        "threshold": -100,
    }, cookies=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_alert_invalid_pair(alert_client):
    resp = await alert_client.post("/api/alerts", json={
        "type": "price",
        "pair": "INVALID-PAIR",
        "condition": "crosses_above",
        "threshold": 70000,
    }, cookies=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_alert_pct_move_window_out_of_range(alert_client):
    resp = await alert_client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "pct_move",
        "threshold": 5,
        "secondary_threshold": 120,  # max is 60
    }, cookies=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_alert_max_limit(alert_client):
    """Create 50 alerts, then verify 51st is rejected with 409."""
    for i in range(50):
        resp = await alert_client.post("/api/alerts", json={
            "type": "indicator",
            "condition": "rsi_above",
            "threshold": 70 + (i * 0.01),
            "urgency": "silent",
        }, cookies=AUTH)
        assert resp.status_code == 200

    resp = await alert_client.post("/api/alerts", json={
        "type": "indicator",
        "condition": "rsi_above",
        "threshold": 99,
    }, cookies=AUTH)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_alerts(alert_client):
    # Create one alert
    await alert_client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "crosses_above",
        "threshold": 70000,
    }, cookies=AUTH)
    resp = await alert_client.get("/api/alerts", cookies=AUTH)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_delete_alert(alert_client):
    create_resp = await alert_client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "crosses_above",
        "threshold": 80000,
    }, cookies=AUTH)
    alert_id = create_resp.json()["id"]
    resp = await alert_client.delete(f"/api/alerts/{alert_id}", cookies=AUTH)
    assert resp.status_code == 200
    assert resp.json()["deleted"] == alert_id


@pytest.mark.asyncio
async def test_update_alert(alert_client):
    create_resp = await alert_client.post("/api/alerts", json={
        "type": "indicator",
        "condition": "rsi_above",
        "threshold": 70,
    }, cookies=AUTH)
    alert_id = create_resp.json()["id"]
    resp = await alert_client.patch(f"/api/alerts/{alert_id}", json={
        "threshold": 75,
        "urgency": "critical",
    }, cookies=AUTH)
    assert resp.status_code == 200
    assert resp.json()["threshold"] == 75
    assert resp.json()["urgency"] == "critical"


@pytest.mark.asyncio
async def test_alert_settings_crud(alert_client):
    # Get defaults
    resp = await alert_client.get("/api/alerts/settings", cookies=AUTH)
    assert resp.status_code == 200
    assert resp.json()["quiet_hours_enabled"] is False

    # Update
    resp = await alert_client.patch("/api/alerts/settings", json={
        "quiet_hours_enabled": True,
        "quiet_hours_start": "23:00",
        "quiet_hours_tz": "America/New_York",
    }, cookies=AUTH)
    assert resp.status_code == 200
    assert resp.json()["quiet_hours_enabled"] is True
    assert resp.json()["quiet_hours_start"] == "23:00"


@pytest.mark.asyncio
async def test_alert_history_default_window(alert_client):
    resp = await alert_client.get("/api/alerts/history", cookies=AUTH)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_alert_history_with_date_filter(alert_client):
    resp = await alert_client.get(
        "/api/alerts/history?since=2026-01-01T00:00:00Z&until=2026-12-31T23:59:59Z",
        cookies=AUTH,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_signal_filter_validation(alert_client):
    resp = await alert_client.post("/api/alerts", json={
        "type": "signal",
        "filters": {"min_score": 60, "direction": "LONG"},
        "urgency": "normal",
    }, cookies=AUTH)
    assert resp.status_code == 200
    assert resp.json()["filters"]["min_score"] == 60
