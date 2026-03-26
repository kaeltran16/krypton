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
from app.engine.models import FactorType


@pytest.fixture
def prompt_file(tmp_path):
    template = """Analyze the following crypto futures data for {pair} on {timeframe} timeframe.

Technical Indicators:
{indicators}

Order Flow:
{order_flow}

Patterns:
{patterns}

On-chain:
{onchain}

ML Context:
{ml_context}

News:
{news}

Preliminary Score: {preliminary_score} (positive = bullish, negative = bearish)
Blended Score: {blended_score}
Agreement: {agreement}

Recent Candles (last 20):
{candles}

Return 1-5 factors as JSON."""
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
        patterns="No patterns detected.",
        onchain="On-chain data not available.",
        ml_context="ML model not available.",
        news="No recent news.",
        preliminary_score="72",
        blended_score="72",
        agreement="neutral",
        candles="[candle data here]",
    )
    assert "BTC-USDT-SWAP" in rendered
    assert "RSI: 32" in rendered
    assert "{pair}" not in rendered


def test_parse_llm_response_valid_factors():
    content = '{"factors": [{"type": "rsi_divergence", "direction": "bullish", "strength": 2, "reason": "RSI higher lows"}], "explanation": "Divergence forming.", "levels": {"entry": 67420, "stop_loss": 66890, "take_profit_1": 67950, "take_profit_2": 68480}}'
    result = parse_llm_response(content)
    assert result is not None
    assert len(result.factors) == 1
    assert result.factors[0].type == FactorType.RSI_DIVERGENCE
    assert result.levels.entry == 67420


def test_parse_llm_response_with_code_fences():
    content = '```json\n{"factors": [{"type": "level_breakout", "direction": "bullish", "strength": 3, "reason": "Broke resistance"}], "explanation": "Clean breakout.", "levels": null}\n```'
    result = parse_llm_response(content)
    assert result is not None
    assert result.factors[0].type == FactorType.LEVEL_BREAKOUT
    assert result.levels is None


def test_parse_llm_response_invalid():
    result = parse_llm_response("This is not JSON at all")
    assert result is None


def test_parse_llm_response_empty_factors():
    """Empty factors list returns None."""
    content = '{"factors": [], "explanation": "Nothing to say."}'
    result = parse_llm_response(content)
    assert result is None


def test_parse_llm_response_unknown_factor_type():
    """Unknown factor type returns None."""
    content = '{"factors": [{"type": "made_up", "direction": "bullish", "strength": 1, "reason": "x"}], "explanation": "x"}'
    result = parse_llm_response(content)
    assert result is None


def test_parse_llm_response_invalid_strength():
    """Strength outside [1,2,3] returns None."""
    content = '{"factors": [{"type": "rsi_divergence", "direction": "bullish", "strength": 5, "reason": "x"}], "explanation": "x"}'
    result = parse_llm_response(content)
    assert result is None


def test_parse_llm_response_truncates_to_5_factors():
    """More than 5 factors truncated to 5."""
    factors = [{"type": "rsi_divergence", "direction": "bullish", "strength": 1, "reason": f"r{i}"} for i in range(7)]
    import json
    content = json.dumps({"factors": factors, "explanation": "many factors"})
    result = parse_llm_response(content)
    assert result is not None
    assert len(result.factors) == 5


def test_parse_llm_response_missing_factors():
    """Missing factors field returns None."""
    content = '{"explanation": "No factors here"}'
    result = parse_llm_response(content)
    assert result is None


async def test_call_openrouter_success():
    """Successful API call returns LLMResult with token usage."""
    mock_response = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"factors": [{"type": "rsi_divergence", "direction": "bullish", "strength": 2, "reason": "RSI diverging"}], "explanation": "Looks good.", "levels": null}'}}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 150},
            "model": "anthropic/claude-3.5-sonnet",
        },
    )
    mock_response.request = httpx.Request("POST", OPENROUTER_URL)
    with patch("app.engine.llm.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _mock_async_client(post_return=mock_response)
        result = await call_openrouter("test prompt", "fake-key", "test-model")
        assert result is not None
        assert result.response.factors[0].type.value == "rsi_divergence"
        assert result.prompt_tokens == 800
        assert result.completion_tokens == 150


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
