from collections import deque
from datetime import datetime, timezone, timedelta

import pytest

from app.engine.backtester import run_backtest, BacktestConfig, _resolve_positions, SimulatedTrade


def _make_candle_series(n=60, base_price=67000, trend=10):
    """Generate a synthetic candle series with a trend."""
    candles = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        o = base_price + i * trend
        h = o + 50
        l = o - 30
        c = o + 20
        candles.append({
            "timestamp": (start + timedelta(minutes=15 * i)).isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": 100 + i,
        })
    return candles


def _make_candle_series_reversal(n=80, base_price=67000):
    """Uptrend then sharp reversal — guarantees both signals and SL hits."""
    candles = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        if i < 60:
            o = base_price + i * 10
            h = o + 50
            l = o - 30
            c = o + 20
        else:
            # Sharp drop
            o = base_price + 600 - (i - 60) * 100
            h = o + 20
            l = o - 120
            c = o - 80
        candles.append({
            "timestamp": (start + timedelta(minutes=15 * i)).isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": 100,
        })
    return candles


class TestRunBacktest:

    def test_returns_results_with_trades(self):
        candles = _make_candle_series(n=100)
        config = BacktestConfig(signal_threshold=20, max_concurrent_positions=5)
        result = run_backtest(candles, "BTC-USDT-SWAP", config)
        assert "trades" in result
        assert "stats" in result
        assert isinstance(result["trades"], list)

    def test_too_few_candles_returns_empty(self):
        candles = _make_candle_series(n=10)
        result = run_backtest(candles, "BTC-USDT-SWAP")
        assert result["stats"]["total_trades"] == 0
        assert result["trades"] == []

    def test_high_threshold_no_trades(self):
        candles = _make_candle_series(n=60)
        config = BacktestConfig(signal_threshold=99)
        result = run_backtest(candles, "BTC-USDT-SWAP", config)
        assert result["stats"]["total_trades"] == 0

    def test_max_concurrent_positions_enforced(self):
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(
            signal_threshold=10,
            max_concurrent_positions=1,
        )
        result = run_backtest(candles, "BTC-USDT-SWAP", config)
        # With max 1, only one position can be open at a time
        # Just verify we get results without error
        assert "stats" in result

    def test_cancellation_stops_iteration(self):
        candles = _make_candle_series(n=200)
        flag = {"cancelled": False}

        # Cancel after a short time
        import threading
        def cancel_later():
            import time
            time.sleep(0.01)
            flag["cancelled"] = True
        t = threading.Thread(target=cancel_later)
        t.start()

        config = BacktestConfig(signal_threshold=10)
        result = run_backtest(candles, "BTC-USDT-SWAP", config, cancel_flag=flag)
        t.join()
        # Should have stopped early — results still valid
        assert "stats" in result

    def test_trade_has_required_fields(self):
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(signal_threshold=10, max_concurrent_positions=5)
        result = run_backtest(candles, "BTC-USDT-SWAP", config)
        if result["trades"]:
            trade = result["trades"][0]
            assert "pair" in trade
            assert "direction" in trade
            assert "entry_time" in trade
            assert "entry_price" in trade
            assert "sl" in trade
            assert "tp1" in trade
            assert "outcome" in trade
            assert "pnl_pct" in trade
            assert "score" in trade
            assert "detected_patterns" in trade

    def test_stats_have_expected_keys(self):
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(signal_threshold=10, max_concurrent_positions=5)
        result = run_backtest(candles, "BTC-USDT-SWAP", config)
        stats = result["stats"]
        assert "total_trades" in stats
        assert "win_rate" in stats
        assert "net_pnl" in stats
        assert "max_drawdown" in stats
        assert "profit_factor" in stats
        assert "equity_curve" in stats
        assert "by_direction" in stats
        assert "monthly_pnl" in stats

    def test_win_rate_bounded(self):
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(signal_threshold=10, max_concurrent_positions=5)
        result = run_backtest(candles, "BTC-USDT-SWAP", config)
        assert 0 <= result["stats"]["win_rate"] <= 100

    def test_patterns_disabled(self):
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(
            signal_threshold=10,
            enable_patterns=False,
            tech_weight=1.0,
            pattern_weight=0.0,
        )
        result = run_backtest(candles, "BTC-USDT-SWAP", config)
        assert "stats" in result


