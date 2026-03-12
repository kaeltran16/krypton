from app.engine.models import LLMResponse

CONFIDENCE_MULTIPLIER = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.3}


def compute_preliminary_score(
    technical_score: int,
    order_flow_score: int,
    tech_weight: float = 0.40,
    flow_weight: float = 0.22,
    onchain_score: int = 0,
    onchain_weight: float = 0.23,
    pattern_score: int = 0,
    pattern_weight: float = 0.15,
) -> int:
    total = tech_weight + flow_weight + onchain_weight + pattern_weight
    if abs(total - 1.0) > 0.01:
        tech_weight, flow_weight, onchain_weight, pattern_weight = (
            tech_weight / total, flow_weight / total,
            onchain_weight / total, pattern_weight / total,
        )
    return round(
        technical_score * tech_weight
        + order_flow_score * flow_weight
        + onchain_score * onchain_weight
        + pattern_score * pattern_weight
    )


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


def compute_final_score(
    preliminary_score: int,
    llm_response: LLMResponse | None,
) -> int:
    if llm_response is None:
        return preliminary_score

    multiplier = CONFIDENCE_MULTIPLIER.get(llm_response.confidence, 0.5)

    if llm_response.opinion == "confirm":
        final = preliminary_score + 20 * multiplier
    elif llm_response.opinion == "caution":
        final = preliminary_score - 15 * multiplier
    else:  # contradict
        final = max(min(preliminary_score, 40), -40)

    return max(min(round(final), 100), -100)


def _validate_llm_levels(direction: str, levels: dict) -> bool:
    """Sanity-check that LLM levels make directional sense."""
    if direction == "LONG":
        return levels["stop_loss"] < levels["entry"] < levels["take_profit_1"] < levels["take_profit_2"]
    return levels["stop_loss"] > levels["entry"] > levels["take_profit_1"] > levels["take_profit_2"]


def calculate_levels(
    direction: str,
    current_price: float,
    atr: float,
    llm_levels: dict | None = None,
    ml_atr_multiples: dict | None = None,
    llm_opinion: str | None = None,
    sl_bounds: tuple[float, float] = (0.5, 3.0),
    tp1_min_atr: float = 1.0,
    tp2_max_atr: float = 8.0,
    rr_floor: float = 1.0,
    caution_sl_factor: float = 0.8,
) -> dict:
    # Priority 1: LLM explicit levels (if validated)
    if llm_levels and _validate_llm_levels(direction, llm_levels):
        return llm_levels

    # Priority 2: ML regression multiples (clamped to safety bounds)
    if ml_atr_multiples is not None:
        sl_atr = ml_atr_multiples["sl_atr"]
        tp1_atr = ml_atr_multiples["tp1_atr"]
        tp2_atr = ml_atr_multiples["tp2_atr"]

        # Clamp SL to bounds
        sl_atr = max(sl_bounds[0], min(sl_atr, sl_bounds[1]))

        # Clamp TP1 minimum
        tp1_atr = max(tp1_min_atr, tp1_atr)

        # TP2 minimum: TP1 * 1.2
        tp2_atr = max(tp1_atr * 1.2, tp2_atr)

        # TP2 maximum
        tp2_atr = min(tp2_max_atr, tp2_atr)

        # Risk/reward floor: TP1/SL >= rr_floor
        if sl_atr > 0 and tp1_atr / sl_atr < rr_floor:
            tp1_atr = sl_atr * rr_floor

        # Caution SL tightening (only when not using LLM explicit levels)
        if llm_opinion == "caution":
            sl_atr = sl_atr * caution_sl_factor

    else:
        # Priority 3: ATR defaults
        sl_atr = 1.5
        tp1_atr = 2.0
        tp2_atr = 3.0

        # Caution SL tightening for ATR defaults too
        if llm_opinion == "caution":
            sl_atr = sl_atr * caution_sl_factor

    sign = 1 if direction == "LONG" else -1
    return {
        "entry": current_price,
        "stop_loss": current_price - sign * sl_atr * atr,
        "take_profit_1": current_price + sign * tp1_atr * atr,
        "take_profit_2": current_price + sign * tp2_atr * atr,
    }
