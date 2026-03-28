# backend/app/engine/onchain_scorer.py — full rewrite
import json
import logging

from app.engine.scoring import sigmoid_score

logger = logging.getLogger(__name__)

# Per-asset profile definitions
_PROFILES = {
    "BTC": {
        "netflow_norm": 3000,
        "whale_baseline": 3,
        "metrics": ["exchange_netflow", "whale_tx_count", "nupl", "hashrate_change_pct", "addr_trend_pct"],
    },
    "ETH": {
        "netflow_norm": 50000,
        "whale_baseline": 5,
        "metrics": ["exchange_netflow", "whale_tx_count", "staking_flow", "gas_trend_pct", "addr_trend_pct"],
    },
}


async def _get_metric(redis, pair: str, metric: str) -> float | None:
    """Read a single on-chain metric from Redis. Returns None if missing.

    Handles both plain float strings and JSON objects with a 'value' key
    (the current OnChainCollector stores JSON objects).
    """
    try:
        raw = await redis.get(f"onchain:{pair}:{metric}")
        if raw is None:
            return None
        # Try plain float first, fall back to JSON
        try:
            return float(raw)
        except (ValueError, TypeError):
            data = json.loads(raw)
            return float(data.get("value", 0)) if isinstance(data, dict) else float(data)
    except Exception:
        return None


async def compute_onchain_score(pair: str, redis) -> dict:
    """Compute on-chain score for a given pair using asset-specific profile.

    Returns dict with 'score' in [-100, +100] and 'confidence' in [0, 1].
    Unknown pairs return score=0, confidence=0.
    """
    asset = pair.split("-")[0].upper()
    profile = _PROFILES.get(asset)
    if profile is None:
        return {"score": 0, "confidence": 0.0}

    score = 0.0
    total_metrics = len(profile["metrics"])
    metrics_present = 0
    metric_scores = []

    # Exchange netflow (±35) — outflow = bullish
    netflow = await _get_metric(redis, pair, "exchange_netflow")
    if netflow is not None:
        ms = sigmoid_score(-netflow / profile["netflow_norm"], center=0, steepness=1.5) * 35
        score += ms
        metric_scores.append(ms)
        metrics_present += 1

    # Whale activity (±20) — contrarian
    whale_count = await _get_metric(redis, pair, "whale_tx_count")
    if whale_count is not None:
        ms = sigmoid_score(profile["whale_baseline"] - whale_count, center=0, steepness=0.3) * 20
        score += ms
        metric_scores.append(ms)
        metrics_present += 1

    # Active addresses trend (±15) — rising = bullish
    addr_trend = await _get_metric(redis, pair, "addr_trend_pct")
    if addr_trend is not None:
        ms = sigmoid_score(addr_trend, center=0, steepness=8) * 15
        score += ms
        metric_scores.append(ms)
        metrics_present += 1

    # Asset-specific metrics
    if asset == "BTC":
        nupl = await _get_metric(redis, pair, "nupl")
        if nupl is not None:
            ms = sigmoid_score(0.5 - nupl, center=0, steepness=3) * 15
            score += ms
            metric_scores.append(ms)
            metrics_present += 1

        hashrate = await _get_metric(redis, pair, "hashrate_change_pct")
        if hashrate is not None:
            ms = sigmoid_score(hashrate, center=0, steepness=10) * 15
            score += ms
            metric_scores.append(ms)
            metrics_present += 1

    elif asset == "ETH":
        staking = await _get_metric(redis, pair, "staking_flow")
        if staking is not None:
            ms = sigmoid_score(-staking, center=0, steepness=1) * 15
            score += ms
            metric_scores.append(ms)
            metrics_present += 1

        gas_trend = await _get_metric(redis, pair, "gas_trend_pct")
        if gas_trend is not None:
            ms = sigmoid_score(gas_trend, center=0, steepness=5) * 15
            score += ms
            metric_scores.append(ms)
            metrics_present += 1

    confidence = round(metrics_present / total_metrics, 4) if total_metrics > 0 else 0.0

    # Conviction: average absolute magnitude of available metric scores / max possible
    onchain_conviction = round(
        sum(abs(s) for s in metric_scores) / (len(metric_scores) * 35), 4
    ) if metric_scores else 0.0
    onchain_conviction = min(1.0, onchain_conviction)

    return {
        "score": max(min(round(score), 100), -100),
        "availability": confidence,  # metrics_present / total_metrics
        "conviction": onchain_conviction,
        "confidence": confidence,  # backward compat
    }
