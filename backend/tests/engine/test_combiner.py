import pytest
from app.engine.models import LLMResponse
from app.engine.combiner import (
    compute_preliminary_score,
    compute_final_score,
    calculate_levels,
    blend_with_ml,
    compute_agreement,
)


# ── compute_preliminary_score ──


def test_preliminary_score_weighted():
    """Preliminary score with default 4-way weights (40/22/23/15)."""
    result = compute_preliminary_score(
        technical_score=80, order_flow_score=60, onchain_score=40, pattern_score=50,
    )
    expected = round(80 * 0.40 + 60 * 0.22 + 40 * 0.23 + 50 * 0.15)
    assert result == expected


def test_preliminary_score_two_way_backward_compat():
    """When onchain_score=0 and weights adjusted, behaves like 2-way."""
    result = compute_preliminary_score(
        technical_score=80, order_flow_score=50,
        tech_weight=0.60, flow_weight=0.40,
        onchain_score=0, onchain_weight=0.0,
        pattern_weight=0.0,
    )
    expected = round(80 * 0.60 + 50 * 0.40)
    assert result == expected


def test_preliminary_score_auto_normalization():
    """Weights that don't sum to 1.0 get auto-normalized."""
    result = compute_preliminary_score(
        technical_score=100, order_flow_score=100, onchain_score=100, pattern_score=100,
        tech_weight=0.50, flow_weight=0.50, onchain_weight=0.50, pattern_weight=0.50,
    )
    assert result == 100


def test_preliminary_score_custom_weights():
    """Custom weights with all four components."""
    result = compute_preliminary_score(
        technical_score=70, order_flow_score=50, onchain_score=30, pattern_score=60,
        tech_weight=0.50, flow_weight=0.20, onchain_weight=0.15, pattern_weight=0.15,
    )
    expected = round(70 * 0.50 + 50 * 0.20 + 30 * 0.15 + 60 * 0.15)
    assert result == expected


# ── blend_with_ml ──


def test_blend_with_ml_score_contributes():
    """ML score blends with indicator preliminary when confidence is above threshold."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=80.0, ml_confidence=0.80,
        ml_weight=0.25, ml_confidence_threshold=0.65,
    )
    expected = round(60 * 0.75 + 80.0 * 0.25)
    assert result == expected


def test_blend_with_ml_below_threshold():
    """ML score ignored when confidence below threshold."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=80.0, ml_confidence=0.50,
        ml_weight=0.25, ml_confidence_threshold=0.65,
    )
    assert result == 60


def test_blend_with_ml_none_score():
    """ML score None returns indicator preliminary unchanged."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=None, ml_confidence=None,
    )
    assert result == 60


def test_blend_with_ml_zero_weight():
    """ML weight 0 means no ML contribution."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=80.0, ml_confidence=0.90,
        ml_weight=0.0, ml_confidence_threshold=0.65,
    )
    assert result == 60


def test_blend_with_ml_bounded():
    """Blended score is clamped to -100..+100."""
    result = blend_with_ml(
        indicator_preliminary=95, ml_score=100.0, ml_confidence=0.99,
        ml_weight=0.5, ml_confidence_threshold=0.65,
    )
    assert -100 <= result <= 100


def test_blend_with_ml_negative_scores():
    """Blending works for SHORT (negative) scores."""
    result = blend_with_ml(
        indicator_preliminary=-50, ml_score=-75.0, ml_confidence=0.75,
        ml_weight=0.25, ml_confidence_threshold=0.65,
    )
    expected = round(-50 * 0.75 + -75.0 * 0.25)
    assert result == expected


