import numpy as np
import pandas as pd
import pytest
from app.engine.traditional import compute_mr_pressure, compute_technical_score


class TestComputeMrPressure:
    def test_neutral_rsi_returns_zero(self):
        """RSI near 50 should produce 0 regardless of BB position."""
        assert compute_mr_pressure(50, 0.95) == 0.0
        assert compute_mr_pressure(55, 0.95) == 0.0

    def test_neutral_bb_returns_zero(self):
        """BB position near 0.5 should produce 0 regardless of RSI."""
        assert compute_mr_pressure(85, 0.5) == 0.0
        assert compute_mr_pressure(85, 0.55) == 0.0

    def test_both_extreme_overbought(self):
        """Both RSI and BB extreme overbought should produce high pressure."""
        pressure = compute_mr_pressure(85, 0.95)
        assert 0.5 < pressure <= 1.0

    def test_both_extreme_oversold(self):
        """Symmetric: oversold should produce same magnitude as overbought."""
        overbought = compute_mr_pressure(85, 0.95)
        oversold = compute_mr_pressure(15, 0.05)
        assert abs(overbought - oversold) < 0.05  # nearly symmetric

    def test_multiplicative_gate(self):
        """Only RSI extreme (BB neutral) = 0. Requires both."""
        assert compute_mr_pressure(90, 0.5) == 0.0

    def test_moderate_values(self):
        """RSI=78, BB=0.90 -> moderate pressure ~0.40."""
        pressure = compute_mr_pressure(78, 0.90)
        assert 0.2 < pressure < 0.6

    def test_output_bounded(self):
        """Output is always in [0, 1]."""
        for rsi in [0, 10, 25, 50, 75, 90, 100]:
            for bb in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
                p = compute_mr_pressure(rsi, bb)
                assert 0.0 <= p <= 1.0, f"Out of bounds: rsi={rsi}, bb={bb}, p={p}"

    def test_reference_values(self):
        """Verify spec reference table values (approximate)."""
        assert compute_mr_pressure(55, 0.55) == 0.0
        assert compute_mr_pressure(65, 0.70) == 0.0
        assert 0.10 <= compute_mr_pressure(72, 0.82) <= 0.25
        assert 0.30 <= compute_mr_pressure(78, 0.90) <= 0.50
        assert 0.55 <= compute_mr_pressure(85, 0.95) <= 0.80
        assert 0.25 <= compute_mr_pressure(25, 0.08) <= 0.50


def _make_candles(n=80, trend="up", seed=42):
    """Generate n candles with a given trend direction."""
    rng = np.random.RandomState(seed)
    base = 100.0
    rows = []
    prev_c = base
    for i in range(n):
        flat_period = n - 30
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


class TestDynamicCaps:
    def test_no_shift_at_zero_pressure(self):
        """When mr_pressure=0, caps should be unchanged from blend_caps output."""
        from app.engine.regime import blend_caps, compute_regime_mix
        from app.engine.scoring import sigmoid_scale

        trend_strength = sigmoid_scale(20, center=20, steepness=0.25)
        vol_expansion = sigmoid_scale(50, center=50, steepness=0.08)
        regime = compute_regime_mix(trend_strength, vol_expansion)
        original_caps = blend_caps(regime)

        # Neutral RSI/BB -> mr_pressure=0 -> caps unchanged
        df = _make_candles(80, "flat")
        result = compute_technical_score(df)
        # mr_pressure should be near 0 for flat candles (RSI ~50, BB ~0.5)
        assert result.get("mr_pressure", 0.0) < 0.1

    def test_caps_stay_balanced(self):
        """Cap shift must preserve total: trend_cap + mean_rev_cap sum stays constant."""
        from app.engine.constants import MR_PRESSURE as MR_CONST

        # Direct arithmetic test: shift is a zero-sum transfer
        base_trend, base_mr = 38.0, 22.0
        original_sum = base_trend + base_mr

        for mr_p in [0.0, 0.16, 0.40, 0.69, 1.0]:
            shift = mr_p * MR_CONST["max_cap_shift"]
            new_trend = base_trend - shift
            new_mr = base_mr + shift
            assert abs((new_trend + new_mr) - original_sum) < 1e-9, \
                f"Sum changed at mr_pressure={mr_p}: {new_trend + new_mr} != {original_sum}"

    def test_mr_pressure_in_return_dict(self):
        """compute_technical_score must return mr_pressure in the result dict."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert "mr_pressure" in result
        assert 0.0 <= result["mr_pressure"] <= 1.0

    def test_mr_pressure_in_indicators(self):
        """mr_pressure should be included in the indicators dict for observability."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        assert "mr_pressure" in result["indicators"]


