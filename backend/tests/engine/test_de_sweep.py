"""Tests for DE sweep parameter override plumbing and optimizer integration."""
import pandas as pd
import pytest

from app.engine.traditional import compute_technical_score


def _make_candles(n: int = 100, trend: str = "up") -> pd.DataFrame:
    """Generate synthetic candle DataFrame for testing."""
    import numpy as np
    rng = np.random.RandomState(42)
    base = 50000.0
    rows = []
    for i in range(n):
        if trend == "up":
            c = base + i * 10 + rng.uniform(-5, 15)
        else:
            c = base - i * 10 + rng.uniform(-15, 5)
        o = c + rng.uniform(-20, 20)
        h = max(o, c) + rng.uniform(0, 30)
        l = min(o, c) - rng.uniform(0, 30)
        rows.append({
            "timestamp": f"2026-01-01T{i:04d}",
            "open": o, "high": h, "low": l, "close": c,
            "volume": 100 + rng.uniform(0, 50),
        })
    return pd.DataFrame(rows)


class TestSigmoidOverrides:
    def test_custom_sigmoid_params_change_score(self):
        """Sigmoid overrides via scoring_params produce different scores."""
        df = _make_candles(100, "up")
        r_default = compute_technical_score(df)
        r_override = compute_technical_score(df, scoring_params={
            "trend_strength_steepness": 0.05,  # much flatter than default 0.25
            "trend_score_steepness": 0.10,      # flatter than default 0.30
        })
        # Scores should differ (flatter sigmoid = less extreme scores)
        assert r_default["score"] != r_override["score"]

    def test_sigmoid_defaults_unchanged(self):
        """Empty scoring_params produces identical score to no scoring_params."""
        df = _make_candles(100, "up")
        r_none = compute_technical_score(df)
        r_empty = compute_technical_score(df, scoring_params={})
        assert r_none["score"] == r_empty["score"]


from app.engine.patterns import compute_pattern_score


class TestPatternStrengthOverrides:
    def test_strength_override_changes_score(self):
        """Custom pattern strengths via strength_overrides change output score."""
        patterns = [
            {"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12},
        ]
        ctx = {"adx": 10, "di_plus": 20, "di_minus": 15, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 50000}

        r_default = compute_pattern_score(patterns, ctx)
        r_override = compute_pattern_score(patterns, ctx, strength_overrides={"hammer": 25})
        assert r_override["score"] > r_default["score"]

    def test_no_override_preserves_score(self):
        """None/empty strength_overrides gives identical result."""
        patterns = [
            {"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15},
        ]
        ctx = {"adx": 10, "di_plus": 20, "di_minus": 15, "vol_ratio": 1.0,
               "bb_pos": 0.5, "close": 50000}

        r_none = compute_pattern_score(patterns, ctx)
        r_empty = compute_pattern_score(patterns, ctx, strength_overrides={})
        assert r_none["score"] == r_empty["score"]


from app.engine.backtester import run_backtest, BacktestConfig


class TestBacktestParamOverrides:
    def test_sigmoid_override_via_backtest(self):
        """param_overrides with sigmoid keys reach compute_technical_score and change results."""
        candles = _make_candles(120, "up").to_dict("records")
        r_default = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(signal_threshold=15))
        r_override = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(
            signal_threshold=15,
            param_overrides={
                "trend_strength_steepness": 0.05,
                "vol_expansion_steepness": 0.01,
            },
        ))
        assert "profit_factor" in r_default["stats"]
        assert "profit_factor" in r_override["stats"]
        assert r_default["stats"] != r_override["stats"], (
            "Sigmoid overrides had no effect on backtest results"
        )

    def test_pattern_override_via_backtest(self):
        """param_overrides with pattern keys route to compute_pattern_score without error."""
        candles = _make_candles(120, "up").to_dict("records")
        r_override = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(
            signal_threshold=15,
            param_overrides={"hammer": 25, "bullish_engulfing": 25},
        ))
        # Routing works without error; stats produced
        assert "profit_factor" in r_override["stats"]

    def test_empty_overrides_matches_no_overrides(self):
        """Empty param_overrides dict produces same result as None."""
        candles = _make_candles(120, "up").to_dict("records")
        r_none = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(signal_threshold=15))
        r_empty = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(
            signal_threshold=15, param_overrides={},
        ))
        assert r_none["stats"]["profit_factor"] == r_empty["stats"]["profit_factor"]

    def test_mr_pressure_overrides_still_work(self):
        """Existing MR pressure override channel is preserved."""
        candles = _make_candles(120, "up").to_dict("records")
        r = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(
            signal_threshold=15,
            param_overrides={"mr_pressure": {"max_cap_shift": 0}},
        ))
        assert "profit_factor" in r["stats"]


