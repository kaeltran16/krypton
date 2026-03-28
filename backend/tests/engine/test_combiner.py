import pytest
from app.engine.models import LLMFactor, DEFAULT_FACTOR_WEIGHTS
from app.engine.combiner import (
    compute_preliminary_score,
    compute_llm_contribution,
    compute_final_score,
    calculate_levels,
    blend_with_ml,
    compute_agreement,
    apply_agreement_factor,
    scale_atr_multipliers,
)


# ── compute_preliminary_score ──


def test_preliminary_score_weighted():
    """Preliminary score with default 4-way weights (40/22/23/15)."""
    result = compute_preliminary_score(
        technical_score=80, order_flow_score=60, onchain_score=40, pattern_score=50,
        tech_confidence=1.0, flow_confidence=1.0, onchain_confidence=1.0, pattern_confidence=1.0,
    )
    expected = round(80 * 0.40 + 60 * 0.22 + 40 * 0.23 + 50 * 0.15)
    assert result["score"] == expected


def test_preliminary_score_two_way_backward_compat():
    """When onchain_score=0 and weights adjusted, behaves like 2-way."""
    result = compute_preliminary_score(
        technical_score=80, order_flow_score=50,
        tech_weight=0.60, flow_weight=0.40,
        onchain_score=0, onchain_weight=0.0,
        pattern_weight=0.0,
        tech_confidence=1.0, flow_confidence=1.0,
    )
    expected = round(80 * 0.60 + 50 * 0.40)
    assert result["score"] == expected


def test_preliminary_score_auto_normalization():
    """Weights that don't sum to 1.0 get auto-normalized."""
    result = compute_preliminary_score(
        technical_score=100, order_flow_score=100, onchain_score=100, pattern_score=100,
        tech_weight=0.50, flow_weight=0.50, onchain_weight=0.50, pattern_weight=0.50,
        tech_confidence=1.0, flow_confidence=1.0, onchain_confidence=1.0, pattern_confidence=1.0,
    )
    assert result["score"] == 100


def test_preliminary_score_custom_weights():
    """Custom weights with all four components."""
    result = compute_preliminary_score(
        technical_score=70, order_flow_score=50, onchain_score=30, pattern_score=60,
        tech_weight=0.50, flow_weight=0.20, onchain_weight=0.15, pattern_weight=0.15,
        tech_confidence=1.0, flow_confidence=1.0, onchain_confidence=1.0, pattern_confidence=1.0,
    )
    expected = round(70 * 0.50 + 50 * 0.20 + 30 * 0.15 + 60 * 0.15)
    assert result["score"] == expected


# ── blend_with_ml ──


def test_blend_with_ml_score_contributes():
    """ML score blends with indicator preliminary when confidence is above threshold."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=80.0, ml_confidence=0.80,
        ml_weight_min=0.25, ml_weight_max=0.25,  # fixed weight for backward compat test
        ml_confidence_threshold=0.65,
    )
    expected = round(60 * 0.75 + 80.0 * 0.25)
    assert result == expected


def test_blend_with_ml_below_threshold():
    """ML score ignored when confidence below threshold."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=80.0, ml_confidence=0.50,
        ml_weight_min=0.25, ml_weight_max=0.25, ml_confidence_threshold=0.65,
    )
    assert result == 60


def test_blend_with_ml_none_score():
    """ML score None returns indicator preliminary unchanged."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=None, ml_confidence=None,
    )
    assert result == 60


def test_blend_with_ml_zero_weight():
    """Zero ML weight means no contribution."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=80.0, ml_confidence=0.90,
        ml_weight_min=0.0, ml_weight_max=0.0, ml_confidence_threshold=0.65,
    )
    assert result == 60


def test_blend_with_ml_bounded():
    """Blended score is clamped to -100..+100."""
    result = blend_with_ml(
        indicator_preliminary=95, ml_score=100.0, ml_confidence=0.99,
        ml_weight_min=0.5, ml_weight_max=0.5, ml_confidence_threshold=0.65,
    )
    assert -100 <= result <= 100


def test_blend_with_ml_negative_scores():
    """Blending works for SHORT (negative) scores."""
    result = blend_with_ml(
        indicator_preliminary=-50, ml_score=-75.0, ml_confidence=0.75,
        ml_weight_min=0.25, ml_weight_max=0.25, ml_confidence_threshold=0.65,
    )
    expected = round(-50 * 0.75 + -75.0 * 0.25)
    assert result == expected


