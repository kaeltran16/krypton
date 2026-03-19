"""Test optimization endpoints."""

import pytest

HEADERS = {"X-API-Key": "test-key"}


@pytest.mark.asyncio
async def test_optimize_atr_requires_pair_and_timeframe(client):
    resp = await client.post(
        "/api/backtest/optimize-atr",
        headers=HEADERS,
        json={},
    )
    assert resp.status_code == 422  # validation error


@pytest.mark.asyncio
async def test_optimize_atr_success(client):
    """Happy path: returns current/proposed multipliers and metrics."""
    from unittest.mock import AsyncMock, MagicMock

    tracker = MagicMock()
    tracker.get_multipliers = AsyncMock(return_value=(1.5, 2.0, 3.0))
    tracker.optimize = AsyncMock(return_value={
        "sl_atr": 1.3, "tp1_atr": 2.2, "tp2_atr": 3.5,
        "signals_analyzed": 85,
        "current_sortino": 1.42,
        "proposed_sortino": 1.78,
    })
    client.app.state.tracker = tracker

    resp = await client.post(
        "/api/backtest/optimize-atr",
        headers=HEADERS,
        json={"pair": "BTC-USDT-SWAP", "timeframe": "1h"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"]["sl_atr"] == 1.5
    assert data["proposed"]["sl_atr"] == 1.3
    assert data["metrics"]["signals_analyzed"] == 85
    assert data["metrics"]["proposed_sortino"] == 1.78

    tracker.optimize.assert_called_once_with("BTC-USDT-SWAP", "1h", dry_run=True)


@pytest.mark.asyncio
async def test_optimize_atr_insufficient_signals(client):
    """Returns 400 when not enough resolved signals."""
    from unittest.mock import AsyncMock, MagicMock

    tracker = MagicMock()
    tracker.get_multipliers = AsyncMock(return_value=(1.5, 2.0, 3.0))
    tracker.optimize = AsyncMock(return_value=None)
    client.app.state.tracker = tracker

    resp = await client.post(
        "/api/backtest/optimize-atr",
        headers=HEADERS,
        json={"pair": "BTC-USDT-SWAP", "timeframe": "1h"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_regime_optimizer_does_not_auto_save(client):
    """Regime optimization must NOT write to RegimeWeights or update app.state.regime_weights."""
    import inspect
    from app.api.backtest import optimize_regime
    source = inspect.getsource(optimize_regime)
    assert "session.merge" not in source, "optimize_regime should not merge RegimeWeights"
    assert "regime_weights[" not in source, "optimize_regime should not update app.state.regime_weights"
