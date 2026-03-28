# backend/tests/engine/test_regime_optimizer.py
import pytest

from app.engine.regime_optimizer import (
    compute_fitness, vector_to_regime_dict, regime_dict_to_vector,
    PARAM_BOUNDS, N_PARAMS,
    _build_bounds, _MockRegimeWeights, _BACKTEST_OUTER_KEYS,
    _run_de_optimization,
    signal_vector_to_weight_dict, _SIGNAL_PARAM_BOUNDS,
    optimize_from_signals,
)
from app.engine.regime import REGIMES, CAP_KEYS, OUTER_KEYS


class TestFitness:
    def test_reasonable_stats_produce_positive_fitness(self):
        stats = {
            "win_rate": 55, "profit_factor": 1.5,
            "avg_rr": 1.2, "max_drawdown": 8, "total_trades": 30,
        }
        assert compute_fitness(stats) > 0

    def test_too_few_trades_returns_zero(self):
        stats = {
            "win_rate": 80, "profit_factor": 3.0,
            "avg_rr": 2.0, "max_drawdown": 2, "total_trades": 5,
        }
        assert compute_fitness(stats) == 0

    def test_zero_trades_returns_zero(self):
        stats = {
            "win_rate": 0, "profit_factor": None,
            "avg_rr": 0, "max_drawdown": 0, "total_trades": 0,
        }
        assert compute_fitness(stats) == 0

    def test_higher_win_rate_increases_fitness(self):
        base = {"profit_factor": 1.5, "avg_rr": 1.2, "max_drawdown": 8, "total_trades": 30}
        f1 = compute_fitness({**base, "win_rate": 50})
        f2 = compute_fitness({**base, "win_rate": 60})
        assert f2 > f1


class TestVectorConversion:
    def test_roundtrip_with_prenormalized_weights(self):
        """vector -> dict -> vector is identity when outer weights are already normalized."""
        vec = [30.0, 25.0, 22.0, 18.0] * 4 + [0.6, 0.4] * 4  # 4 regimes
        d = vector_to_regime_dict(vec)
        vec2 = regime_dict_to_vector(d)
        assert len(vec2) == N_PARAMS
        for a, b in zip(vec, vec2):
            assert abs(a - b) < 1e-9

    def test_vector_length_matches_param_count(self):
        assert N_PARAMS == len(PARAM_BOUNDS)
        assert N_PARAMS == 24  # 16 inner caps + 8 outer weights (tech+pattern x 4 regimes)

    def test_outer_weights_normalized(self):
        """vector_to_regime_dict should normalize outer weights per regime."""
        vec = [30.0] * 16 + [0.5, 0.3] * 4  # 16 caps + 8 outer weights
        d = vector_to_regime_dict(vec)
        for regime in ["trending", "ranging", "volatile", "steady"]:
            tech = d[regime]["tech"]
            pattern = d[regime]["pattern"]
            assert abs(tech + pattern - 1.0) < 1e-9

    def test_normalization_changes_raw_values(self):
        """Non-normalized input should be corrected by vector_to_regime_dict."""
        vec = [30.0] * 16 + [0.3, 0.2] * 4  # 0.3+0.2=0.5, not 1.0
        d = vector_to_regime_dict(vec)
        assert abs(d["trending"]["tech"] - 0.6) < 1e-9
        assert abs(d["trending"]["pattern"] - 0.4) < 1e-9


class TestParameterExpansion:
    def test_build_bounds_default(self):
        bounds = _build_bounds(_BACKTEST_OUTER_KEYS)
        # 4 regimes * 4 caps + 4 regimes * 2 outer = 24
        assert len(bounds) == 24

    def test_build_bounds_with_flow(self):
        bounds = _build_bounds(["tech", "pattern", "flow"])
        # 4 regimes * 4 caps + 4 regimes * 3 outer = 28
        assert len(bounds) == 28

    def test_vector_roundtrip_with_flow(self):
        outer_keys = ["tech", "pattern", "flow"]
        n_caps = len(CAP_KEYS)
        n_outer = len(outer_keys)
        # Build a vector: 16 caps + 12 outer weights
        vec = [30.0] * (4 * n_caps) + [0.33] * (4 * n_outer)
        d = vector_to_regime_dict(vec, outer_keys=outer_keys)
        vec2 = regime_dict_to_vector(d, outer_keys=outer_keys)
        d2 = vector_to_regime_dict(vec2, outer_keys=outer_keys)
        for regime in REGIMES:
            for key in outer_keys:
                assert abs(d[regime][key] - d2[regime][key]) < 1e-6

    def test_outer_weights_normalized_with_flow(self):
        outer_keys = ["tech", "pattern", "flow"]
        vec = [25.0] * 16 + [0.2, 0.3, 0.5] * 4
        d = vector_to_regime_dict(vec, outer_keys=outer_keys)
        for regime in REGIMES:
            total = sum(d[regime][k] for k in outer_keys)
            assert abs(total - 1.0) < 1e-6

    def test_mock_regime_weights_with_flow(self):
        outer_keys = ["tech", "pattern", "flow"]
        d = {r: {**{c: 30.0 for c in CAP_KEYS}, "tech": 0.4, "pattern": 0.3, "flow": 0.3} for r in REGIMES}
        mock = _MockRegimeWeights(d, outer_keys=outer_keys)
        assert mock.trending_tech_weight == 0.4
        assert mock.trending_flow_weight == 0.3
        # Non-backtest keys still default to 0
        assert mock.trending_onchain_weight == 0.0
        assert mock.trending_liquidation_weight == 0.0


