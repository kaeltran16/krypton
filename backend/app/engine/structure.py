"""Structure-aware SL/TP placement.

Detects support/resistance zones from swing pivots, then snaps
SL/TP levels to nearby technical structure (S/R zones, Bollinger Bands,
EMAs). Runs as post-processing on levels from any source (ML, LLM, ATR).
"""

from __future__ import annotations

import pandas as pd


def detect_support_resistance(
    candles: pd.DataFrame,
    atr: float,
    lookback: int = 3,
    min_touches: int = 2,
    max_levels: int = 5,
) -> list[dict]:
    """Detect S/R zones from swing pivot clustering.

    Port of frontend detectSupportResistance() from indicators.ts.

    Returns list of {"price": float, "strength": int, "type": "support"|"resistance"}
    sorted by strength descending.
    """
    high = candles["high"].astype(float).values
    low = candles["low"].astype(float).values
    n = len(candles)

    if n < lookback * 2 + 1:
        return []

    current_price = float(candles["close"].iloc[-1])
    tolerance = atr * 0.5

    # Collect swing highs and lows
    pivots: list[dict] = []

    for i in range(lookback, n - lookback):
        is_high = True
        is_low = True

        for j in range(1, lookback + 1):
            if high[i] <= high[i - j] or high[i] <= high[i + j]:
                is_high = False
            if low[i] >= low[i - j] or low[i] >= low[i + j]:
                is_low = False

        if is_high:
            pivots.append({"price": float(high[i]), "type": "high"})
        if is_low:
            pivots.append({"price": float(low[i]), "type": "low"})

    if not pivots:
        return []

    # Cluster nearby pivots into zones
    sorted_pivots = sorted(pivots, key=lambda p: p["price"])
    zones: list[dict] = []

    for p in sorted_pivots:
        merged = False
        for z in zones:
            if abs(z["price"] - p["price"]) <= tolerance:
                # Weighted average to refine zone center
                z["price"] = (z["price"] * z["touches"] + p["price"]) / (z["touches"] + 1)
                z["touches"] += 1
                merged = True
                break
        if not merged:
            zones.append({"price": p["price"], "touches": 1})

    # Filter for minimum touches, sort by strength
    valid = [z for z in zones if z["touches"] >= min_touches]
    valid.sort(key=lambda z: z["touches"], reverse=True)
    top = valid[:max_levels]

    return [
        {
            "price": z["price"],
            "strength": z["touches"],
            "type": "support" if z["price"] < current_price else "resistance",
        }
        for z in top
    ]


def collect_structure_levels(
    candles: pd.DataFrame,
    indicators: dict,
    atr: float,
    liquidation_clusters: list[dict] | None = None,
) -> list[dict]:
    """Collect all technical structure levels from available data.

    Combines S/R zones from pivot detection with dynamic levels from
    Bollinger Bands and EMAs.

    Returns list of {"price": float, "label": str, "strength": int}
    sorted by price ascending.
    """
    levels: list[dict] = []

    # 1. Swing-based S/R zones
    sr_zones = detect_support_resistance(candles, atr)
    for z in sr_zones:
        levels.append({
            "price": z["price"],
            "label": z["type"],
            "strength": z["strength"],
        })

    # 2. Bollinger Bands
    bb_upper = indicators.get("bb_upper")
    bb_lower = indicators.get("bb_lower")
    if bb_upper is not None:
        levels.append({"price": bb_upper, "label": "bb_upper", "strength": 2})
    if bb_lower is not None:
        levels.append({"price": bb_lower, "label": "bb_lower", "strength": 2})

    # BB midline (SMA20) — derive from BB if available
    if bb_upper is not None and bb_lower is not None:
        levels.append({
            "price": (bb_upper + bb_lower) / 2,
            "label": "sma_20",
            "strength": 1,
        })

    # 3. EMAs
    for key, strength in [("ema_50", 3), ("ema_21", 2), ("ema_9", 1)]:
        val = indicators.get(key)
        if val is not None:
            levels.append({"price": val, "label": key, "strength": strength})

    # 4. Liquidation clusters as S/R zones
    if liquidation_clusters:
        for cluster in liquidation_clusters:
            levels.append({
                "price": cluster["price"],
                "label": "liq_cluster",
                "strength": min(10, int(cluster["volume"] / 100)),
            })

    levels.sort(key=lambda lv: lv["price"])
    return levels


