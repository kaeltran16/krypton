"""Liquidation level scoring — aggregates liquidation events into price clusters."""

import math
from datetime import datetime, timezone

from app.engine.scoring import sigmoid_score

BUCKET_WIDTH_ATR_MULT = 0.25
DECAY_HALF_LIFE_HOURS = 4.0
CLUSTER_THRESHOLD_MULT = 2.0


def aggregate_liquidation_buckets(
    events: list[dict],
    atr: float,
    current_price: float,
    decay_half_life_hours: float = DECAY_HALF_LIFE_HOURS,
) -> list[dict]:
    """Aggregate liquidation events into price-level buckets with exponential decay."""
    if not events or atr <= 0:
        return []

    bucket_width = BUCKET_WIDTH_ATR_MULT * atr
    now = datetime.now(timezone.utc)
    buckets: dict[int, float] = {}

    for event in events:
        price = event["price"]
        volume = event["volume"]
        ts = event["timestamp"]

        # exponential decay
        age_hours = (now - ts).total_seconds() / 3600
        decay = math.exp(-math.log(2) * age_hours / decay_half_life_hours)
        weighted_vol = volume * decay

        bucket_idx = round((price - current_price) / bucket_width)
        buckets[bucket_idx] = buckets.get(bucket_idx, 0.0) + weighted_vol

    return [
        {"center": current_price + idx * bucket_width, "total_volume": vol}
        for idx, vol in sorted(buckets.items())
        if vol > 0
    ]


def detect_clusters(
    buckets: list[dict],
    threshold_mult: float = CLUSTER_THRESHOLD_MULT,
) -> list[dict]:
    """Identify clusters: buckets with volume > threshold_mult * median."""
    if len(buckets) < 2:
        return buckets

    volumes = sorted(b["total_volume"] for b in buckets)
    median_vol = volumes[len(volumes) // 2]

    if median_vol <= 0:
        return []

    return [b for b in buckets if b["total_volume"] > threshold_mult * median_vol]


def _depth_modifier(cluster_center: float, current_price: float, atr: float, depth: dict | None) -> float:
    """Compute depth-based modifier for a liquidation cluster. Returns [0.7, 1.3].

    Compares the volume of the relevant side (asks for clusters above, bids for
    clusters below) near the cluster to the average volume across ALL depth levels.
    Thin resistance near a cluster amplifies; thick resistance dampens.
    """
    if not depth:
        return 1.0

    is_above = cluster_center > current_price
    levels = depth.get("asks", []) if is_above else depth.get("bids", [])

    if not levels:
        return 1.0

    nearby_vol = sum(size for price, size in levels if abs(price - cluster_center) <= 0.5 * atr)

    if nearby_vol == 0:
        return 1.0

    all_depth_vols = [size for _, size in depth.get("bids", []) + depth.get("asks", [])]
    avg_vol = sum(all_depth_vols) / len(all_depth_vols) if all_depth_vols else 1.0

    if avg_vol <= 0:
        return 1.0

    ratio = nearby_vol / avg_vol
    if ratio < 0.5:
        modifier = 1.3
    elif ratio > 2.0:
        modifier = 0.7
    else:
        modifier = 1.0 + 0.3 * (1.0 - ratio)

    return max(0.7, min(1.3, modifier))


def compute_liquidation_score(
    events: list[dict],
    current_price: float,
    atr: float,
    depth: dict | None = None,
) -> dict:
    """Score liquidation levels based on cluster proximity to current price.

    Returns {"score": int, "confidence": float, "clusters": list}.
    """
    if not events or atr <= 0:
        return {"score": 0, "confidence": 0.0, "clusters": []}

    buckets = aggregate_liquidation_buckets(events, atr, current_price)
    clusters = detect_clusters(buckets)

    if not clusters:
        return {"score": 0, "confidence": 0.1, "clusters": []}

    # Normalize density relative to median bucket volume for the pair,
    # so scoring works across assets with vastly different volumes (BTC vs WIF).
    all_vols = [b["total_volume"] for b in buckets]
    median_vol = sorted(all_vols)[len(all_vols) // 2] if all_vols else 1.0
    density_norm = max(median_vol * 3, 1.0)  # 3x median = full density contribution

    score = 0.0
    for cluster in clusters:
        distance = cluster["center"] - current_price
        distance_atr = abs(distance) / atr if atr > 0 else float("inf")

        # only score clusters within 2 ATR
        if distance_atr > 2.0:
            continue

        proximity = sigmoid_score(2.0 - distance_atr, center=0, steepness=2.0)
        density = cluster["total_volume"]

        # Direction rationale (per spec Section 8):
        # Cluster ABOVE price = dense short liquidation levels = potential short squeeze
        # as cascading liquidations push price up → bullish.
        # Cluster BELOW price = dense long liquidation levels = potential long cascade
        # as cascading liquidations push price down → bearish.
        direction = 1 if distance > 0 else -1
        mod = _depth_modifier(cluster["center"], current_price, atr, depth)
        score += direction * proximity * min(density / density_norm, 1.0) * 30 * mod

    score = max(min(round(score), 100), -100)

    # confidence based on data freshness and cluster density
    total_vol = sum(b["total_volume"] for b in buckets)
    confidence = min(1.0, len(clusters) / 3.0) * min(1.0, total_vol / density_norm)

    return {
        "score": score,
        "confidence": min(1.0, confidence),
        "clusters": [{"price": c["center"], "volume": c["total_volume"]} for c in clusters],
    }
