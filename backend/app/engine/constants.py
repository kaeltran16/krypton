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
    "bb_width_percentile_window": 100,
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
    "max_scores": {"funding": 30, "oi": 20, "ls_ratio": 30, "cvd": 20},
    "sigmoid_steepnesses": {"funding": 400, "oi": 20, "ls_ratio": 6, "cvd": 3},
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
    "hanging_man": 12,
    "piercing_line": 12,
    "dark_cloud_cover": 12,
    "inverted_hammer": 10,
    "shooting_star": 10,
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

# -- Mean-reversion pressure (exhaustion-aware scoring) --
MR_PRESSURE = {
    "rsi_offset": 10,
    "rsi_range": 30,
    "bb_offset": 0.2,
    "bb_range": 0.3,
    "max_cap_shift": 18,
    "confluence_dampening": 0.7,
    "mr_llm_trigger": 0.30,
}

VOL_MULTIPLIER = {
    "obv_weight": 0.6,
}


PARAMETER_DESCRIPTIONS: dict[str, dict[str, str]] = {
    # ── Blending / Source Weights ──
    "traditional": {
        "description": "Weight given to technical indicator scores (ADX, RSI, BB, OBV, volume) in the final blend",
        "pipeline_stage": "Combiner -> Source Blending",
        "range": "0.0-1.0 — all source weights must sum to 1.0",
    },
    "flow": {
        "description": "Weight given to order flow scores (funding rate, open interest, long/short ratio) in the final blend",
        "pipeline_stage": "Combiner -> Source Blending",
        "range": "0.0-1.0 — all source weights must sum to 1.0",
    },
    "onchain": {
        "description": "Weight given to on-chain metric scores (netflow, whale activity, addresses) in the final blend",
        "pipeline_stage": "Combiner -> Source Blending",
        "range": "0.0-1.0 — all source weights must sum to 1.0",
    },
    "pattern": {
        "description": "Weight given to candlestick pattern scores in the final blend",
        "pipeline_stage": "Combiner -> Source Blending",
        "range": "0.0-1.0 — all source weights must sum to 1.0",
    },
    # ── Thresholds ──
    "signal_threshold": {
        "description": "Minimum absolute blended score required to emit a trading signal. Lower = more signals but lower quality",
        "pipeline_stage": "Combiner -> Signal Emission",
        "range": "20-60",
    },
    "llm_threshold": {
        "description": "Score above which LLM analysis is triggered. Scores below this skip LLM entirely. When equal to signal_threshold, LLM acts as a filter on signals that would already emit rather than promoting weak ones",
        "pipeline_stage": "Combiner -> LLM Gate",
        "range": "10-60 — set equal to signal_threshold for filter-only mode",
    },
    "ml_confidence_threshold": {
        "description": "Minimum ML model confidence required for ML predictions to blend into the score",
        "pipeline_stage": "Combiner -> ML Gate",
        "range": "0.50-0.85 — higher = only very confident ML predictions influence signals",
    },
    "ml_blend_weight": {
        "description": "How much weight the ML model's prediction gets when blended with the traditional score",
        "pipeline_stage": "Combiner -> ML Blending",
        "range": "0.0-1.0 — 0 = ignore ML, 1 = fully trust ML",
    },
    # ── Technical Indicators ──
    "adx_period": {
        "description": "Lookback period for Average Directional Index — measures trend strength",
        "pipeline_stage": "Technical Scoring -> Trend",
        "range": "7-21 — shorter = more responsive, longer = smoother",
    },
    "rsi_period": {
        "description": "Lookback period for Relative Strength Index — measures momentum",
        "pipeline_stage": "Technical Scoring -> Mean Reversion",
        "range": "7-21 — shorter = more sensitive to price swings",
    },
    "sma_period": {
        "description": "Lookback period for Simple Moving Average used as price reference",
        "pipeline_stage": "Technical Scoring -> Trend",
        "range": "10-30",
    },
    "obv_slope_window": {
        "description": "Window for computing On-Balance Volume slope — detects volume-price divergence",
        "pipeline_stage": "Technical Scoring -> Volume",
        "range": "5-15",
    },
    # ── Sigmoid Parameters ──
    "trend_strength_center": {
        "description": "ADX value at the midpoint of the trend-strength sigmoid. Below this, trend is considered weak",
        "pipeline_stage": "Technical Scoring -> Trend",
        "range": "10-35 — higher = requires stronger trend to activate",
    },
    "trend_strength_steepness": {
        "description": "How sharply the trend-strength sigmoid transitions from weak to strong trend",
        "pipeline_stage": "Technical Scoring -> Trend",
        "range": "0.05-0.50 — higher = more binary (on/off) behavior",
    },
    "vol_expansion_center": {
        "description": "Bollinger Band width percentile at the sigmoid midpoint. Determines what counts as expanded volatility",
        "pipeline_stage": "Technical Scoring -> Squeeze/Expansion",
        "range": "30-70",
    },
    "vol_expansion_steepness": {
        "description": "Steepness of the volatility expansion sigmoid curve",
        "pipeline_stage": "Technical Scoring -> Squeeze/Expansion",
        "range": "0.03-0.15",
    },
    "trend_score_steepness": {
        "description": "Steepness of the trend score sigmoid — controls how trend strength maps to score contribution",
        "pipeline_stage": "Technical Scoring -> Trend",
        "range": "0.10-0.60",
    },
    "obv_slope_steepness": {
        "description": "Steepness of the OBV slope sigmoid — controls sensitivity to volume-price divergence",
        "pipeline_stage": "Technical Scoring -> Volume",
        "range": "1-8",
    },
    "volume_ratio_steepness": {
        "description": "Steepness of the volume ratio sigmoid — controls how relative volume maps to score",
        "pipeline_stage": "Technical Scoring -> Volume",
        "range": "1.0-6.0",
    },
    # ── Mean Reversion ──
    "rsi_steepness": {
        "description": "RSI sigmoid steepness for mean reversion scoring. Higher = RSI extremes contribute more sharply",
        "pipeline_stage": "Technical Scoring -> Mean Reversion",
        "range": "0.10-0.50",
    },
    "bb_pos_steepness": {
        "description": "Bollinger Band position sigmoid steepness. Controls how proximity to bands affects mean-reversion score",
        "pipeline_stage": "Technical Scoring -> Mean Reversion",
        "range": "5.0-20.0",
    },
    "squeeze_steepness": {
        "description": "Squeeze/expansion sigmoid steepness for mean reversion context",
        "pipeline_stage": "Technical Scoring -> Squeeze/Expansion",
        "range": "0.05-0.20",
    },
    "blend_ratio": {
        "description": "RSI vs Bollinger Band weighting in mean-reversion score. 0.6 = 60% RSI, 40% BB position",
        "pipeline_stage": "Technical Scoring -> Mean Reversion",
        "range": "0.3-0.8",
    },
    # ── Order Flow ──
    "funding_max": {
        "description": "Maximum score contribution from funding rate. Caps how much extreme funding can influence the signal",
        "pipeline_stage": "Order Flow Scoring",
        "range": "15-50 — funding + oi + ls_ratio max scores must sum <= 100",
    },
    "oi_max": {
        "description": "Maximum score contribution from open interest changes",
        "pipeline_stage": "Order Flow Scoring",
        "range": "10-35",
    },
    "ls_ratio_max": {
        "description": "Maximum score contribution from long/short ratio",
        "pipeline_stage": "Order Flow Scoring",
        "range": "15-50",
    },
    "funding_steepness": {
        "description": "Sigmoid steepness for funding rate scoring. Higher = more sensitive to funding extremes",
        "pipeline_stage": "Order Flow Scoring",
        "range": "200-800",
    },
    "oi_steepness": {
        "description": "Sigmoid steepness for open interest change scoring",
        "pipeline_stage": "Order Flow Scoring",
        "range": "10-40",
    },
    "ls_ratio_steepness": {
        "description": "Sigmoid steepness for long/short ratio scoring",
        "pipeline_stage": "Order Flow Scoring",
        "range": "2-12",
    },
    "cvd_max": {
        "description": "Maximum score contribution from cumulative volume delta",
        "pipeline_stage": "Order Flow Scoring",
        "range": "10-30",
    },
    "cvd_steepness": {
        "description": "Sigmoid steepness for CVD delta scoring. Higher = more sensitive to volume imbalance",
        "pipeline_stage": "Order Flow Scoring",
        "range": "1-8",
    },
    # ── ATR / Levels ──
    "sl": {
        "description": "Default stop-loss distance as ATR multiplier. Higher = wider stop, fewer stop-outs but larger losses",
        "pipeline_stage": "Level Calculation",
        "range": "0.8-2.5 ATR multiples",
    },
    "tp1": {
        "description": "Default take-profit-1 distance as ATR multiplier. First partial exit target",
        "pipeline_stage": "Level Calculation",
        "range": "1.0-4.0 ATR multiples — must be > sl",
    },
    "tp2": {
        "description": "Default take-profit-2 distance as ATR multiplier. Full exit target",
        "pipeline_stage": "Level Calculation",
        "range": "2.0-6.0 ATR multiples — must be > tp1",
    },
    # ── Pattern Strengths ──
    "bullish_engulfing": {
        "description": "Score contribution when a bullish engulfing pattern is detected",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "bearish_engulfing": {
        "description": "Score contribution when a bearish engulfing pattern is detected",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "morning_star": {
        "description": "Score contribution for morning star reversal pattern (three-candle bullish)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "evening_star": {
        "description": "Score contribution for evening star reversal pattern (three-candle bearish)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "three_white_soldiers": {
        "description": "Score contribution for three consecutive bullish candles with higher closes",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "three_black_crows": {
        "description": "Score contribution for three consecutive bearish candles with lower closes",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "marubozu": {
        "description": "Score contribution for marubozu (full-body candle with minimal wicks)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "hammer": {
        "description": "Score contribution for hammer pattern (bullish reversal, long lower shadow)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "hanging_man": {
        "description": "Score contribution for hanging man pattern (bearish reversal after uptrend)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "piercing_line": {
        "description": "Score contribution for piercing line pattern (bullish two-candle reversal)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "dark_cloud_cover": {
        "description": "Score contribution for dark cloud cover (bearish two-candle reversal)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "inverted_hammer": {
        "description": "Score contribution for inverted hammer (potential bullish reversal)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "shooting_star": {
        "description": "Score contribution for shooting star (bearish reversal, long upper shadow)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "doji": {
        "description": "Score contribution for doji (indecision, nearly equal open/close)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    "spinning_top": {
        "description": "Score contribution for spinning top (small body, indecision)",
        "pipeline_stage": "Pattern Scoring",
        "range": "3-25",
    },
    # ── LLM Factor Weights ──
    "support_proximity": {
        "description": "LLM factor weight for price proximity to support level",
        "pipeline_stage": "LLM Gate -> Structure Factors",
        "range": "2-10",
    },
    "resistance_proximity": {
        "description": "LLM factor weight for price proximity to resistance level",
        "pipeline_stage": "LLM Gate -> Structure Factors",
        "range": "2-10",
    },
    "level_breakout": {
        "description": "LLM factor weight for key level breakout detection",
        "pipeline_stage": "LLM Gate -> Structure Factors",
        "range": "3-12",
    },
    "htf_alignment": {
        "description": "LLM factor weight for higher-timeframe trend alignment",
        "pipeline_stage": "LLM Gate -> Structure Factors",
        "range": "3-10",
    },
    "rsi_divergence": {
        "description": "LLM factor weight for RSI divergence with price",
        "pipeline_stage": "LLM Gate -> Momentum Factors",
        "range": "3-10",
    },
    "volume_divergence": {
        "description": "LLM factor weight for volume divergence with price trend",
        "pipeline_stage": "LLM Gate -> Momentum Factors",
        "range": "2-10",
    },
    "macd_divergence": {
        "description": "LLM factor weight for MACD divergence with price",
        "pipeline_stage": "LLM Gate -> Momentum Factors",
        "range": "2-10",
    },
    "volume_exhaustion": {
        "description": "LLM factor weight for volume exhaustion signals",
        "pipeline_stage": "LLM Gate -> Exhaustion Factors",
        "range": "2-8",
    },
    "funding_extreme": {
        "description": "LLM factor weight for extreme funding rate conditions",
        "pipeline_stage": "LLM Gate -> Exhaustion Factors",
        "range": "2-8",
    },
    "crowded_positioning": {
        "description": "LLM factor weight for crowded market positioning",
        "pipeline_stage": "LLM Gate -> Exhaustion Factors",
        "range": "2-8",
    },
    "pattern_confirmation": {
        "description": "LLM factor weight for candlestick pattern confirmation",
        "pipeline_stage": "LLM Gate -> Event Factors",
        "range": "2-8",
    },
    "news_catalyst": {
        "description": "LLM factor weight for news catalyst presence",
        "pipeline_stage": "LLM Gate -> Event Factors",
        "range": "3-10",
    },
    "factor_cap": {
        "description": "Maximum total LLM factor contribution to the final score. Caps LLM influence regardless of individual factor weights",
        "pipeline_stage": "LLM Gate",
        "range": "20-50",
    },
    # ── On-Chain (BTC) ──
    "btc_netflow_max": {
        "description": "Max on-chain score from BTC exchange netflow. Outflow = bullish (accumulation)",
        "pipeline_stage": "On-Chain Scoring -> BTC",
        "range": "5-50",
    },
    "btc_whale_max": {
        "description": "Max on-chain score from BTC whale transaction activity",
        "pipeline_stage": "On-Chain Scoring -> BTC",
        "range": "5-50",
    },
    "btc_addresses_max": {
        "description": "Max on-chain score from BTC active address growth",
        "pipeline_stage": "On-Chain Scoring -> BTC",
        "range": "5-50",
    },
    "btc_nupl_max": {
        "description": "Max on-chain score from BTC Net Unrealized Profit/Loss (contrarian)",
        "pipeline_stage": "On-Chain Scoring -> BTC",
        "range": "5-50",
    },
    "btc_hashrate_max": {
        "description": "Max on-chain score from BTC hashrate trend (rising = bullish)",
        "pipeline_stage": "On-Chain Scoring -> BTC",
        "range": "5-50",
    },
    # ── On-Chain (ETH) ──
    "eth_netflow_max": {
        "description": "Max on-chain score from ETH exchange netflow",
        "pipeline_stage": "On-Chain Scoring -> ETH",
        "range": "5-50",
    },
    "eth_whale_max": {
        "description": "Max on-chain score from ETH whale transaction activity",
        "pipeline_stage": "On-Chain Scoring -> ETH",
        "range": "5-50",
    },
    "eth_addresses_max": {
        "description": "Max on-chain score from ETH active address growth",
        "pipeline_stage": "On-Chain Scoring -> ETH",
        "range": "5-50",
    },
    "eth_staking_max": {
        "description": "Max on-chain score from ETH staking deposits (deposits = bullish)",
        "pipeline_stage": "On-Chain Scoring -> ETH",
        "range": "5-50",
    },
    "eth_gas_max": {
        "description": "Max on-chain score from ETH gas price trend (rising = network activity)",
        "pipeline_stage": "On-Chain Scoring -> ETH",
        "range": "5-50",
    },
    # ── Regime Caps (per-regime inner scoring caps) ──
    "trend_cap": {
        "description": "Maximum score contribution from trend-following indicators within this regime",
        "pipeline_stage": "Regime Detection -> Inner Caps",
        "range": "10-45 — all four caps must sum to 100 per regime",
    },
    "mean_rev_cap": {
        "description": "Maximum score contribution from mean-reversion indicators within this regime",
        "pipeline_stage": "Regime Detection -> Inner Caps",
        "range": "10-45",
    },
    "squeeze_cap": {
        "description": "Maximum score contribution from squeeze/expansion detection within this regime",
        "pipeline_stage": "Regime Detection -> Inner Caps",
        "range": "10-45",
    },
    "volume_cap": {
        "description": "Defines the volume confirmation multiplier amplitude. A value of 28 creates a multiplier range of 0.72x-1.28x applied to the directional score",
        "pipeline_stage": "Regime Detection -> Inner Caps",
        "range": "10-45 — larger values create more aggressive volume confirmation/contradiction",
    },
    # ── Regime Outer Weights ──
    "tech_weight": {
        "description": "Weight given to technical score within this regime's outer blend",
        "pipeline_stage": "Regime Detection -> Outer Weights",
        "range": "0.10-0.50 — all four weights must sum to 1.0 per regime",
    },
    "flow_weight": {
        "description": "Weight given to order flow score within this regime's outer blend",
        "pipeline_stage": "Regime Detection -> Outer Weights",
        "range": "0.10-0.50",
    },
    "onchain_weight": {
        "description": "Weight given to on-chain score within this regime's outer blend",
        "pipeline_stage": "Regime Detection -> Outer Weights",
        "range": "0.10-0.50",
    },
    "pattern_weight": {
        "description": "Weight given to pattern score within this regime's outer blend",
        "pipeline_stage": "Regime Detection -> Outer Weights",
        "range": "0.10-0.50",
    },
    # ── Confluence ──
    "confluence_max_score": {
        "description": "Maximum score bonus from multi-timeframe trend alignment",
        "pipeline_stage": "Confluence Scoring",
        "range": "5-25",
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
            "mr_pressure": _wrap(MR_PRESSURE),
            "vol_multiplier": _wrap(VOL_MULTIPLIER),
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
