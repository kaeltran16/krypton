"""Multi-timeframe confluence scoring and constants."""

from app.engine.constants import CONFLUENCE
from app.engine.scoring import sigmoid_scale

TIMEFRAME_PARENT = {"15m": "1h", "1h": "4h", "4h": "1D"}

CONFLUENCE_ONLY_TIMEFRAMES = {"1D"}

# TTL = 2x the timeframe period in seconds
TIMEFRAME_CACHE_TTL = {"15m": 1800, "1h": 7200, "4h": 28800, "1D": 172800}

# Period in hours, derived from cache TTL (TTL = 2x period)
TIMEFRAME_PERIOD_HOURS = {tf: ttl // 7200 for tf, ttl in TIMEFRAME_CACHE_TTL.items()}

# multi-level ancestor lookup
TIMEFRAME_ANCESTORS = {
    "15m": ["1h", "4h", "1D"],
    "1h": ["4h", "1D"],
    "4h": ["1D"],
}

MAX_POSSIBLE_LEVELS = {tf: len(ancestors) for tf, ancestors in TIMEFRAME_ANCESTORS.items()}

# positional level weights: index 0 = immediate parent, 1 = grandparent, 2 = great-grandparent
DEFAULT_LEVEL_WEIGHTS = [
    CONFLUENCE["level_weights"]["immediate"],
    CONFLUENCE["level_weights"]["grandparent"],
    CONFLUENCE["level_weights"]["great_grandparent"],
]


def _sign(x: float) -> float:
    if x > 0:
        return 1.0
    if x < 0:
        return -1.0
    return 0.0


def _compute_trend_alignment(
    child_trend_score: float,
    parent: dict,
    adx_strength_center: float,
    trend_alignment_steepness: float,
    adx_conviction_ratio: float,
) -> float:
    """Compute alignment for a trend-following child against one parent.

    Returns value in [-1, +1].
    """
    parent_trend_score = parent.get("trend_score", 0)
    parent_adx = parent.get("adx", 0)
    parent_trend_conviction = parent.get("trend_conviction", 0)

    direction_match = _sign(child_trend_score) * _sign(parent_trend_score)
    parent_strength = sigmoid_scale(
        parent_adx, center=adx_strength_center, steepness=trend_alignment_steepness
    )
    conviction_bonus = parent_trend_conviction

    return direction_match * parent_strength * (
        adx_conviction_ratio + (1 - adx_conviction_ratio) * conviction_bonus
    )


def _compute_mr_alignment(
    child_mr_score: float,
    parent: dict,
    mr_penalty_factor: float,
) -> float:
    """Compute alignment for a mean-reverting child against one parent.

    Returns value in [-1, +1].
    """
    parent_regime = parent.get("regime", {})
    parent_mr_score = parent.get("mean_rev_score", 0)
    parent_trend_score = parent.get("trend_score", 0)

    ranging_support = (
        parent_regime.get("ranging", 0)
        * _sign(child_mr_score)
        * _sign(parent_mr_score)
    )
    trend_opposition = (
        parent_regime.get("trending", 0)
        * _sign(child_mr_score)
        * _sign(parent_trend_score)
    )

    raw = ranging_support - mr_penalty_factor * trend_opposition
    return max(-1.0, min(1.0, raw))


def compute_confluence_score(
    child_indicators: dict,
    parent_cache_list: list[dict | None],
    timeframe: str,
    level_weight_1: float | None = None,
    level_weight_2: float | None = None,
    trend_alignment_steepness: float | None = None,
    adx_strength_center: float | None = None,
    adx_conviction_ratio: float | None = None,
    mr_penalty_factor: float | None = None,
) -> dict:
    """Score multi-timeframe alignment as an independent combiner source.

    Args:
        child_indicators: Dict with trend_score, mean_rev_score, trend_conviction
            from compute_technical_score.
        parent_cache_list: List of parent indicator dicts ordered by proximity
            (immediate parent first). None entries = missing/expired cache.
        timeframe: Child timeframe string (e.g. "15m").
        level_weight_1..mr_penalty_factor: Optional overrides for tunable params.

    Returns:
        Dict with "score" (int, -100 to +100) and "confidence" (float, 0-1).
    """
    lw1 = level_weight_1 if level_weight_1 is not None else DEFAULT_LEVEL_WEIGHTS[0]
    lw2 = level_weight_2 if level_weight_2 is not None else DEFAULT_LEVEL_WEIGHTS[1]
    lw3 = max(0.0, 1.0 - lw1 - lw2)
    level_weights = [lw1, lw2, lw3]

    steepness = trend_alignment_steepness if trend_alignment_steepness is not None else CONFLUENCE["trend_alignment_steepness"]
    center = adx_strength_center if adx_strength_center is not None else CONFLUENCE["adx_strength_center"]
    conv_ratio = adx_conviction_ratio if adx_conviction_ratio is not None else CONFLUENCE["adx_conviction_ratio"]
    mr_pen = mr_penalty_factor if mr_penalty_factor is not None else CONFLUENCE["mr_penalty_factor"]

    child_trend_score = child_indicators.get("trend_score", 0)
    child_mr_score = child_indicators.get("mean_rev_score", 0)

    # no thesis => neutral
    if child_trend_score == 0 and child_mr_score == 0:
        return {"score": 0, "confidence": 0.0}

    # determine thesis
    is_trend = abs(child_trend_score) >= abs(child_mr_score)

    max_levels = MAX_POSSIBLE_LEVELS.get(timeframe, 0)
    if max_levels == 0:
        return {"score": 0, "confidence": 0.0}

    alignments = []
    weights = []
    convictions = []

    for i, parent in enumerate(parent_cache_list):
        if i >= max_levels:
            break
        if parent is None:
            continue

        if is_trend:
            alignment = _compute_trend_alignment(
                child_trend_score, parent, center, steepness, conv_ratio
            )
            convictions.append(parent.get("trend_conviction", 0))
        else:
            alignment = _compute_mr_alignment(child_mr_score, parent, mr_pen)
            parent_regime = parent.get("regime", {})
            convictions.append(parent_regime.get("ranging", 0))

        alignments.append(alignment)
        weights.append(level_weights[i])

    if not alignments:
        return {"score": 0, "availability": 0.0, "conviction": 0.0, "confidence": 0.0}

    # normalize weights over available levels
    total_weight = sum(weights)
    weighted_sum = sum(a * w for a, w in zip(alignments, weights))
    normalized = weighted_sum / total_weight if total_weight > 0 else 0

    score = round(normalized * 100)
    score = max(-100, min(100, score))

    available_levels = len(alignments)
    avg_conviction_val = sum(convictions) / len(convictions) if convictions else 0
    conf_availability = round(available_levels / max_levels, 4) if max_levels > 0 else 0.0
    conf_conviction_val = round(avg_conviction_val, 4)
    confidence = round(conf_availability * conf_conviction_val, 4)

    return {
        "score": score,
        "availability": conf_availability,
        "conviction": conf_conviction_val,
        "confidence": confidence,  # backward compat
    }
