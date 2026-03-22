import time
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
async def health_app(app):
    """Extend base app fixture with fields needed by health endpoint.

    The `app` and `client` fixtures from conftest share the same FastAPI instance,
    so mutations here are visible to `client`.
    """
    app.state.redis = AsyncMock()
    app.state.redis.ping = AsyncMock(return_value=True)
    app.state.redis.llen = AsyncMock(return_value=200)
    app.state.redis.lindex = AsyncMock(return_value=None)
    app.state.redis.get = AsyncMock(return_value=None)
    app.state.order_flow = {"BTC-USDT-SWAP": {"funding_rate": 0.001}}
    app.state.start_time = time.time() - 3600
    app.state.last_pipeline_cycle = time.time() - 10

    mock_engine = MagicMock()
    mock_pool = MagicMock()
    mock_pool.checkedout.return_value = 2
    mock_pool.size.return_value = 10
    mock_engine.pool = mock_pool
    app.state.db.engine = mock_engine

    from app.api.connections import ConnectionManager
    app.state.manager = ConnectionManager()
    app.state.ml_predictors = {"BTC-USDT-SWAP": MagicMock()}
    return app


@pytest.mark.asyncio
async def test_health_returns_200(health_app, client, auth_cookies):
    """health_app mutates the shared app instance before client sends the request."""
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("healthy", "degraded", "unhealthy")
    assert "services" in data
    assert "pipeline" in data
    assert "resources" in data
    assert "freshness" in data


@pytest.mark.asyncio
async def test_health_requires_auth(client):
    resp = await client.get("/api/system/health")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health_services_structure(health_app, client, auth_cookies):
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    services = resp.json()["services"]
    assert "redis" in services
    assert "postgres" in services
    assert "okx_ws" in services
    # Redis should be up since we mocked ping
    assert services["redis"]["status"] == "up"
    assert isinstance(services["redis"]["latency_ms"], int)


@pytest.mark.asyncio
async def test_health_pipeline_structure(health_app, client, auth_cookies):
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    pipeline = resp.json()["pipeline"]
    assert "signals_today" in pipeline
    assert "last_cycle_seconds_ago" in pipeline
    assert "active_pairs" in pipeline
    assert "candle_buffer" in pipeline


@pytest.mark.asyncio
async def test_health_resources_structure(health_app, client, auth_cookies):
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    resources = resp.json()["resources"]
    assert "db_pool_active" in resources
    assert resources["db_pool_active"] == 2
    assert resources["db_pool_size"] == 10
    assert "ws_clients" in resources
    assert "uptime_seconds" in resources
    assert resources["uptime_seconds"] >= 3600


@pytest.mark.asyncio
async def test_health_freshness_ml_count(health_app, client, auth_cookies):
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    freshness = resp.json()["freshness"]
    assert freshness["ml_models_loaded"] == 1


@pytest.mark.asyncio
async def test_health_degraded_when_redis_down(health_app, client, auth_cookies):
    health_app.state.redis.ping = AsyncMock(side_effect=Exception("connection refused"))
    resp = await client.get("/api/system/health", cookies=auth_cookies)
    data = resp.json()
    assert data["services"]["redis"]["status"] == "down"
    assert data["services"]["redis"]["latency_ms"] is None
    assert data["status"] in ("degraded", "unhealthy")
