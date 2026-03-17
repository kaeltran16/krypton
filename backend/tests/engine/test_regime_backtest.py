# backend/tests/engine/test_regime_backtest.py
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from app.engine.backtester import run_backtest, BacktestConfig


def _make_candle_series(n=100, base_price=67000, trend=10, minutes_per_candle=15):
    candles = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        o = base_price + i * trend
        candles.append({
            "timestamp": (start + timedelta(minutes=minutes_per_candle * i)).isoformat(),
            "open": o, "high": o + 50, "low": o - 30, "close": o + 20, "volume": 100 + i,
        })
    return candles


class TestBacktestWithRegimeWeights:
    def test_without_regime_weights_runs_normally(self):
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(signal_threshold=20)
        result = run_backtest(candles, "BTC-USDT-SWAP", config, regime_weights=None)
        assert "stats" in result
        assert "trades" in result

    def test_with_regime_weights_runs_successfully(self):
        candles = _make_candle_series(n=100, trend=15)
        config = BacktestConfig(signal_threshold=20)
        rw = MagicMock()
        # Set all 24 float attributes
        for regime in ["trending", "ranging", "volatile"]:
            setattr(rw, f"{regime}_trend_cap", 30.0)
            setattr(rw, f"{regime}_mean_rev_cap", 25.0)
            setattr(rw, f"{regime}_bb_vol_cap", 25.0)
            setattr(rw, f"{regime}_volume_cap", 20.0)
            setattr(rw, f"{regime}_tech_weight", 0.40)
            setattr(rw, f"{regime}_flow_weight", 0.20)
            setattr(rw, f"{regime}_onchain_weight", 0.20)
            setattr(rw, f"{regime}_pattern_weight", 0.20)
        result = run_backtest(candles, "BTC-USDT-SWAP", config, regime_weights=rw)
        assert "stats" in result

    def test_regime_weights_affect_scoring(self):
        """Different regime weights should produce different backtest results."""
        candles = _make_candle_series(n=120, trend=15)
        config = BacktestConfig(signal_threshold=15)

        result_default = run_backtest(candles, "BTC-USDT-SWAP", config, regime_weights=None)

        # Extreme regime weights: all trend, no mean-rev
        rw = MagicMock()
        for regime in ["trending", "ranging", "volatile"]:
            setattr(rw, f"{regime}_trend_cap", 45.0)
            setattr(rw, f"{regime}_mean_rev_cap", 10.0)
            setattr(rw, f"{regime}_bb_vol_cap", 25.0)
            setattr(rw, f"{regime}_volume_cap", 20.0)
            setattr(rw, f"{regime}_tech_weight", 0.80)
            setattr(rw, f"{regime}_flow_weight", 0.0)
            setattr(rw, f"{regime}_onchain_weight", 0.0)
            setattr(rw, f"{regime}_pattern_weight", 0.20)
        result_custom = run_backtest(candles, "BTC-USDT-SWAP", config, regime_weights=rw)

        # Both should run successfully
        assert "stats" in result_default
        assert "stats" in result_custom
        # Extreme cap changes should affect signal generation or scoring
        ds = result_default["stats"]
        cs = result_custom["stats"]
        differs = (
            ds["total_trades"] != cs["total_trades"]
            or ds["win_rate"] != cs["win_rate"]
            or ds["net_pnl"] != cs["net_pnl"]
            or ds["max_drawdown"] != cs["max_drawdown"]
        )
        assert differs, "Regime weights should produce different backtest outcomes"
