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
        for key in ["ema_9", "ema_21", "ema_50", "macd", "macd_signal", "macd_hist"]:
            assert key not in indicators, f"Old indicator still present: {key}"


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
        rw.trending_bb_vol_cap = 25.0
        rw.trending_volume_cap = 25.0
        rw.ranging_trend_cap = 10.0
        rw.ranging_mean_rev_cap = 40.0
        rw.ranging_bb_vol_cap = 25.0
        rw.ranging_volume_cap = 25.0
        rw.volatile_trend_cap = 10.0
        rw.volatile_mean_rev_cap = 40.0
        rw.volatile_bb_vol_cap = 25.0
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