def test_blend_with_ml_disagreement():
    """Indicators positive, ML negative — blend dampens."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=-80.0, ml_confidence=0.80,
        ml_weight_min=0.25, ml_weight_max=0.25, ml_confidence_threshold=0.65,
    )
    expected = round(60 * 0.75 + (-80.0) * 0.25)
    assert result == expected
    assert result < 60  # dampened by disagreement


class TestAdaptiveMLRamp:
    def test_at_threshold_gets_min_weight(self):
        """At exactly the threshold, ML gets minimum weight."""
        result = blend_with_ml(
            indicator_preliminary=60, ml_score=80.0, ml_confidence=0.65,
            ml_weight_min=0.05, ml_weight_max=0.30,
            ml_confidence_threshold=0.65,
        )
        assert result == round(60 * 0.95 + 80 * 0.05)

    def test_at_max_confidence_gets_max_weight(self):
        """At confidence=1.0, ML gets maximum weight."""
        result = blend_with_ml(
            indicator_preliminary=60, ml_score=80.0, ml_confidence=1.0,
            ml_weight_min=0.05, ml_weight_max=0.30,
            ml_confidence_threshold=0.65,
        )
        assert result == round(60 * 0.70 + 80 * 0.30)

    def test_mid_confidence_gets_interpolated_weight(self):
        """Midpoint confidence gets interpolated weight."""
        # ml_confidence=0.825, t=(0.825-0.65)/(1.0-0.65)=0.5
        # weight = 0.05 + 0.25*0.5 = 0.175
        result = blend_with_ml(
            indicator_preliminary=60, ml_score=80.0, ml_confidence=0.825,
            ml_weight_min=0.05, ml_weight_max=0.30,
            ml_confidence_threshold=0.65,
        )
        assert result == round(60 * 0.825 + 80 * 0.175)

    def test_below_threshold_excluded(self):
        """Below threshold, ML doesn't participate."""
        result = blend_with_ml(
            indicator_preliminary=60, ml_score=80.0, ml_confidence=0.50,
            ml_weight_min=0.05, ml_weight_max=0.30,
            ml_confidence_threshold=0.65,
        )
        assert result == 60

    def test_threshold_1_0_returns_preliminary(self):
        """Threshold of 1.0 means ML never participates (division by zero guard)."""
        result = blend_with_ml(
            indicator_preliminary=60, ml_score=80.0, ml_confidence=1.0,
            ml_weight_min=0.05, ml_weight_max=0.30,
            ml_confidence_threshold=1.0,
        )
        assert result == 60


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


# ── compute_llm_contribution ──


def test_llm_contribution_single_bullish_factor():
    """Single bullish factor = positive contribution."""
    factors = [LLMFactor(type="rsi_divergence", direction="bullish", strength=2, reason="test")]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == round(7.0 * 2)


def test_llm_contribution_single_bearish_factor():
    """Bearish factor = negative contribution."""
    factors = [LLMFactor(type="rsi_divergence", direction="bearish", strength=2, reason="test")]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == round(-7.0 * 2)


def test_llm_contribution_bearish_always_negative():
    """Bearish factor always produces negative contribution regardless of context."""
    factors = [LLMFactor(type="funding_extreme", direction="bearish", strength=3, reason="test")]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == round(-5.0 * 3)


def test_llm_contribution_multiple_factors():
    """Multiple factors sum their contributions."""
    factors = [
        LLMFactor(type="level_breakout", direction="bullish", strength=3, reason="broke key"),
        LLMFactor(type="rsi_divergence", direction="bullish", strength=1, reason="mild div"),
        LLMFactor(type="funding_extreme", direction="bearish", strength=2, reason="elevated"),
    ]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    expected = round((8.0 * 3) + (7.0 * 1) + (-5.0 * 2))  # 24 + 7 - 10 = 21
    assert result == expected


def test_llm_contribution_capped_positive():
    """Total capped at +total_cap."""
    factors = [
        LLMFactor(type="level_breakout", direction="bullish", strength=3, reason="a"),
        LLMFactor(type="htf_alignment", direction="bullish", strength=3, reason="b"),
        LLMFactor(type="rsi_divergence", direction="bullish", strength=3, reason="c"),
    ]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == 35