def test_blend_with_ml_disagreement():
    """Indicators positive, ML negative — blend dampens."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=-80.0, ml_confidence=0.80,
        ml_weight=0.25, ml_confidence_threshold=0.65,
    )
    expected = round(60 * 0.75 + (-80.0) * 0.25)
    assert result == expected
    assert result < 60  # dampened by disagreement


# ── compute_agreement ──


def test_agreement_both_positive():
    assert compute_agreement(40, 60.0) == "agree"


def test_agreement_both_negative():
    assert compute_agreement(-30, -50.0) == "agree"


def test_agreement_opposite_signs():
    assert compute_agreement(40, -60.0) == "disagree"


def test_agreement_opposite_signs_reversed():
    assert compute_agreement(-40, 60.0) == "disagree"


def test_agreement_indicator_zero():
    assert compute_agreement(0, 50.0) == "neutral"


def test_agreement_ml_zero():
    assert compute_agreement(40, 0.0) == "neutral"


def test_agreement_ml_none():
    assert compute_agreement(40, None) == "neutral"


# ── compute_final_score ──


def test_final_score_with_confirm():
    llm = LLMResponse(opinion="confirm", confidence="HIGH", explanation="Looks good", levels=None)
    final = compute_final_score(preliminary_score=60, llm_response=llm)
    assert final > 60


def test_final_score_with_caution():
    llm = LLMResponse(opinion="caution", confidence="HIGH", explanation="Be careful", levels=None)
    final = compute_final_score(preliminary_score=60, llm_response=llm)
    assert final < 60


def test_final_score_with_contradict():
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="No way", levels=None)
    final = compute_final_score(preliminary_score=80, llm_response=llm)
    assert final <= 40


def test_final_score_with_contradict_negative():
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Not that bad", levels=None)
    final = compute_final_score(preliminary_score=-80, llm_response=llm)
    assert final >= -40


def test_final_score_without_llm():
    final = compute_final_score(preliminary_score=65, llm_response=None)
    assert final == 65


def test_final_score_bounded():
    llm = LLMResponse(opinion="confirm", confidence="HIGH", explanation="Max boost", levels=None)
    final = compute_final_score(preliminary_score=95, llm_response=llm)
    assert -100 <= final <= 100


# ── calculate_levels ──


def test_calculate_levels_atr_defaults_long():
    """ATR-based levels: SL at 1.5x ATR, TP1 at 2x, TP2 at 3x."""
    levels = calculate_levels(direction="LONG", current_price=67000.0, atr=200.0)
    assert levels["entry"] == 67000.0
    assert levels["stop_loss"] == 67000.0 - 1.5 * 200.0
    assert levels["take_profit_1"] == 67000.0 + 2.0 * 200.0
    assert levels["take_profit_2"] == 67000.0 + 3.0 * 200.0


def test_calculate_levels_atr_defaults_short():
    """Short direction flips SL/TP."""
    levels = calculate_levels(direction="SHORT", current_price=67000.0, atr=200.0)
    assert levels["stop_loss"] == 67000.0 + 1.5 * 200.0
    assert levels["take_profit_1"] == 67000.0 - 2.0 * 200.0
    assert levels["take_profit_2"] == 67000.0 - 3.0 * 200.0


def test_calculate_levels_llm_override():
    """Valid LLM levels take priority over everything."""
    llm_levels = {
        "entry": 67000.0,
        "stop_loss": 66500.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68000.0,
    }
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        llm_levels=llm_levels,
        ml_atr_multiples={"sl_atr": 1.0, "tp1_atr": 1.5, "tp2_atr": 2.5},
    )
    assert levels == llm_levels


def test_calculate_levels_rejects_invalid_llm_levels():
    """LLM levels with SL above entry for LONG should fall back."""
    bad_levels = {
        "entry": 67000.0,
        "stop_loss": 68000.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68000.0,
    }
    levels = calculate_levels(direction="LONG", current_price=67000.0, atr=200.0, llm_levels=bad_levels)
    assert levels["stop_loss"] < levels["entry"]


def test_calculate_levels_ml_regression():
    """ML regression multiples are used when no valid LLM levels."""
    ml_multiples = {"sl_atr": 1.2, "tp1_atr": 2.5, "tp2_atr": 4.0}
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        ml_atr_multiples=ml_multiples,
    )
    assert levels["entry"] == 67000.0
    assert levels["stop_loss"] == 67000.0 - 1.2 * 200.0
    assert levels["take_profit_1"] == 67000.0 + 2.5 * 200.0
    assert levels["take_profit_2"] == 67000.0 + 4.0 * 200.0


def test_calculate_levels_ml_sl_clamped_min():
    """SL clamped to minimum bound."""
    ml_multiples = {"sl_atr": 0.1, "tp1_atr": 2.0, "tp2_atr": 3.0}
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        ml_atr_multiples=ml_multiples,
        sl_bounds=(0.5, 3.0),
    )
    expected_sl = 67000.0 - 0.5 * 200.0
    assert levels["stop_loss"] == expected_sl


def test_calculate_levels_ml_sl_clamped_max():
    """SL clamped to maximum bound."""
    ml_multiples = {"sl_atr": 5.0, "tp1_atr": 2.0, "tp2_atr": 6.0}
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        ml_atr_multiples=ml_multiples,
        sl_bounds=(0.5, 3.0),
    )
    expected_sl = 67000.0 - 3.0 * 200.0
    assert levels["stop_loss"] == expected_sl


def test_calculate_levels_ml_tp1_min():
    """TP1 clamped to minimum."""
    ml_multiples = {"sl_atr": 1.0, "tp1_atr": 0.5, "tp2_atr": 3.0}
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        ml_atr_multiples=ml_multiples,
        tp1_min_atr=1.0,
    )
    expected_tp1 = 67000.0 + 1.0 * 200.0
    assert levels["take_profit_1"] == expected_tp1


def test_calculate_levels_ml_tp2_min_relative():
    """TP2 must be at least TP1 * 1.2."""
    ml_multiples = {"sl_atr": 1.0, "tp1_atr": 2.0, "tp2_atr": 2.1}
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        ml_atr_multiples=ml_multiples,
    )
    # TP2 should be bumped to at least 2.0 * 1.2 = 2.4
    expected_tp2 = 67000.0 + 2.4 * 200.0
    assert levels["take_profit_2"] == expected_tp2


def test_calculate_levels_ml_tp2_max():
    """TP2 clamped to maximum."""
    ml_multiples = {"sl_atr": 1.0, "tp1_atr": 2.0, "tp2_atr": 10.0}
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        ml_atr_multiples=ml_multiples,
        tp2_max_atr=8.0,
    )
    expected_tp2 = 67000.0 + 8.0 * 200.0
    assert levels["take_profit_2"] == expected_tp2


def test_calculate_levels_ml_rr_floor():
    """Risk/reward floor: TP1/SL >= rr_floor."""
    ml_multiples = {"sl_atr": 2.0, "tp1_atr": 1.5, "tp2_atr": 4.0}
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        ml_atr_multiples=ml_multiples,
        rr_floor=1.0,
    )
    # TP1 should be bumped to SL * rr_floor = 2.0
    expected_tp1 = 67000.0 + 2.0 * 200.0
    assert levels["take_profit_1"] == expected_tp1


def test_calculate_levels_caution_tightens_sl_ml():
    """LLM caution tightens SL when using ML multiples."""
    ml_multiples = {"sl_atr": 2.0, "tp1_atr": 3.0, "tp2_atr": 5.0}
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        ml_atr_multiples=ml_multiples,
        llm_opinion="caution",
        caution_sl_factor=0.8,
    )
    expected_sl = 67000.0 - (2.0 * 0.8) * 200.0
    assert levels["stop_loss"] == expected_sl


def test_calculate_levels_caution_tightens_sl_atr_defaults():
    """LLM caution tightens SL when using ATR defaults."""
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        llm_opinion="caution",
        caution_sl_factor=0.8,
    )
    expected_sl = 67000.0 - (1.5 * 0.8) * 200.0
    assert levels["stop_loss"] == expected_sl


def test_calculate_levels_caution_no_effect_with_llm_levels():
    """Caution does not apply when LLM provides explicit levels."""
    llm_levels = {
        "entry": 67000.0,
        "stop_loss": 66500.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68000.0,
    }
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        llm_levels=llm_levels,
        llm_opinion="caution",
        caution_sl_factor=0.8,
    )
    # LLM levels used as-is, no tightening
    assert levels["stop_loss"] == 66500.0


def test_calculate_levels_ml_short_direction():
    """ML levels work correctly for SHORT direction."""
    ml_multiples = {"sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0}
    levels = calculate_levels(
        direction="SHORT", current_price=67000.0, atr=200.0,
        ml_atr_multiples=ml_multiples,
    )
    assert levels["stop_loss"] == 67000.0 + 1.5 * 200.0
    assert levels["take_profit_1"] == 67000.0 - 2.0 * 200.0
    assert levels["take_profit_2"] == 67000.0 - 3.0 * 200.0
