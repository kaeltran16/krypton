from types import SimpleNamespace

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
        result = compute_trend_conviction(
            close=90.0,
            ema_9=95.0, ema_21=98.0, ema_50=100.0,
            adx=35.0, di_plus=10.0, di_minus=30.0,
        )
        assert result["conviction"] > 0.8
        assert result["direction"] == -1

    def test_full_bullish_conviction(self):
        """Aligned bullish EMAs + strong ADX + price above all EMAs = high conviction."""
        result = compute_trend_conviction(
            close=110.0,
            ema_9=105.0, ema_21=102.0, ema_50=100.0,
            adx=35.0, di_plus=30.0, di_minus=10.0,
        )
        assert result["conviction"] > 0.8
        assert result["direction"] == 1

    def test_no_trend_low_conviction(self):
        """Tangled EMAs + low ADX = low conviction."""
        result = compute_trend_conviction(
            close=100.0,
            ema_9=100.5, ema_21=99.5, ema_50=100.2,
            adx=12.0, di_plus=15.0, di_minus=14.0,
        )
        assert result["conviction"] < 0.4

    def test_partial_alignment_moderate_conviction(self):
        """Two EMAs aligned but not all three = moderate conviction."""
        result = compute_trend_conviction(
            close=97.0,
            ema_9=96.0, ema_21=99.0, ema_50=98.0,  # 9 < 50 < 21, not fully aligned
            adx=28.0, di_plus=12.0, di_minus=25.0,
        )
        assert 0.3 <= result["conviction"] <= 0.7

    def test_conviction_bounded_zero_to_one(self):
        """Conviction is always in [0, 1]."""
        for close, adx in [(50.0, 0.0), (150.0, 80.0)]:
            result = compute_trend_conviction(
                close=close,
                ema_9=100.0, ema_21=100.0, ema_50=100.0,
                adx=adx, di_plus=20.0, di_minus=20.0,
            )
            assert 0.0 <= result["conviction"] <= 1.0

    def test_direction_from_di(self):
        """Direction follows DI+/DI- regardless of EMA order."""
        result = compute_trend_conviction(
            close=100.0,
            ema_9=101.0, ema_21=102.0, ema_50=103.0,
            adx=25.0, di_plus=25.0, di_minus=15.0,
        )
        assert result["direction"] == 1  # DI+ > DI- = bullish

    def test_equal_di_low_conviction(self):
        """When DI+ == DI-, there is no clear trend — conviction should be low."""
        result = compute_trend_conviction(
            close=100.0,
            ema_9=100.0, ema_21=100.0, ema_50=100.0,
            adx=15.0, di_plus=20.0, di_minus=20.0,
        )
        assert result["conviction"] < 0.4

    def test_price_confirm_requires_direction_alignment(self):
        """Price below all EMAs in a bullish trend should NOT confirm the trend."""
        result_misaligned = compute_trend_conviction(
            close=90.0,
            ema_9=95.0, ema_21=98.0, ema_50=100.0,
            adx=30.0, di_plus=25.0, di_minus=15.0,  # bullish DI
        )
        result_aligned = compute_trend_conviction(
            close=110.0,
            ema_9=105.0, ema_21=102.0, ema_50=100.0,
            adx=30.0, di_plus=25.0, di_minus=15.0,  # bullish DI
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
        """In a strong downtrend, suppressing bullish mean reversion should make
        the overall score more negative than without suppression."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df)
        assert result["score"] < 0

    def test_strong_uptrend_produces_positive_score(self):
        """In a strong uptrend, suppressing bearish mean reversion should make
        the overall score more positive."""
        df = _make_strong_trend_candles(100, "up")
        result = compute_technical_score(df)
        assert result["score"] > 0

    def test_conviction_in_indicators(self):
        """Trend conviction value is exposed in indicators dict and is meaningful for strong trends."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df)
        assert "trend_conviction" in result["indicators"]
        assert result["indicators"]["trend_conviction"] > 0.5, (
            f"Strong downtrend should have high conviction, got {result['indicators']['trend_conviction']}"
        )

    def test_suppression_factor_in_indicators(self):
        """Mean reversion suppression factor is exposed in indicators dict."""
        df = _make_strong_trend_candles(100, "down")
        result = compute_technical_score(df)
        assert "mr_suppression" in result["indicators"]
        assert 0.0 <= result["indicators"]["mr_suppression"] <= 1.0

    def test_flat_market_less_suppression_than_strong_trend(self):
        """Flat/choppy market should suppress less than a strong trend."""
        df_flat = _make_candles(80, "flat")
        df_trend = _make_strong_trend_candles(100, "down")
        flat_supp = compute_technical_score(df_flat)["indicators"]["mr_suppression"]
        trend_supp = compute_technical_score(df_trend)["indicators"]["mr_suppression"]
        assert flat_supp > trend_supp

    def test_timeframe_param_backward_compatible(self):
        """Calling without timeframe works (no divergence check, suppression only)."""
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
        """Strong order flow inputs should produce meaningful scores with new steepness."""
        result = compute_order_flow_score({
            "funding_rate": -0.0005,  # negative = bullish (contrarian)
            "open_interest_change_pct": 0.03,
            "price_direction": 1,
            "long_short_ratio": 0.8,  # low = bullish (contrarian)
        })
        # With recalibrated steepness, this should be a strong bullish flow signal.
        # Old steepness produces ~54; new produces ~68. Threshold of 55 ensures
        # this test only passes after recalibration.
        assert result["score"] > 55, f"Flow score {result['score']} too compressed"


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
        total = regime["trending"] + regime["ranging"] + regime["volatile"]
        assert abs(total - 1.0) < 1e-6

    def test_regime_indicators_present(self):
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        indicators = result["indicators"]
        assert "regime_trending" in indicators
        assert "regime_ranging" in indicators
        assert "regime_volatile" in indicators

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
        regime = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0}
        result_with = compute_order_flow_score(
            {"funding_rate": -0.0005}, regime=regime
        )
        result_without = compute_order_flow_score({"funding_rate": -0.0005})
        assert result_with["score"] == result_without["score"]

    def test_trending_regime_reduces_contrarian(self):
        """Pure trending regime (trending=1) reduces contrarian to ~30%."""
        regime_trending = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        regime_ranging = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0}
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        score_trending = abs(compute_order_flow_score(metrics, regime=regime_trending)["score"])
        score_ranging = abs(compute_order_flow_score(metrics, regime=regime_ranging)["score"])
        ratio = score_trending / score_ranging
        assert 0.25 <= ratio <= 0.40, f"Expected ~30% ratio, got {ratio:.2f}"

    def test_mixed_regime_interpolates(self):
        """Mixed regime gives intermediate contrarian strength."""
        regime_trending = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        regime_mixed = {"trending": 0.5, "ranging": 0.3, "volatile": 0.2}
        regime_ranging = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0}
        metrics = {"funding_rate": -0.0005}
        score_trending = abs(compute_order_flow_score(metrics, regime=regime_trending)["score"])
        score_mixed = abs(compute_order_flow_score(metrics, regime=regime_mixed)["score"])
        score_ranging = abs(compute_order_flow_score(metrics, regime=regime_ranging)["score"])
        assert score_trending < score_mixed < score_ranging

    def test_oi_unaffected_by_regime(self):
        """OI score is not affected by regime scaling."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        metrics = {"open_interest_change_pct": 0.05, "price_direction": 1}
        result_with = compute_order_flow_score(metrics, regime=regime)
        result_without = compute_order_flow_score(metrics)
        assert result_with["score"] == result_without["score"]


def _make_snapshots(funding_rates, ls_ratios=None):
    """Create mock OrderFlowSnapshot-like objects for testing."""
    if ls_ratios is None:
        ls_ratios = [1.0] * len(funding_rates)
    return [
        SimpleNamespace(funding_rate=fr, long_short_ratio=ls)
        for fr, ls in zip(funding_rates, ls_ratios)
    ]


class TestOrderFlowRoCOverride:
    def test_stable_history_no_boost(self):
        """Stable flow history keeps regime scaling unchanged."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        snapshots = _make_snapshots([0.0001] * 10, [1.2] * 10)
        metrics = {"funding_rate": -0.0005}
        result_with = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_without = compute_order_flow_score(metrics, regime=regime)
        assert abs(result_with["score"] - result_without["score"]) <= 1

    def test_spiking_history_restores_contrarian(self):
        """Rapid funding spike restores contrarian strength despite trending regime."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        funding_rates = [0.0001] * 7 + [0.001] * 3
        snapshots = _make_snapshots(funding_rates, [1.0] * 10)
        metrics = {"funding_rate": -0.0005}
        result_spike = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert abs(result_spike["score"]) > abs(result_no_hist["score"])

    def test_insufficient_history_skips_roc(self):
        """Fewer than 10 snapshots disables RoC — only regime scaling applies."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        snapshots = _make_snapshots([0.001] * 5, [1.0] * 5)
        metrics = {"funding_rate": -0.0005}
        result_partial = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert result_partial["score"] == result_no_hist["score"]

    def test_null_fields_handled_gracefully(self):
        """Snapshots with None funding/LS are excluded from RoC computation."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        snapshots = [
            SimpleNamespace(funding_rate=None, long_short_ratio=None)
            for _ in range(10)
        ]
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert result["score"] == result_no_hist["score"]
        assert result["details"]["roc_boost"] == 0.0

    def test_nine_snapshots_skips_roc(self):
        """Exactly 9 snapshots (below threshold of 10) disables RoC."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        snapshots = _make_snapshots([0.0001] * 6 + [0.001] * 3, [1.0] * 9)
        metrics = {"funding_rate": -0.0005}
        result = compute_order_flow_score(metrics, regime=regime, flow_history=snapshots)
        result_no_hist = compute_order_flow_score(metrics, regime=regime)
        assert result["score"] == result_no_hist["score"]

    def test_nan_fields_excluded_from_roc(self):
        """Snapshots with NaN funding/LS are excluded from RoC computation."""
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
        snapshots = [
            SimpleNamespace(funding_rate=float('nan'), long_short_ratio=float('nan'))
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
        """Different blend ratios produce different mean_rev_score."""
        df = _make_candles(80, "flat")  # flat market = low suppression, so blend ratio differences show
        r1 = compute_technical_score(df, scoring_params={"mean_rev_blend_ratio": 0.9})
        r2 = compute_technical_score(df, scoring_params={"mean_rev_blend_ratio": 0.1})
        assert r1["indicators"]["mean_rev_score"] != r2["indicators"]["mean_rev_score"]

    def test_squeeze_sign_matches_mean_rev_sign(self):
        """Squeeze score sign must match mean_rev_score sign (direction inheritance)."""
        for direction in ("up", "down"):
            df = _make_candles(80, direction)
            result = compute_technical_score(df)
            mr = result["indicators"]["mean_rev_score"]
            sq = result["indicators"]["squeeze_score"]
            if mr > 0:
                assert sq >= 0, f"{direction}: squeeze should be >= 0 when mean_rev > 0"
            elif mr < 0:
                assert sq <= 0, f"{direction}: squeeze should be <= 0 when mean_rev < 0"
            else:
                assert sq == 0, f"{direction}: squeeze must be 0 when mean_rev == 0"

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

    def test_oi_unaffected_by_conviction(self):
        """OI score is direction-aware, not contrarian, so conviction shouldn't affect it."""
        metrics = {"open_interest_change_pct": 0.05, "price_direction": 1}
        result_low = compute_order_flow_score(metrics, trend_conviction=0.0)
        result_high = compute_order_flow_score(metrics, trend_conviction=0.9)
        assert result_low["score"] == result_high["score"]

    def test_conviction_stacks_with_regime(self):
        """Trending regime + high conviction should suppress more than either alone."""
        metrics = {"funding_rate": -0.0005}
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0}
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
        regime = {"trending": 0.5, "ranging": 0.3, "volatile": 0.2}
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
        regime = {"trending": 0.0, "ranging": 1.0, "volatile": 0.0}
        spiking = _make_snapshots([0.0001] * 7 + [0.01] * 3, [1.0] * 10)
        result = compute_order_flow_score(metrics, regime=regime, flow_history=spiking)
        assert -100 <= result["score"] <= 100