def snap_levels_to_structure(
    levels: dict,
    structure: list[dict],
    direction: str,
    atr: float,
    buffer_atr: float = 0.15,
    max_snap_atr: float = 1.5,
    sl_min_atr: float = 1.0,
    sl_max_atr: float = 3.5,
) -> tuple[dict, dict]:
    """Snap SL/TP levels to nearby technical structure.

    Post-processes levels from any source (ML, LLM, ATR default) by
    adjusting them to sit at meaningful technical structure when nearby.

    Args:
        levels: dict with entry, stop_loss, take_profit_1, take_profit_2, levels_source
        structure: sorted list from collect_structure_levels()
        direction: "LONG" or "SHORT"
        atr: current ATR value
        buffer_atr: ATR fraction to place SL beyond structure (0.15 = 15% of ATR)
        max_snap_atr: max distance (in ATR) we'll move a level to reach structure
        sl_min_atr: minimum SL distance from entry in ATR multiples
        sl_max_atr: maximum SL distance from entry in ATR multiples

    Returns:
        (adjusted_levels, snap_info) tuple.
    """
    if not structure or atr <= 0:
        return levels, {}

    entry = levels["entry"]
    sign = 1 if direction == "LONG" else -1
    buffer = buffer_atr * atr
    max_snap = max_snap_atr * atr
    result = dict(levels)
    snap_info = {}

    def _candidates(target: float, side: int) -> list[dict]:
        """Filter structure levels on the given side of entry within snap range."""
        if side > 0:
            return [lv for lv in structure if lv["price"] > entry and abs(lv["price"] - target) <= max_snap]
        return [lv for lv in structure if lv["price"] < entry and abs(lv["price"] - target) <= max_snap]

    def _best(candidates: list[dict], target: float) -> dict:
        return min(candidates, key=lambda lv: abs(lv["price"] - target) / max(lv["strength"], 1))

    # SL: find structure on the protective side (below entry for LONG, above for SHORT)
    sl = levels["stop_loss"]
    sl_cands = _candidates(sl, -sign)
    if sl_cands:
        best = _best(sl_cands, sl)
        new_sl = best["price"] - sign * buffer
        sl_dist = abs(entry - new_sl)
        sl_dist = max(sl_min_atr * atr, min(sl_max_atr * atr, sl_dist))
        result["stop_loss"] = entry - sign * sl_dist
        snap_info["sl_snapped_to"] = best["label"]
        snap_info["sl_structure_price"] = round(best["price"], 2)

    # TP1: find structure on the profit side
    tp1 = levels["take_profit_1"]
    tp1_cands = _candidates(tp1, sign)
    if tp1_cands:
        best = _best(tp1_cands, tp1)
        new_tp1 = best["price"] - sign * buffer  # slightly before structure
        if abs(new_tp1 - entry) > sl_min_atr * atr:
            result["take_profit_1"] = new_tp1
            snap_info["tp1_snapped_to"] = best["label"]
            snap_info["tp1_structure_price"] = round(best["price"], 2)

    # TP2: find structure beyond TP1
    tp2 = levels["take_profit_2"]
    tp1_price = result["take_profit_1"]
    tp2_cands = [
        lv for lv in structure
        if sign * (lv["price"] - tp1_price) > 0 and abs(lv["price"] - tp2) <= max_snap
    ]
    if tp2_cands:
        best = _best(tp2_cands, tp2)
        new_tp2 = best["price"] - sign * buffer
        if sign * (new_tp2 - tp1_price) > 0:
            result["take_profit_2"] = new_tp2
            snap_info["tp2_snapped_to"] = best["label"]
            snap_info["tp2_structure_price"] = round(best["price"], 2)

    # Enforce R:R floor: TP1 distance >= SL distance
    sl_dist = abs(result["entry"] - result["stop_loss"])
    tp1_dist = abs(result["take_profit_1"] - result["entry"])
    if sl_dist > 0 and tp1_dist < sl_dist:
        result["take_profit_1"] = entry + sign * sl_dist
        snap_info.pop("tp1_snapped_to", None)

    return result, snap_info
