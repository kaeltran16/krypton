from datetime import datetime, timezone, timedelta

from app.engine.backtester import run_backtest, BacktestConfig
from app.engine.confluence import compute_confluence_score


def _make_candle_series(n=100, base_price=67000, trend=10, start_minutes_offset=0, minutes_per_candle=15):
    """Generate a synthetic candle series."""
    candles = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=start_minutes_offset)
    for i in range(n):
        o = base_price + i * trend
        candles.append({
            "timestamp": (start + timedelta(minutes=minutes_per_candle * i)).isoformat(),
            "open": o, "high": o + 50, "low": o - 30, "close": o + 20, "volume": 100 + i,
        })
    return candles


class TestPrecomputeParentIndicators:
    def test_returns_enriched_snapshots_after_min_candles(self):
        from app.engine.backtester import precompute_parent_indicators
        parent_candles = _make_candle_series(n=100, minutes_per_candle=60)
        timestamps, indicators = precompute_parent_indicators(parent_candles)
        # Should have snapshots for candles 70..99 = 30 snapshots
        assert len(timestamps) == 30
        assert len(indicators) == 30
        # enriched payload fields matching Redis cache shape
        for ind in indicators:
            assert "trend_score" in ind
            assert "mean_rev_score" in ind
            assert "trend_conviction" in ind
            assert "adx" in ind
            assert "di_plus" in ind
            assert "di_minus" in ind
            assert "regime" in ind

    def test_too_few_candles_returns_empty(self):
        from app.engine.backtester import precompute_parent_indicators
        parent_candles = _make_candle_series(n=50, minutes_per_candle=60)
        timestamps, indicators = precompute_parent_indicators(parent_candles)
        assert timestamps == []
        assert indicators == []

    def test_timestamps_are_sorted(self):
        from app.engine.backtester import precompute_parent_indicators
        parent_candles = _make_candle_series(n=100, minutes_per_candle=60)
        timestamps, _ = precompute_parent_indicators(parent_candles)
        assert timestamps == sorted(timestamps)


class TestLookupParentIndicators:
    def test_finds_most_recent_before_child(self):
        from app.engine.backtester import _lookup_parent_indicators
        timestamps = ["2025-01-01T01:00:00", "2025-01-01T02:00:00", "2025-01-01T03:00:00"]
        indicators = [{"adx": 10}, {"adx": 20}, {"adx": 30}]
        # Child at 02:30 should get the 02:00 snapshot
        result = _lookup_parent_indicators("2025-01-01T02:30:00", timestamps, indicators)
        assert result["adx"] == 20

    def test_returns_none_before_first_snapshot(self):
        from app.engine.backtester import _lookup_parent_indicators
        timestamps = ["2025-01-01T02:00:00"]
        indicators = [{"adx": 10}]
        result = _lookup_parent_indicators("2025-01-01T01:00:00", timestamps, indicators)
        assert result is None

    def test_returns_none_for_empty(self):
        from app.engine.backtester import _lookup_parent_indicators
        result = _lookup_parent_indicators("2025-01-01T01:00:00", [], [])
        assert result is None

    def test_exact_match_uses_that_snapshot(self):
        from app.engine.backtester import _lookup_parent_indicators
        timestamps = ["2025-01-01T01:00:00", "2025-01-01T02:00:00"]
        indicators = [{"adx": 10}, {"adx": 20}]
        result = _lookup_parent_indicators("2025-01-01T02:00:00", timestamps, indicators)
        assert result["adx"] == 20

    def test_never_returns_future_data(self):
        from app.engine.backtester import _lookup_parent_indicators
        timestamps = ["2025-01-01T03:00:00", "2025-01-01T04:00:00"]
        indicators = [{"adx": 30}, {"adx": 40}]
        result = _lookup_parent_indicators("2025-01-01T02:00:00", timestamps, indicators)
        assert result is None


