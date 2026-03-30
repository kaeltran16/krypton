from app.engine.models import LLMFactor, DEFAULT_FACTOR_WEIGHTS
from app.engine.constants import (
    CONVICTION_FLOOR, ML_WEIGHT_MIN, ML_WEIGHT_MAX,
    AGREEMENT_FLOOR, AGREEMENT_CEILING, LEVEL_DEFAULTS,
)


def compute_preliminary_score(
    technical_score: int,
    order_flow_score: int,
    tech_weight: float = 0.40,
    flow_weight: float = 0.22,
    onchain_score: int = 0,
    onchain_weight: float = 0.23,
    pattern_score: int = 0,
    pattern_weight: float = 0.15,
    tech_availability: float | None = None,
    tech_conviction: float | None = None,
    flow_availability: float | None = None,
    flow_conviction: float | None = None,
    onchain_availability: float | None = None,
    onchain_conviction: float | None = None,
    pattern_availability: float | None = None,
    pattern_conviction: float | None = None,
    liquidation_score: int = 0,
    liquidation_weight: float = 0.0,
    liquidation_availability: float | None = None,
    liquidation_conviction: float | None = None,
    confluence_score: int = 0,
    confluence_weight: float = 0.0,
    confluence_availability: float | None = None,
    confluence_conviction: float | None = None,
    tech_confidence: float = 0.0,
    flow_confidence: float = 0.0,
    onchain_confidence: float = 0.0,
    pattern_confidence: float = 0.0,
    liquidation_confidence: float = 0.0,
    confluence_confidence: float = 0.0,
    conviction_floor: float = CONVICTION_FLOOR,
) -> dict:
    avails = [
        tech_availability if tech_availability is not None else tech_confidence,
        flow_availability if flow_availability is not None else flow_confidence,
        onchain_availability if onchain_availability is not None else onchain_confidence,
        pattern_availability if pattern_availability is not None else pattern_confidence,
        liquidation_availability if liquidation_availability is not None else liquidation_confidence,
        confluence_availability if confluence_availability is not None else confluence_confidence,
    ]
    convictions = [
        tech_conviction if tech_conviction is not None else 1.0,
        flow_conviction if flow_conviction is not None else 1.0,
        onchain_conviction if onchain_conviction is not None else 1.0,
        pattern_conviction if pattern_conviction is not None else 1.0,
        liquidation_conviction if liquidation_conviction is not None else 1.0,
        confluence_conviction if confluence_conviction is not None else 1.0,
    ]
    base_weights = [tech_weight, flow_weight, onchain_weight, pattern_weight,
                    liquidation_weight, confluence_weight]
    scores = [technical_score, order_flow_score, onchain_score, pattern_score,
              liquidation_score, confluence_score]

    ew = [w * a for w, a in zip(base_weights, avails)]
    total = sum(ew)
    if total <= 0:
        return {"score": 0, "avg_confidence": 0.0}
    ew = [e / total for e in ew]

    scaled = [s * (conviction_floor + (1 - conviction_floor) * c)
              for s, c in zip(scores, convictions)]

    score = round(sum(sc * w for sc, w in zip(scaled, ew)))

    avg_confidence = sum(a * w for a, w in zip(avails, ew))

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
    ml_weight_min: float = ML_WEIGHT_MIN,
    ml_weight_max: float = ML_WEIGHT_MAX,
    ml_confidence_threshold: float = 0.65,
) -> int:
    """Blend indicator preliminary score with ML score using adaptive weight ramp.

    ML weight ramps linearly from ml_weight_min at threshold to ml_weight_max at 1.0.
    Returns integer -100 to +100.
    """
    if ml_confidence_threshold >= 1.0:
        return indicator_preliminary
    if (
        ml_score is not None
        and ml_confidence is not None
        and ml_confidence >= ml_confidence_threshold
    ):
        t = (ml_confidence - ml_confidence_threshold) / (1.0 - ml_confidence_threshold)
        effective_weight = ml_weight_min + (ml_weight_max - ml_weight_min) * t
        blended = indicator_preliminary * (1 - effective_weight) + ml_score * effective_weight
        return max(min(round(blended), 100), -100)
    return indicator_preliminary


def compute_agreement(indicator_preliminary: int, ml_score: float | None) -> str:
    """Determine agreement between indicators and ML prediction."""
    if ml_score is None or ml_score == 0 or indicator_preliminary == 0:
        return "neutral"
    if (indicator_preliminary > 0 and ml_score > 0) or (indicator_preliminary < 0 and ml_score < 0):
        return "agree"
    return "disagree"


def apply_agreement_factor(
    preliminary: int,
    source_scores: list[int],
    source_availabilities: list[float],
    floor: float = AGREEMENT_FLOOR,
    ceiling: float = AGREEMENT_CEILING,
) -> int:
    """Apply directional agreement bonus/penalty to preliminary score."""
    contributing = [(s, a) for s, a in zip(source_scores, source_availabilities)
                    if a > 0 and s != 0]
    if len(contributing) < 3:
        return preliminary
    positive = sum(1 for s, _ in contributing if s > 0)
    negative = sum(1 for s, _ in contributing if s < 0)
    agreement_ratio = max(positive, negative) / len(contributing)
    # Linear interpolation: floor at 50% agreement, ceiling at 100%
    multiplier = floor + (ceiling - floor) * (agreement_ratio - 0.5) / 0.5
    multiplier = max(floor, min(ceiling, multiplier))
    return max(-100, min(100, round(preliminary * multiplier)))


def compute_llm_contribution(
    factors: list[LLMFactor],
    factor_weights: dict[str, float],
    total_cap: float,
) -> int:
    total = 0.0
    for f in factors:
        weight = factor_weights.get(f.type.value, 0.0)
        sign = 1 if f.direction == "bullish" else (-1 if f.direction == "bearish" else 0)
        total += sign * weight * f.strength
    return round(max(-total_cap, min(total_cap, total)))


def compute_final_score(blended_score: int, llm_contribution: int) -> int:
    return max(-100, min(100, blended_score + llm_contribution))


def aggregate_dual_pass(
    contrib_a: int, contrib_b: int, cap: float,
) -> tuple[int, bool]:
    """Aggregate standard and devil's advocate LLM contributions.

    Returns (merged_contribution, agreed). Standard call direction is preferred
    on disagreement since it uses the primary analysis prompt.
    """
    agreed = (contrib_a >= 0) == (contrib_b >= 0) or contrib_a == 0 or contrib_b == 0

    if agreed:
        merged = (contrib_a + contrib_b) / 2
    else:
        magnitude = min(abs(contrib_a), abs(contrib_b)) / 2
        sign = 1 if contrib_a >= 0 else -1
        merged = sign * magnitude

    return round(max(-cap, min(cap, merged))), agreed


def _validate_llm_levels(direction: str, levels: dict) -> bool:
    """Sanity-check that LLM levels make directional sense."""
    if direction == "LONG":
        return levels["stop_loss"] < levels["entry"] < levels["take_profit_1"] < levels["take_profit_2"]
    return levels["stop_loss"] > levels["entry"] > levels["take_profit_1"] > levels["take_profit_2"]


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