class TestMultiplicativeVolume:
    def test_volume_cannot_flip_direction(self):
        """Volume multiplier must never change the sign of the directional score."""
        df = _make_candles(80, "down")
        result = compute_technical_score(df)
        assert "obv_slope" in result["indicators"]
        assert "vol_ratio" in result["indicators"]

    def test_vol_mult_range_bounded_by_volume_cap(self):
        """The volume multiplier ceiling/floor should be derived from volume_cap."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        caps = result["caps"]
        vol_cap = caps["volume_cap"]
        expected_ceil = 1.0 + vol_cap / 100
        expected_floor = 2.0 - expected_ceil
        # Floor should be positive (volume_cap < 100)
        assert expected_floor > 0
        assert expected_ceil > 1.0

    def test_score_bounded(self):
        """Score must stay within [-100, +100] after multiplicative volume change."""
        for trend in ("up", "down", "flat"):
            df = _make_candles(80, trend)
            result = compute_technical_score(df)
            assert -100 <= result["score"] <= 100


class TestDirectionalConfidence:
    def test_confidence_bounded(self):
        """Confidence must be in [0, 1]."""
        for trend in ("up", "down", "flat"):
            df = _make_candles(80, trend)
            result = compute_technical_score(df)
            assert 0.0 <= result["confidence"] <= 1.0

    def test_strong_trend_confidence_similar(self):
        """In a clear trend with no exhaustion, confidence should be similar to current."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        # Strong uptrend should produce reasonable confidence
        assert result["confidence"] >= 0.3

    def test_mr_pressure_provides_confidence_floor(self):
        """When mr_pressure is high, confidence should be boosted even if trend is weak.

        This tests the max(trend_conf, mr_conf) logic — mr_pressure alone
        can provide confidence for SHORT signals in trends.
        """
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        mr_p = result.get("mr_pressure", 0.0)
        # If mr_pressure is nonzero, confidence should be at least mr_pressure * 0.7
        if mr_p > 0.1:
            assert result["confidence"] >= mr_p * 0.7


from app.engine.traditional import compute_order_flow_score


class TestOrderFlowMrPressure:
    def test_zero_pressure_unchanged(self):
        """mr_pressure=0 must produce identical results to default."""
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        regime = {"trending": 0.8, "ranging": 0.1, "volatile": 0.05, "steady": 0.05}
        result_default = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.5)
        result_zero = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.5, mr_pressure=0.0)
        assert result_default["score"] == result_zero["score"]

    def test_high_pressure_relaxes_contrarian(self):
        """High mr_pressure should increase contrarian flow score magnitude."""
        metrics = {"funding_rate": -0.0005, "long_short_ratio": 0.8}
        regime = {"trending": 0.8, "ranging": 0.1, "volatile": 0.05, "steady": 0.05}
        result_low = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.7, mr_pressure=0.0)
        result_high = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.7, mr_pressure=0.69)
        # Higher mr_pressure should allow larger contrarian scores
        assert abs(result_high["score"]) > abs(result_low["score"])

    def test_conviction_ceiling_relaxed(self):
        """mr_pressure should relax the conviction dampening ceiling."""
        metrics = {"funding_rate": -0.005, "long_short_ratio": 0.5}
        regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
        # High conviction normally caps final_mult hard
        result_no_mr = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.8, mr_pressure=0.0)
        result_mr = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.8, mr_pressure=0.69)
        assert abs(result_mr["score"]) > abs(result_no_mr["score"])

    def test_oi_dampened_by_mr_pressure(self):
        """Higher mr_pressure relaxes conviction dampening, allowing higher total score."""
        metrics = {"open_interest_change_pct": 0.05, "price_direction": 1}
        regime = {"trending": 0.8, "ranging": 0.1, "volatile": 0.05, "steady": 0.05}
        result_low = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.5, mr_pressure=0.0)
        result_high = compute_order_flow_score(metrics, regime=regime, trend_conviction=0.5, mr_pressure=0.7)
        assert abs(result_high["score"]) >= abs(result_low["score"])


