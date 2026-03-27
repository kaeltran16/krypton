"""Parameter group definitions for the optimizer.

Each group defines:
- params: dict of parameter keys with their current-value dot-paths
- sweep_method: "grid" or "de" (differential evolution)
- sweep_ranges: per-param (min, max, step|None) — step=None for DE
- constraints: callable(candidate_dict) -> bool
- priority: int (lower = higher priority, optimized first)
"""

from __future__ import annotations

import math
from typing import Any, Callable

from app.engine.constants import PATTERN_STRENGTHS, PATTERN_BOOST_DEFAULTS
from app.engine.regime import REGIMES, OUTER_KEYS

# ── Priority layers (lower number = optimize first) ──

PRIORITY_LAYERS: list[set[str]] = [
    {"source_weights", "thresholds"},           # layer 0: biggest impact, fewest params
    {"regime_caps", "regime_outer", "atr_levels"},  # layer 1
    {"sigmoid_curves", "order_flow", "pattern_strengths", "pattern_boosts",
     "indicator_periods", "mean_reversion", "llm_factors", "onchain",
     "mr_pressure", "liquidation"},  # layer 2
]


def _priority_for(group_name: str) -> int:
    for i, layer in enumerate(PRIORITY_LAYERS):
        if group_name in layer:
            return i
    return len(PRIORITY_LAYERS)


def _sum_close_to(values: list[float], target: float, tol: float = 0.01) -> bool:
    return abs(sum(values) - target) < tol


# ── Constraint functions ──

def _source_weights_ok(c: dict[str, Any]) -> bool:
    vals = [c["traditional"], c["flow"], c["onchain"], c["pattern"], c["liquidation"]]
    return _sum_close_to(vals, 1.0) and all(v >= 0 for v in vals)


def _thresholds_ok(c: dict[str, Any]) -> bool:
    return (
        c["signal"] > c["llm"]
        and 0 < c["ml_confidence"] < 1
        and c["signal"] > 0
        and c["llm"] > 0
    )


def _regime_caps_ok(c: dict[str, Any]) -> bool:
    for regime in REGIMES:
        keys = [k for k in c if k.startswith(regime)]
        if not _sum_close_to([c[k] for k in keys], 100.0, tol=1.0):
            return False
    return all(v >= 0 for v in c.values())


def _regime_outer_ok(c: dict[str, Any]) -> bool:
    for regime in REGIMES:
        keys = [k for k in c if k.startswith(regime)]
        if not _sum_close_to([c[k] for k in keys], 1.0):
            return False
    return all(v >= 0 for v in c.values())


def _atr_levels_ok(c: dict[str, Any]) -> bool:
    sl, tp1, tp2 = c["sl"], c["tp1"], c["tp2"]
    return tp2 > tp1 > sl > 0 and tp1 / sl >= 1.0  # R:R floor


def _positive_values(c: dict[str, Any]) -> bool:
    return all(v > 0 for v in c.values())


def _pattern_strengths_ok(c: dict[str, Any]) -> bool:
    return all(3 <= v <= 25 for v in c.values())


def _indicator_periods_ok(c: dict[str, Any]) -> bool:
    return all(isinstance(v, int) and v > 0 for v in c.values())


def _mean_reversion_ok(c: dict[str, Any]) -> bool:
    return (
        0 <= c.get("blend_ratio", 0.6) <= 1
        and all(v > 0 for v in c.values())
    )


def _llm_factors_ok(c: dict[str, Any]) -> bool:
    cap = c.get("factor_cap", 35)
    return cap <= 50 and all(v >= 0 for v in c.values())


def _liquidation_ok(c: dict[str, Any]) -> bool:
    return (
        c["cluster_max_score"] + c["asymmetry_max_score"] <= 100
        and all(v > 0 for v in c.values())
        and 0 < c["cluster_weight"] < 1
    )


def _onchain_ok(c: dict[str, Any]) -> bool:
    max_keys = [k for k in c if k.endswith("_max_score")]
    if max_keys and sum(c[k] for k in max_keys) > 100:
        return False
    return all(v >= 0 for v in c.values())


# ── Group definitions ──

