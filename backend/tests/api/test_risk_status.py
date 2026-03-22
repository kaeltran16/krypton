"""Tests for GET /api/risk/status composite endpoint."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.risk import router as risk_router
from tests.conftest import make_test_jwt


def _make_risk_settings(**overrides):
    """Create a mock RiskSettings ORM object."""
    rs = MagicMock()
    rs.risk_per_trade = overrides.get("risk_per_trade", 0.01)
    rs.max_position_size_usd = overrides.get("max_position_size_usd", None)
    rs.daily_loss_limit_pct = overrides.get("daily_loss_limit_pct", 0.03)
    rs.max_concurrent_positions = overrides.get("max_concurrent_positions", 3)
    rs.max_exposure_pct = overrides.get("max_exposure_pct", 1.5)
    rs.cooldown_after_loss_minutes = overrides.get("cooldown_after_loss_minutes", 30)
    rs.max_risk_per_trade_pct = overrides.get("max_risk_per_trade_pct", 0.02)
    rs.updated_at = overrides.get("updated_at", datetime(2026, 3, 22, 9, 0, tzinfo=timezone.utc))
    return rs


def _make_signal(outcome, outcome_at, outcome_pnl_pct):
    """Create a mock Signal ORM object."""
    sig = MagicMock()
    sig.outcome = outcome
    sig.outcome_at = outcome_at
    sig.outcome_pnl_pct = Decimal(str(outcome_pnl_pct))
    return sig


def _mock_db_for_status(risk_settings, resolved_signals=None, last_sl_signal=None):
    """Build a mock DB that handles the multiple queries in the status endpoint.

    The endpoint runs up to 3 queries in sequence:
    1. RiskSettings singleton
    2. Resolved signals for daily P&L (scalars().all())
    3. Last SL_HIT signal (scalar_one_or_none())
    """
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()

        if call_count == 1:
            # Query 1: RiskSettings
            result.scalar_one_or_none.return_value = risk_settings
        elif call_count == 2:
            # Query 2: Resolved signals for daily P&L
            result.scalars.return_value.all.return_value = resolved_signals or []
        elif call_count == 3:
            # Query 3: Last SL_HIT signal
            result.scalar_one_or_none.return_value = last_sl_signal
        return result

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=fake_execute)

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db


def _make_app(okx_client=None, db=None):
    app = FastAPI()
    mock_settings = MagicMock()
    mock_settings.jwt_secret = "test-jwt-secret"
    app.state.settings = mock_settings
    app.state.okx_client = okx_client
    app.state.db = db or MagicMock()
    app.include_router(risk_router)
    return app


def _make_okx(equity=10000.0, positions=None):
    okx = AsyncMock()
    okx.get_balance = AsyncMock(return_value={"total_equity": equity})
    okx.get_positions = AsyncMock(return_value=positions or [])
    return okx


@pytest.fixture
def auth_cookies():
    return {"krypton_token": make_test_jwt()}


@pytest.mark.asyncio
async def test_risk_status_all_ok(auth_cookies):
    """All rules OK: no positions, no daily loss, no cooldown."""
    rs = _make_risk_settings(cooldown_after_loss_minutes=30)
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=None)
    okx = _make_okx(equity=10000.0, positions=[])
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_status"] == "OK"
    assert data["settings"]["risk_per_trade"] == 0.01
    assert data["state"]["equity"] == 10000.0
    assert data["state"]["open_positions_count"] == 0
    assert data["state"]["daily_pnl_pct"] == 0.0
    # All rules should be OK
    for rule in data["rules"]:
        assert rule["status"] == "OK"


@pytest.mark.asyncio
async def test_risk_status_daily_loss_blocked(auth_cookies):
    """daily_loss_limit rule → BLOCKED when daily P&L exceeds limit."""
    rs = _make_risk_settings(daily_loss_limit_pct=0.03)
    # Signals with outcome_pnl_pct summing to -4.0 (i.e., -4% in DB → -0.04 decimal)
    signals = [
        _make_signal("SL_HIT", datetime(2026, 3, 22, 10, 0, tzinfo=timezone.utc), -2.5),
        _make_signal("SL_HIT", datetime(2026, 3, 22, 11, 0, tzinfo=timezone.utc), -1.5),
    ]
    db = _mock_db_for_status(rs, resolved_signals=signals, last_sl_signal=None)
    okx = _make_okx(equity=10000.0, positions=[])
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    data = resp.json()
    assert data["overall_status"] == "BLOCKED"
    daily_rule = next(r for r in data["rules"] if r["rule"] == "daily_loss_limit")
    assert daily_rule["status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_risk_status_max_concurrent_blocked(auth_cookies):
    """max_concurrent rule → BLOCKED when positions at limit."""
    rs = _make_risk_settings(max_concurrent_positions=2)
    positions = [
        {"size": 1.0, "mark_price": 65000.0},
        {"size": 0.5, "mark_price": 3000.0},
    ]
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=None)
    okx = _make_okx(equity=10000.0, positions=positions)
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    data = resp.json()
    pos_rule = next(r for r in data["rules"] if r["rule"] == "max_concurrent")
    assert pos_rule["status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_risk_status_exposure_warning(auth_cookies):
    """max_exposure rule → WARNING when usage > 80%."""
    rs = _make_risk_settings(max_exposure_pct=1.5)
    positions = [{"size": 1.0, "mark_price": 13000.0}]  # 130% of 10k equity → > 80% of 150% limit
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=None)
    okx = _make_okx(equity=10000.0, positions=positions)
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    data = resp.json()
    exp_rule = next(r for r in data["rules"] if r["rule"] == "max_exposure")
    assert exp_rule["status"] == "WARNING"


@pytest.mark.asyncio
async def test_risk_status_cooldown_warning(auth_cookies):
    """cooldown rule appears as WARNING when cooldown is active."""
    now = datetime.now(timezone.utc)
    last_sl = _make_signal("SL_HIT", now - timedelta(minutes=10), -1.0)
    rs = _make_risk_settings(cooldown_after_loss_minutes=30)
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=last_sl)
    okx = _make_okx(equity=10000.0, positions=[])
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    data = resp.json()
    cd_rule = next((r for r in data["rules"] if r["rule"] == "cooldown"), None)
    assert cd_rule is not None
    assert cd_rule["status"] == "WARNING"
    assert "remaining" in cd_rule["reason"].lower() or "min" in cd_rule["reason"].lower()


@pytest.mark.asyncio
async def test_risk_status_cooldown_omitted_when_inactive(auth_cookies):
    """cooldown rule omitted when not configured."""
    rs = _make_risk_settings(cooldown_after_loss_minutes=None)
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=None)
    okx = _make_okx(equity=10000.0, positions=[])
    app = _make_app(okx_client=okx, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    data = resp.json()
    cd_rules = [r for r in data["rules"] if r["rule"] == "cooldown"]
    assert len(cd_rules) == 0


@pytest.mark.asyncio
async def test_risk_status_no_okx_returns_zeros(auth_cookies):
    """When OKX client is None, state fields are zero, all rules OK."""
    rs = _make_risk_settings()
    db = _mock_db_for_status(rs, resolved_signals=[], last_sl_signal=None)
    app = _make_app(okx_client=None, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status", cookies=auth_cookies)

    assert resp.status_code == 200
    data = resp.json()
    assert data["state"]["equity"] == 0
    assert data["state"]["open_positions_count"] == 0
    assert data["state"]["exposure_pct"] == 0
    assert data["overall_status"] == "OK"


@pytest.mark.asyncio
async def test_risk_status_requires_auth():
    """Endpoint requires authentication."""
    rs = _make_risk_settings()
    db = _mock_db_for_status(rs)
    app = _make_app(okx_client=None, db=db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/risk/status")

    assert resp.status_code == 401