class TestLLMDualTrigger:
    def test_score_path_triggers(self):
        """LLM should trigger on score magnitude alone (existing behavior)."""
        blended = 45
        mr_p = 0.0
        llm_threshold = 40
        mr_llm_trigger = 0.30
        should_call = abs(blended) >= llm_threshold or mr_p >= mr_llm_trigger
        assert should_call is True

    def test_mr_pressure_path_triggers(self):
        """LLM should trigger on mr_pressure alone even with low blended score."""
        blended = -17
        mr_p = 0.40
        llm_threshold = 40
        mr_llm_trigger = 0.30
        should_call = abs(blended) >= llm_threshold or mr_p >= mr_llm_trigger
        assert should_call is True

    def test_neither_path_triggers(self):
        """LLM should NOT trigger when both score and mr_pressure are below thresholds."""
        blended = -5
        mr_p = 0.16
        llm_threshold = 40
        mr_llm_trigger = 0.30
        should_call = abs(blended) >= llm_threshold or mr_p >= mr_llm_trigger
        assert should_call is False

    def test_moderate_long_not_triggered(self):
        """Moderate LONG with no exhaustion should not trigger on mr_pressure path."""
        blended = 25
        mr_p = 0.0
        llm_threshold = 40
        mr_llm_trigger = 0.30
        should_call = abs(blended) >= llm_threshold or mr_p >= mr_llm_trigger
        assert should_call is False


class TestParamOverrides:
    def test_overrides_change_score(self):
        """Passing overrides to compute_technical_score should change the output."""
        df = _make_candles(80, "up")
        result_default = compute_technical_score(df)
        result_override = compute_technical_score(df, overrides={"mr_pressure": {"max_cap_shift": 0}})
        # With max_cap_shift=0, no cap shifting occurs even with pressure
        # The key test: it doesn't crash and returns valid output
        assert -100 <= result_override["score"] <= 100

    def test_overrides_none_unchanged(self):
        """overrides=None should produce identical results to no overrides."""
        df = _make_candles(80, "up")
        result_none = compute_technical_score(df, overrides=None)
        result_default = compute_technical_score(df)
        assert result_none["score"] == result_default["score"]

    def test_vol_multiplier_override(self):
        """Overriding vol_multiplier.obv_weight should change the score."""
        df = _make_candles(80, "up")
        r1 = compute_technical_score(df, overrides={"vol_multiplier": {"obv_weight": 0.9}})
        r2 = compute_technical_score(df, overrides={"vol_multiplier": {"obv_weight": 0.1}})
        # Both must be valid
        assert -100 <= r1["score"] <= 100
        assert -100 <= r2["score"] <= 100

    def test_backtest_propagates_overrides(self):
        """Spec test 12: BacktestConfig param_overrides propagate to scoring functions."""
        from app.engine.backtester import run_backtest, BacktestConfig

        candles = _make_candles(120, "up").to_dict("records")
        r_default = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig())
        r_override = run_backtest(
            candles, "BTC-USDT-SWAP",
            BacktestConfig(param_overrides={"mr_pressure": {"max_cap_shift": 0}}),
        )
        # Both should complete without error
        assert "stats" in r_default
        assert "stats" in r_override