class TestPatternBoostOverrides:
    def test_boost_override_changes_score(self):
        """Pattern boost overrides via boost_overrides change output score."""
        from app.engine.patterns import compute_pattern_score
        patterns = [
            {"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12},
        ]
        ctx = {"adx": 10, "di_plus": 20, "di_minus": 15, "vol_ratio": 1.5, "bb_pos": 0.5, "close": 50000}
        r_default = compute_pattern_score(patterns, ctx, regime_trending=0.5)
        r_override = compute_pattern_score(
            patterns, ctx, regime_trending=0.5,
            boost_overrides={"vol_center": 1.0, "vol_steepness": 12.0},
        )
        assert r_override["score"] != r_default["score"]

    def test_boost_override_via_backtest(self):
        """Boost param overrides route through backtester without error."""
        candles = _make_candles(120, "up").to_dict("records")
        r = run_backtest(candles, "BTC-USDT-SWAP", BacktestConfig(
            signal_threshold=15,
            param_overrides={"vol_center": 1.0, "vol_steepness": 12.0},
        ))
        assert "profit_factor" in r["stats"]


class TestPatternBoostsParamGroup:
    def test_group_exists(self):
        """pattern_boosts group is defined in PARAM_GROUPS."""
        from app.engine.param_groups import PARAM_GROUPS
        assert "pattern_boosts" in PARAM_GROUPS

    def test_group_uses_de_sweep(self):
        from app.engine.param_groups import PARAM_GROUPS
        assert PARAM_GROUPS["pattern_boosts"]["sweep_method"] == "de"

    def test_group_constraint_rejects_negative(self):
        from app.engine.param_groups import validate_candidate
        assert not validate_candidate("pattern_boosts", {"vol_center": -1, "vol_steepness": 8, "reversal_boost": 0.3, "continuation_boost": 0.2})

    def test_group_constraint_accepts_valid(self):
        from app.engine.param_groups import validate_candidate
        assert validate_candidate("pattern_boosts", {"vol_center": 1.5, "vol_steepness": 8, "reversal_boost": 0.3, "continuation_boost": 0.2})


from types import SimpleNamespace


class TestBuildRegimeWeights:
    def test_candidate_overrides_base(self):
        """Candidate values override base regime_weights attributes."""
        from app.engine.optimizer import _build_regime_weights

        base = SimpleNamespace(
            trending_trend_cap=38.0, trending_mean_rev_cap=22.0,
            trending_squeeze_cap=12.0, trending_volume_cap=28.0,
            trending_tech_weight=0.45, trending_flow_weight=0.25,
        )
        candidate = {"trending_trend_cap": 30.0, "trending_mean_rev_cap": 30.0}
        rw = _build_regime_weights(candidate, base)

        assert rw.trending_trend_cap == 30.0      # overridden
        assert rw.trending_mean_rev_cap == 30.0    # overridden
        assert rw.trending_squeeze_cap == 12.0     # from base
        assert rw.trending_tech_weight == 0.45     # from base

    def test_no_base_populates_defaults(self):
        """Without base, defaults are populated so blend_caps/blend_outer_weights work."""
        from app.engine.optimizer import _build_regime_weights

        candidate = {"trending_trend_cap": 35.0}
        rw = _build_regime_weights(candidate)
        assert rw.trending_trend_cap == 35.0        # overridden
        assert rw.ranging_trend_cap == 18            # from DEFAULT_CAPS
        assert rw.trending_tech_weight == 0.36       # from DEFAULT_OUTER_WEIGHTS
        assert rw.ranging_tech_weight == 0.32        # from DEFAULT_OUTER_WEIGHTS
        assert rw.volatile_flow_weight == 0.18       # from DEFAULT_OUTER_WEIGHTS
        assert rw.volatile_pattern_weight == 0.10    # from DEFAULT_OUTER_WEIGHTS


class TestRunDeSweep:
    def test_maximizes_simple_quadratic(self):
        """DE sweep finds maximum of a simple quadratic objective."""
        from app.engine.optimizer import _run_de_sweep

        group_def = {
            "sweep_ranges": {"x": (0, 10, None), "y": (0, 10, None)},
            "constraints": lambda c: True,
        }

        def objective(candidate):
            return -((candidate["x"] - 3) ** 2 + (candidate["y"] - 7) ** 2)

        best, fitness = _run_de_sweep(objective, group_def, max_evals=300)
        assert abs(best["x"] - 3) < 0.5
        assert abs(best["y"] - 7) < 0.5

    def test_respects_constraints(self):
        """DE sweep rejects candidates that fail constraints."""
        from app.engine.optimizer import _run_de_sweep

        group_def = {
            "sweep_ranges": {"a": (0, 100, None), "b": (0, 100, None)},
            "constraints": lambda c: c["a"] + c["b"] <= 50,
        }

        def objective(candidate):
            return candidate["a"] + candidate["b"]  # maximize sum

        best, _ = _run_de_sweep(objective, group_def, max_evals=300)
        assert best["a"] + best["b"] <= 50 + 0.5  # within tolerance


from unittest.mock import patch, AsyncMock, MagicMock


class TestDeWiring:
    @pytest.mark.asyncio
    async def test_de_group_calls_de_sweep(self):
        """DE-method groups invoke _run_de_sweep instead of being skipped."""
        from app.engine.optimizer import run_counterfactual_eval

        app = MagicMock()
        app.state.settings = MagicMock()
        app.state.settings.engine_signal_threshold = 40
        app.state.regime_weights = {}

        mock_candle = MagicMock()
        mock_candle.timestamp = "2026-01-01T00:00"
        mock_candle.open = 50000
        mock_candle.high = 50100
        mock_candle.low = 49900
        mock_candle.close = 50050
        mock_candle.volume = 100

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_candle] * 200
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        app.state.db.session_factory.return_value = mock_session

        with patch("app.engine.optimizer._run_de_sweep") as mock_de:
            mock_de.return_value = ({"trend_strength_steepness": 0.20}, 1.5)

            with patch("app.engine.backtester.run_backtest") as mock_bt:
                mock_bt.return_value = {
                    "trades": [],
                    "stats": {
                        "profit_factor": 1.5, "win_rate": 55,
                        "avg_rr": 1.2, "max_drawdown": 5, "total_trades": 20,
                    },
                }
                result = await run_counterfactual_eval(app, "sigmoid_curves")

            assert mock_de.called
            assert result is not None
            assert result["candidate"]["trend_strength_steepness"] == 0.20
            assert result["metrics"]["profit_factor"] == 1.5

    @pytest.mark.asyncio
    async def test_regime_outer_filters_non_backtestable_weights(self):
        """regime_outer DE sweep only includes tech+pattern weights, not flow/onchain/liquidation."""
        from app.engine.optimizer import run_counterfactual_eval

        app = MagicMock()
        app.state.settings = MagicMock()
        app.state.settings.engine_signal_threshold = 40
        app.state.regime_weights = {}

        mock_candle = MagicMock()
        mock_candle.timestamp = "2026-01-01T00:00"
        mock_candle.open = 50000
        mock_candle.high = 50100
        mock_candle.low = 49900
        mock_candle.close = 50050
        mock_candle.volume = 100

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_candle] * 200
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        app.state.db.session_factory.return_value = mock_session

        with patch("app.engine.optimizer._run_de_sweep") as mock_de:
            mock_de.return_value = ({"trending_tech_weight": 0.40, "trending_pattern_weight": 0.15}, 1.2)

            with patch("app.engine.backtester.run_backtest") as mock_bt:
                mock_bt.return_value = {
                    "trades": [],
                    "stats": {
                        "profit_factor": 1.2, "win_rate": 52,
                        "avg_rr": 1.1, "max_drawdown": 6, "total_trades": 15,
                    },
                }
                await run_counterfactual_eval(app, "regime_outer")

            call_args = mock_de.call_args
            group_def = call_args[0][1]
            sweep_keys = set(group_def["sweep_ranges"].keys())
            for key in sweep_keys:
                assert "tech" in key or "pattern" in key, (
                    f"Non-backtestable key {key!r} should not be in regime_outer sweep"
                )
            assert not any("flow" in k for k in sweep_keys)
            assert not any("onchain" in k for k in sweep_keys)
            assert not any("liquidation" in k for k in sweep_keys)

    @pytest.mark.asyncio
    async def test_non_backtestable_group_skipped(self):
        """Non-backtestable DE groups (order_flow, etc.) return None."""
        from app.engine.optimizer import run_counterfactual_eval

        app = MagicMock()
        app.state.settings = MagicMock()
        app.state.regime_weights = {}

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [MagicMock()] * 200
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        app.state.db.session_factory.return_value = mock_session

        result = await run_counterfactual_eval(app, "order_flow")
        assert result is None
