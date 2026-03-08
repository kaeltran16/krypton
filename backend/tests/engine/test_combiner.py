from app.engine.models import LLMResponse
from app.engine.combiner import compute_preliminary_score, compute_final_score, calculate_levels


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
    # After normalization each weight = 0.25, so result = 100
    assert result == 100


def test_preliminary_score_fallback_redistribution():
    """When on-chain is unavailable, caller redistributes weights."""
    # Simulating the fallback logic from run_pipeline with 4-way weights
    base_tech = 0.40
    base_flow = 0.22
    base_onchain = 0.23
    base_pattern = 0.15
    tech_w = base_tech + base_onchain * 0.6  # 0.538
    flow_w = base_flow + base_onchain * 0.4  # 0.312

    result = compute_preliminary_score(
        technical_score=80, order_flow_score=60, pattern_score=50,
        tech_weight=tech_w, flow_weight=flow_w,
        onchain_score=0, onchain_weight=0.0,
        pattern_weight=base_pattern,
    )
    expected = round(80 * tech_w + 60 * flow_w + 50 * base_pattern)
    assert result == expected


def test_preliminary_score_custom_weights():
    """Custom weights with all four components."""
    result = compute_preliminary_score(
        technical_score=70, order_flow_score=50, onchain_score=30, pattern_score=60,
        tech_weight=0.50, flow_weight=0.20, onchain_weight=0.15, pattern_weight=0.15,
    )
    expected = round(70 * 0.50 + 50 * 0.20 + 30 * 0.15 + 60 * 0.15)
    assert result == expected


def test_final_score_with_confirm():
    """LLM confirm should boost the score."""
    llm = LLMResponse(opinion="confirm", confidence="HIGH", explanation="Looks good", levels=None)
    final = compute_final_score(preliminary_score=60, llm_response=llm)
    assert final > 60


def test_final_score_with_caution():
    """LLM caution should dampen the score."""
    llm = LLMResponse(opinion="caution", confidence="HIGH", explanation="Be careful", levels=None)
    final = compute_final_score(preliminary_score=60, llm_response=llm)
    assert final < 60


def test_final_score_with_contradict():
    """LLM contradict should cap positive score at 40."""
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="No way", levels=None)
    final = compute_final_score(preliminary_score=80, llm_response=llm)
    assert final <= 40


def test_final_score_with_contradict_negative():
    """LLM contradict should cap negative score at -40."""
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Not that bad", levels=None)
    final = compute_final_score(preliminary_score=-80, llm_response=llm)
    assert final >= -40


def test_final_score_without_llm():
    """No LLM response = use preliminary score as-is."""
    final = compute_final_score(preliminary_score=65, llm_response=None)
    assert final == 65


def test_final_score_bounded():
    """Final score must stay within -100 to +100."""
    llm = LLMResponse(opinion="confirm", confidence="HIGH", explanation="Max boost", levels=None)
    final = compute_final_score(preliminary_score=95, llm_response=llm)
    assert -100 <= final <= 100


def test_calculate_levels_from_atr():
    """ATR-based levels: SL at 1.5x ATR, TP1 at 2x, TP2 at 3x."""
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0, llm_levels=None
    )
    assert levels["entry"] == 67000.0
    assert levels["stop_loss"] == 67000.0 - 1.5 * 200.0
    assert levels["take_profit_1"] == 67000.0 + 2.0 * 200.0
    assert levels["take_profit_2"] == 67000.0 + 3.0 * 200.0


def test_calculate_levels_short():
    """Short direction flips SL/TP."""
    levels = calculate_levels(
        direction="SHORT", current_price=67000.0, atr=200.0, llm_levels=None
    )
    assert levels["stop_loss"] == 67000.0 + 1.5 * 200.0
    assert levels["take_profit_1"] == 67000.0 - 2.0 * 200.0


def test_calculate_levels_rejects_invalid_llm_levels():
    """LLM levels with SL above entry for LONG should fall back to ATR."""
    bad_levels = {
        "entry": 67000.0,
        "stop_loss": 68000.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68000.0,
    }
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0, llm_levels=bad_levels
    )
    assert levels["stop_loss"] < levels["entry"]
