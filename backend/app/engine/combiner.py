from app.engine.models import LLMFactor, DEFAULT_FACTOR_WEIGHTS


def compute_preliminary_score(
    technical_score: int,
    order_flow_score: int,
    tech_weight: float = 0.40,
    flow_weight: float = 0.22,
    onchain_score: int = 0,
    onchain_weight: float = 0.23,
    pattern_score: int = 0,
    pattern_weight: float = 0.15,
    tech_confidence: float = 0.5,
    flow_confidence: float = 0.5,
    onchain_confidence: float = 0.5,
    pattern_confidence: float = 0.5,
    liquidation_score: int = 0,
    liquidation_weight: float = 0.0,
    liquidation_confidence: float = 0.0,
) -> dict:
    # confidence-weight each source: effective_weight = base_weight * confidence
    ew_tech = tech_weight * tech_confidence
    ew_flow = flow_weight * flow_confidence
    ew_onchain = onchain_weight * onchain_confidence
    ew_pattern = pattern_weight * pattern_confidence
    ew_liq = liquidation_weight * liquidation_confidence
    total = ew_tech + ew_flow + ew_onchain + ew_pattern + ew_liq
    if total > 0:
        ew_tech /= total
        ew_flow /= total
        ew_onchain /= total
        ew_pattern /= total
        ew_liq /= total
    else:
        # fallback to equal weights
        ew_tech = ew_flow = ew_onchain = ew_pattern = ew_liq = 0.2
    score = round(
        technical_score * ew_tech
        + order_flow_score * ew_flow
        + onchain_score * ew_onchain
        + pattern_score * ew_pattern
        + liquidation_score * ew_liq
    )
    # weighted-average confidence (using base weights, not effective weights)
    total_w = tech_weight + flow_weight + onchain_weight + pattern_weight + liquidation_weight
    avg_confidence = (
        tech_confidence * tech_weight
        + flow_confidence * flow_weight
        + onchain_confidence * onchain_weight
        + pattern_confidence * pattern_weight
        + liquidation_confidence * liquidation_weight
    ) / total_w if total_w > 0 else 0.0
    return {"score": score, "avg_confidence": avg_confidence}


def compute_confidence_tier(avg_confidence: float) -> str:
    """Map a weighted-average confidence value to a tier label."""
    if avg_confidence >= 0.7:
        return "high"
    if avg_confidence >= 0.4:
        return "medium"
    return "low"


def blend_with_ml(
    indicator_preliminary: int,
    ml_score: float | None,
    ml_confidence: float | None,
    ml_weight: float = 0.25,
    ml_confidence_threshold: float = 0.65,
) -> int:
    """Blend indicator preliminary score with ML score.

    ML score only contributes when confidence >= threshold.
    Returns integer -100 to +100.
    """
    if (
        ml_score is not None
        and ml_confidence is not None
        and ml_confidence >= ml_confidence_threshold
    ):
        blended = indicator_preliminary * (1 - ml_weight) + ml_score * ml_weight
        return max(min(round(blended), 100), -100)
    return indicator_preliminary


def compute_agreement(indicator_preliminary: int, ml_score: float | None) -> str:
    """Determine agreement between indicators and ML prediction."""
    if ml_score is None or ml_score == 0 or indicator_preliminary == 0:
        return "neutral"
    if (indicator_preliminary > 0 and ml_score > 0) or (indicator_preliminary < 0 and ml_score < 0):
        return "agree"
    return "disagree"


def compute_llm_contribution(
    factors: list[LLMFactor],
    direction: str,
    factor_weights: dict[str, float],
    total_cap: float,
) -> int:
    total = 0.0
    for f in factors:
        weight = factor_weights.get(f.type.value, 0.0)
        aligned = (
            (f.direction == "bullish" and direction == "LONG")
            or (f.direction == "bearish" and direction == "SHORT")
        )
        sign = 1 if aligned else -1
        total += sign * weight * f.strength
    return round(max(-total_cap, min(total_cap, total)))


def compute_final_score(blended_score: int, llm_contribution: int) -> int:
    return max(-100, min(100, blended_score + llm_contribution))


