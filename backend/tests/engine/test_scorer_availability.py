import pytest
import pandas as pd
import numpy as np


def _make_df(n=100, base=67000, trend=10):
    """Minimal candle DataFrame for scorer tests."""
    data = []
    for i in range(n):
        p = base + i * trend
        data.append({
            "timestamp": f"2026-01-01T{i:04d}",
            "open": p, "high": p + 50, "low": p - 50, "close": p + 20,
            "volume": 1000 + i * 10,
        })
    return pd.DataFrame(data)


class TestTechScorerFormat:
    def test_returns_availability_and_conviction(self):
        from app.engine.traditional import compute_technical_score
        df = _make_df()
        result = compute_technical_score(df)
        assert "availability" in result
        assert "conviction" in result
        assert result["availability"] == 1.0  # candle data always present
        assert 0.0 <= result["conviction"] <= 1.0


class TestFlowScorerFormat:
    def test_returns_availability_and_conviction(self):
        from app.engine.traditional import compute_order_flow_score
        metrics = {
            "funding_rate": 0.001,
            "open_interest_change_pct": 5.0,
            "long_short_ratio": 1.2,
        }
        result = compute_order_flow_score(metrics)
        assert "availability" in result
        assert "conviction" in result
        assert 0.0 <= result["availability"] <= 1.0
        assert 0.0 <= result["conviction"] <= 1.0

    def test_empty_metrics_zero_availability(self):
        from app.engine.traditional import compute_order_flow_score
        result = compute_order_flow_score({})
        assert result["availability"] == 0.0

    def test_neutral_subsignals_contribute_half_conviction(self):
        """Sub-signals with score=0 count as 0.5 conviction, not excluded."""
        from app.engine.traditional import compute_order_flow_score
        # Only funding present with neutral value (0)
        metrics = {"funding_rate": 0.0}
        result = compute_order_flow_score(metrics)
        # 1 feed available, score=0 (neutral), conviction should be 0.5
        assert result["conviction"] == pytest.approx(0.5, abs=0.1)


class TestOnchainScorerFormat:
    @pytest.mark.asyncio
    async def test_returns_availability_and_conviction(self):
        from unittest.mock import AsyncMock
        from app.engine.onchain_scorer import compute_onchain_score
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value='{"exchange_netflow": -5000}')
        result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert "availability" in result
        assert "conviction" in result
        assert 0.0 <= result["availability"] <= 1.0
        assert 0.0 <= result["conviction"] <= 1.0


class TestPatternScorerFormat:
    def test_returns_availability_and_conviction(self):
        from app.engine.patterns import compute_pattern_score
        patterns = [
            {"name": "bullish_engulfing", "bias": "bullish", "strength": 15},
            {"name": "hammer", "bias": "bullish", "strength": 12},
        ]
        result = compute_pattern_score(patterns)
        assert "availability" in result
        assert "conviction" in result
        assert 0.0 <= result["availability"] <= 1.0
        assert 0.0 <= result["conviction"] <= 1.0

    def test_no_patterns_zero_availability(self):
        from app.engine.patterns import compute_pattern_score
        result = compute_pattern_score([])
        assert result["availability"] == 0.0


class TestLiquidationScorerFormat:
    def test_returns_availability_and_conviction(self):
        from datetime import datetime, timezone
        from app.engine.liquidation_scorer import compute_liquidation_score
        now = datetime.now(timezone.utc)
        events = [
            {"price": 67100, "volume": 5000, "side": "buy", "timestamp": now},
        ] * 5
        result = compute_liquidation_score(events, current_price=67000, atr=200)
        assert "availability" in result
        assert "conviction" in result
        assert 0.0 <= result["availability"] <= 1.0
        assert 0.0 <= result["conviction"] <= 1.0


class TestConfluenceScorerFormat:
    def test_returns_availability_and_conviction(self):
        from app.engine.confluence import compute_confluence_score
        child = {"trend_score": 30, "mean_rev_score": 0, "trend_conviction": 0.7}
        parent = [{"trend_score": 40, "adx": 25, "di_plus": 30, "di_minus": 15,
                    "trend_conviction": 0.8, "regime": {"trending": 0.7}}]
        result = compute_confluence_score(child, parent, timeframe="15m")
        assert "availability" in result
        assert "conviction" in result
        assert 0.0 <= result["availability"] <= 1.0
        assert 0.0 <= result["conviction"] <= 1.0
