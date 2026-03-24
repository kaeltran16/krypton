# backend/tests/engine/test_onchain_scorer.py — full rewrite
import pytest
from unittest.mock import AsyncMock
from app.engine.onchain_scorer import compute_onchain_score


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    return redis


def _setup_redis(redis, pair, data: dict):
    """Helper to mock Redis keys for on-chain data."""
    async def mock_get(key):
        prefix = f"onchain:{pair}:"
        if key.startswith(prefix):
            metric = key[len(prefix):]
            return str(data.get(metric)) if metric in data else None
        return None
    redis.get = AsyncMock(side_effect=mock_get)


class TestBTCProfile:
    @pytest.mark.asyncio
    async def test_btc_outflow_is_bullish(self, mock_redis):
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"exchange_netflow": -5000})
        result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert result["score"] > 0

    @pytest.mark.asyncio
    async def test_btc_inflow_is_bearish(self, mock_redis):
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"exchange_netflow": 5000})
        result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert result["score"] < 0

    @pytest.mark.asyncio
    async def test_btc_high_nupl_is_bearish(self, mock_redis):
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"nupl": 0.8})
        result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert result["score"] < 0

    @pytest.mark.asyncio
    async def test_btc_score_bounded(self, mock_redis):
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {
            "exchange_netflow": -10000, "whale_tx_count": 0,
            "nupl": -0.5, "hashrate_change_pct": 0.5, "addr_trend_pct": 0.5,
        })
        result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert -100 <= result["score"] <= 100


class TestETHProfile:
    @pytest.mark.asyncio
    async def test_eth_outflow_is_bullish(self, mock_redis):
        _setup_redis(mock_redis, "ETH-USDT-SWAP", {"exchange_netflow": -100000})
        result = await compute_onchain_score("ETH-USDT-SWAP", mock_redis)
        assert result["score"] > 0

    @pytest.mark.asyncio
    async def test_eth_uses_different_normalization(self, mock_redis):
        """Same netflow magnitude should produce different scores for BTC vs ETH."""
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"exchange_netflow": -3000})
        btc_result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)

        _setup_redis(mock_redis, "ETH-USDT-SWAP", {"exchange_netflow": -3000})
        eth_result = await compute_onchain_score("ETH-USDT-SWAP", mock_redis)

        # 3000 is a full normalization unit for BTC but small for ETH (50000)
        assert abs(btc_result["score"]) > abs(eth_result["score"])


class TestUnknownPair:
    @pytest.mark.asyncio
    async def test_unknown_pair_returns_zero(self, mock_redis):
        result = await compute_onchain_score("DOGE-USDT-SWAP", mock_redis)
        assert result["score"] == 0


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_missing_metrics_still_score(self, mock_redis):
        """Only netflow available — should still produce a score from that component."""
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"exchange_netflow": -5000})
        result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert result["score"] > 0

    @pytest.mark.asyncio
    async def test_no_data_returns_zero(self, mock_redis):
        result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert result["score"] == 0


class TestSigmoidContinuity:
    @pytest.mark.asyncio
    async def test_small_netflow_produces_small_score(self, mock_redis):
        """No dead zone — even small netflow should produce non-zero score."""
        _setup_redis(mock_redis, "BTC-USDT-SWAP", {"exchange_netflow": -100})
        result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert result["score"] != 0