def _validate_llm_levels(direction: str, levels: dict) -> bool:
    """Sanity-check that LLM levels make directional sense."""
    if direction == "LONG":
        return levels["stop_loss"] < levels["entry"] < levels["take_profit_1"] < levels["take_profit_2"]
    return levels["stop_loss"] > levels["entry"] > levels["take_profit_1"] > levels["take_profit_2"]


from app.engine.constants import LEVEL_DEFAULTS

_p1 = LEVEL_DEFAULTS["phase1_scaling"]
STRENGTH_MIN = _p1["strength_min"]
SL_STRENGTH_MAX = _p1["sl_strength_max"]
TP_STRENGTH_MAX = _p1["tp_strength_max"]
VOL_FACTOR_MIN = _p1["vol_factor_min"]
VOL_FACTOR_MAX = _p1["vol_factor_max"]


def scale_atr_multipliers(
    score: int,
    bb_width_pct: float,
    sl_base: float,
    tp1_base: float,
    tp2_base: float,
    signal_threshold: int = 40,
) -> dict:
    """Apply signal strength + volatility regime scaling to ATR multipliers.

    Returns dict with effective multipliers and individual scaling factors
    for auditability.
    """
    if signal_threshold >= 100:
        t = 0.0
    else:
        t = (abs(score) - signal_threshold) / (100 - signal_threshold)
        t = max(0.0, min(1.0, t))

    sl_strength = STRENGTH_MIN + (SL_STRENGTH_MAX - STRENGTH_MIN) * t
    tp_strength = STRENGTH_MIN + (TP_STRENGTH_MAX - STRENGTH_MIN) * t

    bb_width_pct = max(0.0, min(100.0, bb_width_pct))
    vol_factor = VOL_FACTOR_MIN + (VOL_FACTOR_MAX - VOL_FACTOR_MIN) * (bb_width_pct / 100)

    return {
        "sl_atr": sl_base * sl_strength * vol_factor,
        "tp1_atr": tp1_base * tp_strength * vol_factor,
        "tp2_atr": tp2_base * tp_strength * vol_factor,
        "sl_strength_factor": round(sl_strength, 4),
        "tp_strength_factor": round(tp_strength, 4),
        "vol_factor": round(vol_factor, 4),
    }


def calculate_levels(
    direction: str,
    current_price: float,
    atr: float,
    llm_levels: dict | None = None,
    ml_atr_multiples: dict | None = None,
    llm_contribution: int = 0,
    sl_bounds: tuple[float, float] = (0.5, 3.0),
    tp1_min_atr: float = 1.0,
    tp2_max_atr: float = 8.0,
    rr_floor: float = 1.0,
    sl_atr_default: float = 1.5,
    tp1_atr_default: float = 2.0,
    tp2_atr_default: float = 3.0,
) -> dict:
    # Priority 1: ML regression multiples
    if ml_atr_multiples is not None:
        sl_atr = ml_atr_multiples["sl_atr"]
        tp1_atr = ml_atr_multiples["tp1_atr"]
        tp2_atr = ml_atr_multiples["tp2_atr"]
        levels_source = "ml"
    elif llm_levels and llm_contribution >= 0 and _validate_llm_levels(direction, llm_levels):
        # Priority 2: LLM explicit levels (only if contribution non-negative)
        return {**llm_levels, "levels_source": "llm"}
    else:
        # Priority 3: ATR defaults
        sl_atr = sl_atr_default
        tp1_atr = tp1_atr_default
        tp2_atr = tp2_atr_default
        levels_source = "atr_default"

    # Shared guardrails
    sl_atr = max(sl_bounds[0], min(sl_atr, sl_bounds[1]))
    tp1_atr = max(tp1_min_atr, tp1_atr)
    tp2_atr = max(tp1_atr * 1.2, tp2_atr)
    tp2_atr = min(tp2_max_atr, tp2_atr)
    if sl_atr > 0 and tp1_atr / sl_atr < rr_floor:
        tp1_atr = sl_atr * rr_floor

    sign = 1 if direction == "LONG" else -1
    return {
        "entry": current_price,
        "stop_loss": current_price - sign * sl_atr * atr,
        "take_profit_1": current_price + sign * tp1_atr * atr,
        "take_profit_2": current_price + sign * tp2_atr * atr,
        "levels_source": levels_source,
    }
