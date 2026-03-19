"""Test GET /api/engine/parameters endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

HEADERS = {"X-API-Key": "test-key"}


@pytest.mark.asyncio
async def test_get_engine_parameters(client):
    resp = await client.get("/api/engine/parameters", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    # top-level categories present
    for key in ("technical", "order_flow", "onchain", "blending", "levels", "patterns", "performance_tracker"):
        assert key in data, f"Missing category: {key}"

    # check a hardcoded param
    adx = data["technical"]["indicator_periods"]["adx"]
    assert adx == {"value": 14, "source": "hardcoded"}

    # check a configurable param
    signal = data["blending"]["thresholds"]["signal"]
    assert signal["source"] == "configurable"
    assert isinstance(signal["value"], int)

    # regime_weights and learned_atr are dynamic (empty in test)
    assert "regime_weights" in data
    assert "learned_atr" in data
