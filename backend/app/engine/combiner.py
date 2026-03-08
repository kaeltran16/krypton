from app.engine.models import LLMResponse

CONFIDENCE_MULTIPLIER = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.3}


def compute_preliminary_score(
    technical_score: int,
    order_flow_score: int,
    tech_weight: float = 0.50,
    flow_weight: float = 0.25,
    onchain_score: int = 0,
    onchain_weight: float = 0.25,
) -> int:
    total = tech_weight + flow_weight + onchain_weight
    if abs(total - 1.0) > 0.01:
        tech_weight, flow_weight, onchain_weight = (
            tech_weight / total, flow_weight / total, onchain_weight / total,
        )
    return round(
        technical_score * tech_weight
        + order_flow_score * flow_weight
        + onchain_score * onchain_weight
    )


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
) -> dict:
    if llm_levels and _validate_llm_levels(direction, llm_levels):
        return llm_levels

    if direction == "LONG":
        return {
            "entry": current_price,
            "stop_loss": current_price - 1.5 * atr,
            "take_profit_1": current_price + 2.0 * atr,
            "take_profit_2": current_price + 3.0 * atr,
        }
    else:
        return {
            "entry": current_price,
            "stop_loss": current_price + 1.5 * atr,
            "take_profit_1": current_price - 2.0 * atr,
            "take_profit_2": current_price - 3.0 * atr,
        }
