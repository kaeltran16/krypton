"""Tests for optimizer API endpoints."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from tests.conftest import make_test_jwt
from app.engine.optimizer import OptimizerState


@pytest.fixture
def optimizer_state(app):
    state = OptimizerState()
    for pnl in [2.0, -0.5, 1.5, -0.3, 3.0, -1.0]:
        state.record_resolution(pnl_pct=pnl)
    app.state.optimizer = state
    return state


@pytest.mark.asyncio
async def test_get_optimizer_status(client, app, optimizer_state):
    resp = await client.get(
        "/api/optimizer/status",
        cookies={"krypton_token": make_test_jwt()},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "groups" in data
    assert "global_profit_factor" in data
    assert "active_shadow" in data
    assert len(data["groups"]) == 15


@pytest.mark.asyncio
async def test_get_optimizer_status_no_auth(client):
    resp = await client.get("/api/optimizer/status")
    assert resp.status_code in (401, 403)
