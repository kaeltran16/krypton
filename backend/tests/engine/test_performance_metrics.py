"""Unit tests for performance metrics computation."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.api.routes import _compute_performance_metrics, _compute_drawdown_series, _compute_pnl_distribution


def _make_signal(pnl_pct, outcome="TP1_HIT", pair="BTC-USDT-SWAP", timeframe="1h",
                 direction="LONG", duration_minutes=120, days_ago=0):
    s = MagicMock()
    s.outcome_pnl_pct = pnl_pct
    s.outcome = outcome
    s.pair = pair
    s.timeframe = timeframe
    s.direction = direction
    s.outcome_duration_minutes = duration_minutes
    s.outcome_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    s.created_at = s.outcome_at - timedelta(minutes=duration_minutes)
    return s


class TestPerformanceMetrics:
    def test_empty_returns_nulls(self):
        m = _compute_performance_metrics([])
        assert m["sharpe_ratio"] is None
        assert m["max_drawdown_pct"] == 0
        assert m["profit_factor"] is None
        assert m["expectancy"] is None
        assert m["avg_hold_time_minutes"] is None
        assert m["best_trade"] is None
        assert m["worst_trade"] is None

    def test_basic_metrics(self):
        signals = [
            _make_signal(2.0, "TP1_HIT", days_ago=1),
            _make_signal(3.0, "TP2_HIT", days_ago=2),
            _make_signal(-1.5, "SL_HIT", days_ago=3),
            _make_signal(1.0, "TP1_HIT", days_ago=4),
            _make_signal(-0.5, "SL_HIT", days_ago=5),
        ]
        m = _compute_performance_metrics(signals)

        assert m["best_trade"]["pnl_pct"] == 3.0
        assert m["worst_trade"]["pnl_pct"] == -1.5
        # profit_factor = (2+3+1) / (1.5+0.5) = 6/2 = 3.0
        assert m["profit_factor"] == 3.0
        assert m["expectancy"] is not None
        assert m["avg_hold_time_minutes"] == 120.0

    def test_profit_factor_no_losses(self):
        signals = [
            _make_signal(2.0, "TP1_HIT"),
            _make_signal(3.0, "TP2_HIT"),
        ]
        m = _compute_performance_metrics(signals)
        # No losing trades => profit_factor is None (div by zero guard)
        assert m["profit_factor"] is None

    def test_sharpe_needs_7_days(self):
        # Only 3 days of data
        signals = [
            _make_signal(1.0, "TP1_HIT", days_ago=0),
            _make_signal(1.0, "TP1_HIT", days_ago=1),
            _make_signal(-0.5, "SL_HIT", days_ago=2),
        ]
        m = _compute_performance_metrics(signals)
        assert m["sharpe_ratio"] is None

    def test_sharpe_with_enough_days(self):
        # 10 days of data
        signals = [_make_signal(0.5 if i % 2 == 0 else -0.3, "TP1_HIT" if i % 2 == 0 else "SL_HIT", days_ago=i)
                    for i in range(10)]
        m = _compute_performance_metrics(signals)
        assert m["sharpe_ratio"] is not None

    def test_max_drawdown(self):
        signals = [
            _make_signal(2.0, "TP1_HIT", days_ago=4),
            _make_signal(1.0, "TP1_HIT", days_ago=3),
            _make_signal(-3.0, "SL_HIT", days_ago=2),  # peak 3.0, now 0.0, dd=3.0
            _make_signal(-1.0, "SL_HIT", days_ago=1),  # now -1.0, dd=4.0
        ]
        m = _compute_performance_metrics(signals)
        assert m["max_drawdown_pct"] == 4.0


class TestDrawdownSeries:
    def test_empty(self):
        assert _compute_drawdown_series([]) == []

    def test_basic(self):
        signals = [
            _make_signal(2.0, days_ago=2),
            _make_signal(-3.0, days_ago=1),
        ]
        series = _compute_drawdown_series(signals)
        assert len(series) == 2
        assert series[0]["drawdown"] == 0  # at peak
        assert series[1]["drawdown"] == -3.0  # drawdown from peak of 2


class TestPnlDistribution:
    def test_empty(self):
        assert _compute_pnl_distribution([]) == []

    def test_basic(self):
        signals = [
            _make_signal(1.0),
            _make_signal(1.5),
            _make_signal(-0.5),
            _make_signal(-1.0),
        ]
        dist = _compute_pnl_distribution(signals)
        assert len(dist) > 0
        total_count = sum(d["count"] for d in dist)
        assert total_count == 4
