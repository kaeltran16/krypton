"""Tests for pipeline monitor API endpoints."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import create_app


def _make_eval_row(
    id=1, pair="BTC-USDT-SWAP", timeframe="15m", emitted=False,
    final_score=25, effective_threshold=40, tech_score=30, flow_score=15,
    minutes_ago=10,
):
    """Build a mock PipelineEvaluation row."""
    row = MagicMock()
    row.id = id
    row.pair = pair
    row.timeframe = timeframe
    row.evaluated_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    row.emitted = emitted
    row.signal_id = 99 if emitted else None
    row.final_score = final_score
    row.effective_threshold = effective_threshold
    row.tech_score = tech_score
    row.flow_score = flow_score
    row.onchain_score = None
    row.pattern_score = 5
    row.liquidation_score = None
    row.confluence_score = 8
    row.indicator_preliminary = 28
    row.blended_score = 26
    row.ml_score = 0.6 if emitted else None
    row.ml_confidence = 0.7 if emitted else None
    row.llm_contribution = 3 if emitted else 0
    row.ml_agreement = "agree" if emitted else "neutral"
    row.indicators = {"adx": 28.5, "rsi": 55.2, "atr": 350.5}
    row.regime = {"trending": 0.4, "ranging": 0.35, "volatile": 0.25}
    row.availabilities = {
        "tech": {"availability": 1.0, "conviction": 0.85},
        "flow": {"availability": 1.0, "conviction": 0.6},
    }
    return row


@pytest.fixture
async def monitor_client():
    from tests.conftest import _test_lifespan
    app = create_app(lifespan_override=_test_lifespan)
    async with _test_lifespan(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac, app


def _cookies():
    from tests.conftest import make_test_jwt
    return {"krypton_token": make_test_jwt()}


@pytest.mark.asyncio
async def test_evaluations_returns_401_without_auth(monitor_client):
    client, _ = monitor_client
    resp = await client.get("/api/monitor/evaluations")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_evaluations_returns_empty_list(monitor_client):
    client, app = monitor_client

    mock_session = AsyncMock()
    # Query for items returns empty
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = []
    # Query for count returns 0
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    mock_session.execute = AsyncMock(side_effect=[items_result, count_result])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    app.state.db.session_factory = MagicMock(return_value=mock_session)

    resp = await client.get("/api/monitor/evaluations", cookies=_cookies())
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_evaluations_returns_items_with_filters(monitor_client):
    client, app = monitor_client

    rows = [_make_eval_row(id=1, emitted=False), _make_eval_row(id=2, emitted=True, final_score=50)]

    mock_session = AsyncMock()
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = rows
    count_result = MagicMock()
    count_result.scalar.return_value = 2
    mock_session.execute = AsyncMock(side_effect=[items_result, count_result])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    app.state.db.session_factory = MagicMock(return_value=mock_session)

    resp = await client.get(
        "/api/monitor/evaluations?pair=BTC-USDT-SWAP&limit=10",
        cookies=_cookies(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] == 2
    assert data["items"][0]["pair"] == "BTC-USDT-SWAP"
    assert data["items"][0]["indicators"]["adx"] == 28.5
    assert data["items"][0]["regime"]["trending"] == 0.4


@pytest.mark.asyncio
async def test_evaluations_limit_rejects_over_200(monitor_client):
    client, _ = monitor_client

    resp = await client.get(
        "/api/monitor/evaluations?limit=500",
        cookies=_cookies(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_summary_rejects_invalid_period(monitor_client):
    client, _ = monitor_client

    resp = await client.get("/api/monitor/summary?period=2h", cookies=_cookies())
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_summary_returns_401_without_auth(monitor_client):
    client, _ = monitor_client
    resp = await client.get("/api/monitor/summary")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_summary_returns_stats(monitor_client):
    client, app = monitor_client

    mock_session = AsyncMock()
    # Main aggregation query: total, emitted_count, avg_abs
    main_result = MagicMock()
    main_row = MagicMock(total=100, emitted_count=5, avg_abs=24.3)
    main_result.one.return_value = main_row
    # Per-pair query: list of (pair, total, emitted, avg_abs)
    pair_result = MagicMock()
    pair_result.all.return_value = [
        MagicMock(pair="BTC-USDT-SWAP", total=50, emitted_count=3, avg_abs=26.1),
        MagicMock(pair="ETH-USDT-SWAP", total=50, emitted_count=2, avg_abs=22.5),
    ]
    mock_session.execute = AsyncMock(side_effect=[main_result, pair_result])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    app.state.db.session_factory = MagicMock(return_value=mock_session)

    resp = await client.get("/api/monitor/summary?period=24h", cookies=_cookies())
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "24h"
    assert data["total_evaluations"] == 100
    assert data["emitted_count"] == 5
    assert data["emission_rate"] == pytest.approx(0.05)
    assert len(data["per_pair"]) >= 2


@pytest.mark.asyncio
async def test_persist_pipeline_evaluation_swallows_errors():
    """Best-effort persist must not propagate exceptions."""
    from app.main import persist_pipeline_evaluation

    mock_db = MagicMock()
    mock_session = AsyncMock()
    mock_session.add = MagicMock(side_effect=RuntimeError("db boom"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_db.session_factory = MagicMock(return_value=mock_session)

    # Must not raise
    await persist_pipeline_evaluation(mock_db, {
        "pair": "BTC-USDT-SWAP", "timeframe": "15m",
        "evaluated_at": datetime.now(timezone.utc), "emitted": False, "signal_id": None,
        "final_score": 25, "effective_threshold": 40, "tech_score": 30, "flow_score": 15,
        "onchain_score": None, "pattern_score": 5, "liquidation_score": None,
        "confluence_score": 8, "indicator_preliminary": 28, "blended_score": 26,
        "ml_score": None, "ml_confidence": None, "llm_contribution": 0,
        "ml_agreement": "neutral", "indicators": {"adx": 28.5},
        "regime": {"trending": 0.4, "ranging": 0.35, "volatile": 0.25},
        "availabilities": {"tech": {"availability": 1.0, "conviction": 0.85}},
    })