PARAM_GROUPS: dict[str, dict] = {
    "source_weights": {
        "params": {
            "traditional": "blending.source_weights.traditional",
            "flow": "blending.source_weights.flow",
            "onchain": "blending.source_weights.onchain",
            "pattern": "blending.source_weights.pattern",
            "liquidation": "blending.source_weights.liquidation",
        },
        "sweep_method": "grid",
        "sweep_ranges": {
            "traditional": (0.10, 0.60, 0.05),
            "flow": (0.05, 0.40, 0.05),
            "onchain": (0.05, 0.40, 0.05),
            "pattern": (0.05, 0.30, 0.05),
            "liquidation": (0.0, 0.20, 0.05),
        },
        "constraints": _source_weights_ok,
        "priority": _priority_for("source_weights"),
    },
    "thresholds": {
        "params": {
            "signal": "blending.thresholds.signal",
            "llm": "blending.thresholds.llm",
            "ml_confidence": "blending.thresholds.ml_confidence",
        },
        "sweep_method": "grid",
        "sweep_ranges": {
            "signal": (20, 60, 5),
            "llm": (10, 40, 5),
            "ml_confidence": (0.50, 0.85, 0.05),
        },
        "constraints": _thresholds_ok,
        "priority": _priority_for("thresholds"),
    },
    "regime_caps": {
        "params": {
            f"{r}_{cap}_cap": f"regime_weights.*.*.{r}_{cap}_cap"
            for r in REGIMES
            for cap in ("trend", "mean_rev", "squeeze", "volume")
        },
        "sweep_method": "de",
        "sweep_ranges": {
            f"{r}_{cap}_cap": (10.0, 45.0, None)
            for r in REGIMES
            for cap in ("trend", "mean_rev", "squeeze", "volume")
        },
        "constraints": _regime_caps_ok,
        "priority": _priority_for("regime_caps"),
    },
    "regime_outer": {
        "params": {
            f"{r}_{src}_weight": f"regime_weights.*.*.{r}_{src}_weight"
            for r in REGIMES
            for src in OUTER_KEYS
        },
        "sweep_method": "de",
        "sweep_ranges": {
            f"{r}_{src}_weight": (
                (0.0, 0.20, None) if src == "liquidation" else (0.10, 0.50, None)
            )
            for r in REGIMES
            for src in OUTER_KEYS
        },
        "constraints": _regime_outer_ok,
        "priority": _priority_for("regime_outer"),
    },
    "atr_levels": {
        "params": {
            "sl": "levels.atr_defaults.sl",
            "tp1": "levels.atr_defaults.tp1",
            "tp2": "levels.atr_defaults.tp2",
        },
        "sweep_method": "grid",
        "sweep_ranges": {
            "sl": (0.8, 2.5, 0.2),
            "tp1": (1.0, 4.0, 0.5),
            "tp2": (2.0, 6.0, 0.5),
        },
        "constraints": _atr_levels_ok,
        "priority": _priority_for("atr_levels"),
    },
    "sigmoid_curves": {
        "params": {
            "trend_strength_center": "technical.sigmoid_params.trend_strength_center",
            "trend_strength_steepness": "technical.sigmoid_params.trend_strength_steepness",
            "vol_expansion_center": "technical.sigmoid_params.vol_expansion_center",
            "vol_expansion_steepness": "technical.sigmoid_params.vol_expansion_steepness",
            "trend_score_steepness": "technical.sigmoid_params.trend_score_steepness",
            "obv_slope_steepness": "technical.sigmoid_params.obv_slope_steepness",
            "volume_ratio_steepness": "technical.sigmoid_params.volume_ratio_steepness",
            "di_spread_steepness": "technical.sigmoid_params.di_spread_steepness",
        },
        "sweep_method": "de",
        "sweep_ranges": {
            "trend_strength_center": (10.0, 35.0, None),
            "trend_strength_steepness": (0.05, 0.50, None),
            "vol_expansion_center": (30.0, 70.0, None),
            "vol_expansion_steepness": (0.03, 0.15, None),
            "trend_score_steepness": (0.10, 0.60, None),
            "obv_slope_steepness": (1.0, 8.0, None),
            "volume_ratio_steepness": (1.0, 6.0, None),
            "di_spread_steepness": (1.0, 6.0, None),
        },
        "constraints": _positive_values,
        "priority": _priority_for("sigmoid_curves"),
    },
    "order_flow": {
        "params": {
            "funding_max": "order_flow.max_scores.funding",
            "oi_max": "order_flow.max_scores.oi",
            "ls_ratio_max": "order_flow.max_scores.ls_ratio",
            "cvd_max": "order_flow.max_scores.cvd",
            "book_max": "order_flow.max_scores.book",
            "funding_steepness": "order_flow.sigmoid_steepnesses.funding",
            "oi_steepness": "order_flow.sigmoid_steepnesses.oi",
            "ls_ratio_steepness": "order_flow.sigmoid_steepnesses.ls_ratio",
            "cvd_steepness": "order_flow.sigmoid_steepnesses.cvd",
            "book_steepness": "order_flow.sigmoid_steepnesses.book",
            "freshness_fresh_seconds": "order_flow.freshness_fresh_seconds",
            "freshness_stale_seconds": "order_flow.freshness_stale_seconds",
        },
        "sweep_method": "de",
        "sweep_ranges": {
            "funding_max": (10, 35, None),
            "oi_max": (10, 35, None),
            "ls_ratio_max": (10, 35, None),
            "cvd_max": (10, 35, None),
            "book_max": (5, 20, None),
            "funding_steepness": (200, 800, None),
            "oi_steepness": (10, 40, None),
            "ls_ratio_steepness": (2, 12, None),
            "cvd_steepness": (2, 10, None),
            "book_steepness": (2, 8, None),
            "freshness_fresh_seconds": (120, 600, None),
            "freshness_stale_seconds": (600, 1800, None),
        },
        "constraints": lambda c: (
            sum(c.get(k, 0) for k in ("funding_max", "oi_max", "ls_ratio_max", "cvd_max", "book_max")) <= 100
            and all(v > 0 for v in c.values())
            and c.get("freshness_stale_seconds", 900) > c.get("freshness_fresh_seconds", 300)
        ),
        "priority": _priority_for("order_flow"),
    },
    "pattern_strengths": {
        "params": {
            name: f"patterns.strengths.{name}"
            for name in PATTERN_STRENGTHS
        },
        "sweep_method": "de",
        "sweep_ranges": {
            name: (3, 25, None)
            for name in PATTERN_STRENGTHS
        },
        "constraints": _pattern_strengths_ok,
        "priority": _priority_for("pattern_strengths"),
    },
    "indicator_periods": {
        "params": {
            "adx_period": "technical.indicator_periods.adx_period",
            "rsi_period": "technical.indicator_periods.rsi_period",
            "sma_period": "technical.indicator_periods.sma_period",
            "obv_slope_window": "technical.indicator_periods.obv_slope_window",
        },
        "sweep_method": "grid",
        "sweep_ranges": {
            "adx_period": (7, 21, 7),
            "rsi_period": (7, 21, 7),
            "sma_period": (10, 30, 5),
            "obv_slope_window": (5, 15, 5),
        },
        "constraints": _indicator_periods_ok,
        "priority": _priority_for("indicator_periods"),
    },
    "mean_reversion": {
        "params": {
            "rsi_steepness": "mean_reversion.rsi_steepness",
            "bb_pos_steepness": "mean_reversion.bb_pos_steepness",
            "squeeze_steepness": "mean_reversion.squeeze_steepness",
            "blend_ratio": "mean_reversion.blend_ratio",
        },
        "sweep_method": "grid",
        "sweep_ranges": {
            "rsi_steepness": (0.10, 0.50, 0.05),
            "bb_pos_steepness": (5.0, 20.0, 2.5),
            "squeeze_steepness": (0.05, 0.20, 0.05),
            "blend_ratio": (0.3, 0.8, 0.1),
        },
        "constraints": _mean_reversion_ok,
        "priority": _priority_for("mean_reversion"),
    },
    "llm_factors": {
        "params": {
            "support_proximity": "blending.llm_factor_weights.support_proximity",
            "resistance_proximity": "blending.llm_factor_weights.resistance_proximity",
            "level_breakout": "blending.llm_factor_weights.level_breakout",
            "htf_alignment": "blending.llm_factor_weights.htf_alignment",
            "rsi_divergence": "blending.llm_factor_weights.rsi_divergence",
            "volume_divergence": "blending.llm_factor_weights.volume_divergence",
            "macd_divergence": "blending.llm_factor_weights.macd_divergence",
            "volume_exhaustion": "blending.llm_factor_weights.volume_exhaustion",
            "funding_extreme": "blending.llm_factor_weights.funding_extreme",
            "crowded_positioning": "blending.llm_factor_weights.crowded_positioning",
            "pattern_confirmation": "blending.llm_factor_weights.pattern_confirmation",
            "news_catalyst": "blending.llm_factor_weights.news_catalyst",
            "factor_cap": "blending.llm_factor_cap",
        },
        "sweep_method": "de",
        "sweep_ranges": {
            "support_proximity": (2.0, 10.0, None),
            "resistance_proximity": (2.0, 10.0, None),
            "level_breakout": (3.0, 12.0, None),
            "htf_alignment": (3.0, 10.0, None),
            "rsi_divergence": (3.0, 10.0, None),
            "volume_divergence": (2.0, 10.0, None),
            "macd_divergence": (2.0, 10.0, None),
            "volume_exhaustion": (2.0, 8.0, None),
            "funding_extreme": (2.0, 8.0, None),
            "crowded_positioning": (2.0, 8.0, None),
            "pattern_confirmation": (2.0, 8.0, None),
            "news_catalyst": (3.0, 10.0, None),
            "factor_cap": (20.0, 50.0, None),
        },
        "constraints": _llm_factors_ok,
        "priority": _priority_for("llm_factors"),
    },
    "onchain": {
        "params": {
            "btc_netflow_max": "onchain.btc_profile.netflow_max_score",
            "btc_whale_max": "onchain.btc_profile.whale_max_score",
            "btc_addresses_max": "onchain.btc_profile.addresses_max_score",
            "btc_nupl_max": "onchain.btc_profile.nupl_max_score",
            "btc_hashrate_max": "onchain.btc_profile.hashrate_max_score",
            "eth_netflow_max": "onchain.eth_profile.netflow_max_score",
            "eth_whale_max": "onchain.eth_profile.whale_max_score",
            "eth_addresses_max": "onchain.eth_profile.addresses_max_score",
            "eth_staking_max": "onchain.eth_profile.staking_max_score",
            "eth_gas_max": "onchain.eth_profile.gas_max_score",
        },
        "sweep_method": "de",
        "sweep_ranges": {
            k: (5, 50, None)
            for k in [
                "btc_netflow_max", "btc_whale_max", "btc_addresses_max",
                "btc_nupl_max", "btc_hashrate_max",
                "eth_netflow_max", "eth_whale_max", "eth_addresses_max",
                "eth_staking_max", "eth_gas_max",
            ]
        },
        "constraints": _onchain_ok,
        "priority": _priority_for("onchain"),
    },
    "pattern_boosts": {
        "params": {
            name: f"patterns.boosts.{name}"
            for name in PATTERN_BOOST_DEFAULTS
        },
        "sweep_method": "de",
        "sweep_ranges": {
            "vol_center": (1.1, 2.0, None),
            "vol_steepness": (3.0, 15.0, None),
            "reversal_boost": (0.1, 0.5, None),
            "continuation_boost": (0.1, 0.4, None),
        },
        "constraints": _positive_values,
        "priority": _priority_for("pattern_boosts"),
    },
}