class TestConfluenceScoreNewSignature:
    def test_trend_aligned_positive_score(self):
        """Bullish child + bullish parent trend => positive confluence."""
        child_indicators = {"trend_score": 60, "mean_rev_score": -10, "trend_conviction": 0.7}
        parent_cache = {
            "trend_score": 50, "mean_rev_score": -5, "trend_conviction": 0.8,
            "adx": 30, "di_plus": 28, "di_minus": 15,
            "regime": {"trending": 0.7, "ranging": 0.2, "volatile": 0.1},
        }
        result = compute_confluence_score(child_indicators, [parent_cache], timeframe="4h")
        assert result["score"] > 0
        assert "confidence" in result

    def test_opposing_directions_negative_score(self):
        """Bullish child + bearish parent trend => negative confluence."""
        child_indicators = {"trend_score": 60, "mean_rev_score": -10, "trend_conviction": 0.7}
        parent_cache = {
            "trend_score": -50, "mean_rev_score": 5, "trend_conviction": 0.8,
            "adx": 30, "di_plus": 12, "di_minus": 30,
            "regime": {"trending": 0.7, "ranging": 0.2, "volatile": 0.1},
        }
        result = compute_confluence_score(child_indicators, [parent_cache], timeframe="4h")
        assert result["score"] < 0

    def test_no_parents_returns_zero(self):
        """All None parents => zero score."""
        child_indicators = {"trend_score": 60, "mean_rev_score": -10, "trend_conviction": 0.7}
        result = compute_confluence_score(child_indicators, [None, None, None], timeframe="15m")
        assert result["score"] == 0
        assert result["confidence"] == 0.0

    def test_neutral_child_returns_zero(self):
        """Zero child scores => zero confluence."""
        child_indicators = {"trend_score": 0, "mean_rev_score": 0, "trend_conviction": 0}
        parent_cache = {
            "trend_score": 50, "mean_rev_score": -5, "trend_conviction": 0.8,
            "adx": 30, "di_plus": 28, "di_minus": 15,
            "regime": {"trending": 0.7, "ranging": 0.2, "volatile": 0.1},
        }
        result = compute_confluence_score(child_indicators, [parent_cache], timeframe="4h")
        assert result["score"] == 0

    def test_multi_level_parents(self):
        """15m timeframe with 3 ancestor levels."""
        child_indicators = {"trend_score": 50, "mean_rev_score": -5, "trend_conviction": 0.6}
        parent_1h = {
            "trend_score": 40, "mean_rev_score": -3, "trend_conviction": 0.7,
            "adx": 25, "di_plus": 24, "di_minus": 14,
            "regime": {"trending": 0.6, "ranging": 0.3, "volatile": 0.1},
        }
        parent_4h = {
            "trend_score": 35, "mean_rev_score": -2, "trend_conviction": 0.6,
            "adx": 22, "di_plus": 22, "di_minus": 15,
            "regime": {"trending": 0.5, "ranging": 0.35, "volatile": 0.15},
        }
        parent_1d = {
            "trend_score": 30, "mean_rev_score": -1, "trend_conviction": 0.5,
            "adx": 20, "di_plus": 20, "di_minus": 16,
            "regime": {"trending": 0.4, "ranging": 0.4, "volatile": 0.2},
        }
        result = compute_confluence_score(
            child_indicators, [parent_1h, parent_4h, parent_1d], timeframe="15m",
        )
        assert result["score"] > 0
        assert result["confidence"] > 0


class TestBacktestWithConfluence:
    def test_with_parent_candles_by_tf(self):
        """Backtest with multi-level parent candles via parent_candles_by_tf."""
        child_candles = _make_candle_series(n=120, base_price=67000, trend=10)
        parent_1h = _make_candle_series(n=100, base_price=67000, trend=10, minutes_per_candle=60)
        parent_4h = _make_candle_series(n=100, base_price=67000, trend=10, minutes_per_candle=240)
        config = BacktestConfig(signal_threshold=20, max_concurrent_positions=5)

        result = run_backtest(
            child_candles, "BTC-USDT-SWAP", config,
            timeframe="15m",
            parent_candles_by_tf={"1h": parent_1h, "4h": parent_4h},
        )
        assert "stats" in result
        assert "trades" in result

    def test_with_legacy_parent_candles(self):
        """Backward compat: single parent_candles param still works."""
        child_candles = _make_candle_series(n=120, base_price=67000, trend=10)
        parent_candles = _make_candle_series(n=100, base_price=67000, trend=10, minutes_per_candle=60)
        config = BacktestConfig(signal_threshold=20, max_concurrent_positions=5)

        result = run_backtest(
            child_candles, "BTC-USDT-SWAP", config,
            timeframe="15m",
            parent_candles=parent_candles,
        )
        assert "stats" in result

    def test_without_parent_candles_runs_normally(self):
        """Backtest without parent candles should work identically to before."""
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(signal_threshold=20)
        result = run_backtest(candles, "BTC-USDT-SWAP", config, timeframe="15m", parent_candles=None)
        assert "stats" in result
        assert "trades" in result

    def test_timeframe_parameter_affects_confluence(self):
        """Different timeframe params should use different ancestor chains."""
        child_candles = _make_candle_series(n=120, base_price=67000, trend=10, minutes_per_candle=60)
        parent_4h = _make_candle_series(n=100, base_price=67000, trend=10, minutes_per_candle=240)
        parent_1d = _make_candle_series(n=100, base_price=67000, trend=10, minutes_per_candle=1440)
        config = BacktestConfig(signal_threshold=20, max_concurrent_positions=5)

        # 1h timeframe has ancestors ["4h", "1D"]
        result = run_backtest(
            child_candles, "BTC-USDT-SWAP", config,
            timeframe="1h",
            parent_candles_by_tf={"4h": parent_4h, "1D": parent_1d},
        )
        assert "stats" in result
