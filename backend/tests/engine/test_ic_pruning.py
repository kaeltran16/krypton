from app.engine.optimizer import (
    compute_ic,
    compute_ew_ic,
    should_prune_source,
    should_reenable_source,
    compute_daily_ic_for_sources,
    get_pruned_sources,
)


def test_ic_positive_correlation():
    """Positive IC means source scores predict outcomes."""
    source_scores = [10, -20, 30, -15, 25]
    outcomes = [0.02, -0.03, 0.04, -0.02, 0.03]  # same direction
    ic = compute_ic(source_scores, outcomes)
    assert ic > 0.5


def test_ic_negative_correlation():
    """Negative IC means source scores anti-predict outcomes."""
    source_scores = [10, -20, 30, -15, 25]
    outcomes = [-0.02, 0.03, -0.04, 0.02, -0.03]  # opposite direction
    ic = compute_ic(source_scores, outcomes)
    assert ic < -0.5


def test_prune_below_threshold():
    """Source with EW-IC < -0.05 should be pruned."""
    ic_history = [-0.1, -0.08, -0.12, -0.09, -0.11]  # 5 entries, EW-IC well below
    assert should_prune_source("order_flow", ic_history, threshold=-0.05) is True


def test_no_prune_above_threshold():
    ic_history = [0.02, 0.04, 0.01, 0.05, 0.03]
    assert should_prune_source("order_flow", ic_history, threshold=-0.05) is False


def test_liquidation_excluded_from_pruning():
    """Liquidation source must be excluded from IC pruning per spec."""
    ic_history = [-0.10, -0.10, -0.10, -0.10, -0.10]  # would normally be pruned
    assert should_prune_source("liquidation", ic_history, threshold=-0.05) is False


def test_re_enable_when_ic_recovers():
    """Source should be re-enabled when EW-IC recovers above 0.0."""
    ic_history = [0.02, 0.04, 0.06, 0.08, 0.1]
    assert should_reenable_source(ic_history) is True


def test_compute_daily_ic_for_sources():
    """Should compute IC per source from resolved signal data."""
    resolved_signals = [
        {"raw_indicators": {"tech_score": 30, "flow_score": -10, "onchain_score": 5, "pattern_score": 10, "liquidation_score": 5}, "outcome_pct": 0.03},
        {"raw_indicators": {"tech_score": -20, "flow_score": 15, "onchain_score": -8, "pattern_score": -5, "liquidation_score": -3}, "outcome_pct": -0.02},
        {"raw_indicators": {"tech_score": 40, "flow_score": -5, "onchain_score": 10, "pattern_score": 15, "liquidation_score": 8}, "outcome_pct": 0.05},
        {"raw_indicators": {"tech_score": -15, "flow_score": 20, "onchain_score": -12, "pattern_score": -8, "liquidation_score": -6}, "outcome_pct": -0.03},
        {"raw_indicators": {"tech_score": 25, "flow_score": -15, "onchain_score": 7, "pattern_score": 12, "liquidation_score": 4}, "outcome_pct": 0.02},
    ]
    ic_map = compute_daily_ic_for_sources(resolved_signals)
    assert "tech" in ic_map
    assert "flow" in ic_map
    assert "onchain" in ic_map
    assert "pattern" in ic_map
    assert "liquidation" in ic_map
    # tech scores correlate positively with outcomes
    assert ic_map["tech"] > 0


def test_get_pruned_sources_returns_set():
    """Should return set of source names that should be pruned."""
    ic_histories = {
        "tech": [-0.10] * 10,          # below threshold but excluded from pruning
        "flow": [0.1, 0.2, 0.15, 0.1, 0.12],  # healthy
        "onchain": [-0.10] * 10,        # below threshold — prunable
        "liquidation": [-0.10] * 10,    # excluded from pruning
    }
    pruned = get_pruned_sources(ic_histories, threshold=-0.05)
    assert "tech" not in pruned  # tech is excluded from pruning
    assert "onchain" in pruned
    assert "flow" not in pruned
    assert "liquidation" not in pruned  # excluded per spec