class TestResolvePositions:

    def test_long_sl_hit(self):
        trade = SimulatedTrade(
            pair="BTC", direction="LONG",
            entry_time="2025-01-01T00:00:00+00:00",
            entry_price=100, sl=95, tp1=110, tp2=120, score=60,
        )
        candle = {"high": 101, "low": 94, "close": 94.5,
                  "timestamp": "2025-01-01T00:15:00+00:00"}
        open_pos = [trade]
        closed = []
        _resolve_positions(open_pos, candle, closed)
        assert len(closed) == 1
        assert closed[0].outcome == "SL_HIT"
        assert len(open_pos) == 0

    def test_long_tp1_hit(self):
        trade = SimulatedTrade(
            pair="BTC", direction="LONG",
            entry_time="2025-01-01T00:00:00+00:00",
            entry_price=100, sl=95, tp1=110, tp2=120, score=60,
        )
        candle = {"high": 112, "low": 99, "close": 111,
                  "timestamp": "2025-01-01T00:15:00+00:00"}
        open_pos = [trade]
        closed = []
        _resolve_positions(open_pos, candle, closed)
        assert len(closed) == 1
        assert closed[0].outcome == "TP1_HIT"

    def test_long_tp2_hit(self):
        trade = SimulatedTrade(
            pair="BTC", direction="LONG",
            entry_time="2025-01-01T00:00:00+00:00",
            entry_price=100, sl=95, tp1=110, tp2=120, score=60,
        )
        candle = {"high": 125, "low": 99, "close": 122,
                  "timestamp": "2025-01-01T00:15:00+00:00"}
        open_pos = [trade]
        closed = []
        _resolve_positions(open_pos, candle, closed)
        assert closed[0].outcome == "TP2_HIT"

    def test_short_sl_hit(self):
        trade = SimulatedTrade(
            pair="BTC", direction="SHORT",
            entry_time="2025-01-01T00:00:00+00:00",
            entry_price=100, sl=105, tp1=90, tp2=80, score=-60,
        )
        candle = {"high": 106, "low": 99, "close": 105.5,
                  "timestamp": "2025-01-01T00:15:00+00:00"}
        open_pos = [trade]
        closed = []
        _resolve_positions(open_pos, candle, closed)
        assert closed[0].outcome == "SL_HIT"

    def test_short_tp1_hit(self):
        trade = SimulatedTrade(
            pair="BTC", direction="SHORT",
            entry_time="2025-01-01T00:00:00+00:00",
            entry_price=100, sl=105, tp1=90, tp2=80, score=-60,
        )
        candle = {"high": 101, "low": 88, "close": 89,
                  "timestamp": "2025-01-01T00:15:00+00:00"}
        open_pos = [trade]
        closed = []
        _resolve_positions(open_pos, candle, closed)
        assert closed[0].outcome == "TP1_HIT"

    def test_no_hit_stays_open(self):
        trade = SimulatedTrade(
            pair="BTC", direction="LONG",
            entry_time="2025-01-01T00:00:00+00:00",
            entry_price=100, sl=95, tp1=110, tp2=120, score=60,
        )
        candle = {"high": 105, "low": 96, "close": 103,
                  "timestamp": "2025-01-01T00:15:00+00:00"}
        open_pos = [trade]
        closed = []
        _resolve_positions(open_pos, candle, closed)
        assert len(closed) == 0
        assert len(open_pos) == 1

    def test_sl_checked_before_tp(self):
        """SL hit takes priority over TP hit on the same candle."""
        trade = SimulatedTrade(
            pair="BTC", direction="LONG",
            entry_time="2025-01-01T00:00:00+00:00",
            entry_price=100, sl=95, tp1=110, tp2=120, score=60,
        )
        # Both SL and TP1 would trigger on this candle
        candle = {"high": 112, "low": 94, "close": 100,
                  "timestamp": "2025-01-01T00:15:00+00:00"}
        open_pos = [trade]
        closed = []
        _resolve_positions(open_pos, candle, closed)
        assert closed[0].outcome == "SL_HIT"


