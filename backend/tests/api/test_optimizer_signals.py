from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import asyncio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.optimizer import router as optimizer_router
from tests.conftest import make_test_jwt


def _mock_signal(outcome="TP1_HIT", pnl=1.5, has_new_keys=True):
    """Create a mock Signal ORM object."""
    sig = MagicMock()
    sig.outcome = outcome
    sig.outcome_pnl_pct = Decimal(str(pnl))
    sig.entry = Decimal("50000")
    sig.stop_loss = Decimal("49500")
    sig.take_profit_1 = Decimal("50750")
    sig.traditional_score = 55
    if has_new_keys:
        sig.raw_indicators = {
            "tech_score": 55, "tech_confidence": 0.7,
            "flow_score": 15, "flow_confidence": 0.5,
            "onchain_score": 0, "onchain_confidence": 0.0,
            "pattern_score": 10, "pattern_confidence": 0.4,
            "liquidation_score": 0, "liquidation_confidence": 0.0,
            "confluence_score": 12, "confluence_confidence": 0.6,
            "regime_trending": 0.5, "regime_ranging": 0.2,
            "regime_volatile": 0.2, "regime_steady": 0.1,
        }
    else:
        # Legacy signal: no per-source keys, just regime + existing indicators
        sig.raw_indicators = {
            "regime_trending": 0.5, "regime_ranging": 0.2,
            "regime_volatile": 0.2,
            "confluence_score": 12, "confluence_confidence": 0.6,
            "liquidation_score": 0, "liquidation_confidence": 0.0,
        }
    return sig


def _mock_db(scalars_all=None):
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db


@pytest.fixture
def optimizer_app():
    app = FastAPI()
    mock_settings = MagicMock()
    mock_settings.jwt_secret = "test-jwt-secret"
    mock_settings.engine_signal_threshold = 40
    app.state.settings = mock_settings
    app.state.db = _mock_db()
    app.state.manager = MagicMock()
    app.state.manager.broadcast = AsyncMock()
    app.state.manager.broadcast_event = AsyncMock()
    app.state.active_signal_optimization = None
    app.include_router(optimizer_router)
    return app


@pytest.mark.asyncio
async def test_optimize_from_signals_insufficient(optimizer_app):
    """Returns 400 when not enough resolved signals."""
    async with AsyncClient(
        transport=ASGITransport(app=optimizer_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/optimizer/optimize-from-signals",
            json={"pair": "BTC-USDT-SWAP", "min_signals": 20},
            cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 400
    data = resp.json()
    assert data["detail"]["error"] == "insufficient_signals"


@pytest.mark.asyncio
async def test_optimize_from_signals_409_when_busy(optimizer_app):
    """Returns 409 when optimization already running."""
    optimizer_app.state.active_signal_optimization = {"pair": "BTC-USDT-SWAP", "cancel_flag": {"cancelled": False}}
    async with AsyncClient(
        transport=ASGITransport(app=optimizer_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/optimizer/optimize-from-signals",
            json={"pair": "BTC-USDT-SWAP"},
            cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 409
    optimizer_app.state.active_signal_optimization = None


@pytest.mark.asyncio
async def test_legacy_signals_backfilled(optimizer_app):
    """Legacy signals without tech_score get backfilled from traditional_score."""
    # Provide 25 legacy signals (no tech_score key)
    legacy_sigs = [_mock_signal(has_new_keys=False) for _ in range(25)]
    optimizer_app.state.db = _mock_db(scalars_all=legacy_sigs)
    async with AsyncClient(
        transport=ASGITransport(app=optimizer_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/optimizer/optimize-from-signals",
            json={"pair": "BTC-USDT-SWAP", "min_signals": 20},
            cookies={"krypton_token": make_test_jwt()},
        )
    # Should accept the signals (status=started), not reject them as insufficient
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "started"
    assert data["signals_queued"] == 25


@pytest.mark.asyncio
async def test_optimize_from_signals_uses_broadcast_event(optimizer_app, monkeypatch):
    """Optimizer events must not go through the signal-only broadcaster."""
    legacy_sigs = [_mock_signal(has_new_keys=False) for _ in range(25)]

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = legacy_sigs
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()

    async def _refresh(proposal):
        proposal.id = 123

    mock_session.refresh = AsyncMock(side_effect=_refresh)

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    optimizer_app.state.db = mock_db
    optimizer_app.state.manager.broadcast = AsyncMock(
        side_effect=AssertionError("optimizer events should not use signal broadcast")
    )
    optimizer_app.state.manager.broadcast_event = AsyncMock()

    def _fake_optimize_from_signals(*args, **kwargs):
        weights = {
            regime: {
                "tech": 0.2,
                "flow": 0.2,
                "onchain": 0.2,
                "pattern": 0.1,
                "liquidation": 0.1,
                "confluence": 0.2,
            }
            for regime in ("trending", "ranging", "volatile", "steady")
        }
        return {"weights": weights, "fitness": 0.42, "evaluations": 12}

    monkeypatch.setattr(
        "app.engine.regime_optimizer.optimize_from_signals",
        _fake_optimize_from_signals,
    )

    async with AsyncClient(
        transport=ASGITransport(app=optimizer_app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/optimizer/optimize-from-signals",
            json={"pair": "BTC-USDT-SWAP", "min_signals": 20},
            cookies={"krypton_token": make_test_jwt()},
        )

    assert resp.status_code == 200
    await asyncio.sleep(0.05)
    assert optimizer_app.state.manager.broadcast_event.await_count >= 2
