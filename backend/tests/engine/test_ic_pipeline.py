import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.engine.optimizer import (
    compute_daily_ic_for_sources,
    get_pruned_sources,
    should_reenable_source,
    IC_PRUNE_EXCLUDED_SOURCES,
)


def test_tech_excluded_from_pruning():
    """Tech source is never prunable."""
    assert "tech" in IC_PRUNE_EXCLUDED_SOURCES


def test_compute_daily_ic_reads_source_scores():
    """IC computation reads per-source scores from raw_indicators."""
    signals = [
        {"raw_indicators": {"tech_score": 50, "flow_score": 30, "onchain_score": 0,
                            "pattern_score": 10, "liquidation_score": 0, "confluence_score": 5},
         "outcome_pct": 2.0},
        {"raw_indicators": {"tech_score": -40, "flow_score": -20, "onchain_score": 0,
                            "pattern_score": -15, "liquidation_score": 0, "confluence_score": -5},
         "outcome_pct": -1.5},
    ] * 5  # need at least 5 for compute_ic
    ic_map = compute_daily_ic_for_sources(signals)
    assert "tech" in ic_map
    assert "flow" in ic_map
    assert "onchain" in ic_map
    assert "pattern" in ic_map
    assert "liquidation" in ic_map
    assert "confluence" in ic_map
    # tech and flow scores correlate with outcomes (positive when positive, negative when negative)
    assert ic_map["tech"] > 0
    assert ic_map["flow"] > 0


def test_get_pruned_sources_uses_ew_ic():
    """Sources with bad EW-IC are pruned; insufficient data is not."""
    # Only 4 days of bad IC — not enough (need >= 5)
    histories = {"flow": [-0.1] * 4}
    pruned = get_pruned_sources(histories, threshold=-0.05)
    assert "flow" not in pruned

    # 10 days of bad IC — EW-IC well below threshold, should prune
    histories = {"flow": [-0.1] * 10}
    pruned = get_pruned_sources(histories, threshold=-0.05)
    assert "flow" in pruned


def test_reenable_checks_ew_ic():
    """Re-enable checks EW-IC, not just the latest value."""
    # All positive history — EW-IC positive, should re-enable
    history = [0.02, 0.04, 0.06, 0.08, 0.1]
    assert should_reenable_source(history) is True
    # Mostly negative — EW-IC still negative, should not re-enable
    history = [-0.1] * 29 + [0.05]
    assert should_reenable_source(history) is False
