"""Test POST /api/engine/apply endpoint."""

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock, AsyncMock
from tests.conftest import make_test_jwt

COOKIES = {"krypton_token": make_test_jwt()}


@pytest.mark.asyncio
async def test_preview_returns_diff(client):
    resp = await client.post(
        "/api/engine/apply",
        cookies=COOKIES,
        json={
            "changes": {"blending.thresholds.signal": 35},
            "confirm": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["preview"] is True
    assert len(data["diff"]) == 1
    assert data["diff"][0]["path"] == "blending.thresholds.signal"
    assert data["diff"][0]["current"] == 40
    assert data["diff"][0]["proposed"] == 35


@pytest.mark.asyncio
async def test_preview_is_default(client):
    resp = await client.post(
        "/api/engine/apply",
        cookies=COOKIES,
        json={"changes": {"blending.thresholds.signal": 35}},
    )
    assert resp.status_code == 200
    assert resp.json()["preview"] is True


@pytest.mark.asyncio
async def test_empty_changes_rejected(client):
    resp = await client.post(
        "/api/engine/apply",
        cookies=COOKIES,
        json={"changes": {}},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_unknown_dot_path_returns_unknown_source(client):
    """Unknown dot-paths are included in diff with source 'unknown'."""
    resp = await client.post(
        "/api/engine/apply",
        cookies=COOKIES,
        json={
            "changes": {"nonexistent.path": 42},
            "confirm": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["diff"][0]["source"] == "unknown"
    assert data["diff"][0]["current"] is None


@pytest.mark.asyncio
async def test_confirmed_regime_weight_update_clears_online_overlay_state(app, client):
    rw = MagicMock()
    rw.pair = "BTC-USDT-SWAP"
    rw.timeframe = "1h"
    rw.trending_tech_weight = 0.34

    ps = MagicMock()

    pipeline_result = MagicMock()
    pipeline_result.scalar_one_or_none.return_value = ps

    pair_row_result = MagicMock()
    pair_row_result.scalar_one_or_none.return_value = rw

    reload_result = MagicMock()
    reload_result.scalars.return_value.all.return_value = [rw]

    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False
    session.execute = AsyncMock(side_effect=[pipeline_result, pair_row_result, reload_result])
    session.commit = AsyncMock()

    app.state.db.session_factory = MagicMock(return_value=session)
    app.state.regime_weights = {("BTC-USDT-SWAP", "1h"): rw}
    app.state.regime_weight_signal_windows = {
        ("BTC-USDT-SWAP", "1h"): [{"id": idx} for idx in range(20)]
    }
    app.state.regime_weight_overlays = {
        ("BTC-USDT-SWAP", "1h"): {
            "trending": {"tech": 0.01, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "ranging": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "volatile": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "steady": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "eligible_count": 20,
            "window_oldest_outcome_at": "2026-03-20T00:00:00+00:00",
            "window_newest_outcome_at": "2026-04-01T00:00:00+00:00",
            "rebuilt_at": "2026-04-01T00:00:01+00:00",
        }
    }

    resp = await client.post(
        "/api/engine/apply",
        cookies=COOKIES,
        json={
            "changes": {
                "regime_weights.BTC-USDT-SWAP.1h.trending_tech_weight": 0.40,
            },
            "confirm": True,
        },
    )

    assert resp.status_code == 200
    assert ("BTC-USDT-SWAP", "1h") not in app.state.regime_weight_signal_windows
    assert ("BTC-USDT-SWAP", "1h") not in app.state.regime_weight_overlays
