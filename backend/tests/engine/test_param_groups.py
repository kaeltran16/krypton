"""Tests for parameter group definitions."""

from app.engine.param_groups import (
    PARAM_GROUPS,
    get_group,
    validate_candidate,
    PRIORITY_LAYERS,
)


def test_all_groups_defined():
    expected = {
        "source_weights", "thresholds", "regime_caps", "regime_outer",
        "atr_levels", "sigmoid_curves", "order_flow", "pattern_strengths",
        "indicator_periods", "mean_reversion", "llm_factors", "onchain",
    }
    assert set(PARAM_GROUPS.keys()) == expected


def test_get_group_returns_definition():
    g = get_group("source_weights")
    assert "params" in g
    assert "sweep_method" in g
    assert "constraints" in g
    assert "priority" in g


def test_get_group_unknown_returns_none():
    assert get_group("nonexistent") is None


def test_source_weights_constraint_sum_to_one():
    valid = {"traditional": 0.4, "flow": 0.2, "onchain": 0.25, "pattern": 0.15}
    assert validate_candidate("source_weights", valid) is True


def test_source_weights_constraint_rejects_bad_sum():
    invalid = {"traditional": 0.5, "flow": 0.3, "onchain": 0.3, "pattern": 0.1}
    assert validate_candidate("source_weights", invalid) is False


def test_thresholds_constraint_signal_gt_llm():
    valid = {"signal": 40, "llm": 20, "ml_confidence": 0.65}
    assert validate_candidate("thresholds", valid) is True

    invalid = {"signal": 15, "llm": 20, "ml_confidence": 0.65}
    assert validate_candidate("thresholds", invalid) is False


def test_priority_layers_ordered():
    assert PRIORITY_LAYERS[0] == {"source_weights", "thresholds"}
    assert len(PRIORITY_LAYERS) >= 3


def test_regime_caps_constraint_sum_per_regime():
    valid = {
        "trending_trend_cap": 38, "trending_mean_rev_cap": 22,
        "trending_squeeze_cap": 12, "trending_volume_cap": 28,
        "ranging_trend_cap": 18, "ranging_mean_rev_cap": 40,
        "ranging_squeeze_cap": 16, "ranging_volume_cap": 26,
        "volatile_trend_cap": 25, "volatile_mean_rev_cap": 28,
        "volatile_squeeze_cap": 22, "volatile_volume_cap": 25,
    }
    assert validate_candidate("regime_caps", valid) is True
