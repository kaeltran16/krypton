"""Tests for ML health endpoint."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
async def ml_health_app(app):
    """Extend base app fixture with fields needed by ML health endpoint.

    The `app` and `client` fixtures from conftest share the same FastAPI instance,
    so mutations here are visible to `client`.
    """
    mock_predictor = MagicMock()
    mock_predictor.n_members = 3
    mock_predictor.stale_member_count = 1
    mock_predictor.oldest_member_age_days = 25.0
    app.state.ml_predictors = {"btc_usdt_swap": mock_predictor}
    app.state.regime_classifier = None
    return app


@pytest.mark.asyncio
async def test_ml_health_returns_structure(ml_health_app, client, auth_cookies):
    resp = await client.get("/api/ml/health", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "ml_health" in data
    assert "ensemble" in data["ml_health"]
    assert "regime_classifier" in data["ml_health"]
    ensemble = data["ml_health"]["ensemble"]
    assert ensemble["pairs_loaded"] == 1
    assert ensemble["members_loaded"] == 3
    assert ensemble["members_stale"] == 1
    assert ensemble["oldest_member_days"] == 25.0