def test_llm_contribution_capped_negative():
    """Total capped at -total_cap."""
    factors = [
        LLMFactor(type="level_breakout", direction="bearish", strength=3, reason="a"),
        LLMFactor(type="htf_alignment", direction="bearish", strength=3, reason="b"),
        LLMFactor(type="rsi_divergence", direction="bearish", strength=3, reason="c"),
    ]
    result = compute_llm_contribution(factors, DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == -35


def test_llm_contribution_empty_factors():
    """Empty factor list returns 0."""
    result = compute_llm_contribution([], DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == 0


def test_llm_contribution_custom_weights():
    """Custom weight dict overrides defaults."""
    custom = {"rsi_divergence": 10.0}
    factors = [LLMFactor(type="rsi_divergence", direction="bullish", strength=2, reason="test")]
    result = compute_llm_contribution(factors, custom, 35.0)
    assert result == 20


# ── compute_final_score (new signature) ──


def test_final_score_adds_contribution():
    assert compute_final_score(60, 14) == 74


def test_final_score_subtracts_contribution():
    assert compute_final_score(60, -14) == 46


def test_final_score_no_llm():
    assert compute_final_score(60, 0) == 60


def test_final_score_clamped_high():
    assert compute_final_score(90, 35) == 100


def test_final_score_clamped_low():
    assert compute_final_score(-90, -35) == -100


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


def test_calculate_levels_ml_first_over_llm():
    """ML takes priority over LLM when both available."""
    llm_levels = {
        "entry": 67000.0, "stop_loss": 66500.0,
        "take_profit_1": 67500.0, "take_profit_2": 68000.0,
    }
    ml_multiples = {"sl_atr": 1.2, "tp1_atr": 2.5, "tp2_atr": 4.0}
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        llm_levels=llm_levels, ml_atr_multiples=ml_multiples,
        llm_contribution=10,
    )
    assert levels["levels_source"] == "ml"


def test_calculate_levels_llm_fallback_no_ml():
    """LLM levels used when ML not available and contribution >= 0."""
    llm_levels = {
        "entry": 67000.0, "stop_loss": 66500.0,
        "take_profit_1": 67500.0, "take_profit_2": 68000.0,
    }
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        llm_levels=llm_levels, llm_contribution=5,
    )
    assert levels == {**llm_levels, "levels_source": "llm"}


def test_calculate_levels_llm_skipped_negative_contribution():
    """LLM levels skipped when contribution < 0."""
    llm_levels = {
        "entry": 67000.0, "stop_loss": 66500.0,
        "take_profit_1": 67500.0, "take_profit_2": 68000.0,
    }
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        llm_levels=llm_levels, llm_contribution=-5,
    )
    assert levels["levels_source"] == "atr_default"


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
    """Path 1 returns levels_source='ml'."""
    result = calculate_levels(
        "LONG", 50000.0, 500.0,
        ml_atr_multiples={"sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0},
    )
    assert result["levels_source"] == "ml"


def test_levels_source_llm():
    """Path 2 returns levels_source='llm'."""
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


# ── apply_agreement_factor ──


class TestAgreementFactor:
    def test_full_agreement_boosts(self):
        """5/5 same direction gets ceiling multiplier."""
        result = apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 30, 20, 10, 5],
            source_availabilities=[1.0, 1.0, 1.0, 1.0, 1.0],
        )
        assert result > 50

    def test_full_disagreement_penalizes(self):
        """3 vs 2 split gets penalty."""
        result = apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 30, 20, -10, -5],
            source_availabilities=[1.0, 1.0, 1.0, 1.0, 1.0],
        )
        assert result < 50

    def test_fewer_than_3_sources_no_change(self):
        """<3 contributing sources means no bonus/penalty."""
        result = apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 30],
            source_availabilities=[1.0, 1.0],
        )
        assert result == 50

    def test_zero_score_excluded(self):
        """Sources with score=0 don't count."""
        result = apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 0, 0, 0, 30],
            source_availabilities=[1.0, 1.0, 1.0, 1.0, 1.0],
        )
        assert result == 50

    def test_unavailable_excluded(self):
        """Sources with availability=0 don't count."""
        result = apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 30, 20, 10, 5],
            source_availabilities=[1.0, 1.0, 1.0, 0.0, 0.0],
        )
        assert result == apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 30, 20],
            source_availabilities=[1.0, 1.0, 1.0],
        )

    def test_bounded_to_100(self):
        """Result clamped to [-100, 100]."""
        result = apply_agreement_factor(
            preliminary=95,
            source_scores=[90, 80, 70, 60, 50],
            source_availabilities=[1.0, 1.0, 1.0, 1.0, 1.0],
        )
        assert result <= 100

    def test_zero_preliminary_stays_zero(self):
        """Can't create signal from nothing."""
        result = apply_agreement_factor(
            preliminary=0,
            source_scores=[40, 30, 20],
            source_availabilities=[1.0, 1.0, 1.0],
        )
        assert result == 0
