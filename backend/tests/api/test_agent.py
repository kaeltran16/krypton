from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_post_analysis_requires_agent_key(client):
    resp = await client.post(
        "/api/agent/analysis",
        json={"type": "brief", "narrative": "test"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_analysis_rejects_invalid_key(client):
    resp = await client.post(
        "/api/agent/analysis",
        json={"type": "brief", "narrative": "test"},
        headers={"X-Agent-Key": "wrong-key"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_analysis_validates_type(client):
    resp = await client.post(
        "/api/agent/analysis",
        json={"type": "invalid_type", "narrative": "test"},
        headers={"X-Agent-Key": "test-agent-key"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_analysis_strips_html_from_reasoning(client, app):
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    saved_row = MagicMock()
    saved_row.id = 1
    saved_row.type = "brief"
    saved_row.pair = None
    saved_row.narrative = "clean text"
    saved_row.annotations = [
        {
            "type": "level",
            "pair": "BTC-USDT-SWAP",
            "reasoning": "safe text",
            "label": "Support",
        }
    ]
    saved_row.metadata_ = {}
    saved_row.created_at = datetime.now(timezone.utc)

    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock(
        side_effect=lambda row: row.__dict__.update(saved_row.__dict__)
    )

    app.state.db.session_factory = MagicMock(return_value=mock_session)
    app.state.manager.broadcast_event = AsyncMock()

    resp = await client.post(
        "/api/agent/analysis",
        json={
            "type": "brief",
            "narrative": "<script>alert('xss')</script>clean text",
            "annotations": [
                {
                    "type": "level",
                    "pair": "BTC-USDT-SWAP",
                    "reasoning": "<img onerror=alert(1)>safe text",
                    "label": "Support",
                    "price": 65000,
                    "style": "solid",
                    "color": "#ff0000",
                }
            ],
        },
        headers={"X-Agent-Key": "test-agent-key"},
    )

    assert resp.status_code == 200
    call_args = mock_session.add.call_args[0][0]
    assert "<script>" not in call_args.narrative
    assert "<img" not in call_args.annotations[0]["reasoning"]


@pytest.mark.asyncio
async def test_get_analysis_requires_auth(client):
    resp = await client.get("/api/agent/analysis")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_analysis_returns_rows(client, app, auth_cookies):
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    row = MagicMock()
    row.id = 1
    row.type = "brief"
    row.pair = None
    row.narrative = "Market is bullish"
    row.annotations = []
    row.metadata_ = {"focus": "BTC"}
    row.created_at = datetime.now(timezone.utc)

    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = [row]
    mock_session.execute = AsyncMock(return_value=execute_result)

    app.state.db.session_factory = MagicMock(return_value=mock_session)

    resp = await client.get("/api/agent/analysis", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["type"] == "brief"
    assert data[0]["metadata"]["focus"] == "BTC"


@pytest.mark.asyncio
async def test_post_analysis_success(client, app):
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    saved_row = MagicMock()
    saved_row.id = 1
    saved_row.type = "brief"
    saved_row.pair = None
    saved_row.narrative = "Market is bullish"
    saved_row.annotations = []
    saved_row.metadata_ = {"focus": "BTC"}
    saved_row.created_at = datetime.now(timezone.utc)

    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock(
        side_effect=lambda row: row.__dict__.update(saved_row.__dict__)
    )

    app.state.db.session_factory = MagicMock(return_value=mock_session)
    app.state.manager.broadcast_event = AsyncMock()

    resp = await client.post(
        "/api/agent/analysis",
        json={
            "type": "brief",
            "narrative": "Market is bullish",
            "annotations": [],
            "metadata": {"focus": "BTC"},
        },
        headers={"X-Agent-Key": "test-agent-key"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "brief"
    assert data["narrative"] == "Market is bullish"
    app.state.manager.broadcast_event.assert_awaited_once()
    broadcast_payload = app.state.manager.broadcast_event.call_args[0][0]
    assert broadcast_payload["type"] == "agent_analysis"


@pytest.mark.asyncio
async def test_post_analysis_caps_annotations_at_30(client, app):
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    saved_row = MagicMock()
    saved_row.id = 1
    saved_row.type = "brief"
    saved_row.pair = None
    saved_row.narrative = "test"
    saved_row.annotations = [
        {"type": "level", "pair": "BTC-USDT-SWAP", "reasoning": "x"}
    ] * 30
    saved_row.metadata_ = {}
    saved_row.created_at = datetime.now(timezone.utc)

    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock(
        side_effect=lambda row: row.__dict__.update(saved_row.__dict__)
    )

    app.state.db.session_factory = MagicMock(return_value=mock_session)
    app.state.manager.broadcast_event = AsyncMock()

    annotations = [
        {
            "type": "level",
            "pair": "BTC-USDT-SWAP",
            "reasoning": f"level {i}",
            "label": f"L{i}",
            "price": 60000 + i,
            "style": "solid",
            "color": "#fff",
        }
        for i in range(35)
    ]

    resp = await client.post(
        "/api/agent/analysis",
        json={"type": "brief", "narrative": "test", "annotations": annotations},
        headers={"X-Agent-Key": "test-agent-key"},
    )

    assert resp.status_code == 200
    call_args = mock_session.add.call_args[0][0]
    assert len(call_args.annotations) <= 30
