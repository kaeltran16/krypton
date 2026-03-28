"""Backtest-driven regime weight optimizer using differential evolution."""

from __future__ import annotations

import logging
from typing import Any

from app.engine.backtester import run_backtest, BacktestConfig
from app.engine.combiner import compute_preliminary_score
from app.engine.regime import REGIMES, CAP_KEYS, OUTER_KEYS, blend_outer_weights

logger = logging.getLogger(__name__)

_N_REGIMES = len(REGIMES)
_N_CAPS = len(CAP_KEYS)
# Backtester only optimizes tech + pattern; flow/onchain/liquidation are fixed
# at 0 because those data sources aren't available during backtesting.
_BACKTEST_OUTER_KEYS = ["tech", "pattern"]
_N_OUTER = len(_BACKTEST_OUTER_KEYS)
N_PARAMS = _N_REGIMES * _N_CAPS + _N_REGIMES * _N_OUTER

_CAP_BOUNDS = (10.0, 45.0)
_WEIGHT_BOUNDS = (0.10, 0.50)

# Default bounds for backward compat
PARAM_BOUNDS = [_CAP_BOUNDS] * (_N_REGIMES * _N_CAPS) + [_WEIGHT_BOUNDS] * (_N_REGIMES * _N_OUTER)


def _build_bounds(outer_keys: list[str]) -> list[tuple]:
    """Build DE parameter bounds for given outer key set."""
    n_outer = len(outer_keys)
    return [_CAP_BOUNDS] * (_N_REGIMES * _N_CAPS) + [_WEIGHT_BOUNDS] * (_N_REGIMES * n_outer)

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


def vector_to_regime_dict(vec: list[float], outer_keys: list[str] | None = None) -> dict:
    """Convert a flat parameter vector to a nested regime dict.

    Returns dict with one key per regime (trending, ranging, volatile, steady).
    Each has: trend_cap, mean_rev_cap, squeeze_cap, volume_cap, plus outer weights
    for the given outer_keys, normalized to sum to 1.0 per regime.
    """
    if outer_keys is None:
        outer_keys = _BACKTEST_OUTER_KEYS
    n_outer = len(outer_keys)
    result = {}
    caps_offset = _N_REGIMES * _N_CAPS
    for i, regime in enumerate(REGIMES):
        caps = {key: vec[i * _N_CAPS + j] for j, key in enumerate(CAP_KEYS)}
        raw = [vec[caps_offset + i * n_outer + j] for j in range(n_outer)]
        w_total = sum(raw)
        if w_total > 0:
            for j, key in enumerate(outer_keys):
                caps[key] = raw[j] / w_total
        else:
            for key in outer_keys:
                caps[key] = 1.0 / n_outer
        result[regime] = caps
    return result


def regime_dict_to_vector(d: dict, outer_keys: list[str] | None = None) -> list[float]:
    """Convert nested regime dict back to flat vector."""
    if outer_keys is None:
        outer_keys = _BACKTEST_OUTER_KEYS
    vec = []
    for regime in REGIMES:
        for key in CAP_KEYS:
            vec.append(d[regime][key])
    for regime in REGIMES:
        for key in outer_keys:
            vec.append(d[regime][key])
    return vec


class _MockRegimeWeights:
    """Lightweight object mimicking RegimeWeights DB row for backtester."""

    def __init__(self, regime_dict: dict, outer_keys: list[str] | None = None):
        if outer_keys is None:
            outer_keys = _BACKTEST_OUTER_KEYS
        for regime in REGIMES:
            for key in CAP_KEYS:
                setattr(self, f"{regime}_{key}", regime_dict[regime].get(key, 30.0))
            for src in OUTER_KEYS:
                if src in outer_keys and src in regime_dict[regime]:
                    setattr(self, f"{regime}_{src}_weight", regime_dict[regime][src])
                else:
                    setattr(self, f"{regime}_{src}_weight", 0.0)


