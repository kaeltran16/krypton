"""Candlestick pattern detection and scoring."""

from __future__ import annotations

import pandas as pd

from app.engine.scoring import sigmoid_score


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


def _detect_doji(c, avg_b: float) -> dict | None:
    body = _body(c)
    total = c["high"] - c["low"]
    if total > 0 and body / total < 0.1:
        return {"name": "Doji", "type": "candlestick", "bias": "neutral", "strength": 8}
    return None


def _detect_spinning_top(c, avg_b: float) -> dict | None:
    body = _body(c)
    upper = _upper_shadow(c)
    lower = _lower_shadow(c)
    if body < avg_b * 0.4 and upper > body * 0.5 and lower > body * 0.5:
        if body / (c["high"] - c["low"]) >= 0.1:  # not a doji
            return {"name": "Spinning Top", "type": "candlestick", "bias": "neutral", "strength": 5}
    return None


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
                return {"name": "Bullish Engulfing", "type": "candlestick", "bias": "bullish", "strength": 15}
    return None


def _detect_bearish_engulfing(prev, curr) -> dict | None:
    if _is_bullish(prev) and _is_bearish(curr):
        if curr["open"] >= prev["close"] and curr["close"] <= prev["open"]:
            if _body(curr) > _body(prev):
                return {"name": "Bearish Engulfing", "type": "candlestick", "bias": "bearish", "strength": 15}
    return None


def _detect_piercing_line(prev, curr) -> dict | None:
    if _is_bearish(prev) and _is_bullish(curr):
        midpoint = (prev["open"] + prev["close"]) / 2
        if curr["open"] < prev["close"] and curr["close"] > midpoint:
            return {"name": "Piercing Line", "type": "candlestick", "bias": "bullish", "strength": 12}
    return None


def _detect_dark_cloud_cover(prev, curr) -> dict | None:
    if _is_bullish(prev) and _is_bearish(curr):
        midpoint = (prev["open"] + prev["close"]) / 2
        if curr["open"] > prev["close"] and curr["close"] < midpoint:
            return {"name": "Dark Cloud Cover", "type": "candlestick", "bias": "bearish", "strength": 12}
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
                return {"name": "Three White Soldiers", "type": "candlestick", "bias": "bullish", "strength": 15}
    return None


def _detect_three_black_crows(c1, c2, c3, avg_b: float) -> dict | None:
    if _is_bearish(c1) and _is_bearish(c2) and _is_bearish(c3):
        if c2["close"] < c1["close"] and c3["close"] < c2["close"]:
            if _body(c1) > avg_b * 0.5 and _body(c2) > avg_b * 0.5 and _body(c3) > avg_b * 0.5:
                return {"name": "Three Black Crows", "type": "candlestick", "bias": "bearish", "strength": 15}
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_candlestick_patterns(candles: pd.DataFrame) -> list[dict]:
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

    # Compute trend direction for hammer-family patterns
    if len(df) >= 6:
        trend_change = curr["close"] - float(df.iloc[-6]["close"])
        if trend_change > 0:
            trend_dir = 1
        elif trend_change < 0:
            trend_dir = -1
        else:
            trend_dir = 0
    else:
        trend_dir = 0

    # Trend-aware single-candle (hammer family)
    for detector in (_detect_hammer, _detect_inverted_hammer):
        result = detector(curr, avg_b, trend_dir)
        if result:
            patterns.append(result)

    # Uniform single-candle (no trend context needed)
    for detector in (_detect_doji, _detect_spinning_top, _detect_marubozu):
        result = detector(curr, avg_b)
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


def compute_pattern_score(
    patterns: list[dict],
    indicator_ctx: dict | None = None,
) -> int:
    """Score detected candlestick patterns with contextual boosts.

    Args:
        patterns: List of detected pattern dicts with 'bias' and 'strength'.
        indicator_ctx: Dict with keys: adx, di_plus, di_minus, vol_ratio, bb_pos, close.
                       If None, no boosts are applied (base strength only).

    Returns:
        Score in [-100, +100].
    """
    if not patterns:
        return 0

    # When no context is provided, use neutral defaults (no boosts applied)
    if indicator_ctx is None:
        indicator_ctx = {"adx": 0, "di_plus": 0, "di_minus": 0, "vol_ratio": 1.0, "bb_pos": 0.5, "close": 0}

    adx = indicator_ctx["adx"]
    di_plus = indicator_ctx["di_plus"]
    di_minus = indicator_ctx["di_minus"]
    vol_ratio = indicator_ctx["vol_ratio"]
    bb_pos = indicator_ctx["bb_pos"]

    # Determine ADX trend direction
    adx_bullish = di_plus > di_minus

    total = 0.0

    for p in patterns:
        bias = p.get("bias", "neutral")
        strength = p.get("strength", 0)

        if bias == "neutral":
            continue

        # Trend-alignment boost
        trend_boost = 1.0
        if adx >= 15:
            pattern_bullish = bias == "bullish"
            if pattern_bullish != adx_bullish:
                # Reversal signal
                trend_boost = 1.3
            elif adx >= 30:
                # Continuation with strong trend
                trend_boost = 1.2

        # Volume confirmation boost
        vol_boost = 1.0
        if vol_ratio > 1.5:
            vol_boost = 1.3
        elif vol_ratio > 1.2:
            vol_boost = 1.15

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

    return max(min(round(total), 100), -100)
