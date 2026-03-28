import pytest

REQUIRED_INDICATOR_KEYS = [
    "tech_score", "tech_confidence",
    "flow_score", "flow_confidence",
    "onchain_score", "onchain_confidence",
    "pattern_score", "pattern_confidence",
    "liquidation_score", "liquidation_confidence",
    "confluence_score", "confluence_confidence",
    "regime_trending", "regime_ranging", "regime_volatile", "regime_steady",
]


def test_raw_indicators_keys_defined():
    """Verify the REQUIRED_INDICATOR_KEYS list is importable (sanity)."""
    assert len(REQUIRED_INDICATOR_KEYS) == 16


def _build_mock_raw_indicators():
    """Simulate the raw_indicators dict as it would be built in main.py."""
    from app.main import _build_raw_indicators
    tech_result = {
        "score": 45,
        "indicators": {
            "regime_trending": 0.5, "regime_ranging": 0.2,
            "regime_volatile": 0.2, "regime_steady": 0.1,
            "trend_conviction": 0.6, "atr": 50.0,
        },
        "caps": {"trend_cap": 30, "mean_rev_cap": 25},
    }
    return _build_raw_indicators(
        tech_result=tech_result, tech_conf=0.7,
        flow_result={"score": 20, "confidence": 0.5, "details": {}},
        onchain_score=10, onchain_conf=0.3,
        pat_score=15, pattern_conf=0.4,
        liq_score=5, liq_conf=0.2, liq_clusters=[], liq_details={},
        confluence_score=12, confluence_conf=0.6,
        ml_score=30, ml_confidence=0.8,
        blended=55, indicator_preliminary=48,
        scaled={"sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0,
                "sl_strength_factor": 1.0, "tp_strength_factor": 1.0, "vol_factor": 1.0},
        levels={"levels_source": "atr_defaults"},
        outer={}, snap_info=None, llm_contribution=0.0,
    )


def test_raw_indicators_has_all_source_scores():
    """raw_indicators must contain all per-source scores for the live optimizer."""
    ri = _build_mock_raw_indicators()
    for key in REQUIRED_INDICATOR_KEYS:
        assert key in ri, f"Missing key: {key}"


def test_raw_indicators_regime_steady_present():
    """regime_steady must be present (was previously missing)."""
    ri = _build_mock_raw_indicators()
    assert ri["regime_steady"] == 0.1
