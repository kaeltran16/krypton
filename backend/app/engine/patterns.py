"""Candlestick pattern detection and scoring."""

from __future__ import annotations

import pandas as pd

from app.engine.constants import PATTERN_BOOST_DEFAULTS
from app.engine.scoring import sigmoid_score, sigmoid_scale


def _body(row) -> float:
    return abs(row["close"] - row["open"])


def _upper_shadow(row) -> float:
    return row["high"] - max(row["close"], row["open"])


def _lower_shadow(row) -> float:
    return min(row["close"], row["open"]) - row["low"]


def _is_bullish(row) -> bool:
    return row["close"] > row["open"]


def _is_bearish(row) -> bool:
    return row["close"] < row["open"]


def _avg_body(df: pd.DataFrame, n: int = 10) -> float:
    bodies = (df["close"] - df["open"]).abs().tail(n)
    return float(bodies.mean()) if len(bodies) > 0 else 1.0


# ---------------------------------------------------------------------------
# Single-candle patterns
# ---------------------------------------------------------------------------

def _detect_hammer(c, avg_b: float, trend_dir: int) -> dict | None:
    body = _body(c)
    lower = _lower_shadow(c)
    upper = _upper_shadow(c)
    if body < avg_b * 0.5 and lower >= body * 2 and upper < body * 0.5:
        if trend_dir == 0:
            return None
        if trend_dir < 0:
            return {"name": "Hammer", "type": "candlestick", "bias": "bullish", "strength": 12}
        return {"name": "Hanging Man", "type": "candlestick", "bias": "bearish", "strength": 12}
    return None


def _detect_inverted_hammer(c, avg_b: float, trend_dir: int) -> dict | None:
    body = _body(c)
    upper = _upper_shadow(c)
    lower = _lower_shadow(c)
    if body < avg_b * 0.5 and upper >= body * 2 and lower < body * 0.5:
        if trend_dir == 0:
            return None
        if trend_dir < 0:
            return {"name": "Inverted Hammer", "type": "candlestick", "bias": "bullish", "strength": 10}
        return {"name": "Shooting Star", "type": "candlestick", "bias": "bearish", "strength": 10}
    return None


def _detect_doji(c, avg_b: float, trend_bias: str = "neutral") -> dict | None:
    body = _body(c)
    total = c["high"] - c["low"]
    if total > 0 and body / total < 0.1:
        return {"name": "Doji", "type": "candlestick", "bias": trend_bias, "strength": 8}
    return None


def _detect_spinning_top(c, avg_b: float, trend_bias: str = "neutral") -> dict | None:
    body = _body(c)
    upper = _upper_shadow(c)
    lower = _lower_shadow(c)
    if body < avg_b * 0.4 and upper > body * 0.5 and lower > body * 0.5:
        if body / (c["high"] - c["low"]) >= 0.1:
            return {"name": "Spinning Top", "type": "candlestick", "bias": trend_bias, "strength": 5}
    return None


def _proportional_strength(base: int, ratio: float, cap: float = 1.0) -> int:
    """Scale strength between 60%-100% of base, proportional to ratio/cap."""
    return round(base * (0.6 + 0.4 * min(ratio, cap) / cap))


def _has_exhaustion(c1, c2, c3, shadow_fn) -> bool:
    """Check if a three-candle continuation shows exhaustion."""
    bodies = [_body(c1), _body(c2), _body(c3)]
    return bodies[2] < bodies[0] * 0.8 or shadow_fn(c3) > bodies[2] * 0.5


def _detect_marubozu(c, avg_b: float) -> dict | None:
    body = _body(c)
    upper = _upper_shadow(c)
    lower = _lower_shadow(c)
    total = c["high"] - c["low"]
    if total > 0 and body / total > 0.9 and body > avg_b * 1.2:
        bias = "bullish" if _is_bullish(c) else "bearish"
        return {"name": "Marubozu", "type": "candlestick", "bias": bias, "strength": 13}
    return None


# ---------------------------------------------------------------------------
# Two-candle patterns
# ---------------------------------------------------------------------------

def _detect_bullish_engulfing(prev, curr) -> dict | None:
    if _is_bearish(prev) and _is_bullish(curr):
        if curr["open"] <= prev["close"] and curr["close"] >= prev["open"]:
            if _body(curr) > _body(prev):
                strength = _proportional_strength(15, _body(curr) / _body(prev), cap=2.5)
                return {"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": strength}
    return None


def _detect_bearish_engulfing(prev, curr) -> dict | None:
    if _is_bullish(prev) and _is_bearish(curr):
        if curr["open"] >= prev["close"] and curr["close"] <= prev["open"]:
            if _body(curr) > _body(prev):
                strength = _proportional_strength(15, _body(curr) / _body(prev), cap=2.5)
                return {"name": "Bearish Engulfing", "type": "candlestick", "bias": "bearish", "strength": strength}
    return None


