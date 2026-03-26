import math

from app.engine.scoring import sigmoid_score
from app.engine.constants import ORDER_FLOW


def test_funding_rate_sigmoid_activates_in_normal_range():
    """Funding rate sigmoid should produce gradual scores, not binary saturation."""
    steepness = ORDER_FLOW["sigmoid_steepnesses"]["funding"]
    score_low = abs(sigmoid_score(-0.0001, center=0, steepness=steepness))
    score_mid = abs(sigmoid_score(-0.0005, center=0, steepness=steepness))
    score_high = abs(sigmoid_score(-0.005, center=0, steepness=steepness))

    # at 0.01% funding rate, should produce non-zero output
    assert score_low > 0.01, f"Funding sigmoid dead at 0.01%: {score_low}"
    # at 0.05% funding rate, should be higher but not saturated
    assert score_mid > score_low, "Should increase with larger funding rate"
    assert score_mid < 0.95, f"Funding sigmoid saturated too early at 0.05%: {score_mid}"
    # at 0.5% (extreme), should be near saturation
    assert score_high > 0.70, f"Funding sigmoid too flat at extreme: {score_high}"


def test_oi_change_sigmoid_activates_in_normal_range():
    """OI change sigmoid should respond to 2-10% changes."""
    steepness = ORDER_FLOW["sigmoid_steepnesses"]["oi"]
    score_2pct = abs(sigmoid_score(2.0, center=0, steepness=steepness))
    score_10pct = abs(sigmoid_score(10.0, center=0, steepness=steepness))

    assert score_2pct > 0.10, f"OI sigmoid too flat at 2%: {score_2pct}"
    assert score_10pct > 0.70, f"OI sigmoid too flat at 10%: {score_10pct}"


from app.engine.traditional import compute_order_flow_score


def test_order_flow_uses_constant_steepness():
    """Order flow scoring should use steepness from ORDER_FLOW constants, not hardcoded."""
    metrics = {"funding_rate": 0.0003, "open_interest_change_pct": 5.0, "price_direction": 1}
    result = compute_order_flow_score(metrics)
    assert abs(result["details"]["funding_score"]) > 1.0, "Funding score too small with recalibrated sigmoid"
    assert abs(result["details"]["oi_score"]) > 2.0, "OI score too small with recalibrated sigmoid"


from app.engine.scoring import sigmoid_score
from app.engine.traditional import compute_trend_conviction


def test_ema_alignment_is_continuous():
    """EMA alignment should produce continuous values, not discrete 0/0.5/1.0 steps."""
    di_dir = sigmoid_score((30 - 15) / (30 + 15), center=0, steepness=3.0)
    r1 = compute_trend_conviction(close=110, ema_9=108, ema_21=105, ema_50=100, atr=2.0,
                                   adx=25.0, di_direction=di_dir)
    r2 = compute_trend_conviction(close=101, ema_9=100.5, ema_21=100.0, ema_50=99.0, atr=2.0,
                                   adx=25.0, di_direction=di_dir)

    assert r1["direction"] == 1
    assert r2["direction"] == 1
    assert r1["conviction"] > r2["conviction"]
    assert r1["conviction"] != r2["conviction"]


def test_ema_alignment_preserves_direction():
    """Bearish EMA alignment should produce negative direction."""
    di_dir = sigmoid_score((12 - 28) / (12 + 28), center=0, steepness=3.0)
    r = compute_trend_conviction(
        close=95, ema_9=96, ema_21=98, ema_50=100, atr=2.0,
        adx=25.0, di_direction=di_dir,
    )
    assert r["direction"] == -1
    assert r["conviction"] > 0.3


def test_ema_alignment_atr_zero_no_crash():
    """ATR=0 should not cause division error."""
    di_dir = sigmoid_score((30 - 15) / (30 + 15), center=0, steepness=3.0)
    r = compute_trend_conviction(
        close=105, ema_9=104, ema_21=102, ema_50=100, atr=0.0,
        adx=25.0, di_direction=di_dir,
    )
    assert r["direction"] == 1
    assert 0.0 <= r["conviction"] <= 1.0


from app.engine.param_groups import PARAM_GROUPS


def test_recalibrated_defaults_within_param_group_bounds():
    """Recalibrated sigmoid defaults must fall within optimizer sweep bounds."""
    flow_group = PARAM_GROUPS["order_flow"]
    params = flow_group["sweep_ranges"]

    for key in ["funding_steepness", "oi_steepness", "ls_ratio_steepness"]:
        if key in params:
            p_min, p_max, _ = params[key]
            default = ORDER_FLOW["sigmoid_steepnesses"][key.replace("_steepness", "")]
            assert p_min <= default <= p_max, (
                f"{key} default {default} outside bounds [{p_min}, {p_max}]"
            )
