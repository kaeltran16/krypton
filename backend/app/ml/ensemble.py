"""ML + LLM ensemble decision logic."""

# Default minimum ML confidence to emit any signal
DEFAULT_MIN_CONFIDENCE = 0.65


def compute_ensemble_signal(
    ml_prediction: dict,
    llm_response: dict | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> dict:
    """Combine ML model prediction with LLM gate opinion.

    Args:
        ml_prediction: dict with direction, confidence, sl_atr, tp1_atr, tp2_atr.
        llm_response: dict with opinion (confirm/caution/contradict) and
                      confidence (HIGH/MEDIUM/LOW). None if LLM unavailable.

    Returns:
        dict with: emit (bool), direction, confidence, sl_atr, tp1_atr, tp2_atr,
                   position_scale (0-1 multiplier for position sizing).
    """
    direction = ml_prediction["direction"]
    confidence = ml_prediction["confidence"]
    sl_atr = ml_prediction["sl_atr"]
    tp1_atr = ml_prediction["tp1_atr"]
    tp2_atr = ml_prediction["tp2_atr"]

    # No signal if NEUTRAL or low confidence
    if direction == "NEUTRAL" or confidence < min_confidence:
        return {"emit": False, "direction": direction, "confidence": confidence,
                "sl_atr": sl_atr, "tp1_atr": tp1_atr, "tp2_atr": tp2_atr,
                "position_scale": 0.0}

    position_scale = 1.0

    if llm_response is None:
        # No LLM available — emit with reduced confidence
        position_scale = 0.7
    elif llm_response["opinion"] == "contradict":
        # Hard veto
        return {"emit": False, "direction": direction, "confidence": confidence,
                "sl_atr": sl_atr, "tp1_atr": tp1_atr, "tp2_atr": tp2_atr,
                "position_scale": 0.0}
    elif llm_response["opinion"] == "caution":
        # Tighten SL, reduce position
        sl_atr = sl_atr * 0.8
        position_scale = 0.6
    elif llm_response["opinion"] == "confirm":
        # Full agreement
        llm_confidence_map = {"HIGH": 1.0, "MEDIUM": 0.85, "LOW": 0.7}
        position_scale = llm_confidence_map.get(llm_response.get("confidence", "MEDIUM"), 0.85)

    return {
        "emit": True,
        "direction": direction,
        "confidence": confidence,
        "sl_atr": sl_atr,
        "tp1_atr": tp1_atr,
        "tp2_atr": tp2_atr,
        "position_scale": position_scale,
    }
