import pytest
from pydantic import ValidationError
from app.engine.models import (
    FactorType, FactorCategory, LLMFactor, LLMResponse, LLMResult,
    FACTOR_CATEGORIES, DEFAULT_FACTOR_WEIGHTS,
)


def test_factor_type_enum_has_12_members():
    assert len(FactorType) == 12


def test_factor_categories_maps_all_types():
    for ft in FactorType:
        assert ft in FACTOR_CATEGORIES


def test_llm_factor_valid():
    f = LLMFactor(type="rsi_divergence", direction="bullish", strength=2, reason="RSI higher lows")
    assert f.type == FactorType.RSI_DIVERGENCE
    assert f.strength == 2


def test_llm_factor_invalid_strength():
    with pytest.raises(ValidationError):
        LLMFactor(type="rsi_divergence", direction="bullish", strength=4, reason="bad")


def test_llm_factor_invalid_type():
    with pytest.raises(ValidationError):
        LLMFactor(type="made_up_factor", direction="bullish", strength=1, reason="bad")


def test_llm_factor_invalid_direction():
    with pytest.raises(ValidationError):
        LLMFactor(type="rsi_divergence", direction="neutral", strength=1, reason="bad")


def test_llm_response_valid():
    r = LLMResponse(
        factors=[LLMFactor(type="rsi_divergence", direction="bullish", strength=2, reason="test")],
        explanation="Test explanation",
    )
    assert len(r.factors) == 1
    assert r.levels is None


def test_llm_response_with_levels():
    from app.engine.models import LLMLevels
    r = LLMResponse(
        factors=[LLMFactor(type="level_breakout", direction="bullish", strength=3, reason="broke key level")],
        explanation="Breakout confirmed",
        levels=LLMLevels(entry=67000, stop_loss=66200, take_profit_1=67800, take_profit_2=68600),
    )
    assert r.levels.entry == 67000


def test_llm_result_has_token_fields():
    r = LLMResult(
        response=LLMResponse(
            factors=[LLMFactor(type="rsi_divergence", direction="bullish", strength=1, reason="test")],
            explanation="test",
        ),
        prompt_tokens=1250,
        completion_tokens=180,
        model="anthropic/claude-3.5-sonnet",
    )
    assert r.prompt_tokens == 1250
    assert r.model == "anthropic/claude-3.5-sonnet"


def test_default_factor_weights_has_all_types():
    for ft in FactorType:
        assert ft.value in DEFAULT_FACTOR_WEIGHTS