def _penetration_ratio(prev, curr) -> float:
    """How far curr's close penetrates past prev's midpoint, normalized 0..1."""
    midpoint = (prev["open"] + prev["close"]) / 2
    half_body = abs(prev["open"] - prev["close"]) / 2
    if half_body <= 0:
        return 1.0
    return min(abs(curr["close"] - midpoint) / half_body, 1.0)


def _detect_piercing_line(prev, curr) -> dict | None:
    if _is_bearish(prev) and _is_bullish(curr):
        midpoint = (prev["open"] + prev["close"]) / 2
        if curr["open"] < prev["close"] and curr["close"] > midpoint:
            strength = _proportional_strength(12, _penetration_ratio(prev, curr))
            return {"name": "Piercing Line", "type": "candlestick", "bias": "bullish", "strength": strength}
    return None


def _detect_dark_cloud_cover(prev, curr) -> dict | None:
    if _is_bullish(prev) and _is_bearish(curr):
        midpoint = (prev["open"] + prev["close"]) / 2
        if curr["open"] > prev["close"] and curr["close"] < midpoint:
            strength = _proportional_strength(12, _penetration_ratio(prev, curr))
            return {"name": "Dark Cloud Cover", "type": "candlestick", "bias": "bearish", "strength": strength}
    return None


# ---------------------------------------------------------------------------
# Three-candle patterns
# ---------------------------------------------------------------------------

def _detect_morning_star(c1, c2, c3, avg_b: float) -> dict | None:
    if _is_bearish(c1) and _is_bullish(c3):
        if _body(c2) < avg_b * 0.4:
            if c3["close"] > (c1["open"] + c1["close"]) / 2:
                return {"name": "Morning Star", "type": "candlestick", "bias": "bullish", "strength": 15}
    return None


def _detect_evening_star(c1, c2, c3, avg_b: float) -> dict | None:
    if _is_bullish(c1) and _is_bearish(c3):
        if _body(c2) < avg_b * 0.4:
            if c3["close"] < (c1["open"] + c1["close"]) / 2:
                return {"name": "Evening Star", "type": "candlestick", "bias": "bearish", "strength": 15}
    return None


def _detect_three_white_soldiers(c1, c2, c3, avg_b: float) -> dict | None:
    if _is_bullish(c1) and _is_bullish(c2) and _is_bullish(c3):
        if c2["close"] > c1["close"] and c3["close"] > c2["close"]:
            if _body(c1) > avg_b * 0.5 and _body(c2) > avg_b * 0.5 and _body(c3) > avg_b * 0.5:
                strength = round(15 * 0.6) if _has_exhaustion(c1, c2, c3, _upper_shadow) else 15
                return {"name": "Three White Soldiers", "type": "candlestick", "bias": "bullish", "strength": strength}
    return None


def _detect_three_black_crows(c1, c2, c3, avg_b: float) -> dict | None:
    if _is_bearish(c1) and _is_bearish(c2) and _is_bearish(c3):
        if c2["close"] < c1["close"] and c3["close"] < c2["close"]:
            if _body(c1) > avg_b * 0.5 and _body(c2) > avg_b * 0.5 and _body(c3) > avg_b * 0.5:
                strength = round(15 * 0.6) if _has_exhaustion(c1, c2, c3, _lower_shadow) else 15
                return {"name": "Three Black Crows", "type": "candlestick", "bias": "bearish", "strength": strength}
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_candlestick_patterns(candles: pd.DataFrame, indicator_ctx: dict | None = None) -> list[dict]:
    """Detect candlestick patterns from recent candles.

    Args:
        candles: DataFrame with columns [open, high, low, close, volume].
                 Uses last 10 rows for avg body calculation, last 3 for patterns.

    Returns:
        List of dicts: {name, type, bias, strength}.
    """
    if len(candles) < 3:
        return []

    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)

    avg_b = _avg_body(df)
    patterns: list[dict] = []

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    third = df.iloc[-3] if len(df) >= 3 else None

    # Compute trend direction for hammer-family and indecision patterns
    _has_ctx = indicator_ctx and "adx" in indicator_ctx
    _di_plus = indicator_ctx.get("di_plus", 0) if _has_ctx else 0
    _di_minus = indicator_ctx.get("di_minus", 0) if _has_ctx else 0
    _di_dir = 1 if _di_plus > _di_minus else (-1 if _di_minus > _di_plus else 0)

    if _has_ctx and indicator_ctx["adx"] >= 15:
        trend_dir = _di_dir
    elif _has_ctx:
        trend_dir = 0
    elif len(df) >= 6:
        trend_change = curr["close"] - float(df.iloc[-6]["close"])
        trend_dir = 1 if trend_change > 0 else (-1 if trend_change < 0 else 0)
    else:
        trend_dir = 0

    for detector in (_detect_hammer, _detect_inverted_hammer):
        result = detector(curr, avg_b, trend_dir)
        if result:
            patterns.append(result)

    _indecision_bias = "neutral"
    if _has_ctx and indicator_ctx["adx"] >= 15 and _di_dir != 0:
        _indecision_bias = "bearish" if _di_dir == 1 else "bullish"

    for detector in (_detect_doji, _detect_spinning_top):
        result = detector(curr, avg_b, trend_bias=_indecision_bias)
        if result:
            patterns.append(result)
    result = _detect_marubozu(curr, avg_b)
    if result:
        patterns.append(result)

    # Two-candle
    for detector in (_detect_bullish_engulfing, _detect_bearish_engulfing,
                     _detect_piercing_line, _detect_dark_cloud_cover):
        result = detector(prev, curr)
        if result:
            patterns.append(result)

    # Three-candle
    if third is not None:
        for detector in (_detect_morning_star, _detect_evening_star,
                         _detect_three_white_soldiers, _detect_three_black_crows):
            result = detector(third, prev, curr, avg_b)
            if result:
                patterns.append(result)

    return patterns