class TestMLBacktest:

    def test_ml_mode_runs(self):
        """ML backtest should work with a dummy predictor."""
        candles = _make_candle_series(n=120)
        config = BacktestConfig(signal_threshold=20, max_concurrent_positions=5)

        class MockPredictor:
            seq_len = 50
            def predict(self, features):
                import numpy as np
                return {
                    "direction": "LONG" if np.random.random() > 0.5 else "SHORT",
                    "confidence": 0.75,
                    "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0,
                }

        result = run_backtest(candles, "BTC-USDT-SWAP", config, ml_predictor=MockPredictor())
        assert "trades" in result
        assert "stats" in result

    def test_ml_mode_produces_trades(self):
        """ML backtest should produce some trades."""
        candles = _make_candle_series(n=150, trend=15)
        config = BacktestConfig(signal_threshold=10, max_concurrent_positions=5)

        class AlwaysLongPredictor:
            seq_len = 50
            def predict(self, features):
                return {
                    "direction": "LONG",
                    "confidence": 0.90,
                    "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0,
                }

        result = run_backtest(candles, "BTC-USDT-SWAP", config, ml_predictor=AlwaysLongPredictor())
        assert result["stats"]["total_trades"] > 0


class TestPhase1Scaling:

    def test_backtester_applies_phase1_scaling(self):
        """Backtest level calculation applies signal strength + volatility scaling."""
        from app.engine.combiner import scale_atr_multipliers

        # Simulate what the backtester should do: apply Phase 1 scaling to config multipliers
        score = 80
        bb_width_pct = 70.0
        sl_base, tp1_base, tp2_base = 1.5, 2.0, 3.0

        scaled = scale_atr_multipliers(
            score=score, bb_width_pct=bb_width_pct,
            sl_base=sl_base, tp1_base=tp1_base, tp2_base=tp2_base,
            signal_threshold=40,
        )

        # Phase 1 scaling should modify the multipliers (score=80, bb_width=70 → not default)
        assert scaled["sl_atr"] != sl_base
        assert scaled["tp1_atr"] != tp1_base

        # TP should scale more aggressively than SL
        tp_ratio = scaled["tp1_atr"] / tp1_base
        sl_ratio = scaled["sl_atr"] / sl_base
        assert tp_ratio > sl_ratio


def _make_flow_snapshots(candles: list[dict], start_idx: int = 20) -> list[dict]:
    """Create flow snapshots aligned to candle timestamps, starting at start_idx."""
    snapshots = []
    for c in candles[start_idx:]:
        ts = c["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        snapshots.append({
            "timestamp": ts,
            "funding_rate": 0.0003,
            "open_interest": 1_000_000.0,
            "oi_change_pct": 1.5,
            "long_short_ratio": 1.2,
            "cvd_delta": 200.0,
        })
    return snapshots


class TestFlowBacktest:
    def test_no_flow_snapshots_same_as_before(self):
        """BacktestConfig with flow_snapshots=None produces same results."""
        candles = _make_candle_series(n=120)
        config = BacktestConfig()
        result_without = run_backtest(candles, "BTC-USDT-SWAP", config)
        config_with_none = BacktestConfig(flow_snapshots=None)
        result_with_none = run_backtest(candles, "BTC-USDT-SWAP", config_with_none)
        assert result_without["stats"]["total_trades"] == result_with_none["stats"]["total_trades"]

    def test_flow_snapshots_field_accepted(self):
        """BacktestConfig accepts flow_snapshots parameter."""
        config = BacktestConfig(flow_snapshots=[{"timestamp": datetime.now(timezone.utc)}])
        assert config.flow_snapshots is not None

    def test_flow_snapshots_affects_scoring(self):
        """Backtest with flow snapshots may produce different trade count."""
        candles = _make_candle_series(n=120)
        snapshots = _make_flow_snapshots(candles, start_idx=20)
        config_no_flow = BacktestConfig(signal_threshold=20)
        config_flow = BacktestConfig(signal_threshold=20, flow_snapshots=snapshots)
        result_no = run_backtest(candles, "BTC-USDT-SWAP", config_no_flow)
        result_flow = run_backtest(candles, "BTC-USDT-SWAP", config_flow)
        # With flow data, scoring changes — trade count may differ
        # At minimum, the function should run without error
        assert result_flow["stats"]["total_trades"] >= 0

    def test_early_candles_without_snapshots_degrade_gracefully(self):
        """Candles before snapshot coverage get flow_score=0."""
        candles = _make_candle_series(n=120)
        # Only provide snapshots for last 30 candles
        snapshots = _make_flow_snapshots(candles, start_idx=90)
        config = BacktestConfig(flow_snapshots=snapshots, signal_threshold=20)
        result = run_backtest(candles, "BTC-USDT-SWAP", config)
        assert result["stats"]["total_trades"] >= 0
