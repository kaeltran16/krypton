"""Liquidation level scoring — cluster proximity + directional asymmetry."""

import math
from datetime import datetime, timezone
from statistics import median, mean

from app.engine.constants import LIQUIDATION
from app.engine.scoring import sigmoid_score

_BUCKET_WIDTH = LIQUIDATION["bucket_width_atr_mult"]
_MAD_MULT = LIQUIDATION["mad_multiplier"]
_MIN_MEAN_MULT = LIQUIDATION["min_cluster_mean_mult"]
_MAX_DIST = LIQUIDATION["max_distance_atr"]
_DEPTH_CENTER = LIQUIDATION["depth_sigmoid_center"]
_DEPTH_STEEP = LIQUIDATION["depth_sigmoid_steepness"]
_MIN_ASYM_EVENTS = LIQUIDATION["min_asymmetry_events"]


def _decay_weight(ts: datetime, half_life_hours: float) -> float:
    age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    return math.exp(-math.log(2) * age_hours / half_life_hours)


def aggregate_liquidation_buckets(
    events: list[dict],
    atr: float,
    current_price: float,
    decay_half_life_hours: float = 4.0,
) -> list[dict]:
    """Aggregate events into ATR-width price buckets with decay and side breakdown.

    Returns list of {"center", "total_volume", "side_breakdown": {"short", "long"}}.
    """
    if not events or atr <= 0:
        return []

    bucket_width = _BUCKET_WIDTH * atr
    buckets: dict[int, dict] = {}

    for event in events:
        price = event["price"]
        volume = event["volume"]
        side = event.get("side")

        weighted_vol = volume * _decay_weight(event["timestamp"], decay_half_life_hours)

        idx = round((price - current_price) / bucket_width)
        if idx not in buckets:
            buckets[idx] = {"total": 0.0, "short": 0.0, "long": 0.0}
        buckets[idx]["total"] += weighted_vol
        if side == "buy":
            buckets[idx]["short"] += weighted_vol
        elif side == "sell":
            buckets[idx]["long"] += weighted_vol

    return [
        {
            "center": current_price + idx * bucket_width,
            "total_volume": b["total"],
            "side_breakdown": {"short": b["short"], "long": b["long"]},
        }
        for idx, b in sorted(buckets.items())
        if b["total"] > 0
    ]


def detect_clusters(buckets: list[dict]) -> list[dict]:
    """Identify clusters using MAD-based threshold with mean floor."""
    if len(buckets) < 2:
        return buckets

    volumes = [b["total_volume"] for b in buckets]
    med = median(volumes)
    mad = median(abs(v - med) for v in volumes)
    threshold = max(med + _MAD_MULT * mad, _MIN_MEAN_MULT * mean(volumes))

    return [b for b in buckets if b["total_volume"] > threshold]


def depth_modifier(ratio: float) -> float:
    """Smooth sigmoid depth modifier. Returns [0.7, 1.3].

    Low ratio (thin book near cluster) -> amplify (closer to 1.3).
    High ratio (thick book near cluster) -> dampen (closer to 0.7).
    """
    s = sigmoid_score(ratio, center=_DEPTH_CENTER, steepness=_DEPTH_STEEP)
    return max(0.7, min(1.3, 1.0 - 0.3 * s))


def get_depth_ratio(cluster_center: float, current_price: float, atr: float, depth: dict | None) -> float:
    """Compute nearby/average volume ratio for the depth modifier."""
    if not depth:
        return 1.0  # neutral

    is_above = cluster_center > current_price
    levels = depth.get("asks", []) if is_above else depth.get("bids", [])
    if not levels:
        return 1.0

    nearby_vol = sum(size for price, size in levels if abs(price - cluster_center) <= 0.5 * atr)
    if nearby_vol == 0:
        return 1.0

    all_vols = [size for _, size in depth.get("bids", []) + depth.get("asks", [])]
    avg_vol = sum(all_vols) / len(all_vols) if all_vols else 1.0
    if avg_vol <= 0:
        return 1.0

    return nearby_vol / avg_vol


