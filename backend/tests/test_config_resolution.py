"""Test that nullable PipelineSettings columns override env-based Settings."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace


def _make_ps(**overrides):
    """Create a mock PipelineSettings row with defaults + overrides."""
    defaults = {
        "pairs": ["BTC-USDT-SWAP"],
        "timeframes": ["15m", "1h"],
        "signal_threshold": 40,
        "onchain_enabled": True,
        "news_alerts_enabled": True,
        "news_context_window": 30,
        "mean_rev_rsi_steepness": 0.25,
        "mean_rev_bb_pos_steepness": 10.0,
        "squeeze_steepness": 0.10,
        "mean_rev_blend_ratio": 0.6,
        # nullable overrides — None by default
        "traditional_weight": None,
        "flow_weight": None,
        "onchain_weight": None,
        "pattern_weight": None,
        "ml_weight_min": None,
        "ml_weight_max": None,
        "ml_confidence_threshold": None,
        "llm_threshold": None,
        "llm_factor_weights": None,
        "llm_factor_total_cap": None,
        "confluence_level_weight_1": None,
        "confluence_level_weight_2": None,
        "confluence_trend_alignment_steepness": None,
        "confluence_adx_strength_center": None,
        "confluence_adx_conviction_ratio": None,
        "confluence_mr_penalty_factor": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_none_override_keeps_env_default():
    """When DB column is None, env value should remain untouched."""
    from app.main import _apply_pipeline_overrides

    settings = MagicMock()
    settings.engine_traditional_weight = 0.40
    settings.engine_flow_weight = 0.22

    ps = _make_ps()  # all overrides None
    _apply_pipeline_overrides(settings, ps)

    assert settings.engine_traditional_weight == 0.40
    assert settings.engine_flow_weight == 0.22


def test_non_none_override_applies():
    """When DB column has a value, it should override the env setting."""
    from app.main import _apply_pipeline_overrides

    settings = MagicMock()
    settings.engine_traditional_weight = 0.40
    settings.engine_llm_threshold = 20
    settings.llm_factor_total_cap = 35.0

    ps = _make_ps(traditional_weight=0.50, llm_threshold=30, llm_factor_total_cap=40.0)
    _apply_pipeline_overrides(settings, ps)

    assert settings.engine_traditional_weight == 0.50
    assert settings.engine_llm_threshold == 30
    assert settings.llm_factor_total_cap == 40.0


@pytest.mark.parametrize("db_col,settings_field,value", [
    ("traditional_weight", "engine_traditional_weight", 0.50),
    ("flow_weight", "engine_flow_weight", 0.30),
    ("onchain_weight", "engine_onchain_weight", 0.20),
    ("pattern_weight", "engine_pattern_weight", 0.10),
    ("ml_weight_min", "engine_ml_weight_min", 0.10),
    ("ml_weight_max", "engine_ml_weight_max", 0.35),
    ("ml_confidence_threshold", "ml_confidence_threshold", 0.80),
    ("llm_threshold", "engine_llm_threshold", 30),
    ("llm_factor_weights", "llm_factor_weights", {"support_proximity": 8.0}),
    ("llm_factor_total_cap", "llm_factor_total_cap", 40.0),
    ("confluence_level_weight_1", "engine_confluence_level_weight_1", 0.45),
    ("confluence_mr_penalty_factor", "engine_confluence_mr_penalty_factor", 0.60),
])
def test_each_override_mapping(db_col, settings_field, value):
    """Verify every entry in _OVERRIDE_MAP routes correctly."""
    from app.main import _apply_pipeline_overrides

    settings = MagicMock()
    setattr(settings, settings_field, "original")

    ps = _make_ps(**{db_col: value})
    _apply_pipeline_overrides(settings, ps)

    assert getattr(settings, settings_field) == value