def _run_de_optimization(
    objective_fn,
    param_bounds: list[tuple],
    max_iterations: int = 300,
    cancel_flag: dict | None = None,
    on_progress=None,
) -> dict:
    """Shared differential evolution runner.

    Returns dict with best_fitness (positive), best_vector, and evaluations count.
    """
    from scipy.optimize import differential_evolution

    best = {"fitness": 0.0, "vector": None}
    eval_count = [0]

    def wrapped_objective(vec):
        if cancel_flag and cancel_flag.get("cancelled"):
            return 0.0
        eval_count[0] += 1
        cost = objective_fn(list(vec))
        fitness = -cost  # objective returns negative fitness for minimization
        if fitness > best["fitness"] or best["vector"] is None:
            best["fitness"] = fitness
            best["vector"] = list(vec)
        return cost

    def callback(xk, convergence):
        if cancel_flag and cancel_flag.get("cancelled"):
            return True
        if on_progress:
            on_progress(eval_count[0], best["fitness"])
        return False

    result = differential_evolution(
        wrapped_objective,
        bounds=param_bounds,
        maxiter=max_iterations,
        seed=42,
        tol=0.01,
        polish=False,
        callback=callback,
    )

    if best["vector"] is None:
        best["vector"] = list(result.x)
        best["fitness"] = -result.fun

    return {
        "best_fitness": best["fitness"],
        "best_vector": best["vector"],
        "evaluations": eval_count[0],
    }


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
    has_flow = config and config.flow_snapshots
    outer_keys = ["tech", "pattern", "flow"] if has_flow else _BACKTEST_OUTER_KEYS
    bounds = _build_bounds(outer_keys)

    best_result: dict[str, Any] = {"stats": {}, "weights": {}}

    def objective(vec):
        regime_dict = vector_to_regime_dict(vec, outer_keys=outer_keys)
        mock_rw = _MockRegimeWeights(regime_dict, outer_keys=outer_keys)
        result = run_backtest(
            candles, pair, config,
            parent_candles=parent_candles,
            regime_weights=mock_rw,
        )
        fitness = compute_fitness(result["stats"])
        if fitness > best_result.get("fitness", 0):
            best_result["stats"] = result["stats"]
            best_result["weights"] = regime_dict
            best_result["fitness"] = fitness
            logger.info(
                "Regime optimizer: new best fitness=%.4f (wr=%.1f%%, pf=%.2f)",
                fitness, result["stats"].get("win_rate", 0),
                result["stats"].get("profit_factor", 0) or 0,
            )
        return -fitness

    de_result = _run_de_optimization(
        objective_fn=objective,
        param_bounds=bounds,
        max_iterations=max_iterations,
        cancel_flag=cancel_flag,
        on_progress=on_progress,
    )

    if not best_result.get("weights"):
        regime_dict = vector_to_regime_dict(de_result["best_vector"], outer_keys=outer_keys)
        best_result["weights"] = regime_dict
        best_result["fitness"] = de_result["best_fitness"]

    best_result["evaluations"] = de_result["evaluations"]
    return best_result


# ── Live Signal Optimizer ──

_SIGNAL_PARAM_BOUNDS = [_WEIGHT_BOUNDS] * (_N_REGIMES * len(OUTER_KEYS))  # 24


def signal_vector_to_weight_dict(vec: list[float]) -> dict:
    """Convert flat weight vector (24 floats) to per-regime outer weight dict.

    No caps — only outer weights for all 6 OUTER_KEYS.
    """
    n = len(OUTER_KEYS)
    result = {}
    for i, regime in enumerate(REGIMES):
        raw = [vec[i * n + j] for j in range(n)]
        w_total = sum(raw)
        if w_total > 0:
            result[regime] = {key: raw[j] / w_total for j, key in enumerate(OUTER_KEYS)}
        else:
            result[regime] = {key: 1.0 / n for key in OUTER_KEYS}
    return result


