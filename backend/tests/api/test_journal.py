from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import create_router


def _make_signal(**overrides):
    """Create a mock Signal object with default values."""
    now = datetime.now(timezone.utc)
    defaults = {
        "id": 1,
        "pair": "BTC-USDT-SWAP",
        "timeframe": "1h",
        "direction": "LONG",
        "final_score": 65,
        "traditional_score": 60,
        "llm_opinion": "confirm",
        "llm_confidence": "HIGH",
        "explanation": "Test signal",
        "entry": Decimal("50000"),
        "stop_loss": Decimal("49000"),
        "take_profit_1": Decimal("51000"),
        "take_profit_2": Decimal("52000"),
        "raw_indicators": {},
        "created_at": now,
        "outcome": "TP1_HIT",
        "outcome_at": now + timedelta(hours=2),
        "outcome_pnl_pct": Decimal("2.0"),
        "outcome_duration_minutes": 120,
        "user_note": None,
        "user_status": "OBSERVED",
    }
    defaults.update(overrides)
    signal = MagicMock()
    for k, v in defaults.items():
        setattr(signal, k, v)
    return signal


def _mock_db(scalars_all=None, scalar_one=None):
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    mock_result.scalar_one_or_none.return_value = scalar_one
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db, mock_session


def _make_app(db_mock, redis_mock=None):
    app = FastAPI()
    mock_settings = MagicMock()
    mock_settings.krypton_api_key = "test-key"
    app.state.settings = mock_settings
    app.state.db = db_mock
    app.state.redis = redis_mock or _make_redis()
    router = create_router()
    app.include_router(router)
    return app


def _make_redis(cached=None):
    mock = MagicMock()
    mock.get = AsyncMock(return_value=cached)
    mock.set = AsyncMock()
    mock.keys = AsyncMock(return_value=[])
    mock.delete = AsyncMock()
    return mock


HEADERS = {"X-API-Key": "test-key"}


# ---------- PATCH /api/signals/{id}/journal ----------


@pytest.mark.asyncio
async def test_journal_patch_valid_update():
    signal = _make_signal()
    db, session = _mock_db(scalar_one=signal)
    app = _make_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/api/signals/1/journal",
            json={"status": "TRADED", "note": "Good entry"},
            headers=HEADERS,
        )

    assert resp.status_code == 200
    assert signal.user_status == "TRADED"
    assert signal.user_note == "Good entry"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_journal_patch_invalid_status():
    signal = _make_signal()
    db, _ = _mock_db(scalar_one=signal)
    app = _make_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/api/signals/1/journal",
            json={"status": "INVALID"},
            headers=HEADERS,
        )

    assert resp.status_code == 400
    assert "Invalid status" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_journal_patch_note_too_long():
    signal = _make_signal()
    db, _ = _mock_db(scalar_one=signal)
    app = _make_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/api/signals/1/journal",
            json={"note": "x" * 501},
            headers=HEADERS,
        )

    assert resp.status_code == 422  # pydantic validation


