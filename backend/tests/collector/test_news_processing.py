"""Tests for news processing: LLM batch scoring and daily budget enforcement."""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.collector.news import score_headlines_with_llm, NewsCollector


# --- LLM batch scoring ---

@pytest.mark.asyncio
async def test_score_headlines_success():
    """LLM returns valid scores for a batch of headlines."""
    headlines = [
        {"headline": "Fed cuts rates", "source": "reuters"},
        {"headline": "BTC hits 100k", "source": "coindesk"},
    ]

    llm_response = json.dumps([
        {"impact": "high", "sentiment": "bullish", "summary": "Dovish signal"},
        {"impact": "medium", "sentiment": "bullish", "summary": "Milestone reached"},
    ])

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": llm_response}}],
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.collector.news.httpx.AsyncClient", return_value=mock_client):
        result = await score_headlines_with_llm(headlines, "test-key", "test-model")

    assert len(result) == 2
    assert result[0]["impact"] == "high"
    assert result[1]["sentiment"] == "bullish"


@pytest.mark.asyncio
async def test_score_headlines_no_api_key():
    """Without API key, returns empty dicts."""
    headlines = [{"headline": "test", "source": "test"}]
    result = await score_headlines_with_llm(headlines, "", "model")
    assert result == [{}]


@pytest.mark.asyncio
async def test_score_headlines_llm_failure():
    """When LLM call fails, returns empty dicts."""
    headlines = [{"headline": "test", "source": "test"}]

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("timeout"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.collector.news.httpx.AsyncClient", return_value=mock_client):
        result = await score_headlines_with_llm(headlines, "key", "model")

    assert result == [{}]


@pytest.mark.asyncio
async def test_score_headlines_empty_list():
    """Empty headline list returns empty list."""
    result = await score_headlines_with_llm([], "key", "model")
    assert result == []


@pytest.mark.asyncio
async def test_score_headlines_markdown_wrapped():
    """LLM response wrapped in markdown code block is parsed correctly."""
    headlines = [{"headline": "test", "source": "test"}]

    llm_response = '```json\n[{"impact": "low", "sentiment": "neutral", "summary": "No effect"}]\n```'

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": llm_response}}],
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.collector.news.httpx.AsyncClient", return_value=mock_client):
        result = await score_headlines_with_llm(headlines, "key", "model")

    assert result[0]["impact"] == "low"


# --- Daily budget enforcement ---

def test_budget_resets_on_new_day():
    """LLM call counter resets at midnight UTC."""
    from datetime import date

    collector = NewsCollector(
        pairs=["BTC-USDT-SWAP"],
        db=MagicMock(),
        redis=MagicMock(),
        ws_manager=MagicMock(),
        llm_daily_budget=200,
    )
    collector._llm_calls_today = 199
    # Simulate a new day
    collector._budget_reset_date = date(2020, 1, 1)
    collector._check_budget()
    assert collector._llm_calls_today == 0


def test_budget_no_reset_same_day():
    """Counter stays when date hasn't changed."""
    from datetime import datetime, timezone

    collector = NewsCollector(
        pairs=["BTC-USDT-SWAP"],
        db=MagicMock(),
        redis=MagicMock(),
        ws_manager=MagicMock(),
        llm_daily_budget=200,
    )
    collector._llm_calls_today = 150
    collector._budget_reset_date = datetime.now(timezone.utc).date()
    collector._check_budget()
    assert collector._llm_calls_today == 150