def compute_cluster_score(
    events: list[dict],
    current_price: float,
    atr: float,
    depth: dict | None = None,
    cluster_max_score: float = 30.0,
    proximity_steepness: float = 2.0,
    decay_half_life_hours: float = 4.0,
) -> dict:
    """Score liquidation clusters by proximity, density, and side-aware direction.

    Returns {"score": int, "confidence": float, "clusters": list, "details": dict}.
    """
    if not events or atr <= 0:
        return {"score": 0, "confidence": 0.0, "clusters": [], "details": {
            "cluster_count": 0, "buckets_total": 0, "per_cluster": [],
        }}

    buckets = aggregate_liquidation_buckets(events, atr, current_price, decay_half_life_hours)
    clusters = detect_clusters(buckets)

    if not clusters:
        return {"score": 0, "confidence": 0.1, "clusters": [], "details": {
            "cluster_count": 0, "buckets_total": len(buckets), "per_cluster": [],
        }}

    all_vols = [b["total_volume"] for b in buckets]
    density_norm = max(median(all_vols) * 3, 1.0)

    score = 0.0
    per_cluster = []
    for cluster in clusters:
        distance = cluster["center"] - current_price
        distance_atr = abs(distance) / atr

        if distance_atr > _MAX_DIST:
            continue

        proximity = sigmoid_score(
            _MAX_DIST - distance_atr, center=0, steepness=proximity_steepness,
        )
        density = cluster["total_volume"]
        sb = cluster["side_breakdown"]
        net = sb["short"] - sb["long"]
        total_side = sb["short"] + sb["long"]

        if total_side > 0:
            direction = 1 if net > 0 else -1
            side_scale = abs(net) / total_side
        else:
            # no side info: fall back to price position
            direction = 1 if distance > 0 else -1
            side_scale = 1.0

        depth_ratio = get_depth_ratio(cluster["center"], current_price, atr, depth)
        mod = depth_modifier(depth_ratio)
        contribution = direction * side_scale * proximity * min(density / density_norm, 1.0) * cluster_max_score * mod
        score += contribution

        per_cluster.append({
            "price": cluster["center"],
            "proximity": round(proximity, 4),
            "density_ratio": round(min(density / density_norm, 1.0), 4),
            "depth_mod": round(mod, 4),
            "direction": direction,
            "contribution": round(contribution, 2),
        })

    score = max(min(round(score), 100), -100)
    total_vol = sum(b["total_volume"] for b in buckets)
    confidence = min(1.0, len(clusters) / 3.0) * min(1.0, total_vol / density_norm)

    return {
        "score": score,
        "confidence": min(1.0, confidence),
        "clusters": [
            {"price": c["center"], "volume": c["total_volume"], "side_breakdown": c["side_breakdown"]}
            for c in clusters
        ],
        "details": {
            "cluster_count": len(per_cluster),
            "buckets_total": len(buckets),
            "per_cluster": per_cluster,
        },
    }


