"""Tests for optimizer models and logic."""

import pytest

from app.db.models import ParameterProposal, ShadowResult
from app.engine.optimizer import (
    compute_ew_ic,
    should_prune_source,
    should_reenable_source,
    IC_PRUNE_THRESHOLD,
    IC_REENABLE_THRESHOLD,
)


def test_parameter_proposal_model_exists():
    """ParameterProposal model has expected columns."""
    cols = {c.name for c in ParameterProposal.__table__.columns}
    assert "id" in cols
    assert "status" in cols
    assert "parameter_group" in cols
    assert "changes" in cols
    assert "backtest_metrics" in cols
    assert "shadow_metrics" in cols
    assert "created_at" in cols
    assert "shadow_started_at" in cols
    assert "promoted_at" in cols
    assert "rejected_reason" in cols


def test_shadow_result_model_exists():
    """ShadowResult model has expected columns."""
    cols = {c.name for c in ShadowResult.__table__.columns}
    assert "id" in cols
    assert "proposal_id" in cols
    assert "signal_id" in cols
    assert "shadow_score" in cols
    assert "shadow_entry" in cols
    assert "shadow_sl" in cols
    assert "shadow_tp1" in cols
    assert "shadow_tp2" in cols
    assert "shadow_outcome" in cols


from app.engine.optimizer import OptimizerState, OPTIMIZER_CONFIG, evaluate_shadow_results


def test_optimizer_config_defaults():
    assert OPTIMIZER_CONFIG["min_signals_for_eval"] == 50
    assert OPTIMIZER_CONFIG["shadow_signal_count"] == 20
    assert OPTIMIZER_CONFIG["improvement_threshold"] == 0.05
    assert OPTIMIZER_CONFIG["rollback_drop_pct"] == 0.15
    assert OPTIMIZER_CONFIG["rollback_window"] == 10
    assert OPTIMIZER_CONFIG["cooldown_signals"] == 50


def test_optimizer_state_init():
    state = OptimizerState()
    assert state.resolved_count == 0
    assert state.global_pnl_history == []
    assert state.active_shadow_proposal_id is None
    assert state.last_optimized == {}


def test_optimizer_state_record_resolution():
    state = OptimizerState()
    state.record_resolution(pnl_pct=2.5)
    state.record_resolution(pnl_pct=-1.0)
    assert state.resolved_count == 2
    assert state.global_pnl_history == [2.5, -1.0]


def test_optimizer_state_profit_factor():
    state = OptimizerState()
    for pnl in [3.0, -1.0, 2.0, -0.5]:
        state.record_resolution(pnl_pct=pnl)
    # gains = 3.0 + 2.0 = 5.0, losses = 1.0 + 0.5 = 1.5
    assert abs(state.profit_factor() - (5.0 / 1.5)) < 0.01


def test_optimizer_state_profit_factor_no_losses():
    state = OptimizerState()
    state.record_resolution(pnl_pct=2.0)
    assert state.profit_factor() == float("inf")


def test_optimizer_state_profit_factor_no_data():
    state = OptimizerState()
    assert state.profit_factor() is None


def test_optimizer_state_needs_eval():
    state = OptimizerState()
    # Not enough signals yet
    assert state.needs_eval("source_weights") is False
    # Add enough signals
    for _ in range(OPTIMIZER_CONFIG["min_signals_for_eval"]):
        state.record_resolution(pnl_pct=1.0)
    assert state.needs_eval("source_weights") is True
    # Mark as optimized
    state.last_optimized["source_weights"] = state.resolved_count
    assert state.needs_eval("source_weights") is False
    # Add cooldown-worth of signals
    for _ in range(OPTIMIZER_CONFIG["cooldown_signals"]):
        state.record_resolution(pnl_pct=1.0)
    assert state.needs_eval("source_weights") is True


def test_optimizer_state_respects_priority():
    state = OptimizerState()
    for _ in range(OPTIMIZER_CONFIG["min_signals_for_eval"]):
        state.record_resolution(pnl_pct=1.0)
    state.active_shadow_proposal_id = 99
    assert state.can_propose("sigmoid_curves") is False
    state.active_shadow_proposal_id = None
    assert state.can_propose("sigmoid_curves") is True


def test_evaluate_shadow_promote():
    """Shadow with better profit factor -> promote."""
    current_pnls = [3.0, -1.0, 2.0, -0.5, 1.5]  # PF = 6.5/1.5 = 4.33
    shadow_pnls = [4.0, -0.8, 3.0, -0.3, 2.0]    # PF = 9.0/1.1 = 8.18
    result = evaluate_shadow_results(current_pnls, shadow_pnls)
    assert result == "promote"


def test_evaluate_shadow_reject():
    """Shadow with much worse profit factor -> reject."""
    current_pnls = [3.0, -1.0, 2.0, -0.5]  # PF = 5.0/1.5 = 3.33
    shadow_pnls = [1.0, -2.0, 0.5, -1.5]   # PF = 1.5/3.5 = 0.43
    result = evaluate_shadow_results(current_pnls, shadow_pnls)
    assert result == "reject"


def test_evaluate_shadow_inconclusive():
    """Shadow within 10% of current -> inconclusive."""
    current_pnls = [3.0, -1.0, 2.0, -0.5]  # PF = 5.0/1.5 = 3.33
    shadow_pnls = [2.8, -1.0, 2.1, -0.5]   # PF = 4.9/1.5 = 3.27
    result = evaluate_shadow_results(current_pnls, shadow_pnls)
    assert result == "inconclusive"


