"""Unit tests for cross-pair correlation dampener."""

import pytest

from app.engine.risk import compute_correlation_factor, _pearson


# ── _pearson ──


def test_pearson_perfect_positive():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [2.0, 4.0, 6.0, 8.0, 10.0]
    assert _pearson(x, y) == pytest.approx(1.0)


def test_pearson_perfect_negative():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [10.0, 8.0, 6.0, 4.0, 2.0]
    assert _pearson(x, y) == pytest.approx(-1.0)


def test_pearson_uncorrelated():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [3.0, 1.0, 5.0, 2.0, 4.0]
    assert abs(_pearson(x, y)) < 0.5


def test_pearson_empty():
    assert _pearson([], []) == 0.0


def test_pearson_single():
    assert _pearson([1.0], [2.0]) == 0.0


def test_pearson_constant():
    assert _pearson([1.0, 1.0, 1.0], [2.0, 3.0, 4.0]) == 0.0


# ── compute_correlation_factor ──


def test_no_open_positions():
    result = compute_correlation_factor(
        new_pair="BTC-USDT-SWAP",
        new_direction="LONG",
        open_positions=[],
        returns_by_pair={},
    )
    assert result["factor"] == 1.0
    assert result["max_correlation"] == 0.0
    assert result["correlated_pair"] is None


def test_no_returns_data():
    result = compute_correlation_factor(
        new_pair="BTC-USDT-SWAP",
        new_direction="LONG",
        open_positions=[{"pair": "ETH-USDT-SWAP", "direction": "LONG"}],
        returns_by_pair={},
    )
    assert result["factor"] == 1.0


def test_same_pair_ignored():
    """Same pair as new signal should not affect dampening."""
    returns = [0.01 * i for i in range(25)]
    result = compute_correlation_factor(
        new_pair="BTC-USDT-SWAP",
        new_direction="LONG",
        open_positions=[{"pair": "BTC-USDT-SWAP", "direction": "LONG"}],
        returns_by_pair={"BTC-USDT-SWAP": returns},
    )
    assert result["factor"] == 1.0


def test_opposite_direction_no_dampening():
    """Opposite direction positions should not trigger dampening."""
    returns = [0.01 * i for i in range(25)]
    result = compute_correlation_factor(
        new_pair="BTC-USDT-SWAP",
        new_direction="LONG",
        open_positions=[{"pair": "ETH-USDT-SWAP", "direction": "SHORT"}],
        returns_by_pair={
            "BTC-USDT-SWAP": returns,
            "ETH-USDT-SWAP": returns,
        },
    )
    assert result["factor"] == 1.0


def test_highly_correlated_same_direction():
    """Perfectly correlated same-direction positions should dampen to floor."""
    base = [0.01 * i for i in range(25)]
    result = compute_correlation_factor(
        new_pair="BTC-USDT-SWAP",
        new_direction="LONG",
        open_positions=[{"pair": "ETH-USDT-SWAP", "direction": "LONG"}],
        returns_by_pair={
            "BTC-USDT-SWAP": base,
            "ETH-USDT-SWAP": base,  # identical returns = correlation 1.0
        },
        dampening_floor=0.4,
    )
    assert result["factor"] == pytest.approx(0.4)
    assert result["max_correlation"] == pytest.approx(1.0)
    assert result["correlated_pair"] == "ETH-USDT-SWAP"


def test_uncorrelated_no_dampening():
    """Uncorrelated pairs should not dampen."""
    import random
    random.seed(42)
    btc = [random.gauss(0, 0.01) for _ in range(25)]
    # Reverse to break any pattern
    eth = list(reversed(btc))
    eth[0], eth[-1] = eth[-1], eth[0]

    result = compute_correlation_factor(
        new_pair="BTC-USDT-SWAP",
        new_direction="LONG",
        open_positions=[{"pair": "ETH-USDT-SWAP", "direction": "LONG"}],
        returns_by_pair={
            "BTC-USDT-SWAP": btc,
            "ETH-USDT-SWAP": eth,
        },
        dampening_floor=0.4,
    )
    # Correlation should be low, factor near 1.0
    assert result["factor"] > 0.8


def test_partial_correlation():
    """Moderate correlation should give partial dampening."""
    base = [0.01 * i for i in range(25)]
    noisy = [b + (0.005 if i % 2 == 0 else -0.005) for i, b in enumerate(base)]
    result = compute_correlation_factor(
        new_pair="BTC-USDT-SWAP",
        new_direction="LONG",
        open_positions=[{"pair": "ETH-USDT-SWAP", "direction": "LONG"}],
        returns_by_pair={
            "BTC-USDT-SWAP": base,
            "ETH-USDT-SWAP": noisy,
        },
        dampening_floor=0.4,
    )
    assert 0.4 < result["factor"] < 1.0


def test_custom_dampening_floor():
    base = [0.01 * i for i in range(25)]
    result = compute_correlation_factor(
        new_pair="BTC-USDT-SWAP",
        new_direction="LONG",
        open_positions=[{"pair": "ETH-USDT-SWAP", "direction": "LONG"}],
        returns_by_pair={
            "BTC-USDT-SWAP": base,
            "ETH-USDT-SWAP": base,
        },
        dampening_floor=0.5,
    )
    assert result["factor"] == pytest.approx(0.5)


def test_insufficient_lookback():
    """Returns shorter than lookback should not dampen."""
    short = [0.01, 0.02, 0.03]
    result = compute_correlation_factor(
        new_pair="BTC-USDT-SWAP",
        new_direction="LONG",
        open_positions=[{"pair": "ETH-USDT-SWAP", "direction": "LONG"}],
        returns_by_pair={
            "BTC-USDT-SWAP": short,
            "ETH-USDT-SWAP": short,
        },
        lookback=20,
    )
    assert result["factor"] == 1.0


def test_multiple_open_positions_picks_worst():
    """Should use the highest correlation across all open positions."""
    base = [0.01 * i for i in range(25)]
    uncorrelated = [(-1) ** i * 0.01 for i in range(25)]
    result = compute_correlation_factor(
        new_pair="BTC-USDT-SWAP",
        new_direction="LONG",
        open_positions=[
            {"pair": "ETH-USDT-SWAP", "direction": "LONG"},
            {"pair": "WIF-USDT-SWAP", "direction": "LONG"},
        ],
        returns_by_pair={
            "BTC-USDT-SWAP": base,
            "ETH-USDT-SWAP": base,  # perfect correlation
            "WIF-USDT-SWAP": uncorrelated,
        },
        dampening_floor=0.4,
    )
    # ETH is the correlated one
    assert result["correlated_pair"] == "ETH-USDT-SWAP"
    assert result["factor"] == pytest.approx(0.4)
