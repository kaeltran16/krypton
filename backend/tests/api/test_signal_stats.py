from unittest.mock import MagicMock, AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import create_router
from tests.conftest import make_test_jwt


@pytest.mark.asyncio
async def test_signal_stats_endpoint():
    app = FastAPI()

    mock_settings = MagicMock()
    mock_settings.jwt_secret = "test-jwt-secret"
    app.state.settings = mock_settings

    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(
        return_value='{"win_rate": 67.5, "avg_rr": 1.8, "total_resolved": 20, "total_wins": 13, "total_losses": 7, "by_pair": {}, "by_timeframe": {}}'
    )
    app.state.redis = mock_redis

    router = create_router()
    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/signals/stats", cookies={"krypton_token": make_test_jwt()}
        )
    assert response.status_code == 200
    data = response.json()
    assert "win_rate" in data
    assert "avg_rr" in data
    assert data["win_rate"] == 67.5