def optimize_from_signals(
    signals: list[dict],
    pair: str,
    signal_threshold: int = 40,
    max_iterations: int = 300,
    cancel_flag: dict | None = None,
    on_progress=None,
) -> dict:
    """Optimize outer weights by re-scoring resolved signals with candidate vectors.

    Raises ValueError if fewer than MIN_TRADES signals provided.
    """
    if len(signals) < MIN_TRADES:
        raise ValueError(f"insufficient signals: {len(signals)} < {MIN_TRADES}")

    # Pre-compute per-signal data that doesn't change across DE evaluations
    precomputed = []
    for sig in signals:
        ri = sig.get("raw_indicators") or {}
        regime = {
            "trending": ri.get("regime_trending", 0),
            "ranging": ri.get("regime_ranging", 0),
            "volatile": ri.get("regime_volatile", 0),
            "steady": ri.get("regime_steady", 0),
        }
        scores = {key: ri.get(f"{key}_score", 0) for key in OUTER_KEYS}
        confs = {key: ri.get(f"{key}_confidence", 0.0) for key in OUTER_KEYS}
        available = frozenset(k for k in OUTER_KEYS if scores[k] != 0 or confs[k] != 0)
        is_win = sig["outcome"] in ("TP1_HIT", "TP2_HIT")
        pnl = sig.get("outcome_pnl_pct") or 0.0
        entry = float(sig.get("entry", 0))
        sl = float(sig.get("stop_loss", 0))
        sl_pct = abs(entry - sl) / entry * 100 if entry else 0
        rr = abs(pnl / sl_pct) if sl_pct else 0
        precomputed.append({
            "regime": regime, "scores": scores, "confs": confs,
            "available": available, "is_win": is_win, "pnl": pnl, "rr": rr,
        })

    def objective(vec):
        weight_dict = signal_vector_to_weight_dict(vec)
        mock_rw = _MockRegimeWeights(weight_dict, outer_keys=list(OUTER_KEYS))

        kept_trades = []
        for pc in precomputed:
            outer = blend_outer_weights(pc["regime"], mock_rw)

            weights = {}
            total_w = 0.0
            for key in OUTER_KEYS:
                if key not in pc["available"]:
                    weights[key] = 0.0
                else:
                    weights[key] = outer[key]
                    total_w += outer[key]
            if total_w > 0:
                weights = {k: v / total_w for k, v in weights.items()}

            result = compute_preliminary_score(
                technical_score=pc["scores"]["tech"],
                order_flow_score=pc["scores"]["flow"],
                tech_weight=weights["tech"],
                flow_weight=weights["flow"],
                tech_confidence=pc["confs"]["tech"],
                flow_confidence=pc["confs"]["flow"],
                onchain_score=pc["scores"]["onchain"],
                onchain_weight=weights["onchain"],
                onchain_confidence=pc["confs"]["onchain"],
                pattern_score=pc["scores"]["pattern"],
                pattern_weight=weights["pattern"],
                pattern_confidence=pc["confs"]["pattern"],
                liquidation_score=pc["scores"]["liquidation"],
                liquidation_weight=weights["liquidation"],
                liquidation_confidence=pc["confs"]["liquidation"],
                confluence_score=pc["scores"]["confluence"],
                confluence_weight=weights["confluence"],
                confluence_confidence=pc["confs"]["confluence"],
            )

            if abs(result["score"]) >= signal_threshold:
                kept_trades.append({"win": pc["is_win"], "pnl_pct": pc["pnl"], "rr": pc["rr"]})

        if not kept_trades:
            return 0.0  # will map to fitness=0

        total = len(kept_trades)
        wins = sum(1 for t in kept_trades if t["win"])
        gross_profit = sum(t["pnl_pct"] for t in kept_trades if t["pnl_pct"] > 0) or 0
        gross_loss = abs(sum(t["pnl_pct"] for t in kept_trades if t["pnl_pct"] < 0)) or 0
        pf = gross_profit / gross_loss if gross_loss else (gross_profit if gross_profit else 0)
        avg_rr = sum(t["rr"] for t in kept_trades) / total

        cum, peak, max_dd = 0.0, 0.0, 0.0
        for t in kept_trades:
            cum += t["pnl_pct"]
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)

        fitness = compute_fitness({
            "total_trades": total,
            "win_rate": wins / total * 100,
            "profit_factor": pf,
            "avg_rr": avg_rr,
            "max_drawdown": max_dd,
        })

        return -fitness

    de_result = _run_de_optimization(
        objective_fn=objective,
        param_bounds=_SIGNAL_PARAM_BOUNDS,
        max_iterations=max_iterations,
        cancel_flag=cancel_flag,
        on_progress=on_progress,
    )

    weights = signal_vector_to_weight_dict(de_result["best_vector"])
    return {
        "weights": weights,
        "fitness": de_result["best_fitness"],
        "evaluations": de_result["evaluations"],
    }
