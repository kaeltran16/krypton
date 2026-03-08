import json

import pytest
from unittest.mock import AsyncMock

from app.engine.onchain_scorer import (
    compute_onchain_score,
    _score_exchange_netflow,
    _score_whale_movements,
    _score_nupl,
    _score_active_addresses_trend,
)


# --- Pure unit tests for individual scoring functions ---

def test_netflow_outflow_is_bullish():
    """Negative netflow (coins leaving exchanges) should be bullish (positive)."""
    score = _score_exchange_netflow(-3000)
    assert score > 0


def test_netflow_inflow_is_bearish():
    """Positive netflow (coins entering exchanges) should be bearish (negative)."""
    score = _score_exchange_netflow(3000)
    assert score < 0


def test_netflow_zero():
    assert _score_exchange_netflow(0) == 0


def test_netflow_capped_at_35():
    """Even extreme values should cap at ±35."""
    assert _score_exchange_netflow(-999999) == 35
    assert _score_exchange_netflow(999999) == -35


def test_whale_low_activity_bullish():
    assert _score_whale_movements(1) == 10


def test_whale_moderate_neutral():
    assert _score_whale_movements(4) == 0


def test_whale_high_activity_bearish():
    assert _score_whale_movements(15) == -25


def test_nupl_extreme_greed_bearish():
    assert _score_nupl(0.8) == -20


def test_nupl_capitulation_bullish():
    assert _score_nupl(-0.1) == 20


def test_nupl_optimism_neutral():
    assert _score_nupl(0.3) == 0


def test_active_addresses_rising_bullish():
    history = [100, 100, 100, 100, 120, 130, 140, 150]
    score = _score_active_addresses_trend(history)
    assert score > 0


def test_active_addresses_falling_bearish():
    history = [150, 140, 130, 120, 100, 100, 100, 100]
    score = _score_active_addresses_trend(history)
    assert score < 0


def test_active_addresses_flat_neutral():
    history = [100, 100, 100, 100, 100, 100, 100, 100]
    score = _score_active_addresses_trend(history)
    assert score == 0


def test_active_addresses_too_short():
    """Not enough data points returns 0."""
    assert _score_active_addresses_trend([100, 200]) == 0


# --- Integration tests with mocked Redis ---

@pytest.mark.asyncio
async def test_compute_onchain_score_all_metrics():
    """Score with all metrics present."""
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=lambda key: {
        "onchain:BTC-USDT-SWAP:exchange_netflow": json.dumps({"value": -2000}),
        "onchain:BTC-USDT-SWAP:whale_tx_count": json.dumps({"value": 3}),
        "onchain:BTC-USDT-SWAP:nupl": json.dumps({"value": 0.3}),
    }.get(key))
    redis.lrange = AsyncMock(return_value=[
        json.dumps({"v": 100}) for _ in range(6)
    ])

    score = await compute_onchain_score("BTC-USDT-SWAP", redis)
    assert -100 <= score <= 100
    # Netflow bullish ~14 + whale neutral 0 + nupl neutral 0 + addr flat 0
    assert score > 0


@pytest.mark.asyncio
async def test_compute_onchain_score_no_data():
    """When no metrics are cached, returns 0."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.lrange = AsyncMock(return_value=[])

    score = await compute_onchain_score("BTC-USDT-SWAP", redis)
    assert score == 0


@pytest.mark.asyncio
async def test_compute_onchain_score_partial_data():
    """Only netflow available — returns partial score based on that alone."""
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=lambda key: {
        "onchain:BTC-USDT-SWAP:exchange_netflow": json.dumps({"value": 5000}),
    }.get(key))
    redis.lrange = AsyncMock(return_value=[])

    score = await compute_onchain_score("BTC-USDT-SWAP", redis)
    assert score == -35  # Max bearish from netflow only


@pytest.mark.asyncio
async def test_compute_onchain_score_bounded():
    """Score stays within -100 to +100 even with extreme values."""
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=lambda key: {
        "onchain:BTC-USDT-SWAP:exchange_netflow": json.dumps({"value": -99999}),
        "onchain:BTC-USDT-SWAP:whale_tx_count": json.dumps({"value": 0}),
        "onchain:BTC-USDT-SWAP:nupl": json.dumps({"value": -0.5}),
    }.get(key))
    # Strongly rising trend
    hist = [json.dumps({"v": v}) for v in [10, 10, 10, 10, 100, 100, 100, 100]]
    redis.lrange = AsyncMock(return_value=hist)

    score = await compute_onchain_score("BTC-USDT-SWAP", redis)
    assert -100 <= score <= 100
