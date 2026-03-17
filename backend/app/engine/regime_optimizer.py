"""Backtest-driven regime weight optimizer using differential evolution."""

from __future__ import annotations

import logging
from typing import Any

from app.engine.backtester import run_backtest, BacktestConfig
from app.engine.regime import REGIMES, CAP_KEYS

logger = logging.getLogger(__name__)

# 12 inner caps (3 regimes x 4 caps) + 6 outer weights (3 regimes x 2: tech + pattern)
# Flow and onchain outer weights are not optimized (always 0 in backtester)
N_PARAMS = 18

# Bounds: (min, max) for each parameter
_CAP_BOUNDS = (10.0, 45.0)
_WEIGHT_BOUNDS = (0.10, 0.50)

PARAM_BOUNDS = [_CAP_BOUNDS] * 12 + [_WEIGHT_BOUNDS] * 6

# Parameter layout:
# [0-3]   trending: trend_cap, mean_rev_cap, bb_vol_cap, volume_cap
# [4-7]   ranging:  trend_cap, mean_rev_cap, bb_vol_cap, volume_cap
# [8-11]  volatile: trend_cap, mean_rev_cap, bb_vol_cap, volume_cap
# [12-13] trending: tech_weight, pattern_weight
# [14-15] ranging:  tech_weight, pattern_weight
# [16-17] volatile: tech_weight, pattern_weight

MIN_TRADES = 20


def compute_fitness(stats: dict, min_trades: int = MIN_TRADES) -> float:
    """Compute normalized fitness from backtest stats.

    All components scaled to 0-1 before weighting.
    Returns 0 if too few trades.
    """
    total_trades = stats.get("total_trades", 0)
    if total_trades < min_trades:
        return 0.0

    win_rate = stats.get("win_rate", 0) / 100
    pf = stats.get("profit_factor", 0) or 0
    profit_factor = min(pf, 5) / 5
    avg_rr = min(stats.get("avg_rr", 0), 5) / 5
    max_dd = min(stats.get("max_drawdown", 0), 100) / 100

    return win_rate * 0.4 + profit_factor * 0.3 + avg_rr * 0.2 - max_dd * 0.1


def vector_to_regime_dict(vec: list[float]) -> dict:
    """Convert a flat parameter vector to a nested regime dict.

    Returns dict with keys: trending, ranging, volatile.
    Each has: trend_cap, mean_rev_cap, bb_vol_cap, volume_cap, tech, pattern.
    Outer weights (tech + pattern) are normalized to sum to 1.0 per regime.
    """
    result = {}
    for i, regime in enumerate(REGIMES):
        caps = {key: vec[i * 4 + j] for j, key in enumerate(CAP_KEYS)}
        raw_tech = vec[12 + i * 2]
        raw_pattern = vec[12 + i * 2 + 1]
        w_total = raw_tech + raw_pattern
        if w_total > 0:
            caps["tech"] = raw_tech / w_total
            caps["pattern"] = raw_pattern / w_total
        else:
            caps["tech"] = 0.5
            caps["pattern"] = 0.5
        result[regime] = caps
    return result


def regime_dict_to_vector(d: dict) -> list[float]:
    """Convert nested regime dict back to flat vector."""
    vec = []
    for regime in REGIMES:
        for key in CAP_KEYS:
            vec.append(d[regime][key])
    for regime in REGIMES:
        vec.append(d[regime]["tech"])
        vec.append(d[regime]["pattern"])
    return vec


class _MockRegimeWeights:
    """Lightweight object mimicking RegimeWeights DB row for backtester."""

    def __init__(self, regime_dict: dict):
        for regime in REGIMES:
            for key in CAP_KEYS:
                setattr(self, f"{regime}_{key}", regime_dict[regime][key])
            setattr(self, f"{regime}_tech_weight", regime_dict[regime]["tech"])
            setattr(self, f"{regime}_pattern_weight", regime_dict[regime]["pattern"])
            # Flow and onchain are fixed at 0 for backtester optimization
            setattr(self, f"{regime}_flow_weight", 0.0)
            setattr(self, f"{regime}_onchain_weight", 0.0)


def optimize_regime_weights(
    candles: list[dict],
    pair: str,
    config: BacktestConfig | None = None,
    parent_candles: list[dict] | None = None,
    max_iterations: int = 300,
    cancel_flag: dict | None = None,
    on_progress: Any = None,
) -> dict:
    """Run differential evolution to find optimal regime weights.

    Args:
        candles: Historical candle data for backtesting.
        pair: Trading pair.
        config: Backtest config (threshold, patterns, etc.)
        parent_candles: Parent TF candles for confluence.
        max_iterations: Max optimizer iterations.
        cancel_flag: Dict with "cancelled" key to abort.
        on_progress: Optional callable(eval_count, best_fitness) called each generation.

    Returns:
        Dict with "weights" (regime dict), "fitness" (float), "stats" (backtest stats).
    """
    from scipy.optimize import differential_evolution

    best_result: dict[str, Any] = {"fitness": 0.0, "stats": {}, "weights": {}}
    eval_count = [0]  # mutable counter for closure

    def objective(vec):
        if cancel_flag and cancel_flag.get("cancelled"):
            return 0.0  # early exit

        eval_count[0] += 1
        regime_dict = vector_to_regime_dict(list(vec))
        mock_rw = _MockRegimeWeights(regime_dict)

        result = run_backtest(
            candles, pair, config,
            parent_candles=parent_candles,
            regime_weights=mock_rw,
        )
        fitness = compute_fitness(result["stats"])

        if fitness > best_result["fitness"]:
            best_result["fitness"] = fitness
            best_result["stats"] = result["stats"]
            best_result["weights"] = regime_dict
            logger.info(
                "Regime optimizer eval #%d: new best fitness=%.4f (wr=%.1f%%, pf=%.2f)",
                eval_count[0], fitness,
                result["stats"].get("win_rate", 0),
                result["stats"].get("profit_factor", 0) or 0,
            )

        return -fitness  # minimize negative fitness

    def progress_callback(xk, convergence):
        """Called after each generation — log progress and notify caller."""
        if cancel_flag and cancel_flag.get("cancelled"):
            return True  # stops the optimizer
        logger.info(
            "Regime optimizer: %d evals, best fitness=%.4f, convergence=%.4f",
            eval_count[0], best_result["fitness"], convergence,
        )
        if on_progress:
            on_progress(eval_count[0], best_result["fitness"])
        return False

    result = differential_evolution(
        objective,
        bounds=PARAM_BOUNDS,
        maxiter=max_iterations,
        seed=42,
        tol=0.01,
        polish=False,
        callback=progress_callback,
    )

    if best_result["fitness"] == 0.0:
        # Fallback: use the scipy result
        regime_dict = vector_to_regime_dict(list(result.x))
        best_result["weights"] = regime_dict
        best_result["fitness"] = -result.fun

    best_result["evaluations"] = eval_count[0]
    return best_result