@pytest.mark.asyncio
async def test_journal_patch_not_found():
    db, _ = _mock_db(scalar_one=None)
    app = _make_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/api/signals/999/journal",
            json={"status": "TRADED"},
            headers=HEADERS,
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_journal_patch_invalidates_stats_cache():
    signal = _make_signal()
    db, _ = _mock_db(scalar_one=signal)
    redis = _make_redis()
    redis.keys = AsyncMock(return_value=["signal_stats:7d", "signal_stats:30d"])
    app = _make_app(db, redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.patch(
            "/api/signals/1/journal",
            json={"status": "TRADED"},
            headers=HEADERS,
        )

    redis.delete.assert_awaited_once_with("signal_stats:7d", "signal_stats:30d")


# ---------- GET /api/signals/stats (extended) ----------


@pytest.mark.asyncio
async def test_stats_equity_curve_empty():
    db, _ = _mock_db(scalars_all=[])
    redis = _make_redis()
    app = _make_app(db, redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/signals/stats?days=7", headers=HEADERS)

    data = resp.json()
    assert data["equity_curve"] == []
    assert data["streaks"] == {"current": 0, "best_win": 0, "worst_loss": 0}


@pytest.mark.asyncio
async def test_stats_streaks_mixed():
    now = datetime.now(timezone.utc)
    signals = [
        _make_signal(id=1, outcome="TP1_HIT", created_at=now - timedelta(hours=5), outcome_at=now - timedelta(hours=4)),
        _make_signal(id=2, outcome="TP2_HIT", created_at=now - timedelta(hours=4), outcome_at=now - timedelta(hours=3)),
        _make_signal(id=3, outcome="SL_HIT", created_at=now - timedelta(hours=3), outcome_at=now - timedelta(hours=2), outcome_pnl_pct=Decimal("-1.5")),
        _make_signal(id=4, outcome="SL_HIT", created_at=now - timedelta(hours=2), outcome_at=now - timedelta(hours=1), outcome_pnl_pct=Decimal("-1.0")),
        _make_signal(id=5, outcome="SL_HIT", created_at=now - timedelta(hours=1), outcome_at=now, outcome_pnl_pct=Decimal("-0.5")),
    ]
    db, _ = _mock_db(scalars_all=signals)
    redis = _make_redis()
    app = _make_app(db, redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/signals/stats?days=7", headers=HEADERS)

    data = resp.json()
    assert data["streaks"]["best_win"] == 2
    assert data["streaks"]["worst_loss"] == -3
    assert data["streaks"]["current"] == -3


@pytest.mark.asyncio
async def test_stats_hourly_performance_bucketing():
    now = datetime.now(timezone.utc)
    hour_9 = now.replace(hour=9, minute=0, second=0, microsecond=0)
    hour_14 = now.replace(hour=14, minute=0, second=0, microsecond=0)
    signals = [
        _make_signal(id=1, created_at=hour_9, outcome_pnl_pct=Decimal("2.0")),
        _make_signal(id=2, created_at=hour_9, outcome_pnl_pct=Decimal("4.0")),
        _make_signal(id=3, created_at=hour_14, outcome_pnl_pct=Decimal("-1.0")),
    ]
    db, _ = _mock_db(scalars_all=signals)
    redis = _make_redis()
    app = _make_app(db, redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/signals/stats?days=7", headers=HEADERS)

    data = resp.json()
    hourly = {h["hour"]: h for h in data["hourly_performance"]}
    assert len(data["hourly_performance"]) == 24
    assert hourly[9]["avg_pnl"] == 3.0
    assert hourly[9]["count"] == 2
    assert hourly[14]["avg_pnl"] == -1.0
    assert hourly[14]["count"] == 1
    assert hourly[0]["count"] == 0


@pytest.mark.asyncio
async def test_stats_all_period_capped_365():
    db, _ = _mock_db(scalars_all=[])
    redis = _make_redis()
    app = _make_app(db, redis)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/signals/stats?days=365", headers=HEADERS)
    assert resp.status_code == 200

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/signals/stats?days=366", headers=HEADERS)
    assert resp.status_code == 422  # exceeds max


# ---------- GET /api/signals/calendar ----------


@pytest.mark.asyncio
async def test_calendar_day_aggregation():
    base = datetime(2026, 3, 5, 10, 0, 0, tzinfo=timezone.utc)
    signals = [
        _make_signal(id=1, created_at=base, outcome="TP1_HIT", outcome_pnl_pct=Decimal("2.0")),
        _make_signal(id=2, created_at=base + timedelta(hours=1), outcome="SL_HIT", outcome_pnl_pct=Decimal("-1.0")),
        _make_signal(id=3, created_at=base + timedelta(days=1), outcome="TP2_HIT", outcome_pnl_pct=Decimal("4.0")),
    ]
    db, _ = _mock_db(scalars_all=signals)
    app = _make_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/signals/calendar?month=2026-03", headers=HEADERS)

    data = resp.json()
    assert len(data["days"]) == 2
    day1 = data["days"][0]
    assert day1["date"] == "2026-03-05"
    assert day1["signal_count"] == 2
    assert day1["net_pnl"] == 1.0
    assert day1["wins"] == 1
    assert day1["losses"] == 1

    summary = data["monthly_summary"]
    assert summary["total_signals"] == 3
    assert summary["net_pnl"] == 5.0


@pytest.mark.asyncio
async def test_calendar_empty_month():
    db, _ = _mock_db(scalars_all=[])
    app = _make_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/signals/calendar?month=2026-01", headers=HEADERS)

    data = resp.json()
    assert data["days"] == []
    assert data["monthly_summary"]["total_signals"] == 0
    assert data["monthly_summary"]["best_day"] is None


@pytest.mark.asyncio
async def test_calendar_month_boundary():
    # Signal on last day of March
    last_day = datetime(2026, 3, 31, 23, 30, 0, tzinfo=timezone.utc)
    signals = [
        _make_signal(id=1, created_at=last_day, outcome="TP1_HIT", outcome_pnl_pct=Decimal("1.5")),
    ]
    db, _ = _mock_db(scalars_all=signals)
    app = _make_app(db)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/signals/calendar?month=2026-03", headers=HEADERS)

    data = resp.json()
    assert len(data["days"]) == 1
    assert data["days"][0]["date"] == "2026-03-31"
