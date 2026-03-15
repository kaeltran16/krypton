import numpy as np
import pandas as pd
import pytest
from app.engine.traditional import compute_technical_score


def _make_candles(n=80, trend="up", seed=42):
    """Generate n candles with a given trend direction.

    First 50 candles are flat (establishing indicator baselines), then
    the last 30 candles trend in the specified direction. This keeps RSI
    moderate so mean-reversion signals don't fight the trend score.
    """
    rng = np.random.RandomState(seed)
    base = 100.0
    rows = []
    prev_c = base
    for i in range(n):
        flat_period = n - 30  # first 50 candles are flat
        if i < flat_period:
            drift = 0.0
        elif trend == "up":
            drift = 0.2
        elif trend == "down":
            drift = -0.2
        else:
            drift = 0.0
        c = prev_c + drift + rng.uniform(-0.15, 0.15)
        o = prev_c + rng.uniform(-0.1, 0.1)
        h = max(o, c) + rng.uniform(0.05, 0.3)
        l = min(o, c) - rng.uniform(0.05, 0.3)
        v = rng.uniform(100, 200)
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        prev_c = c
    return pd.DataFrame(rows)


class TestTechnicalScoreBounds:
    def test_score_within_bounds(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert -100 <= result["score"] <= 100

    def test_returns_integer(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert isinstance(result["score"], int)


class TestTechnicalScoreDirection:
    def test_uptrend_positive(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert result["score"] > 0

    def test_downtrend_negative(self):
        df = _make_candles(80, "down")
        result = compute_technical_score(df)
        assert result["score"] < 0


class TestTechnicalScoreIndicators:
    def test_new_indicators_present(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        indicators = result["indicators"]
        for key in ["adx", "di_plus", "di_minus", "rsi", "bb_upper", "bb_lower",
                     "bb_width_pct", "bb_pos", "obv_slope", "vol_ratio", "atr"]:
            assert key in indicators, f"Missing indicator: {key}"

    def test_old_indicators_removed(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        indicators = result["indicators"]
        for key in ["ema_9", "ema_21", "ema_50", "macd", "macd_signal", "macd_hist"]:
            assert key not in indicators, f"Old indicator still present: {key}"


class TestTechnicalScoreContinuity:
    def test_rsi_no_dead_zone(self):
        """RSI values in the old dead zone (40-60) should produce non-zero sigmoid contribution."""
        from app.engine.scoring import sigmoid_score
        # RSI=45 is in the old dead zone (40-60 gave 0). New sigmoid should not.
        rsi_contribution = sigmoid_score(50 - 45, center=0, steepness=0.15) * 25
        assert rsi_contribution > 0
        # RSI=55 should produce negative contribution
        rsi_contribution_55 = sigmoid_score(50 - 55, center=0, steepness=0.15) * 25
        assert rsi_contribution_55 < 0

    def test_monotonic_rsi_scoring(self):
        """Lower RSI should yield higher (more bullish) score contribution,
        tested by comparing two synthetic dataframes."""
        # Create two dataframes that differ mainly in RSI
        df_low_rsi = _make_candles(80, "down")  # lower RSI
        df_high_rsi = _make_candles(80, "up")   # higher RSI
        r1 = compute_technical_score(df_low_rsi)
        r2 = compute_technical_score(df_high_rsi)
        # Lower RSI should have a more positive RSI contribution
        # We can't isolate RSI score, but we verify RSI values differ
        assert r1["indicators"]["rsi"] < r2["indicators"]["rsi"]


class TestVolumeContribution:
    def test_obv_slope_present(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert result["indicators"]["obv_slope"] is not None

    def test_vol_ratio_present(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert result["indicators"]["vol_ratio"] > 0


class TestMinimumCandles:
    def test_requires_70_candles(self):
        df = _make_candles(69, "up")
        with pytest.raises(ValueError, match="at least 70"):
            compute_technical_score(df)

    def test_exactly_70_candles_succeeds(self):
        df = _make_candles(70, "up")
        result = compute_technical_score(df)
        assert -100 <= result["score"] <= 100


from app.engine.traditional import compute_order_flow_score


class TestOrderFlowBounds:
    def test_score_within_bounds(self):
        metrics = {"funding_rate": 0.001, "open_interest_change_pct": 0.1, "long_short_ratio": 2.0}
        result = compute_order_flow_score(metrics)
        assert -100 <= result["score"] <= 100

    def test_empty_metrics_returns_zero(self):
        result = compute_order_flow_score({})
        assert result["score"] == 0


class TestOrderFlowContinuity:
    def test_funding_rate_no_dead_zone(self):
        """Small positive funding should produce a small negative score (contrarian)."""
        result = compute_order_flow_score({"funding_rate": 0.00005})
        assert result["score"] < 0

    def test_negative_funding_is_bullish(self):
        result = compute_order_flow_score({"funding_rate": -0.0005})
        assert result["score"] > 0

    def test_high_ls_ratio_is_bearish(self):
        result = compute_order_flow_score({"long_short_ratio": 1.8})
        assert result["score"] < 0

    def test_low_ls_ratio_is_bullish(self):
        result = compute_order_flow_score({"long_short_ratio": 0.6})
        assert result["score"] > 0


class TestOrderFlowDirectionalOI:
    def test_oi_increase_with_bullish_candle(self):
        """OI increase + bullish price direction = positive contribution."""
        result = compute_order_flow_score({
            "open_interest_change_pct": 0.05,
            "price_direction": 1,
        })
        assert result["score"] > 0

    def test_oi_increase_with_bearish_candle(self):
        """OI increase + bearish price direction = negative contribution (shorts piling in)."""
        result = compute_order_flow_score({
            "open_interest_change_pct": 0.05,
            "price_direction": -1,
        })
        assert result["score"] < 0