def test_evaluate_shadow_empty():
    result = evaluate_shadow_results([], [])
    assert result == "inconclusive"


def test_full_lifecycle_scenario():
    """Simulate: signals resolve -> group flagged -> validate candidate -> evaluate shadow."""
    from app.engine.param_groups import validate_candidate

    state = OptimizerState()
    for pnl in [2.0, -0.5, 1.5, -0.3, 3.0, -1.0] * 10:
        state.record_resolution(pnl_pct=pnl)
    assert state.needs_eval("source_weights") is True
    assert state.can_propose("source_weights") is True

    candidate = {"traditional": 0.30, "flow": 0.20, "onchain": 0.25, "pattern": 0.15, "liquidation": 0.10}
    assert validate_candidate("source_weights", candidate) is True

    state.last_optimized["source_weights"] = state.resolved_count
    assert state.needs_eval("source_weights") is False

    current = [2.0, -0.5, 1.5, -0.3]
    shadow = [3.0, -0.4, 2.0, -0.2]
    assert evaluate_shadow_results(current, shadow) == "promote"


def test_rollback_detection():
    state = OptimizerState()
    for _ in range(20):
        state.record_resolution(pnl_pct=2.0)
    state._pf_at_promotion[1] = state.profit_factor()
    for _ in range(OPTIMIZER_CONFIG["rollback_window"]):
        state.record_resolution(pnl_pct=-3.0)
    assert state.check_rollback_needed(1) is True


# -- compute_ew_ic tests --


def test_compute_ew_ic_empty():
    assert compute_ew_ic([]) == 0.0


def test_compute_ew_ic_single_value():
    assert compute_ew_ic([0.3]) == 0.3


def test_compute_ew_ic_short_history():
    """With < 3 values, returns simple mean."""
    assert compute_ew_ic([0.1, 0.2]) == pytest.approx(0.15)


def test_compute_ew_ic_normal():
    """Hand-calculated: init=mean(0.1,0.2,0.3)=0.2, then EW over 0.4, 0.5."""
    # i=3: 0.1*0.4 + 0.9*0.2 = 0.22
    # i=4: 0.1*0.5 + 0.9*0.22 = 0.248
    result = compute_ew_ic([0.1, 0.2, 0.3, 0.4, 0.5])
    assert result == pytest.approx(0.248)


def test_compute_ew_ic_negative_trend():
    """All negative ICs produce strongly negative EW-IC."""
    result = compute_ew_ic([-0.1, -0.08, -0.12, -0.09, -0.11])
    # init = mean(-0.1, -0.08, -0.12) = -0.1
    # i=3: 0.1*(-0.09) + 0.9*(-0.1) = -0.099
    # i=4: 0.1*(-0.11) + 0.9*(-0.099) = -0.1001
    assert result == pytest.approx(-0.1001)


def test_compute_ew_ic_exactly_three_values():
    """With exactly 3 values, returns their mean (no EW iteration)."""
    assert compute_ew_ic([0.1, 0.2, 0.3]) == pytest.approx(0.2)


# -- should_prune_source tests --


def test_should_prune_excluded_source():
    """tech and liquidation are never pruned regardless of IC."""
    bad_history = [-0.2] * 10
    assert should_prune_source("tech", bad_history) is False
    assert should_prune_source("liquidation", bad_history) is False


def test_should_prune_insufficient_data():
    """Less than 5 days of history should not trigger pruning."""
    assert should_prune_source("order_flow", [-0.2, -0.3, -0.1, -0.2]) is False


def test_should_prune_positive_ew_ic():
    """Source with positive EW-IC should not be pruned."""
    history = [0.1, 0.15, 0.2, 0.1, 0.12]
    assert should_prune_source("order_flow", history) is False


def test_should_prune_negative_ew_ic():
    """Source with EW-IC below threshold should be pruned."""
    history = [-0.1, -0.08, -0.12, -0.09, -0.11]
    assert compute_ew_ic(history) < IC_PRUNE_THRESHOLD
    assert should_prune_source("order_flow", history) is True


def test_should_prune_borderline():
    """Source with EW-IC just above threshold should not be pruned (< not <=)."""
    # EW-IC = -0.04, which is above IC_PRUNE_THRESHOLD (-0.05)
    history = [-0.04, -0.04, -0.04, -0.04, -0.04]
    assert compute_ew_ic(history) > IC_PRUNE_THRESHOLD
    assert should_prune_source("order_flow", history) is False


# -- should_reenable_source tests --


def test_should_reenable_insufficient_data():
    """Less than 5 days of history should not trigger re-enable."""
    assert should_reenable_source([0.1, 0.2, 0.3]) is False


def test_should_reenable_positive_ew_ic():
    """Source with EW-IC above 0 should be re-enabled."""
    # Need enough positive momentum to overcome EW smoothing
    history = [0.0, 0.02, 0.05, 0.08, 0.1]
    assert compute_ew_ic(history) > IC_REENABLE_THRESHOLD
    assert should_reenable_source(history) is True


def test_should_reenable_still_negative():
    """Source with negative EW-IC should not be re-enabled."""
    history = [-0.2, -0.15, -0.1, -0.12, -0.08]
    assert compute_ew_ic(history) < IC_REENABLE_THRESHOLD
    assert should_reenable_source(history) is False
