"""Tests for GET /api/news and GET /api/news/recent endpoints."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.news import router


def _mock_db(scalars_all=None):
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db


def _make_news_event(**overrides):
    """Create a mock NewsEvent object."""
    now = datetime.now(timezone.utc)
    defaults = {
        "id": 1,
        "headline": "Test headline",
        "source": "cryptopanic",
        "url": "https://example.com/article",
        "category": "crypto",
        "impact": "high",
        "sentiment": "bullish",
        "affected_pairs": ["BTC"],
        "llm_summary": "Test summary",
        "published_at": now,
        "created_at": now,
    }
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


@pytest.fixture
def app_with_news():
    app = FastAPI()
    mock_settings = MagicMock()
    mock_settings.krypton_api_key = "test-key"
    app.state.settings = mock_settings
    app.state.db = _mock_db()
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_get_news_requires_auth(app_with_news):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_news), base_url="http://test"
    ) as client:
        resp = await client.get("/api/news")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_news_empty(app_with_news):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_news), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/news", headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_news_returns_events():
    news = [_make_news_event(id=1), _make_news_event(id=2, impact="medium")]
    app = FastAPI()
    app.state.settings = MagicMock(krypton_api_key="test-key")
    app.state.db = _mock_db(scalars_all=news)
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/news", headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["id"] == 1
    assert data[1]["impact"] == "medium"


@pytest.mark.asyncio
async def test_get_news_filter_category():
    """Category filter parameter is accepted."""
    app = FastAPI()
    app.state.settings = MagicMock(krypton_api_key="test-key")
    app.state.db = _mock_db()
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/news?category=crypto",
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_news_filter_impact():
    """Impact filter parameter is accepted."""
    app = FastAPI()
    app.state.settings = MagicMock(krypton_api_key="test-key")
    app.state.db = _mock_db()
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/news?impact=high",
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_news_invalid_category():
    """Invalid category returns 422."""
    app = FastAPI()
    app.state.settings = MagicMock(krypton_api_key="test-key")
    app.state.db = _mock_db()
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/news?category=invalid",
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_recent_news_requires_auth(app_with_news):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_news), base_url="http://test"
    ) as client:
        resp = await client.get("/api/news/recent")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_recent_news_returns_high_medium():
    """Recent endpoint returns high+medium impact only."""
    news = [
        _make_news_event(id=1, impact="high"),
        _make_news_event(id=2, impact="medium"),
    ]
    app = FastAPI()
    app.state.settings = MagicMock(krypton_api_key="test-key")
    app.state.db = _mock_db(scalars_all=news)
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/news/recent", headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


@pytest.mark.asyncio
async def test_news_router_registered():
    """Verify news router is registered on the full app."""
    from app.main import create_app

    @asynccontextmanager
    async def noop_lifespan(app):
        app.state.settings = MagicMock(krypton_api_key="test-key")
        yield

    app = create_app(lifespan_override=noop_lifespan)
    routes = [r.path for r in app.routes]
    assert "/api/news" in routes
    assert "/api/news/recent" in routes
