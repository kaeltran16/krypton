"""Multi-timeframe confluence scoring and constants."""

from app.engine.scoring import sigmoid_scale

TIMEFRAME_PARENT = {"15m": "1h", "1h": "4h", "4h": "1D"}

CONFLUENCE_ONLY_TIMEFRAMES = {"1D"}

# TTL = 2x the timeframe period in seconds
TIMEFRAME_CACHE_TTL = {"15m": 1800, "1h": 7200, "4h": 28800, "1D": 172800}

# Period in hours, derived from cache TTL (TTL = 2x period)
TIMEFRAME_PERIOD_HOURS = {tf: ttl // 7200 for tf, ttl in TIMEFRAME_CACHE_TTL.items()}


def di_direction(di_plus: float, di_minus: float) -> int:
    """Return +1 if DI+ > DI-, else -1."""
    return 1 if di_plus > di_minus else -1


def compute_confluence_score(
    child_direction: int,
    parent_indicators: dict | None,
    max_score: int = 15,
) -> int:
    """Score alignment between child and parent timeframe trends.

    Args:
        child_direction: +1 if child DI+ > DI-, -1 otherwise.
        parent_indicators: Dict with adx, di_plus, di_minus from parent TF, or None.
        max_score: Maximum absolute score.

    Returns:
        Integer in [-max_score, +max_score]. 0 if parent data unavailable.
    """
    if parent_indicators is None:
        return 0

    di_plus = parent_indicators.get("di_plus", 0)
    di_minus = parent_indicators.get("di_minus", 0)

    if di_plus == di_minus:
        return 0

    parent_direction = di_direction(di_plus, di_minus)
    adx = parent_indicators.get("adx", 0)
    parent_strength = sigmoid_scale(adx, center=15, steepness=0.30)

    if child_direction == parent_direction:
        raw = max_score * parent_strength
    else:
        raw = -max_score * parent_strength

    return round(max(min(raw, max_score), -max_score))
