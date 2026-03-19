"""Test backtest parameter override mapping."""

import pytest


def test_apply_overrides_maps_dot_paths():
    """Verify dot-path overrides are routed to the correct BacktestConfig fields."""
    from app.api.backtest import _apply_overrides
    from app.engine.backtester import BacktestConfig

    config = BacktestConfig()
    original_threshold = config.signal_threshold
    original_sl = config.sl_atr_multiplier

    overrides = {
        "blending.thresholds.signal": 25,
        "levels.atr_defaults.sl": 1.8,
        "blending.source_weights.traditional": 0.50,
        "nonexistent.path": 999,  # should be silently ignored
    }
    result = _apply_overrides(config, overrides)

    assert result.signal_threshold == 25
    assert result.sl_atr_multiplier == 1.8
    assert result.tech_weight == 0.50


def test_apply_overrides_ignores_unknown_paths():
    """Unknown dot-paths should not raise or modify config."""
    from app.api.backtest import _apply_overrides
    from app.engine.backtester import BacktestConfig

    config = BacktestConfig()
    original = BacktestConfig()

    _apply_overrides(config, {"unknown.path": 42, "also.unknown": 99})

    assert config.signal_threshold == original.signal_threshold
    assert config.sl_atr_multiplier == original.sl_atr_multiplier
