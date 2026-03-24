# backend/tests/engine/test_regime_optimizer.py
import pytest

from app.engine.regime_optimizer import (
    compute_fitness, vector_to_regime_dict, regime_dict_to_vector,
    PARAM_BOUNDS, N_PARAMS,
)


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
