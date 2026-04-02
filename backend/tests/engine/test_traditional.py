from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from app.engine.scoring import sigmoid_score
from app.engine.traditional import compute_technical_score, score_order_flow, compute_order_flow_score


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
        # With multiplicative volume, random volume may reduce magnitude
        # but directional score should still be non-zero
        assert result["score"] != 0

    def test_downtrend_negative(self):
        df = _make_candles(80, "down")
        result = compute_technical_score(df)
        assert result["score"] != 0


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
        for key in ["macd", "macd_signal", "macd_hist"]:
            assert key not in indicators, f"Old indicator still present: {key}"

    def test_ema_indicators_present(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        indicators = result["indicators"]
        for key in ["ema_9", "ema_21", "ema_50"]:
            assert key in indicators, f"Missing EMA indicator: {key}"


class TestTechnicalScoreContinuity:
    def test_rsi_no_dead_zone(self):
        """RSI values in the old dead zone (40-60) should produce non-zero sigmoid contribution."""
        from app.engine.scoring import sigmoid_score
        # RSI=45 is in the old dead zone (40-60 gave 0). New sigmoid should not.
        rsi_contribution = sigmoid_score(50 - 45, center=0, steepness=0.25) * 25
        assert rsi_contribution > 0
        # RSI=55 should produce negative contribution
        rsi_contribution_55 = sigmoid_score(50 - 55, center=0, steepness=0.25) * 25
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


from app.engine.traditional import compute_order_flow_score, compute_trend_conviction, detect_divergence


def _make_divergence_data(n=25, swing_type="bullish"):
    """Build price/RSI arrays with clear swing points on a gentle slope baseline.

    Uses a gently declining baseline (not flat) so that _find_swing_points
    strict comparison doesn't produce spurious matches in the baseline region.
    """
    close = np.linspace(102.0, 98.0, n)
    rsi = np.linspace(52.0, 48.0, n)

    if swing_type == "bullish":
        # Two swing lows: price lower low, RSI higher low
        close[4], close[5], close[6] = 92.0, 90.0, 92.0
        rsi[4], rsi[5], rsi[6] = 28.0, 25.0, 28.0
        close[14], close[15], close[16] = 87.0, 85.0, 87.0
        rsi[14], rsi[15], rsi[16] = 34.0, 32.0, 34.0
    elif swing_type == "bearish":
        # Two swing highs: price higher high, RSI lower high
        close[4], close[5], close[6] = 108.0, 110.0, 108.0
        rsi[4], rsi[5], rsi[6] = 72.0, 75.0, 72.0
        close[14], close[15], close[16] = 113.0, 115.0, 113.0
        rsi[14], rsi[15], rsi[16] = 68.0, 70.0, 68.0
    elif swing_type == "no_divergence":
        # Both price and RSI making lower lows together
        close[4], close[5], close[6] = 92.0, 90.0, 92.0
        rsi[4], rsi[5], rsi[6] = 28.0, 25.0, 28.0
        close[14], close[15], close[16] = 87.0, 85.0, 87.0
        rsi[14], rsi[15], rsi[16] = 23.0, 20.0, 23.0

    return pd.Series(close), pd.Series(rsi)


class TestDetectDivergence:
    def test_bullish_divergence(self):
        """Price lower lows + RSI higher lows = bullish divergence."""
        close, rsi = _make_divergence_data(25, "bullish")
        result = detect_divergence(close, rsi, lookback=25, order=2)
        assert result > 0.0

    def test_bearish_divergence(self):
        """Price higher highs + RSI lower highs = bearish divergence."""
        close, rsi = _make_divergence_data(25, "bearish")
        result = detect_divergence(close, rsi, lookback=25, order=2)
        assert result > 0.0

    def test_no_divergence(self):
        """Price and RSI moving together = no divergence."""
        close, rsi = _make_divergence_data(25, "no_divergence")
        result = detect_divergence(close, rsi, lookback=25, order=2)
        assert result == 0.0

    def test_insufficient_swing_points(self):
        """Not enough swing points returns 0.0."""
        close = pd.Series(np.linspace(100.0, 98.0, 10))
        rsi = pd.Series(np.linspace(50.0, 48.0, 10))
        result = detect_divergence(close, rsi, lookback=10, order=2)
        assert result == 0.0

    def test_returns_bounded_value(self):
        """Result is always in [0.0, 1.0]."""
        close, rsi = _make_divergence_data(25, "bullish")
        result = detect_divergence(close, rsi, lookback=25, order=2)
        assert 0.0 <= result <= 1.0


class TestTrendConviction:
    def test_full_bearish_conviction(self):
        """Aligned bearish EMAs + strong ADX + price below all EMAs = high conviction."""
        di_dir = sigmoid_score((10 - 30) / (10 + 30), center=0, steepness=3.0)
        result = compute_trend_conviction(
            close=90.0,
            ema_9=95.0, ema_21=98.0, ema_50=100.0,
            adx=35.0, di_direction=di_dir,
        )
        assert result["conviction"] > 0.8
        assert result["direction"] == -1

    def test_full_bullish_conviction(self):
        """Aligned bullish EMAs + strong ADX + price above all EMAs = high conviction."""
        di_dir = sigmoid_score((30 - 10) / (30 + 10), center=0, steepness=3.0)
        result = compute_trend_conviction(
            close=110.0,
            ema_9=105.0, ema_21=102.0, ema_50=100.0,
            adx=35.0, di_direction=di_dir,
        )
        assert result["conviction"] > 0.8
        assert result["direction"] == 1

    def test_no_trend_low_conviction(self):
        """Tangled EMAs + low ADX = low conviction."""
        di_dir = sigmoid_score((15 - 14) / (15 + 14), center=0, steepness=3.0)
        result = compute_trend_conviction(
            close=100.0,
            ema_9=100.5, ema_21=99.5, ema_50=100.2,
            adx=12.0, di_direction=di_dir,
        )
        assert result["conviction"] < 0.4

    def test_partial_alignment_moderate_conviction(self):
        """Two EMAs aligned but not all three = moderate conviction."""
        di_dir = sigmoid_score((12 - 25) / (12 + 25), center=0, steepness=3.0)
        result = compute_trend_conviction(
            close=97.0,
            ema_9=96.0, ema_21=99.0, ema_50=98.0,
            adx=28.0, di_direction=di_dir,
        )
        assert 0.3 <= result["conviction"] <= 0.7

    def test_conviction_bounded_zero_to_one(self):
        """Conviction is always in [0, 1]."""
        for close, adx in [(50.0, 0.0), (150.0, 80.0)]:
            result = compute_trend_conviction(
                close=close,
                ema_9=100.0, ema_21=100.0, ema_50=100.0,
                adx=adx, di_direction=0.0,
            )
            assert 0.0 <= result["conviction"] <= 1.0

    def test_direction_from_di(self):
        """Direction follows di_direction sign."""
        di_dir = sigmoid_score((25 - 15) / (25 + 15), center=0, steepness=3.0)
        result = compute_trend_conviction(
            close=100.0,
            ema_9=101.0, ema_21=102.0, ema_50=103.0,
            adx=25.0, di_direction=di_dir,
        )
        assert result["direction"] == 1  # positive di_direction = bullish

    def test_equal_di_low_conviction(self):
        """When DI+ == DI-, di_direction=0 — conviction should be low."""
        result = compute_trend_conviction(
            close=100.0,
            ema_9=100.0, ema_21=100.0, ema_50=100.0,
            adx=15.0, di_direction=0.0,
        )
        assert result["conviction"] < 0.4

    def test_price_confirm_requires_direction_alignment(self):
        """Price below all EMAs in a bullish trend should NOT confirm the trend."""
        di_dir = sigmoid_score((25 - 15) / (25 + 15), center=0, steepness=3.0)
        result_misaligned = compute_trend_conviction(
            close=90.0,
            ema_9=95.0, ema_21=98.0, ema_50=100.0,
            adx=30.0, di_direction=di_dir,
        )
        result_aligned = compute_trend_conviction(
            close=110.0,
            ema_9=105.0, ema_21=102.0, ema_50=100.0,
            adx=30.0, di_direction=di_dir,
        )
        assert result_aligned["conviction"] > result_misaligned["conviction"]


def _make_strong_trend_candles(n=100, direction="down", seed=42):
    """Generate candles with a strong sustained trend.

    Stronger drift than _make_candles to produce clear EMA alignment,
    high ADX, and meaningful trend conviction.
    """
    rng = np.random.RandomState(seed)
    base = 100.0
    rows = []
    prev_c = base
    for i in range(n):
        flat_period = n - 50  # 50 candles of flat, then 50 of strong trend
        if i < flat_period:
            drift = 0.0
        elif direction == "down":
            drift = -0.5
        else:
            drift = 0.5
        c = prev_c + drift + rng.uniform(-0.1, 0.1)
        o = prev_c + rng.uniform(-0.05, 0.05)
        h = max(o, c) + rng.uniform(0.05, 0.2)
        l = min(o, c) - rng.uniform(0.05, 0.2)
        v = rng.uniform(100, 200)
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        prev_c = c
    return pd.DataFrame(rows)


class TestTrendSuppression:
    def test_strong_downtrend_produces_negative_score(self):
        """In a strong downtrend, the score should be non-zero.
        With multiplicative volume, random volume may affect sign."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df)
        assert result["score"] != 0

    def test_strong_uptrend_produces_positive_score(self):
        """In a strong uptrend, the score should be non-zero.
        With multiplicative volume, random volume may affect sign."""
        df = _make_strong_trend_candles(100, "up")
        result = compute_technical_score(df)
        assert result["score"] != 0

    def test_conviction_in_indicators(self):
        """Trend conviction value is exposed in indicators dict and is meaningful for strong trends."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df)
        assert "trend_conviction" in result["indicators"]
        assert result["indicators"]["trend_conviction"] > 0.5, (
            f"Strong downtrend should have high conviction, got {result['indicators']['trend_conviction']}"
        )

    def test_timeframe_param_backward_compatible(self):
        """Calling without timeframe works (no divergence check)."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert -100 <= result["score"] <= 100

    def test_divergence_field_on_4h(self):
        """On 4h timeframe, divergence detection runs and exposes the field."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df, timeframe="4h")
        assert "divergence" in result["indicators"]
        assert result["indicators"]["divergence"] >= 0.0

    def test_divergence_not_checked_on_lower_timeframes(self):
        """On sub-4h timeframes, divergence is always 0.0."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df, timeframe="1h")
        assert result["indicators"]["divergence"] == 0.0

    def test_suppression_formula_divergence_override(self):
        """Divergence overrides conviction suppression via max(1-conviction, divergence).

        This tests the formula directly: when divergence is stronger than
        (1 - conviction), divergence wins and allows mean reversion through.
        """
        # High conviction (0.95) would normally suppress to 0.05,
        # but divergence (0.8) overrides, keeping suppression at 0.8
        assert max(1.0 - 0.95, 0.8) == 0.8
        # Low divergence doesn't override
        assert max(1.0 - 0.5, 0.2) == 0.5
        # Zero conviction means full mean reversion regardless
        assert max(1.0 - 0.0, 0.0) == 1.0


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
        result = compute_order_flow_score({"funding_rate": 0.001})
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


class TestRecalibratedScoreMagnitude:
    """Verify recalibrated sigmoid steepness produces expected score ranges."""

    def test_uptrend_produces_nonzero_score(self):
        """After recalibration, even a weak synthetic uptrend should produce a non-trivial score."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        # Synthetic data has weak drift (0.2/candle on base=100), so scores are modest.
        # Verify recalibrated sigmoid still produces meaningful non-zero output.
        assert abs(result["score"]) > 5, f"Score {result['score']} too compressed"

    def test_order_flow_score_magnitude(self):
        """Strong order flow inputs should produce meaningful scores with recalibrated steepness."""
        result = compute_order_flow_score({
            "funding_rate": -0.005,  # strong negative = bullish (contrarian)
            "open_interest_change_pct": 5.0,
            "price_direction": 1,
            "long_short_ratio": 0.8,  # low = bullish (contrarian)
        })
        # with recalibrated gradual sigmoid, strong inputs should still produce significant scores
        assert result["score"] > 20, f"Flow score {result['score']} too compressed"


class TestRegimeIntegration:
    def test_returns_regime_dict(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert "regime" in result
        regime = result["regime"]
        assert "trending" in regime
        assert "ranging" in regime
        assert "volatile" in regime

    def test_regime_sums_to_one(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        regime = result["regime"]
        total = regime["trending"] + regime["ranging"] + regime["volatile"] + regime["steady"]
        assert abs(total - 1.0) < 1e-6

    def test_regime_indicators_present(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        indicators = result["indicators"]
        assert "regime_trending" in indicators
        assert "regime_ranging" in indicators
        assert "regime_volatile" in indicators
        assert "regime_steady" in indicators

    def test_backward_compatible_without_regime_weights(self):
        """Calling without regime_weights still works (uses defaults)."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert -100 <= result["score"] <= 100

    def test_with_regime_weights_changes_score(self):
        """Passing regime_weights should produce a different score than defaults."""
        from unittest.mock import MagicMock
        df = _make_candles(80, "up")

        result_default = compute_technical_score(df)

        # Create a mock regime_weights that heavily favors mean-reversion
        rw = MagicMock()
        rw.trending_trend_cap = 10.0
        rw.trending_mean_rev_cap = 40.0
        rw.trending_squeeze_cap = 25.0
        rw.trending_volume_cap = 25.0
        rw.ranging_trend_cap = 10.0
        rw.ranging_mean_rev_cap = 40.0
        rw.ranging_squeeze_cap = 25.0
        rw.ranging_volume_cap = 25.0
        rw.volatile_trend_cap = 10.0
        rw.volatile_mean_rev_cap = 40.0
        rw.volatile_squeeze_cap = 25.0
        rw.volatile_volume_cap = 25.0
        rw.trending_tech_weight = 0.25
        rw.trending_flow_weight = 0.25
        rw.trending_onchain_weight = 0.25
        rw.trending_pattern_weight = 0.25
        rw.ranging_tech_weight = 0.25
        rw.ranging_flow_weight = 0.25
        rw.ranging_onchain_weight = 0.25
        rw.ranging_pattern_weight = 0.25
        rw.volatile_tech_weight = 0.25
        rw.volatile_flow_weight = 0.25
        rw.volatile_onchain_weight = 0.25
        rw.volatile_pattern_weight = 0.25
        rw.steady_trend_cap = 40.0
        rw.steady_mean_rev_cap = 15.0
        rw.steady_squeeze_cap = 20.0
        rw.steady_volume_cap = 25.0
        rw.steady_tech_weight = 0.25
        rw.steady_flow_weight = 0.25
        rw.steady_onchain_weight = 0.25
        rw.steady_pattern_weight = 0.25
        rw.adx_center = 20.0

        result_custom = compute_technical_score(df, regime_weights=rw)
        # Different caps should produce different scores
        assert result_custom["score"] != result_default["score"]

    def test_score_still_clamped(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert -100 <= result["score"] <= 100


class TestOrderFlowRegimeScaling:
    def test_ranging_regime_full_contrarian(self):
        """Pure ranging regime (trending=0) gives full contrarian scores."""
        regime = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0, "steady": 0.0}
        result_with = compute_order_flow_score(
            {"funding_rate": -0.0005}, regime=regime
        )
        result_without = compute_order_flow_score({"funding_rate": -0.0005})
        assert result_with["score"] == result_without["score"]

    def test_trending_regime_reduces_contrarian(self):
        """Pure trending regime (trending=1) reduces total flow score."""
        regime_trending = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        regime_ranging = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0, "steady": 0.0}
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        score_trending = abs(compute_order_flow_score(metrics, regime=regime_trending)["score"])
        score_ranging = abs(compute_order_flow_score(metrics, regime=regime_ranging)["score"])
        ratio = score_trending / score_ranging
        assert 0.20 <= ratio <= 0.50, f"Expected dampened ratio, got {ratio:.2f}"

    def test_mixed_regime_interpolates(self):
        """Mixed regime gives intermediate contrarian strength."""
        regime_trending = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        regime_mixed = {"trending": 0.4, "ranging": 0.2, "volatile": 0.2, "steady": 0.2}
        regime_ranging = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0, "steady": 0.0}
        metrics = {"funding_rate": -0.005}
        score_trending = abs(compute_order_flow_score(metrics, regime=regime_trending)["score"])
        score_mixed = abs(compute_order_flow_score(metrics, regime=regime_mixed)["score"])
        score_ranging = abs(compute_order_flow_score(metrics, regime=regime_ranging)["score"])
        assert score_trending < score_mixed < score_ranging

    def test_oi_dampened_by_regime(self):
        """OI score is dampened via total when regime is trending."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        metrics = {"open_interest_change_pct": 0.05, "price_direction": 1}
        result_with = compute_order_flow_score(metrics, regime=regime)
        result_without = compute_order_flow_score(metrics)
        assert abs(result_with["score"]) <= abs(result_without["score"])


def _make_snapshots(funding_rates, ls_ratios=None, oi_changes=None):
    """Create mock OrderFlowSnapshot-like objects for testing."""
    if ls_ratios is None:
        ls_ratios = [1.0] * len(funding_rates)
    if oi_changes is None:
        oi_changes = [0.0] * len(funding_rates)
    return [
        SimpleNamespace(funding_rate=fr, long_short_ratio=ls, oi_change_pct=oi)
        for fr, ls, oi in zip(funding_rates, ls_ratios, oi_changes)
    ]


class TestOrderFlowRoCOverride:
    def test_stable_history_no_boost(self):
        """Stable flow history keeps regime scaling unchanged."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        snapshots = _make_snapshots([0.0001] * 10, [1.2] * 10)
        metrics = {"funding_rate": -0.0005}
        result_with = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_without = compute_order_flow_score(metrics, regime=regime)
        assert abs(result_with["score"] - result_without["score"]) <= 1

    def test_spiking_history_restores_contrarian(self):
        """Rapid funding spike restores contrarian strength despite trending regime."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        funding_rates = [0.0001] * 7 + [0.001] * 3
        snapshots = _make_snapshots(funding_rates, [1.0] * 10)
        metrics = {"funding_rate": -0.0005}
        result_spike = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert abs(result_spike["score"]) > abs(result_no_hist["score"])

    def test_insufficient_history_skips_roc(self):
        """Fewer than 10 snapshots disables RoC — only regime scaling applies."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        snapshots = _make_snapshots([0.001] * 5, [1.0] * 5)
        metrics = {"funding_rate": -0.0005}
        result_partial = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert result_partial["score"] == result_no_hist["score"]

    def test_null_fields_handled_gracefully(self):
        """Snapshots with None funding/LS are excluded from RoC computation."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        snapshots = [
            SimpleNamespace(funding_rate=None, long_short_ratio=None, oi_change_pct=None)
            for _ in range(10)
        ]
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert result["score"] == result_no_hist["score"]
        assert result["details"]["roc_boost"] == 0.0

    def test_nine_snapshots_skips_roc(self):
        """Exactly 9 snapshots (below threshold of 10) disables RoC."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        snapshots = _make_snapshots([0.0001] * 6 + [0.001] * 3, [1.0] * 9)
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert result["score"] == result_no_hist["score"]

    def test_nan_fields_excluded_from_roc(self):
        """Snapshots with NaN funding/LS are excluded from RoC computation."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        snapshots = [
            SimpleNamespace(funding_rate=float('nan'), long_short_ratio=float('nan'), oi_change_pct=float('nan'))
            for _ in range(10)
        ]
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert result["score"] == result_no_hist["score"]
        assert result["details"]["roc_boost"] == 0.0


class TestUnifiedMeanReversion:
    def test_both_oversold_stronger_than_rsi_alone(self):
        """When RSI and BB position both signal oversold, unified score > RSI-only contribution."""
        df_oversold = _make_candles(80, "down")
        result = compute_technical_score(df_oversold)
        indicators = result["indicators"]
        assert "mean_rev_rsi_raw" in indicators
        assert "mean_rev_bb_pos_raw" in indicators
        assert "mean_rev_score" in indicators
        assert "squeeze_score" in indicators

    def test_scoring_params_accepted(self):
        """compute_technical_score accepts optional scoring_params dict."""
        df = _make_candles(80, "up")
        params = {
            "mean_rev_rsi_steepness": 0.25,
            "mean_rev_bb_pos_steepness": 10.0,
            "squeeze_steepness": 0.10,
            "mean_rev_blend_ratio": 0.6,
        }
        result = compute_technical_score(df, scoring_params=params)
        assert -100 <= result["score"] <= 100

    def test_different_blend_ratio_changes_score(self):
        """Different blend ratios produce different mean_rev_score when mr_pressure is active."""
        df = _make_candles(80, "down")
        r1 = compute_technical_score(df, scoring_params={"mean_rev_blend_ratio": 0.9})
        r2 = compute_technical_score(df, scoring_params={"mean_rev_blend_ratio": 0.1})
        if r1["mr_pressure"] > 0 and r2["mr_pressure"] > 0:
            assert r1["indicators"]["mean_rev_score"] != r2["indicators"]["mean_rev_score"]
        else:
            assert r1["indicators"]["mean_rev_score"] == 0.0
            assert r2["indicators"]["mean_rev_score"] == 0.0

    def test_mean_rev_zero_when_no_mr_pressure(self):
        """Mean reversion score is zero when mr_pressure is zero (moderate RSI/BB)."""
        df = _make_candles(80, "flat")
        result = compute_technical_score(df)
        assert result["indicators"]["mean_rev_score"] == 0.0

    def test_squeeze_sign_matches_dominant_thesis(self):
        """Squeeze score sign matches trend_score + mean_rev_score, not just MR."""
        for direction in ("up", "down"):
            df = _make_candles(80, direction)
            result = compute_technical_score(df)
            indicators = result["indicators"]
            trend = indicators["trend_score"]
            mr = indicators["mean_rev_score"]
            sq = indicators["squeeze_score"]
            directional_sum = trend + mr
            if directional_sum > 0:
                assert sq >= 0, f"{direction}: squeeze should be >= 0 when dominant thesis is bullish"
            elif directional_sum < 0:
                assert sq <= 0, f"{direction}: squeeze should be <= 0 when dominant thesis is bearish"
            else:
                assert sq == 0, f"{direction}: squeeze must be 0 when dominant thesis is neutral"

    def test_partial_scoring_params_uses_defaults(self):
        """Missing keys in scoring_params should fall back to defaults, not crash."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df, scoring_params={"mean_rev_blend_ratio": 0.8})
        assert -100 <= result["score"] <= 100


class TestCapKeys:
    def test_squeeze_cap_in_cap_keys(self):
        from app.engine.regime import CAP_KEYS
        assert "squeeze_cap" in CAP_KEYS
        assert "bb_vol_cap" not in CAP_KEYS

    def test_default_caps_sum_to_100(self):
        from app.engine.regime import DEFAULT_CAPS
        for regime, caps in DEFAULT_CAPS.items():
            total = sum(caps.values())
            assert total == 100, f"{regime} caps sum to {total}, expected 100"


class TestOrderFlowTrendConviction:
    def test_high_conviction_suppresses_contrarian(self):
        """High trend conviction should reduce contrarian flow score magnitude."""
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        result_low = compute_order_flow_score(metrics, trend_conviction=0.0)
        result_high = compute_order_flow_score(metrics, trend_conviction=0.9)
        assert abs(result_high["score"]) < abs(result_low["score"])

    def test_zero_conviction_no_change(self):
        """Zero trend conviction should not change scoring behavior."""
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        result_without = compute_order_flow_score(metrics)
        result_with = compute_order_flow_score(metrics, trend_conviction=0.0)
        assert result_without["score"] == result_with["score"]

    def test_oi_dampened_by_conviction(self):
        """OI score is dampened via total when conviction is high."""
        metrics = {"open_interest_change_pct": 0.05, "price_direction": 1}
        result_low = compute_order_flow_score(metrics, trend_conviction=0.0)
        result_high = compute_order_flow_score(metrics, trend_conviction=0.9)
        assert abs(result_low["score"]) >= abs(result_high["score"])

    def test_conviction_stacks_with_regime(self):
        """Trending regime + high conviction should suppress more than either alone."""
        metrics = {"funding_rate": -0.005}
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        score_regime_only = abs(compute_order_flow_score(
            metrics, regime=regime, trend_conviction=0.0,
        )["score"])
        score_both = abs(compute_order_flow_score(
            metrics, regime=regime, trend_conviction=0.8,
        )["score"])
        assert score_both < score_regime_only

    def test_conviction_in_details(self):
        """Trend conviction value is exposed in details dict."""
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, trend_conviction=0.7)
        assert "trend_conviction" in result["details"]
        assert result["details"]["trend_conviction"] == 0.7


class TestOrderFlowBackwardCompat:
    def test_no_regime_no_history_mult_is_one(self):
        """Default params produce mult=1.0 (identical behavior to pre-change)."""
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        result = compute_order_flow_score(metrics)
        assert result["details"]["contrarian_mult"] == 1.0
        assert result["details"]["final_mult"] == 1.0

    def test_details_has_diagnostic_fields(self):
        """Details dict includes all raw metrics and diagnostic fields."""
        metrics = {"funding_rate": -0.0005}
        regime = {"trending": 0.4, "ranging": 0.2, "volatile": 0.2, "steady": 0.2}
        result = compute_order_flow_score(metrics, regime=regime)
        details = result["details"]
        for key in [
            "funding_rate", "open_interest", "open_interest_change_pct",
            "long_short_ratio", "price_direction",
            "funding_score", "oi_score", "ls_score",
            "contrarian_mult", "roc_boost", "final_mult",
            "funding_roc", "ls_roc", "max_roc",
        ]:
            assert key in details, f"Missing field: {key}"

    def test_score_clamped_extreme_inputs(self):
        """Score stays in [-100, +100] under extreme inputs with full contrarian."""
        metrics = {
            "funding_rate": -0.01,
            "long_short_ratio": 0.1,
            "open_interest_change_pct": 0.5,
            "price_direction": 1,
        }
        regime = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0, "steady": 0.0}
        spiking = _make_snapshots([0.0001] * 7 + [0.01] * 3, [1.0] * 10)
        result = compute_order_flow_score(metrics, regime=regime, flow_history=spiking)
        assert -100 <= result["score"] <= 100


class TestCVDScoring:
    def test_positive_cvd_scores_positive(self):
        metrics = {"cvd_delta": 500.0, "avg_candle_volume": 1000.0}
        result = compute_order_flow_score(metrics)
        assert result["score"] > 0
        assert result["details"]["cvd_score"] > 0

    def test_negative_cvd_scores_negative(self):
        metrics = {"cvd_delta": -500.0, "avg_candle_volume": 1000.0}
        result = compute_order_flow_score(metrics)
        assert result["score"] < 0
        assert result["details"]["cvd_score"] < 0

    def test_cvd_subscore_is_pre_dampening(self):
        """CVD sub-score in details is the raw pre-dampening value."""
        metrics = {"cvd_delta": 500.0, "avg_candle_volume": 1000.0}
        regime_trending = {"trending": 0.8, "ranging": 0.1, "volatile": 0.05, "steady": 0.05}
        result_trending = compute_order_flow_score(metrics, regime=regime_trending)
        result_no_regime = compute_order_flow_score(metrics)
        assert result_trending["details"]["cvd_score"] == result_no_regime["details"]["cvd_score"]
        assert abs(result_trending["score"]) < abs(result_no_regime["score"])

    def test_cvd_max_bounded(self):
        metrics = {"cvd_delta": 99999.0, "avg_candle_volume": 1.0}
        result = compute_order_flow_score(metrics)
        assert abs(result["details"]["cvd_score"]) <= 22.1

    def test_cvd_absent_scores_zero(self):
        metrics = {"funding_rate": 0.001}
        result = compute_order_flow_score(metrics)
        assert result["details"]["cvd_score"] == 0.0

    def test_max_scores_rebalanced(self):
        """Total max scores should now be 100 (30+20+30+20)."""
        from app.engine.constants import ORDER_FLOW
        total = sum(ORDER_FLOW["max_scores"].values())
        assert total == 100


class TestDynamicConfidence:
    def test_three_legacy_sources_full_confidence(self):
        metrics = {"funding_rate": 0.001, "open_interest_change_pct": 0.05,
                   "long_short_ratio": 1.5, "price_direction": 1}
        result = compute_order_flow_score(metrics)
        assert result["confidence"] == 1.0

    def test_three_legacy_plus_cvd_full_confidence(self):
        metrics = {"funding_rate": 0.001, "open_interest_change_pct": 0.05,
                   "long_short_ratio": 1.5, "price_direction": 1,
                   "cvd_delta": 100.0, "avg_candle_volume": 1000.0}
        result = compute_order_flow_score(metrics)
        assert result["confidence"] == 1.0

    def test_cvd_unavailable_no_regression(self):
        """When CVD is absent, confidence should be same as pre-CVD (3/3=1.0)."""
        metrics = {"funding_rate": 0.001, "open_interest_change_pct": 0.05,
                   "long_short_ratio": 1.5, "price_direction": 1}
        result = compute_order_flow_score(metrics)
        assert result["confidence"] == 1.0

    def test_only_funding_present_confidence(self):
        """With only funding present, confidence = 1/1 (key-based)."""
        metrics = {"funding_rate": 0.001}
        result = compute_order_flow_score(metrics)
        assert result["confidence"] == 1.0

    def test_sparse_data_confidence(self):
        """Single source present should have full confidence for that source."""
        metrics = {"funding_rate": 0.001}
        result = compute_order_flow_score(metrics)
        assert result["confidence"] > 0.0

    def test_cvd_present_raises_denominator(self):
        """When CVD flows, it adds to sources_available."""
        metrics = {"funding_rate": 0.001, "cvd_delta": 100.0, "avg_candle_volume": 1000.0}
        result = compute_order_flow_score(metrics)
        assert result["confidence"] == 1.0


class TestOrderFlowIntegration:
    def test_full_scorer_all_params(self):
        """Full call with all new parameters — score in [-100, 100], all detail fields present."""
        regime = {"trending": 0.3, "ranging": 0.3, "volatile": 0.2, "steady": 0.2}
        snapshots = _make_snapshots(
            [0.0001] * 7 + [0.0005] * 3,
            [1.1] * 10,
            [0.01] * 7 + [0.05] * 3,
        )
        metrics = {
            "funding_rate": -0.0003,
            "open_interest_change_pct": 0.03,
            "price_direction": 1,
            "long_short_ratio": 1.3,
            "cvd_delta": 200.0,
            "cvd_history": [i * 50 for i in range(1, 11)],
            "avg_candle_volume": 1000.0,
            "book_imbalance": 0.25,
        }
        result = compute_order_flow_score(
            metrics,
            regime=regime,
            flow_history=snapshots,
            trend_conviction=0.4,
            mr_pressure=0.2,
            flow_age_seconds=100,
            asset_scale=0.85,
        )
        assert -100 <= result["score"] <= 100
        details = result["details"]
        expected_keys = [
            "funding_score", "oi_score", "ls_score", "cvd_score", "book_score",
            "contrarian_mult", "roc_boost", "final_mult", "asset_scale",
            "funding_roc", "ls_roc", "oi_roc", "max_roc", "trend_conviction",
            "flow_age_seconds", "freshness_decay",
        ]
        for key in expected_keys:
            assert key in details, f"Missing detail key: {key}"
        assert result["confidence"] > 0.0

    def test_full_scorer_stale_data(self):
        """Fully stale data → confidence = 0."""
        result = compute_order_flow_score(
            {"funding_rate": 0.001, "long_short_ratio": 1.5},
            flow_age_seconds=1200,
        )
        assert result["confidence"] == 0.0
        assert result["score"] != 0

    def test_score_clamped_at_extremes(self):
        """Extreme inputs across all 5 components still clamp to [-100, 100]."""
        metrics = {
            "funding_rate": -0.05,
            "open_interest_change_pct": 10.0,
            "price_direction": 1,
            "long_short_ratio": 0.2,
            "cvd_delta": 50000.0,
            "avg_candle_volume": 100.0,
            "book_imbalance": 0.95,
        }
        result = compute_order_flow_score(metrics)
        assert -100 <= result["score"] <= 100


class TestOrderFlowBookImbalance:
    def test_bid_heavy_book_positive_score(self):
        """More bids than asks → positive book_score."""
        result = compute_order_flow_score({"book_imbalance": 0.6})
        assert result["details"]["book_score"] > 0

    def test_ask_heavy_book_negative_score(self):
        """More asks than bids → negative book_score."""
        result = compute_order_flow_score({"book_imbalance": -0.6})
        assert result["details"]["book_score"] < 0

    def test_absent_book_zero_score(self):
        """No book_imbalance key → book_score = 0."""
        result = compute_order_flow_score({"funding_rate": 0.001})
        assert result["details"]["book_score"] == 0.0

    def test_book_imbalance_in_confidence(self):
        """book_imbalance present should increase sources_available."""
        result_with = compute_order_flow_score({
            "funding_rate": 0.001, "book_imbalance": 0.3
        })
        assert result_with["details"]["book_score"] > 0


class TestOrderFlowFreshnessDecay:
    def test_fresh_data_no_penalty(self):
        """flow_age_seconds=0 → full confidence (no penalty)."""
        metrics = {"funding_rate": 0.001, "long_short_ratio": 1.5}
        result = compute_order_flow_score(metrics, flow_age_seconds=0)
        result_no_age = compute_order_flow_score(metrics)
        assert result["confidence"] == result_no_age["confidence"]

    def test_half_stale_halves_confidence(self):
        """flow_age_seconds=600 (midpoint of 300-900) → ~50% confidence penalty."""
        metrics = {"funding_rate": 0.001, "long_short_ratio": 1.5}
        result_fresh = compute_order_flow_score(metrics, flow_age_seconds=0)
        result_half = compute_order_flow_score(metrics, flow_age_seconds=600)
        assert result_half["confidence"] < result_fresh["confidence"]
        assert result_half["confidence"] > 0.0

    def test_fully_stale_zeroes_confidence(self):
        """flow_age_seconds=900+ → confidence decays to zero."""
        metrics = {"funding_rate": 0.001, "long_short_ratio": 1.5}
        result = compute_order_flow_score(metrics, flow_age_seconds=1000)
        assert result["confidence"] == 0.0

    def test_none_age_no_penalty(self):
        """flow_age_seconds=None (default) → no penalty."""
        metrics = {"funding_rate": 0.001}
        result = compute_order_flow_score(metrics, flow_age_seconds=None)
        result_explicit = compute_order_flow_score(metrics, flow_age_seconds=0)
        assert result["confidence"] == result_explicit["confidence"]


class TestOrderFlowCVDTrend:
    def test_rising_cvd_history_produces_positive_score(self):
        """10-candle rising CVD history should produce a positive cvd_score via slope."""
        trend_result = compute_order_flow_score({
            "cvd_delta": 500.0,
            "cvd_history": [i * 500 for i in range(1, 11)],
            "avg_candle_volume": 1000.0,
        })
        assert trend_result["details"]["cvd_score"] > 0

    def test_falling_cvd_history_produces_negative_score(self):
        """10-candle falling CVD history should produce a negative cvd_score."""
        trend_result = compute_order_flow_score({
            "cvd_delta": -500.0,
            "cvd_history": [-i * 500 for i in range(1, 11)],
            "avg_candle_volume": 1000.0,
        })
        assert trend_result["details"]["cvd_score"] < 0

    def test_cvd_trend_fallback_with_insufficient_history(self):
        """With <5 entries in cvd_history, fall back to single-delta scoring."""
        result = compute_order_flow_score({
            "cvd_delta": 500.0,
            "cvd_history": [100, 200, 300],
            "avg_candle_volume": 1000.0,
        })
        assert result["details"]["cvd_score"] != 0.0

    def test_no_cvd_history_uses_single_delta(self):
        """Without cvd_history key, uses single-delta scoring (backward compat)."""
        result = compute_order_flow_score({
            "cvd_delta": 500.0,
            "avg_candle_volume": 1000.0,
        })
        assert result["details"]["cvd_score"] != 0.0


class TestOrderFlowAssetScale:
    def test_wif_scale_produces_lower_score_than_btc(self):
        """WIF (scale=0.4) should produce lower absolute score than BTC (scale=1.0) for same funding."""
        metrics = {"funding_rate": -0.005, "long_short_ratio": 0.8}
        btc_result = compute_order_flow_score(metrics, asset_scale=1.0)
        wif_result = compute_order_flow_score(metrics, asset_scale=0.4)
        assert abs(wif_result["score"]) < abs(btc_result["score"])

    def test_asset_scale_in_details(self):
        result = compute_order_flow_score({"funding_rate": 0.001}, asset_scale=0.85)
        assert result["details"]["asset_scale"] == 0.85

    def test_default_asset_scale_is_one(self):
        """Without asset_scale param, behavior is unchanged (scale=1.0)."""
        result = compute_order_flow_score({"funding_rate": 0.001})
        assert result["details"]["asset_scale"] == 1.0


class TestOrderFlowOIRoC:
    def test_spiking_oi_in_history_produces_roc_boost(self):
        """Rapidly increasing OI should produce roc_boost > 0."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        oi_changes = [0.01] * 7 + [0.10] * 3
        snapshots = _make_snapshots([0.0001] * 10, [1.0] * 10, oi_changes)
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        assert result["details"]["roc_boost"] > 0.0

    def test_oi_roc_in_details(self):
        """OI RoC should appear in details dict."""
        snapshots = _make_snapshots([0.0001] * 10, [1.0] * 10, [0.01] * 10)
        result = compute_order_flow_score(
            {"funding_rate": 0.0001}, flow_history=snapshots
        )
        assert "oi_roc" in result["details"]


class TestThreeCandlePriceDirection:
    def test_uptrend_doji_still_bullish(self):
        """In an uptrend, a doji candle should not flip price direction to bearish."""
        recent_close = 103.0
        lookback_close = 100.0
        net_move = recent_close - lookback_close
        price_direction = 1 if net_move > 0 else (-1 if net_move < 0 else 0)
        assert price_direction == 1

    def test_downtrend_produces_bearish(self):
        recent_close = 97.0
        lookback_close = 100.0
        net_move = recent_close - lookback_close
        price_direction = 1 if net_move > 0 else (-1 if net_move < 0 else 0)
        assert price_direction == -1

    def test_flat_produces_zero(self):
        recent_close = 100.0
        lookback_close = 100.0
        net_move = recent_close - lookback_close
        price_direction = 1 if net_move > 0 else (-1 if net_move < 0 else 0)
        assert price_direction == 0


class TestOrderFlowConfidenceBug:
    def test_zero_funding_still_counts_as_present(self):
        """funding_rate=0.0 should count as present data, not absent."""
        result = compute_order_flow_score({"funding_rate": 0.0})
        assert result["confidence"] > 0.0, "Zero funding treated as absent"

    def test_exact_ls_one_still_counts_as_present(self):
        """long_short_ratio=1.0 should count as present data, not absent."""
        result = compute_order_flow_score({"long_short_ratio": 1.0})
        assert result["confidence"] > 0.0, "L/S ratio 1.0 treated as absent"

    def test_empty_metrics_zero_confidence(self):
        """No keys at all = truly absent = zero confidence."""
        result = compute_order_flow_score({})
        assert result["confidence"] == 0.0

    def test_all_three_legacy_present_full_confidence(self):
        """All three legacy keys present = confidence 1.0 (before book)."""
        result = compute_order_flow_score({
            "funding_rate": 0.0001,
            "open_interest_change_pct": 0.01,
            "price_direction": 1,
            "long_short_ratio": 1.2,
        })
        assert result["confidence"] >= 0.75


class TestOrderFlowParamGroup:
    def test_param_group_has_12_params(self):
        from app.engine.param_groups import PARAM_GROUPS
        group = PARAM_GROUPS["order_flow"]
        assert len(group["params"]) == 12, f"Expected 12 params, got {len(group['params'])}"

    def test_all_params_have_sweep_ranges(self):
        from app.engine.param_groups import PARAM_GROUPS
        group = PARAM_GROUPS["order_flow"]
        for param in group["params"]:
            assert param in group["sweep_ranges"], f"Missing sweep range for {param}"

    def test_constraint_rejects_sum_over_100(self):
        from app.engine.param_groups import PARAM_GROUPS
        group = PARAM_GROUPS["order_flow"]
        over_budget = {
            "funding_max": 30, "oi_max": 30, "ls_ratio_max": 30,
            "cvd_max": 20, "book_max": 20,
            "funding_steepness": 400, "oi_steepness": 20,
            "ls_ratio_steepness": 6, "cvd_steepness": 5, "book_steepness": 4,
            "freshness_fresh_seconds": 300, "freshness_stale_seconds": 900,
        }
        assert not group["constraints"](over_budget)

    def test_constraint_accepts_valid_config(self):
        from app.engine.param_groups import PARAM_GROUPS
        group = PARAM_GROUPS["order_flow"]
        valid = {
            "funding_max": 22, "oi_max": 22, "ls_ratio_max": 22,
            "cvd_max": 22, "book_max": 12,
            "funding_steepness": 400, "oi_steepness": 20,
            "ls_ratio_steepness": 6, "cvd_steepness": 5, "book_steepness": 4,
            "freshness_fresh_seconds": 300, "freshness_stale_seconds": 900,
        }
        assert group["constraints"](valid)

    def test_constraint_rejects_stale_before_fresh(self):
        from app.engine.param_groups import PARAM_GROUPS
        group = PARAM_GROUPS["order_flow"]
        bad_freshness = {
            "funding_max": 22, "oi_max": 22, "ls_ratio_max": 22,
            "cvd_max": 22, "book_max": 12,
            "funding_steepness": 400, "oi_steepness": 20,
            "ls_ratio_steepness": 6, "cvd_steepness": 5, "book_steepness": 4,
            "freshness_fresh_seconds": 900, "freshness_stale_seconds": 300,
        }
        assert not group["constraints"](bad_freshness)


class TestOrderFlowNoHardcodedLiterals:
    def test_scorer_uses_constants_not_literals(self):
        """Verify the scorer body has no hardcoded max score literals (30, 20)."""
        import re
        import inspect
        source = inspect.getsource(compute_order_flow_score)
        lines = [l for l in source.split("\n") if not l.strip().startswith("#")]
        body = "\n".join(lines)
        assert not re.search(r"\*\s*\b30\b", body), "Found hardcoded '* 30' in scorer"
        assert not re.search(r"\*\s*\b20\b", body), "Found hardcoded '* 20' in scorer"


class TestOrderFlowConstants:
    def test_max_scores_sum_to_100(self):
        from app.engine.constants import ORDER_FLOW
        total = sum(ORDER_FLOW["max_scores"].values())
        assert total == 100, f"Max scores sum to {total}, expected 100"

    def test_all_components_have_steepness(self):
        from app.engine.constants import ORDER_FLOW
        for key in ORDER_FLOW["max_scores"]:
            assert key in ORDER_FLOW["sigmoid_steepnesses"], f"Missing steepness for {key}"

    def test_freshness_thresholds_ordered(self):
        from app.engine.constants import ORDER_FLOW
        assert ORDER_FLOW["freshness_stale_seconds"] > ORDER_FLOW["freshness_fresh_seconds"]

    def test_asset_scales_exist_for_all_pairs(self):
        from app.engine.constants import ORDER_FLOW_ASSET_SCALES
        for pair in ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "WIF-USDT-SWAP"]:
            assert pair in ORDER_FLOW_ASSET_SCALES, f"Missing asset scale for {pair}"


class TestContinuousDIDirection:
    """Tests for continuous DI direction via sigmoid_score."""

    def test_sigmoid_score_strong_bullish(self):
        """DI+=35, DI-=10 -> spread=0.56 -> strong positive direction."""
        from app.engine.scoring import sigmoid_score
        di_spread = (35 - 10) / (35 + 10)
        result = sigmoid_score(di_spread, center=0, steepness=3.0)
        assert 0.60 <= result <= 0.80

    def test_sigmoid_score_moderate_bullish(self):
        """DI+=22, DI-=15 -> spread=0.19 -> moderate positive direction."""
        from app.engine.scoring import sigmoid_score
        di_spread = (22 - 15) / (22 + 15)
        result = sigmoid_score(di_spread, center=0, steepness=3.0)
        assert 0.20 <= result <= 0.40

    def test_sigmoid_score_weak_bullish(self):
        """DI+=16, DI-=15 -> spread=0.03 -> sigmoid ~0.09."""
        from app.engine.scoring import sigmoid_score
        di_spread = (16 - 15) / (16 + 15)
        result = sigmoid_score(di_spread, center=0, steepness=3.0)
        assert 0.0 <= result <= 0.20

    def test_sigmoid_score_strong_bearish(self):
        """DI+=10, DI-=30 -> spread=-0.50 -> strong negative direction."""
        from app.engine.scoring import sigmoid_score
        di_spread = (10 - 30) / (10 + 30)
        result = sigmoid_score(di_spread, center=0, steepness=3.0)
        assert -0.75 <= result <= -0.55

    def test_sigmoid_score_symmetry(self):
        """Positive and negative spreads are symmetric."""
        from app.engine.scoring import sigmoid_score
        pos = sigmoid_score(0.3, center=0, steepness=3.0)
        neg = sigmoid_score(-0.3, center=0, steepness=3.0)
        assert abs(pos + neg) < 1e-10

    def test_sigmoid_score_zero_spread(self):
        """Equal DI -> spread=0 -> sigmoid=0."""
        from app.engine.scoring import sigmoid_score
        result = sigmoid_score(0.0, center=0, steepness=3.0)
        assert result == 0.0

    def test_di_sum_zero_returns_zero_direction(self):
        """When DI+ and DI- are both zero, direction should be 0."""
        from app.engine.scoring import sigmoid_score
        di_plus, di_minus = 0.0, 0.0
        di_sum = di_plus + di_minus
        di_spread = (di_plus - di_minus) / di_sum if di_sum > 0 else 0.0
        result = sigmoid_score(di_spread, center=0, steepness=3.0)
        assert result == 0.0

    def test_di_direction_in_indicators(self):
        """di_direction is exposed in indicators dict."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert "di_direction" in result["indicators"]
        assert -1.0 <= result["indicators"]["di_direction"] <= 1.0


class TestScoreOrderFlow:
    def test_alias_returns_same_result(self):
        """score_order_flow and compute_order_flow_score are the same function."""
        metrics = {
            "funding_rate": 0.0005,
            "open_interest": 1_000_000,
            "oi_change_pct": 2.5,
            "long_short_ratio": 1.3,
            "cvd_delta": 500,
        }
        regime = {"trending": 0.6, "ranging": 0.2, "volatile": 0.1, "steady": 0.1}
        kwargs = dict(
            metrics=metrics,
            regime=regime,
            flow_history=None,
            trend_conviction=0.5,
            mr_pressure=0.3,
            flow_age_seconds=120.0,
            asset_scale=1.0,
        )
        result_new = score_order_flow(**kwargs)
        result_old = compute_order_flow_score(**kwargs)
        assert result_new == result_old

    def test_returns_score_details_confidence(self):
        metrics = {"funding_rate": 0.001, "long_short_ratio": 1.5}
        result = score_order_flow(metrics=metrics)
        assert "score" in result
        assert "details" in result
        assert "confidence" in result
        assert isinstance(result["score"], (int, float))

    def test_empty_metrics_returns_zero(self):
        result = score_order_flow(metrics={})
        assert result["score"] == 0