def _mr_pressure_ok(c: dict[str, Any]) -> bool:
    return (
        c["max_cap_shift"] > 0
        and 0 < c["confluence_dampening"] < 1
        and 0 < c["obv_weight"] < 1
        and 0 < c["mr_llm_trigger"] < 1
    )


PARAM_GROUPS["liquidation"] = {
    "params": {
        "cluster_max_score": "liquidation.cluster_max_score",
        "asymmetry_max_score": "liquidation.asymmetry_max_score",
        "cluster_weight": "liquidation.cluster_weight",
        "proximity_steepness": "liquidation.proximity_steepness",
        "decay_half_life_hours": "liquidation.decay_half_life_hours",
        "asymmetry_steepness": "liquidation.asymmetry_steepness",
    },
    "sweep_method": "de",
    "sweep_ranges": {
        "cluster_max_score": (15, 45, None),
        "asymmetry_max_score": (10, 40, None),
        "cluster_weight": (0.4, 0.8, None),
        "proximity_steepness": (1.0, 4.0, None),
        "decay_half_life_hours": (2.0, 8.0, None),
        "asymmetry_steepness": (1.5, 6.0, None),
    },
    "constraints": _liquidation_ok,
    "priority": _priority_for("liquidation"),
}

PARAM_GROUPS["mr_pressure"] = {
    "params": {
        "max_cap_shift": "technical.mr_pressure.max_cap_shift",
        "confluence_dampening": "technical.mr_pressure.confluence_dampening",
        "obv_weight": "technical.vol_multiplier.obv_weight",
        "mr_llm_trigger": "technical.mr_pressure.mr_llm_trigger",
    },
    "sweep_method": "grid",
    "sweep_ranges": {
        "max_cap_shift": (8, 24, 4),
        "confluence_dampening": (0.30, 0.90, 0.15),
        "obv_weight": (0.30, 0.80, 0.10),
        "mr_llm_trigger": (0.20, 0.45, 0.05),
    },
    "constraints": _mr_pressure_ok,
    "priority": _priority_for("mr_pressure"),
}


def get_group(name: str) -> dict | None:
    """Return a parameter group definition by name."""
    return PARAM_GROUPS.get(name)


def validate_candidate(group_name: str, candidate: dict[str, Any]) -> bool:
    """Check whether a candidate parameter set satisfies the group's constraints."""
    group = PARAM_GROUPS.get(group_name)
    if not group:
        return False
    return group["constraints"](candidate)
