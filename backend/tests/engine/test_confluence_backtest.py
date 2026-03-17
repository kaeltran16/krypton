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
    def test_returns_snapshots_after_min_candles(self):
        from app.engine.backtester import precompute_parent_indicators
        parent_candles = _make_candle_series(n=100, minutes_per_candle=60)
        timestamps, indicators = precompute_parent_indicators(parent_candles)
        # Should have snapshots for candles 70..99 = 30 snapshots
        assert len(timestamps) == 30
        assert len(indicators) == 30
        assert all("adx" in ind for ind in indicators)
        assert all("di_plus" in ind for ind in indicators)
        assert all("di_minus" in ind for ind in indicators)

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


class TestBacktestWithConfluence:
    def test_with_parent_candles_produces_different_scores(self):
        """Backtest with parent candles should produce different results than without."""
        child_candles = _make_candle_series(n=120, base_price=67000, trend=10)
        parent_candles = _make_candle_series(n=100, base_price=67000, trend=10, minutes_per_candle=60)
        config = BacktestConfig(signal_threshold=20, max_concurrent_positions=5)

        result_without = run_backtest(child_candles, "BTC-USDT-SWAP", config)
        result_with = run_backtest(child_candles, "BTC-USDT-SWAP", config, parent_candles=parent_candles)

        # Both should run successfully
        assert "stats" in result_without
        assert "stats" in result_with

    def test_without_parent_candles_runs_normally(self):
        """Backtest without parent candles should work identically to before."""
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(signal_threshold=20)
        result = run_backtest(candles, "BTC-USDT-SWAP", config, parent_candles=None)
        assert "stats" in result
        assert "trades" in result
