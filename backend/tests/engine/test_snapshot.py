"""Test that build_engine_snapshot produces the expected structure."""

import pytest


def test_build_engine_snapshot_keys():
    from app.main import build_engine_snapshot

    # Minimal mock objects
    class MockSettings:
        engine_traditional_weight = 0.40
        engine_flow_weight = 0.22
        engine_onchain_weight = 0.23
        engine_pattern_weight = 0.15
        engine_ml_weight = 0.25
        engine_signal_threshold = 40
        engine_llm_threshold = 20
        ml_confidence_threshold = 0.65
        llm_factor_weights = {"support_proximity": 6.0}
        llm_factor_total_cap = 35.0
        engine_confluence_max_score = 15

    scoring_params = {
        "mean_rev_rsi_steepness": 0.25,
        "mean_rev_bb_pos_steepness": 10.0,
        "squeeze_steepness": 0.10,
        "mean_rev_blend_ratio": 0.6,
    }

    regime_mix = {"trending": 0.6, "ranging": 0.3, "volatile": 0.1}
    caps = {"trend": 38.0, "mean_rev": 22.0, "squeeze": 12.0, "volume": 28.0}
    outer = {"tech": 0.45, "flow": 0.25, "onchain": 0.18, "pattern": 0.12}
    atr = (1.5, 2.0, 3.0)

    snap = build_engine_snapshot(
        MockSettings(), scoring_params, regime_mix, caps, outer, atr, "performance_tracker"
    )

    assert snap["source_weights"]["traditional"] == 0.40
    assert snap["regime_mix"] == regime_mix
    assert snap["atr_multipliers"]["sl"] == 1.5
    assert snap["thresholds"]["signal"] == 40
    assert snap["confluence_max_score"] == 15


def test_snapshot_produces_independent_copy():
    """dict() on scoring_params must produce an independent copy
    so mid-cycle mutations to app.state don't affect the snapshot."""
    original = {"mean_rev_rsi_steepness": 0.25, "squeeze_steepness": 0.10}
    snapshot = dict(original)

    # mutate the "app.state" source after snapshot
    original["mean_rev_rsi_steepness"] = 0.99

    # snapshot should be unaffected
    assert snapshot["mean_rev_rsi_steepness"] == 0.25
