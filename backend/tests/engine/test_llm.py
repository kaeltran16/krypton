from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.engine.llm import (
    OPENROUTER_URL,
    call_openrouter,
    load_prompt_template,
    parse_llm_response,
    render_prompt,
)


@pytest.fixture
def prompt_file(tmp_path):
    template = """Analyze the following crypto futures data for {pair} on {timeframe} timeframe.

Technical Indicators:
{indicators}

Order Flow:
{order_flow}

Preliminary Score: {preliminary_score} ({direction})

Recent Candles (last 20):
{candles}

Respond in JSON:
{{"opinion": "confirm|caution|contradict", "confidence": "HIGH|MEDIUM|LOW", "explanation": "...", "levels": {{"entry": 0, "stop_loss": 0, "take_profit_1": 0, "take_profit_2": 0}}}}"""
    f = tmp_path / "signal_analysis.txt"
    f.write_text(template)
    return f


def _mock_async_client(post_return=None, post_side_effect=None):
    """Create a mock httpx.AsyncClient with async context manager support."""
    mock_client = AsyncMock()
    if post_side_effect:
        mock_client.post.side_effect = post_side_effect
    else:
        mock_client.post.return_value = post_return
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def test_load_prompt_template(prompt_file):
    """Load a prompt template from file."""
    template = load_prompt_template(prompt_file)
    assert "{pair}" in template
    assert "{indicators}" in template


def test_render_prompt(prompt_file):
    """Render prompt with placeholder substitution."""
    template = load_prompt_template(prompt_file)
    rendered = render_prompt(
        template=template,
        pair="BTC-USDT-SWAP",
        timeframe="15m",
        indicators="RSI: 32, EMA9: 67100",
        order_flow="Funding: 0.0001, L/S: 1.2",
        preliminary_score="72",
        direction="LONG",
        candles="[candle data here]",
    )
    assert "BTC-USDT-SWAP" in rendered
    assert "RSI: 32" in rendered
    assert "{pair}" not in rendered


def test_parse_llm_response_valid_json():
    content = '{"opinion": "confirm", "confidence": "HIGH", "explanation": "Strong setup.", "levels": {"entry": 67420, "stop_loss": 66890, "take_profit_1": 67950, "take_profit_2": 68480}}'
    result = parse_llm_response(content)
    assert result is not None
    assert result.opinion == "confirm"
    assert result.levels.entry == 67420


def test_parse_llm_response_with_code_fences():
    content = '```json\n{"opinion": "caution", "confidence": "MEDIUM", "explanation": "Watch out.", "levels": null}\n```'
    result = parse_llm_response(content)
    assert result is not None
    assert result.opinion == "caution"
    assert result.levels is None


def test_parse_llm_response_invalid():
    result = parse_llm_response("This is not JSON at all")
    assert result is None


def test_parse_llm_response_missing_fields():
    content = '{"opinion": "confirm"}'
    result = parse_llm_response(content)
    assert result is None


def test_parse_llm_response_invalid_opinion():
    """Invalid opinion value should be rejected by Literal validation."""
    content = '{"opinion": "agree", "confidence": "HIGH", "explanation": "Strong."}'
    result = parse_llm_response(content)
    assert result is None


async def test_call_openrouter_success():
    """Successful API call returns parsed LLMResponse."""
    mock_response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": '{"opinion": "confirm", "confidence": "HIGH", "explanation": "Looks good.", "levels": null}'
                    }
                }
            ]
        },
    )
    mock_response.request = httpx.Request("POST", OPENROUTER_URL)
    with patch("app.engine.llm.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _mock_async_client(post_return=mock_response)
        result = await call_openrouter("test prompt", "fake-key", "test-model")
        assert result is not None
        assert result.opinion == "confirm"


async def test_call_openrouter_timeout():
    """Timeout returns None gracefully."""
    with patch("app.engine.llm.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _mock_async_client(
            post_side_effect=httpx.TimeoutException("timed out"),
        )
        result = await call_openrouter("test prompt", "fake-key", "test-model")
        assert result is None


async def test_call_openrouter_api_error():
    """HTTP error returns None gracefully."""
    mock_response = httpx.Response(500, text="Internal Server Error")
    mock_response.request = httpx.Request("POST", OPENROUTER_URL)
    with patch("app.engine.llm.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _mock_async_client(post_return=mock_response)
        result = await call_openrouter("test prompt", "fake-key", "test-model")
        assert result is None
