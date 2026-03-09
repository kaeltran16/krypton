"""Tests for pipeline settings API endpoints."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.pipeline_settings import router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline_settings_row(**overrides):
    row = MagicMock()
    row.id = 1
    row.pairs = overrides.get("pairs", ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    row.timeframes = overrides.get("timeframes", ["15m", "1h", "4h"])
    row.signal_threshold = overrides.get("signal_threshold", 50)
    row.onchain_enabled = overrides.get("onchain_enabled", True)
    row.news_alerts_enabled = overrides.get("news_alerts_enabled", True)
    row.news_context_window = overrides.get("news_context_window", 30)
    row.updated_at = overrides.get("updated_at", datetime.now(timezone.utc))
    return row


def _mock_db(scalar_one=None):
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_one
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.refresh = AsyncMock()

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db, mock_session


@pytest.fixture
def app_with_pipeline():
    app = FastAPI()

    mock_settings = MagicMock()
    mock_settings.krypton_api_key = "test-key"
    mock_settings.pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    mock_settings.timeframes = ["15m", "1h", "4h"]
    mock_settings.engine_signal_threshold = 50
    mock_settings.onchain_enabled = True
    mock_settings.news_high_impact_push_enabled = True
    mock_settings.news_llm_context_window_minutes = 30
    app.state.settings = mock_settings

    row = _make_pipeline_settings_row()
    db, _ = _mock_db(scalar_one=row)
    app.state.db = db
    app.state.pipeline_settings_lock = asyncio.Lock()

    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# GET tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_requires_auth(app_with_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_pipeline), base_url="http://test"
    ) as client:
        resp = await client.get("/api/pipeline/settings")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_settings_returns_defaults(app_with_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_pipeline), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/pipeline/settings",
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pairs"] == ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    assert data["timeframes"] == ["15m", "1h", "4h"]
    assert data["signal_threshold"] == 50
    assert data["onchain_enabled"] is True
    assert data["news_alerts_enabled"] is True
    assert data["news_context_window"] == 30


# ---------------------------------------------------------------------------
# PUT tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_partial_update(app_with_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_pipeline), base_url="http://test"
    ) as client:
        resp = await client.put(
            "/api/pipeline/settings",
            headers={"X-API-Key": "test-key"},
            json={"signal_threshold": 70},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_put_patches_settings_in_memory(app_with_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_pipeline), base_url="http://test"
    ) as client:
        await client.put(
            "/api/pipeline/settings",
            headers={"X-API-Key": "test-key"},
            json={"signal_threshold": 75, "news_context_window": 60},
        )
    settings = app_with_pipeline.state.settings
    # Field name mapping: signal_threshold → engine_signal_threshold
    assert settings.engine_signal_threshold == 75
    # Field name mapping: news_context_window → news_llm_context_window_minutes
    assert settings.news_llm_context_window_minutes == 60


@pytest.mark.asyncio
async def test_put_invalid_pair_format_returns_422(app_with_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_pipeline), base_url="http://test"
    ) as client:
        resp = await client.put(
            "/api/pipeline/settings",
            headers={"X-API-Key": "test-key"},
            json={"pairs": ["invalid-pair"]},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_empty_pairs_returns_422(app_with_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_pipeline), base_url="http://test"
    ) as client:
        resp = await client.put(
            "/api/pipeline/settings",
            headers={"X-API-Key": "test-key"},
            json={"pairs": []},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_invalid_timeframe_returns_422(app_with_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_pipeline), base_url="http://test"
    ) as client:
        resp = await client.put(
            "/api/pipeline/settings",
            headers={"X-API-Key": "test-key"},
            json={"timeframes": ["2h"]},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_threshold_out_of_range_returns_422(app_with_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_pipeline), base_url="http://test"
    ) as client:
        resp = await client.put(
            "/api/pipeline/settings",
            headers={"X-API-Key": "test-key"},
            json={"signal_threshold": 150},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_empty_body_returns_400(app_with_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_pipeline), base_url="http://test"
    ) as client:
        resp = await client.put(
            "/api/pipeline/settings",
            headers={"X-API-Key": "test-key"},
            json={},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_boolean_fields(app_with_pipeline):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_pipeline), base_url="http://test"
    ) as client:
        resp = await client.put(
            "/api/pipeline/settings",
            headers={"X-API-Key": "test-key"},
            json={"onchain_enabled": False, "news_alerts_enabled": False},
        )
    assert resp.status_code == 200
    settings = app_with_pipeline.state.settings
    assert settings.onchain_enabled is False
    assert settings.news_high_impact_push_enabled is False
