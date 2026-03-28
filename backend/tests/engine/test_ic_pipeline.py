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


def test_get_pruned_sources_respects_min_days():
    """Sources need 30 consecutive bad days before pruning."""
    # Only 10 days of bad IC — not enough
    histories = {"flow": [-0.1] * 10}
    pruned = get_pruned_sources(histories, threshold=-0.05, min_days=30)
    assert "flow" not in pruned

    # 30 days of bad IC — should prune
    histories = {"flow": [-0.1] * 30}
    pruned = get_pruned_sources(histories, threshold=-0.05, min_days=30)
    assert "flow" in pruned


def test_reenable_checks_latest_only():
    """Re-enable checks only the latest IC value."""
    # 29 bad days then 1 good day
    history = [-0.1] * 29 + [0.05]
    assert should_reenable_source(history) is True
