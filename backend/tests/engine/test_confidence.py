"""Tests for confidence emission from all scoring sources."""
import pandas as pd
import numpy as np

from tests.engine.test_traditional import _make_candles
from app.engine.traditional import compute_technical_score, compute_order_flow_score


class TestTechnicalConfidence:
    def test_confidence_key_present(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0

    def test_high_adx_high_conviction_means_high_confidence(self):
        """Strong trend indicators should produce higher confidence than weak ones."""
        df_strong = _make_candles(80, "up")
        df_weak = _make_candles(80, "flat")
        r_strong = compute_technical_score(df_strong)
        r_weak = compute_technical_score(df_weak)
        # strong trend should have higher confidence
        assert r_strong["confidence"] >= r_weak["confidence"]


class TestOrderFlowConfidence:
    def test_confidence_key_present(self):
        result = compute_order_flow_score({"funding_rate": 0.001})
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0

    def test_all_inputs_present_higher_confidence(self):
        """All 3 inputs present should give higher confidence than single input."""
        result_single = compute_order_flow_score({"funding_rate": 0.001})
        result_all = compute_order_flow_score({
            "funding_rate": 0.001,
            "open_interest_change_pct": 5.0,
            "price_direction": 1,
            "long_short_ratio": 1.2,
        })
        assert result_all["confidence"] > result_single["confidence"]

    def test_empty_metrics_low_confidence(self):
        result = compute_order_flow_score({})
        assert result["confidence"] <= 0.5


from unittest.mock import AsyncMock
import pytest
from app.engine.onchain_scorer import compute_onchain_score


class TestOnchainConfidence:
    @pytest.mark.asyncio
    async def test_returns_dict_with_confidence(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=lambda key: {
            "onchain:BTC-USDT-SWAP:exchange_netflow": "-500",
            "onchain:BTC-USDT-SWAP:whale_tx_count": "5",
        }.get(key))
        result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert isinstance(result, dict)
        assert "score" in result
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_empty_data_low_confidence(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert result["confidence"] == 0.0
        assert result["score"] == 0


from app.engine.patterns import compute_pattern_score


class TestPatternConfidence:
    def test_returns_dict_with_confidence(self):
        patterns = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        result = compute_pattern_score(patterns)
        assert isinstance(result, dict)
        assert "score" in result
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0

    def test_no_patterns_zero_confidence(self):
        result = compute_pattern_score([])
        assert result["score"] == 0
        assert result["confidence"] == 0.0

    def test_more_patterns_higher_confidence(self):
        single = [{"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}]
        multi = [
            {"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12},
            {"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15},
        ]
        r1 = compute_pattern_score(single)
        r2 = compute_pattern_score(multi)
        assert r2["confidence"] >= r1["confidence"]
