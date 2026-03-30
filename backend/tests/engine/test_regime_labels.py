"""Tests for retrospective regime label generation."""

import numpy as np
import pandas as pd
import pytest

from app.engine.regime_labels import generate_regime_labels, LABEL_MAP


@pytest.fixture
def trending_candles():
    """Candles with a strong uptrend."""
    n = 200
    rng = np.random.default_rng(42)
    prices = 100 + np.cumsum(rng.uniform(0.2, 0.8, size=n))  # steady upward drift
    df = pd.DataFrame({
        "open": prices - rng.uniform(0.1, 0.3, n),
        "high": prices + rng.uniform(0.3, 1.0, n),
        "low": prices - rng.uniform(0.3, 1.0, n),
        "close": prices,
        "volume": rng.uniform(100, 1000, n),
    })
    return df


@pytest.fixture
def ranging_candles():
    """Candles oscillating in a tight range."""
    n = 200
    rng = np.random.default_rng(42)
    base = 100 + np.sin(np.linspace(0, 10 * np.pi, n)) * 0.5  # tiny oscillation
    df = pd.DataFrame({
        "open": base - 0.1,
        "high": base + rng.uniform(0.1, 0.3, n),
        "low": base - rng.uniform(0.1, 0.3, n),
        "close": base,
        "volume": rng.uniform(100, 1000, n),
    })
    return df


def test_output_shape(trending_candles):
    labels = generate_regime_labels(trending_candles, horizon=48)
    assert len(labels) == len(trending_candles)
    assert set(labels.unique()).issubset({0, 1, 2, 3})


def test_label_map_has_4_classes():
    assert len(LABEL_MAP) == 4
    assert "trending" in LABEL_MAP.values()
    assert "ranging" in LABEL_MAP.values()
    assert "volatile" in LABEL_MAP.values()
    assert "steady" in LABEL_MAP.values()


def test_last_horizon_candles_are_ranging(trending_candles):
    """Last horizon candles can't look forward — default to ranging."""
    labels = generate_regime_labels(trending_candles, horizon=48)
    # Last 48 candles should be labeled ranging (default) since no forward data
    assert all(labels.iloc[-48:] == 3)  # ranging=3


def test_trending_data_produces_trending_labels(trending_candles):
    labels = generate_regime_labels(trending_candles, horizon=48)
    lookable = labels.iloc[:-48]
    trending_pct = (lookable == 0).mean()  # trending=0
    assert trending_pct > 0.3, f"Expected >30% trending labels, got {trending_pct:.1%}"


def test_ranging_data_produces_ranging_labels(ranging_candles):
    labels = generate_regime_labels(ranging_candles, horizon=48)
    lookable = labels.iloc[:-48]
    ranging_pct = (lookable == 3).mean()  # ranging=3
    assert ranging_pct > 0.3, f"Expected >30% ranging labels, got {ranging_pct:.1%}"


def test_minimum_data_returns_all_default():
    """With fewer candles than horizon, all labels should be default."""
    df = pd.DataFrame({
        "open": [100] * 10,
        "high": [101] * 10,
        "low": [99] * 10,
        "close": [100] * 10,
        "volume": [500] * 10,
    })
    labels = generate_regime_labels(df, horizon=48)
    assert len(labels) == 10
    assert all(labels == 3)  # all ranging (default)