class TestSharedDERunner:
    def test_basic_optimization(self):
        """Shared DE runner finds minimum of simple quadratic."""
        def objective(vec):
            return sum(x ** 2 for x in vec)

        result = _run_de_optimization(
            objective_fn=objective,
            param_bounds=[(-5, 5), (-5, 5)],
            max_iterations=50,
        )
        assert "best_fitness" in result
        assert "best_vector" in result
        assert "evaluations" in result
        assert abs(result["best_fitness"]) < 0.1  # near-zero cost at optimum
        assert all(abs(x) < 0.5 for x in result["best_vector"])  # near origin

    def test_cancel_flag_stops_early(self):
        call_count = [0]
        cancel = {"cancelled": False}

        def objective(vec):
            call_count[0] += 1
            if call_count[0] >= 5:
                cancel["cancelled"] = True
            return sum(x ** 2 for x in vec)

        result = _run_de_optimization(
            objective_fn=objective,
            param_bounds=[(-5, 5)] * 3,
            max_iterations=200,
            cancel_flag=cancel,
        )
        assert call_count[0] < 200 * 15  # should stop well before max

    def test_on_progress_called(self):
        progress_calls = []

        def on_progress(evals, fitness):
            progress_calls.append((evals, fitness))

        def objective(vec):
            return sum(x ** 2 for x in vec)

        _run_de_optimization(
            objective_fn=objective,
            param_bounds=[(-5, 5)] * 2,
            max_iterations=10,
            on_progress=on_progress,
        )
        assert len(progress_calls) > 0


def _make_mock_signals(n=25, win_rate=0.6):
    """Generate mock resolved signals with per-source scores in raw_indicators."""
    signals = []
    for i in range(n):
        is_win = i < int(n * win_rate)
        outcome = "TP1_HIT" if is_win else "SL_HIT"
        entry = 50000.0
        sl = entry - 500  # LONG
        tp1 = entry + 750
        pnl = 1.5 if is_win else -1.0
        signals.append({
            "outcome": outcome,
            "outcome_pnl_pct": pnl,
            "entry": entry,
            "stop_loss": sl,
            "take_profit_1": tp1,
            "raw_indicators": {
                "tech_score": 45 + (i % 20),
                "tech_confidence": 0.7,
                "flow_score": 15,
                "flow_confidence": 0.5,
                "onchain_score": 0,
                "onchain_confidence": 0.0,
                "pattern_score": 10,
                "pattern_confidence": 0.4,
                "liquidation_score": 5,
                "liquidation_confidence": 0.2,
                "confluence_score": 12,
                "confluence_confidence": 0.6,
                "regime_trending": 0.5,
                "regime_ranging": 0.2,
                "regime_volatile": 0.2,
                "regime_steady": 0.1,
            },
        })
    return signals


class TestSignalVectorHelpers:
    def test_signal_vector_roundtrip(self):
        n = len(OUTER_KEYS)  # 6
        vec = [0.2] * (4 * n)  # 24 params, equal weights
        d = signal_vector_to_weight_dict(vec)
        assert set(d.keys()) == set(REGIMES)
        for regime in REGIMES:
            total = sum(d[regime][k] for k in OUTER_KEYS)
            assert abs(total - 1.0) < 1e-6

    def test_signal_param_bounds_length(self):
        assert len(_SIGNAL_PARAM_BOUNDS) == 4 * len(OUTER_KEYS)  # 24


class TestOptimizeFromSignals:
    def test_basic_optimization(self):
        signals = _make_mock_signals(n=30, win_rate=0.6)
        result = optimize_from_signals(signals, pair="BTC-USDT-SWAP", max_iterations=10)
        assert "weights" in result
        assert "fitness" in result
        assert "evaluations" in result
        assert result["fitness"] >= 0

    def test_insufficient_signals_raises(self):
        signals = _make_mock_signals(n=5)
        with pytest.raises(ValueError, match="insufficient"):
            optimize_from_signals(signals, pair="BTC-USDT-SWAP")

    def test_all_signals_suppressed_returns_zero_fitness(self):
        """Threshold so high no signal passes -> fitness=0 from MIN_TRADES gate."""
        signals = _make_mock_signals(n=25)
        result = optimize_from_signals(
            signals, pair="BTC-USDT-SWAP",
            signal_threshold=999,  # nothing passes
            max_iterations=5,
        )
        assert result["fitness"] == 0.0

    def test_cancel_flag_stops_optimization(self):
        signals = _make_mock_signals(n=30)
        cancel = {"cancelled": True}
        result = optimize_from_signals(
            signals, pair="BTC-USDT-SWAP",
            cancel_flag=cancel, max_iterations=100,
        )
        assert result["evaluations"] < 100 * 15  # stopped early

    def test_weights_are_normalized(self):
        signals = _make_mock_signals(n=30, win_rate=0.7)
        result = optimize_from_signals(signals, pair="BTC-USDT-SWAP", max_iterations=10)
        for regime in REGIMES:
            total = sum(result["weights"][regime][k] for k in OUTER_KEYS)
            assert abs(total - 1.0) < 1e-6
