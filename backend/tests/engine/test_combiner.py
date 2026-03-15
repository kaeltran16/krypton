import pytest
from app.engine.models import LLMResponse
from app.engine.combiner import (
    compute_preliminary_score,
    compute_final_score,
    calculate_levels,
    blend_with_ml,
    compute_agreement,
    scale_atr_multipliers,
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
    assert final == 50  # 80 - 1 * min(30, 80) * 1.0 = 50


def test_final_score_with_contradict_negative():
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Not that bad", levels=None)
    final = compute_final_score(preliminary_score=-80, llm_response=llm)
    assert final == -50  # -80 - (-1) * min(30, 80) * 1.0 = -50


def test_final_score_with_contradict_medium():
    llm = LLMResponse(opinion="contradict", confidence="MEDIUM", explanation="Meh", levels=None)
    final = compute_final_score(preliminary_score=80, llm_response=llm)
    assert final == 62  # 80 - 1 * min(18, 80) * 1.0 = 62 (multiplier 0.6: 30*0.6=18)


def test_final_score_with_contradict_zero():
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Zero", levels=None)
    final = compute_final_score(preliminary_score=0, llm_response=llm)
    assert final == 0  # zero guard: no directional bias


def test_final_score_with_contradict_clamps_at_zero():
    """Penalty larger than abs(score) clamps to zero instead of flipping sign."""
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Disagree", levels=None)
    final = compute_final_score(preliminary_score=20, llm_response=llm)
    assert final == 0  # 20 - 1 * min(30, 20) * 1.0 = 0 (clamped, not -10)


def test_final_score_with_contradict_clamps_at_zero_negative():
    """Negative score: penalty clamps to zero instead of flipping to positive."""
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Disagree", levels=None)
    final = compute_final_score(preliminary_score=-25, llm_response=llm)
    assert final == 0  # -25 - (-1) * min(30, 25) * 1.0 = 0 (clamped, not +5)


def test_final_score_with_contradict_borderline_emission():
    """Score of 70 with HIGH contradict lands exactly at threshold=40."""
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Doubt", levels=None)
    final = compute_final_score(preliminary_score=70, llm_response=llm)
    assert final == 40  # 70 - 1 * min(30, 70) * 1.0 = 40 (borderline emit)


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
    assert levels == {**llm_levels, "levels_source": "llm"}


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


# ── scale_atr_multipliers ──


def test_scale_at_threshold_minimum():
    """Score exactly at threshold -> t=0 -> all factors = 0.8."""
    result = scale_atr_multipliers(
        score=40, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
        signal_threshold=40,
    )
    # t=0 -> sl_strength=0.8, tp_strength=0.8, vol_factor=1.0 (50th pct)
    assert result["sl_strength_factor"] == 0.8
    assert result["tp_strength_factor"] == 0.8
    assert result["vol_factor"] == 1.0
    assert round(result["sl_atr"], 4) == round(1.5 * 0.8 * 1.0, 4)
    assert round(result["tp1_atr"], 4) == round(2.0 * 0.8 * 1.0, 4)
    assert round(result["tp2_atr"], 4) == round(3.0 * 0.8 * 1.0, 4)


def test_scale_at_max_score():
    """Score=100 -> t=1.0 -> sl_strength=1.2, tp_strength=1.4."""
    result = scale_atr_multipliers(
        score=100, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
        signal_threshold=40,
    )
    assert result["sl_strength_factor"] == 1.2
    assert result["tp_strength_factor"] == 1.4
    assert result["vol_factor"] == 1.0


def test_scale_negative_score_uses_abs():
    """Negative score uses abs(score) for t calculation."""
    pos = scale_atr_multipliers(
        score=65, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    neg = scale_atr_multipliers(
        score=-65, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    assert pos["sl_strength_factor"] == neg["sl_strength_factor"]
    assert pos["tp_strength_factor"] == neg["tp_strength_factor"]


def test_scale_volatility_squeeze():
    """Low BB width pct -> vol_factor < 1.0 (tighter levels)."""
    result = scale_atr_multipliers(
        score=50, bb_width_pct=10.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    assert result["vol_factor"] == 0.8
    assert result["vol_factor"] < 1.0


def test_scale_volatility_expansion():
    """High BB width pct -> vol_factor > 1.0 (wider levels)."""
    result = scale_atr_multipliers(
        score=50, bb_width_pct=90.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    assert result["vol_factor"] > 1.0


def test_scale_combined_effect():
    """Strong signal + high vol -> levels significantly wider."""
    result = scale_atr_multipliers(
        score=80, bb_width_pct=80.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
        signal_threshold=40,
    )
    # Should be noticeably larger than base
    assert result["sl_atr"] > 1.5
    assert result["tp1_atr"] > 2.0
    assert result["tp2_atr"] > 3.0
    # TP strength scales faster than SL strength
    tp_ratio = result["tp1_atr"] / 2.0
    sl_ratio = result["sl_atr"] / 1.5
    assert tp_ratio > sl_ratio


def test_scale_returns_all_keys():
    """Return dict has all expected keys."""
    result = scale_atr_multipliers(
        score=50, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    expected_keys = {"sl_atr", "tp1_atr", "tp2_atr", "sl_strength_factor", "tp_strength_factor", "vol_factor"}
    assert set(result.keys()) == expected_keys


def test_scale_below_threshold_clamps_to_zero():
    """Score below threshold -> t clamped to 0 -> factors = 0.8."""
    result = scale_atr_multipliers(
        score=20, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
        signal_threshold=40,
    )
    assert result["sl_strength_factor"] == 0.8
    assert result["tp_strength_factor"] == 0.8


def test_scale_threshold_100_no_division_by_zero():
    """signal_threshold=100 -> t=0, no crash."""
    result = scale_atr_multipliers(
        score=100, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
        signal_threshold=100,
    )
    assert result["sl_strength_factor"] == 0.8
    assert result["tp_strength_factor"] == 0.8


def test_scale_bb_width_pct_clamped_high():
    """bb_width_pct > 100 is clamped to 100 -> vol_factor caps at 1.25."""
    result = scale_atr_multipliers(
        score=50, bb_width_pct=150.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    assert result["vol_factor"] == 1.25


def test_scale_bb_width_pct_clamped_low():
    """bb_width_pct < 0 is clamped to 0 -> vol_factor floors at 0.75."""
    result = scale_atr_multipliers(
        score=50, bb_width_pct=-10.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    assert result["vol_factor"] == 0.75


# ── calculate_levels enhancements ──


def test_levels_source_atr_default():
    """Path 3 returns levels_source='atr_default'."""
    result = calculate_levels("LONG", 50000.0, 500.0)
    assert result["levels_source"] == "atr_default"


def test_levels_source_ml():
    """Path 2 returns levels_source='ml'."""
    result = calculate_levels(
        "LONG", 50000.0, 500.0,
        ml_atr_multiples={"sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0},
    )
    assert result["levels_source"] == "ml"


def test_levels_source_llm():
    """Path 1 returns levels_source='llm'."""
    llm = {"entry": 50000.0, "stop_loss": 49000.0, "take_profit_1": 51000.0, "take_profit_2": 52000.0}
    result = calculate_levels("LONG", 50000.0, 500.0, llm_levels=llm)
    assert result["levels_source"] == "llm"


def test_custom_atr_defaults():
    """Path 3 uses provided defaults instead of hardcoded 1.5/2.0/3.0."""
    result = calculate_levels(
        "LONG", 50000.0, 500.0,
        sl_atr_default=2.0, tp1_atr_default=3.0, tp2_atr_default=5.0,
    )
    assert result["stop_loss"] == 50000.0 - 2.0 * 500.0
    assert result["take_profit_1"] == 50000.0 + 3.0 * 500.0
    assert result["take_profit_2"] == 50000.0 + 5.0 * 500.0


def test_atr_defaults_clamped_to_bounds():
    """Path 3 clamps provided defaults to sl_bounds/tp limits."""
    result = calculate_levels(
        "LONG", 50000.0, 500.0,
        sl_atr_default=5.0,  # exceeds sl_bounds max (3.0)
        tp1_atr_default=0.5,  # below tp1_min_atr (1.0)
        tp2_atr_default=10.0,  # exceeds tp2_max_atr (8.0)
    )
    # SL clamped to 3.0
    assert result["stop_loss"] == 50000.0 - 3.0 * 500.0
    # TP1 clamped to 1.0, then rr_floor bumps it to sl(3.0)*rr_floor(1.0) = 3.0
    assert result["take_profit_1"] == 50000.0 + 3.0 * 500.0
    # TP2 clamped to 8.0
    assert result["take_profit_2"] == 50000.0 + 8.0 * 500.0


def test_atr_defaults_rr_floor_enforced():
    """Path 3 enforces R:R floor on provided defaults."""
    result = calculate_levels(
        "LONG", 50000.0, 500.0,
        sl_atr_default=2.5,
        tp1_atr_default=1.5,  # TP1/SL = 0.6 < rr_floor(1.0)
        tp2_atr_default=4.0,
        rr_floor=1.0,
    )
    # TP1 should be bumped to sl * rr_floor = 2.5
    assert result["take_profit_1"] == 50000.0 + 2.5 * 500.0