def compute_asymmetry_score(
    events: list[dict],
    decay_half_life_hours: float = 4.0,
    asymmetry_max_score: float = 25.0,
    asymmetry_steepness: float = 3.0,
) -> dict:
    """Score directional imbalance of liquidation events.

    Returns {"score": int, "confidence": float, "raw_asymmetry": float, ...}.
    """
    if not events:
        return {
            "score": 0, "confidence": 0.0, "raw_asymmetry": 0.0,
            "short_liq_vol": 0.0, "long_liq_vol": 0.0, "event_count": 0,
        }

    short_vol = 0.0
    long_vol = 0.0
    event_count = 0

    for event in events:
        side = event.get("side")
        if not side:
            continue
        weighted = event["volume"] * _decay_weight(event["timestamp"], decay_half_life_hours)
        if side == "buy":
            short_vol += weighted
        elif side == "sell":
            long_vol += weighted
        event_count += 1

    total = short_vol + long_vol
    if total == 0:
        return {
            "score": 0, "confidence": 0.0, "raw_asymmetry": 0.0,
            "short_liq_vol": 0.0, "long_liq_vol": 0.0, "event_count": event_count,
        }

    raw_asymmetry = (short_vol - long_vol) / total

    score = round(sigmoid_score(raw_asymmetry, center=0, steepness=asymmetry_steepness) * asymmetry_max_score)
    score = max(min(score, round(asymmetry_max_score)), -round(asymmetry_max_score))

    # confidence: need both volume and event count
    all_vols = [e["volume"] for e in events]
    density_norm = max(median(all_vols) * 3, 1.0) if all_vols else 1.0
    min_vol_threshold = density_norm * 0.5
    volume_ratio = min(total / min_vol_threshold, 1.0) if min_vol_threshold > 0 else 0.0
    confidence = volume_ratio * min(event_count / _MIN_ASYM_EVENTS, 1.0)

    return {
        "score": score,
        "confidence": min(1.0, confidence),
        "raw_asymmetry": round(raw_asymmetry, 4),
        "short_liq_vol": round(short_vol, 2),
        "long_liq_vol": round(long_vol, 2),
        "event_count": event_count,
    }


def compute_liquidation_score(
    events: list[dict],
    current_price: float,
    atr: float,
    depth: dict | None = None,
    cluster_max_score: float = 30.0,
    asymmetry_max_score: float = 25.0,
    cluster_weight: float = 0.6,
    proximity_steepness: float = 2.0,
    decay_half_life_hours: float = 4.0,
    asymmetry_steepness: float = 3.0,
) -> dict:
    """Compose cluster + asymmetry scores into final liquidation score.

    Returns {"score", "confidence", "clusters", "details"}.
    """
    if not events or atr <= 0:
        return {"score": 0, "confidence": 0.0, "clusters": [], "details": {}}

    cluster_result = compute_cluster_score(
        events, current_price, atr, depth,
        cluster_max_score=cluster_max_score,
        proximity_steepness=proximity_steepness,
        decay_half_life_hours=decay_half_life_hours,
    )
    asymmetry_result = compute_asymmetry_score(
        events,
        decay_half_life_hours=decay_half_life_hours,
        asymmetry_max_score=asymmetry_max_score,
        asymmetry_steepness=asymmetry_steepness,
    )

    asym_weight = 1.0 - cluster_weight
    combined_score = round(
        cluster_result["score"] * cluster_weight
        + asymmetry_result["score"] * asym_weight
    )
    combined_score = max(min(combined_score, 100), -100)
    combined_confidence = (
        cluster_result["confidence"] * cluster_weight
        + asymmetry_result["confidence"] * asym_weight
    )

    return {
        "score": combined_score,
        "confidence": min(1.0, combined_confidence),
        "clusters": cluster_result["clusters"],
        "details": {
            "cluster_score": cluster_result["score"],
            "cluster_confidence": round(cluster_result["confidence"], 4),
            "cluster_count": cluster_result["details"].get("cluster_count", 0),
            "buckets_total": cluster_result["details"].get("buckets_total", 0),
            "per_cluster": cluster_result["details"].get("per_cluster", []),
            "asymmetry_score": asymmetry_result["score"],
            "asymmetry_confidence": round(asymmetry_result["confidence"], 4),
            "raw_asymmetry": asymmetry_result["raw_asymmetry"],
            "long_liq_vol": asymmetry_result["long_liq_vol"],
            "short_liq_vol": asymmetry_result["short_liq_vol"],
            "event_count": asymmetry_result["event_count"],
            "cluster_weight": cluster_weight,
            "asymmetry_weight": asym_weight,
        },
    }