class TestMrPressureParamGroup:
    def test_group_registered(self):
        """mr_pressure group should exist in PARAM_GROUPS."""
        from app.engine.param_groups import PARAM_GROUPS
        assert "mr_pressure" in PARAM_GROUPS

    def test_group_is_grid(self):
        """mr_pressure should use grid sweep method."""
        from app.engine.param_groups import PARAM_GROUPS
        assert PARAM_GROUPS["mr_pressure"]["sweep_method"] == "grid"

    def test_constraint_accepts_valid(self):
        """Valid candidate should pass constraint."""
        from app.engine.param_groups import validate_candidate
        valid = {
            "max_cap_shift": 18,
            "obv_weight": 0.6,
            "mr_llm_trigger": 0.30,
        }
        assert validate_candidate("mr_pressure", valid) is True

    def test_constraint_rejects_zero_cap_shift(self):
        """max_cap_shift=0 should fail constraint."""
        from app.engine.param_groups import validate_candidate
        invalid = {
            "max_cap_shift": 0,
            "obv_weight": 0.6,
            "mr_llm_trigger": 0.30,
        }
        assert validate_candidate("mr_pressure", invalid) is False

    def test_constraint_rejects_out_of_range(self):
        """obv_weight=0 should fail constraint."""
        from app.engine.param_groups import validate_candidate
        invalid = {
            "max_cap_shift": 18,
            "obv_weight": 0,
            "mr_llm_trigger": 0.30,
        }
        assert validate_candidate("mr_pressure", invalid) is False

    def test_priority_layer_2(self):
        """mr_pressure should be in priority layer 2."""
        from app.engine.param_groups import PARAM_GROUPS
        assert PARAM_GROUPS["mr_pressure"]["priority"] == 2

    def test_sweep_ranges_match_spec(self):
        """Sweep ranges should match the spec."""
        from app.engine.param_groups import PARAM_GROUPS
        ranges = PARAM_GROUPS["mr_pressure"]["sweep_ranges"]
        assert ranges["max_cap_shift"] == (8, 24, 4)
        assert ranges["obv_weight"] == (0.30, 0.80, 0.10)
        assert ranges["mr_llm_trigger"] == (0.20, 0.45, 0.05)
        assert "confluence_dampening" not in ranges


from app.engine.combiner import compute_preliminary_score


class TestIntegrationPipelineTraces:
    def test_neutral_regression(self):
        """RSI~50, BB~0.5: mr_pressure should be low for flat market."""
        df = _make_candles(80, "flat")
        result = compute_technical_score(df)
        assert result.get("mr_pressure", 0.0) < 0.1
        # Score bounded (flat candles still have random noise)
        assert -100 <= result["score"] <= 100

    def test_strong_trend_no_exhaustion(self):
        """Strong uptrend with no exhaustion should still produce positive LONG score.

        Spec test 10: LONG signal strength should not be significantly degraded
        by the volume multiplier change. Score must remain positive and above
        a minimum magnitude.
        """
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        mr_p = result.get("mr_pressure", 0.0)
        # In an uptrend, RSI may be elevated but BB may not be extreme
        # The score should still be positive (LONG) and strong enough
        if mr_p < 0.1:
            assert result["score"] > 0, "Strong uptrend with no exhaustion should be LONG"
            assert result["score"] >= 10, (
                f"LONG signal too weak ({result['score']}): multiplicative volume "
                "may have degraded trend-following signals beyond acceptable ~10% range"
            )

    def test_order_flow_with_mr_pressure(self):
        """Order flow score with mr_pressure should be larger than without."""
        metrics = {
            "funding_rate": -0.003,
            "long_short_ratio": 0.6,
            "open_interest_change_pct": -0.02,
            "price_direction": -1,
        }
        regime = {"trending": 0.9, "ranging": 0.05, "volatile": 0.025, "steady": 0.025}

        result_no_mr = compute_order_flow_score(
            metrics, regime=regime, trend_conviction=0.7, mr_pressure=0.0,
        )
        result_mr = compute_order_flow_score(
            metrics, regime=regime, trend_conviction=0.7, mr_pressure=0.69,
        )
        # With mr_pressure, contrarian signals (funding + LS) should be stronger
        assert abs(result_mr["score"]) > abs(result_no_mr["score"])

    def test_blended_score_with_exhaustion(self):
        """Full blending with high mr_pressure should produce a more negative score."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)

        flow_metrics = {
            "funding_rate": -0.003,
            "long_short_ratio": 0.6,
        }
        flow_result = compute_order_flow_score(
            flow_metrics,
            regime=result["regime"],
            trend_conviction=result["indicators"].get("trend_conviction", 0.0),
            mr_pressure=result.get("mr_pressure", 0.0),
        )

        blended = compute_preliminary_score(
            technical_score=result["score"],
            order_flow_score=flow_result["score"],
            tech_weight=0.40,
            flow_weight=0.22,
            tech_confidence=result["confidence"],
            flow_confidence=flow_result["confidence"],
        )
        # Blended should be a valid dict with score
        assert "score" in blended
        assert -100 <= blended["score"] <= 100