def _pattern_key(name: str) -> str:
    """Convert display name to override key: 'Bullish Engulfing' -> 'bullish_engulfing'."""
    return name.lower().replace(" ", "_")


def compute_pattern_score(
    patterns: list[dict],
    indicator_ctx: dict | None = None,
    strength_overrides: dict[str, int | float] | None = None,
    regime_trending: float | None = None,
    boost_overrides: dict[str, float] | None = None,
) -> dict:
    """Score detected candlestick patterns with contextual boosts.

    Args:
        patterns: List of detected pattern dicts with 'bias' and 'strength'.
        indicator_ctx: Dict with keys: adx, di_plus, di_minus, vol_ratio, bb_pos, close.
                       If None, no boosts are applied (base strength only).

    Returns:
        Dict with 'score' in [-100, +100] and 'confidence' in [0, 1].
    """
    if not patterns:
        return {"score": 0, "confidence": 0.0}

    if indicator_ctx is None:
        indicator_ctx = {"adx": 0, "di_plus": 0, "di_minus": 0, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 0}

    _boosts = {**PATTERN_BOOST_DEFAULTS, **(boost_overrides or {})}

    adx = indicator_ctx["adx"]
    di_plus = indicator_ctx["di_plus"]
    di_minus = indicator_ctx["di_minus"]
    vol_ratio = indicator_ctx["vol_ratio"]
    bb_pos = indicator_ctx["bb_pos"]

    # Determine ADX trend direction
    adx_bullish = di_plus > di_minus

    total = 0.0
    bull_count = 0
    bear_count = 0

    for p in patterns:
        bias = p.get("bias", "neutral")
        strength = p.get("strength", 0)
        if strength_overrides:
            strength = strength_overrides.get(_pattern_key(p.get("name", "")), strength)

        if bias == "neutral":
            continue

        if bias == "bullish":
            bull_count += 1
        else:
            bear_count += 1

        # Trend-alignment boost
        trend_boost = 1.0
        pattern_bullish = bias == "bullish"
        if regime_trending is not None:
            if pattern_bullish != adx_bullish:
                trend_boost = 1.0 + _boosts["reversal_boost"] * regime_trending
            else:
                trend_boost = 1.0 + _boosts["continuation_boost"] * regime_trending
        elif adx >= 15:
            if pattern_bullish != adx_bullish:
                trend_boost = 1.3
            elif adx >= 30:
                trend_boost = 1.2

        # Volume confirmation boost (continuous sigmoid curve)
        vol_boost = 1.0 + 0.3 * sigmoid_scale(
            vol_ratio, center=_boosts["vol_center"], steepness=_boosts["vol_steepness"]
        )

        # Level-proximity boost (continuous, min 1.0)
        raw_level_boost = 0.5 * sigmoid_score(
            abs(bb_pos - 0.5) - 0.3, center=0, steepness=10
        )
        level_boost = 1.0 + max(0, raw_level_boost)

        boosted_strength = strength * trend_boost * vol_boost * level_boost

        if bias == "bullish":
            total += boosted_strength
        else:  # bearish
            total -= boosted_strength

    non_neutral = bull_count + bear_count
    if non_neutral == 0:
        confidence = 0.0
    else:
        agreement = max(bull_count, bear_count) / non_neutral
        confidence = round(min(non_neutral / 3.0, 1.0) * agreement, 4)

    return {"score": max(min(round(total), 100), -100), "confidence": confidence}
