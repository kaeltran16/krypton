"""Centralized engine constants registry.

All hardcoded scoring/scaling constants live here. Engine modules
import what they need; the API reads the full tree via
get_engine_constants().
"""

# -- Technical scoring --
INDICATOR_PERIODS = {
    "adx": 14,
    "rsi": 14,
    "sma": 20,
    "bb_std": 2,
    "ema_spans": [9, 21, 50],
    "obv_slope_window": 10,
    "bb_width_percentile_window": 50,
}

SIGMOID_PARAMS = {
    "trend_strength_center": 20,
    "trend_strength_steepness": 0.25,
    "vol_expansion_center": 50,
    "vol_expansion_steepness": 0.08,
    "trend_score_steepness": 0.30,
    "obv_slope_steepness": 4,
    "volume_ratio_steepness": 3.0,
}

# -- Order flow scoring --
ORDER_FLOW = {
    "max_scores": {"funding": 35, "oi": 20, "ls_ratio": 35},
    "sigmoid_steepnesses": {"funding": 8000, "oi": 65, "ls_ratio": 6},
    "trending_floor": 0.3,
    "recent_window": 3,
    "baseline_window": 7,
    "roc_threshold": 0.0005,
    "roc_steepness": 8000,
    "ls_roc_scale": 0.003,
}

# -- On-chain scoring --
ONCHAIN_PROFILES = {
    "btc": {
        "netflow_normalization": 3000,
        "whale_baseline": 3,
        "max_scores": {
            "netflow": 35, "whale": 20, "addresses": 15,
            "nupl": 15, "hashrate": 15,
        },
    },
    "eth": {
        "netflow_normalization": 50000,
        "whale_baseline": 5,
        "max_scores": {
            "netflow": 35, "whale": 20, "addresses": 15,
            "staking": 15, "gas": 15,
        },
    },
}

# -- Level calculation / ATR scaling --
LEVEL_DEFAULTS = {
    "atr_defaults": {"sl": 1.5, "tp1": 2.0, "tp2": 3.0},
    "atr_guardrails": {
        "sl_bounds": [0.5, 3.0],
        "tp1_min": 1.0,
        "tp2_max": 8.0,
        "rr_floor": 1.0,
    },
    "phase1_scaling": {
        "strength_min": 0.8,
        "sl_strength_max": 1.2,
        "tp_strength_max": 1.4,
        "vol_factor_min": 0.75,
        "vol_factor_max": 1.25,
    },
}

# -- Pattern strengths --
PATTERN_STRENGTHS = {
    "bullish_engulfing": 15,
    "bearish_engulfing": 15,
    "morning_star": 15,
    "evening_star": 15,
    "three_white_soldiers": 15,
    "three_black_crows": 15,
    "marubozu": 13,
    "hammer": 12,
    "piercing_line": 12,
    "dark_cloud_cover": 12,
    "inverted_hammer": 10,
    "doji": 8,
    "spinning_top": 5,
}

# -- Performance tracker --
PERFORMANCE_TRACKER = {
    "optimization_params": {
        "min_signals": 40,
        "window_size": 100,
        "trigger_interval": 10,
    },
    "guardrails": {
        "sl_range": [0.8, 2.5],
        "tp1_range": [1.0, 4.0],
        "tp2_range": [2.0, 6.0],
        "max_sl_adj": 0.3,
        "max_tp_adj": 0.5,
    },
}


def get_engine_constants() -> dict:
    """Return all hardcoded engine constants as a nested dict.

    Used by GET /api/engine/parameters to serve the full parameter tree.
    Each leaf is wrapped as {"value": ..., "source": "hardcoded"}.
    """

    def _wrap(d):
        """Recursively wrap leaf values with source annotation.

        Dicts are treated as branches and recursed into.
        Non-dict values (int, float, list, str) become leaves.
        """
        if isinstance(d, dict):
            return {k: _wrap(v) for k, v in d.items()}
        return {"value": d, "source": "hardcoded"}

    return {
        "technical": {
            "indicator_periods": _wrap(INDICATOR_PERIODS),
            "sigmoid_params": _wrap(SIGMOID_PARAMS),
        },
        "order_flow": {
            "max_scores": _wrap(ORDER_FLOW["max_scores"]),
            "sigmoid_steepnesses": _wrap(ORDER_FLOW["sigmoid_steepnesses"]),
            "regime_params": _wrap({
                "trending_floor": ORDER_FLOW["trending_floor"],
                "roc_threshold": ORDER_FLOW["roc_threshold"],
                "roc_steepness": ORDER_FLOW["roc_steepness"],
                "ls_roc_scale": ORDER_FLOW["ls_roc_scale"],
                "recent_window": ORDER_FLOW["recent_window"],
                "baseline_window": ORDER_FLOW["baseline_window"],
            }),
        },
        "onchain": {
            "btc_profile": _wrap(ONCHAIN_PROFILES["btc"]),
            "eth_profile": _wrap(ONCHAIN_PROFILES["eth"]),
        },
        "levels": {
            "atr_defaults": _wrap(LEVEL_DEFAULTS["atr_defaults"]),
            "atr_guardrails": _wrap(LEVEL_DEFAULTS["atr_guardrails"]),
            "phase1_scaling": _wrap(LEVEL_DEFAULTS["phase1_scaling"]),
        },
        "patterns": {
            "strengths": _wrap(PATTERN_STRENGTHS),
        },
        "performance_tracker": {
            "optimization_params": _wrap(PERFORMANCE_TRACKER["optimization_params"]),
            "guardrails": _wrap(PERFORMANCE_TRACKER["guardrails"]),
        },
    }
