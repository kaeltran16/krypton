"""Unit tests for news sentiment scorer."""

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.news_scorer import compute_news_score, _recency_weight


# ── recency weight ──


def test_recency_weight_at_zero():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _recency_weight(now, now) == pytest.approx(1.0)


def test_recency_weight_at_half_life():
    now = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    published = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert _recency_weight(published, now, half_life_minutes=60.0) == pytest.approx(0.5, rel=1e-3)


def test_recency_weight_decays():
    now = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    published = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    w = _recency_weight(published, now, half_life_minutes=60.0)
    assert w == pytest.approx(0.25, rel=1e-3)


# ── compute_news_score ──


def _make_event(sentiment="bullish", impact="high", minutes_ago=10, now=None):
    if now is None:
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    return MagicMock(
        sentiment=sentiment,
        impact=impact,
        published_at=now - timedelta(minutes=minutes_ago),
    )


def _mock_db(events):
    """Create a mock db that returns events from session.execute."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = events

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    db = MagicMock()
    db.session_factory.return_value = mock_session
    return db


_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_no_events_returns_zero():
    db = _mock_db([])
    result = await compute_news_score("BTC-USDT-SWAP", db, _now=_NOW)
    assert result["score"] == 0
    assert result["availability"] == 0.0
    assert result["conviction"] == 0.0


@pytest.mark.asyncio
async def test_single_bullish_event():
    events = [_make_event("bullish", "high", minutes_ago=5, now=_NOW)]
    db = _mock_db(events)
    result = await compute_news_score("BTC-USDT-SWAP", db, _now=_NOW)
    assert result["score"] > 0
    assert result["details"]["bullish_count"] == 1
    assert result["details"]["bearish_count"] == 0


@pytest.mark.asyncio
async def test_single_bearish_event():
    events = [_make_event("bearish", "high", minutes_ago=5, now=_NOW)]
    db = _mock_db(events)
    result = await compute_news_score("BTC-USDT-SWAP", db, _now=_NOW)
    assert result["score"] < 0
    assert result["details"]["bearish_count"] == 1


@pytest.mark.asyncio
async def test_mixed_sentiment_reduces_score():
    events = [
        _make_event("bullish", "high", minutes_ago=5, now=_NOW),
        _make_event("bearish", "high", minutes_ago=5, now=_NOW),
    ]
    db = _mock_db(events)
    result = await compute_news_score("BTC-USDT-SWAP", db, _now=_NOW)
    assert abs(result["score"]) < 10


@pytest.mark.asyncio
async def test_volume_scaling():
    """More articles should produce higher absolute scores."""
    one_event = [_make_event("bullish", "high", minutes_ago=5, now=_NOW)]
    five_events = [_make_event("bullish", "high", minutes_ago=5, now=_NOW) for _ in range(5)]

    db1 = _mock_db(one_event)
    db5 = _mock_db(five_events)

    r1 = await compute_news_score("BTC-USDT-SWAP", db1, _now=_NOW)
    r5 = await compute_news_score("BTC-USDT-SWAP", db5, _now=_NOW)

    assert r5["score"] >= r1["score"]
    assert r5["details"]["volume_scale"] >= r1["details"]["volume_scale"]


@pytest.mark.asyncio
async def test_impact_weighting():
    """High impact should weigh more than low impact."""
    high = [_make_event("bullish", "high", minutes_ago=5, now=_NOW)]
    low = [_make_event("bullish", "low", minutes_ago=5, now=_NOW)]

    db_high = _mock_db(high)
    db_low = _mock_db(low)

    r_high = await compute_news_score("BTC-USDT-SWAP", db_high, _now=_NOW)
    r_low = await compute_news_score("BTC-USDT-SWAP", db_low, _now=_NOW)

    assert r_high["score"] > 0
    assert r_low["score"] > 0


@pytest.mark.asyncio
async def test_conviction_unanimous():
    events = [_make_event("bullish", "high", minutes_ago=5, now=_NOW) for _ in range(3)]
    db = _mock_db(events)
    result = await compute_news_score("BTC-USDT-SWAP", db, _now=_NOW)
    assert result["conviction"] == 1.0


@pytest.mark.asyncio
async def test_conviction_split():
    events = [
        _make_event("bullish", "high", minutes_ago=5, now=_NOW),
        _make_event("bearish", "high", minutes_ago=5, now=_NOW),
    ]
    db = _mock_db(events)
    result = await compute_news_score("BTC-USDT-SWAP", db, _now=_NOW)
    assert result["conviction"] == 0.5


@pytest.mark.asyncio
async def test_score_clamped():
    events = [_make_event("bullish", "high", minutes_ago=1, now=_NOW) for _ in range(20)]
    db = _mock_db(events)
    result = await compute_news_score("BTC-USDT-SWAP", db, _now=_NOW)
    assert -100 <= result["score"] <= 100


@pytest.mark.asyncio
async def test_db_error_returns_zero():
    db = MagicMock()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("db error"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    db.session_factory.return_value = mock_session

    result = await compute_news_score("BTC-USDT-SWAP", db, _now=_NOW)
    assert result["score"] == 0
    assert result["availability"] == 0.0
