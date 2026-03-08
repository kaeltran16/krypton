"""On-chain metric scorer.

Reads cached on-chain data from Redis and produces a composite score (-100 to +100).

Metric weights:
  Exchange netflow:       ±35 (large inflows = bearish, outflows = bullish)
  Whale movements:        ±25 (transfers to exchanges = bearish, to cold = bullish)
  NUPL / MVRV:            ±20 (extreme greed = bearish, extreme fear = bullish)
  Active addresses trend: ±20 (rising = bullish, falling = bearish)
"""
import json
import logging

logger = logging.getLogger(__name__)

MAX_SCORE = 100
MIN_SCORE = -100


def _clamp(value: int) -> int:
    return max(MIN_SCORE, min(MAX_SCORE, value))


def _score_exchange_netflow(netflow: float) -> int:
    """Negative netflow (outflow) is bullish, positive (inflow) is bearish.
    Scale: roughly ±35 points based on magnitude."""
    if netflow == 0:
        return 0
    # Normalize: typical large daily netflow is ~5000 BTC
    normalized = max(-1.0, min(1.0, -netflow / 5000))
    return round(normalized * 35)


def _score_whale_movements(tx_count: int) -> int:
    """High whale tx count suggests accumulation (bullish) or distribution.
    Simple heuristic: moderate count is neutral, very high is bearish (selling pressure)."""
    if tx_count <= 2:
        return 10  # Low activity, slight bullish (accumulation quiet)
    if tx_count <= 5:
        return 0  # Neutral
    if tx_count <= 10:
        return -10  # Moderate selling pressure
    return -25  # High whale activity, bearish


def _score_nupl(nupl: float) -> int:
    """Net Unrealized Profit/Loss — contrarian indicator.
    > 0.75: extreme greed → bearish
    0.5-0.75: greed → slightly bearish
    0.25-0.5: optimism → neutral
    0-0.25: hope → slightly bullish
    < 0: capitulation → bullish"""
    if nupl > 0.75:
        return -20
    if nupl > 0.5:
        return -10
    if nupl > 0.25:
        return 0
    if nupl > 0:
        return 10
    return 20


def _score_active_addresses_trend(history: list[float]) -> int:
    """Rising active addresses = bullish momentum, falling = bearish.
    Compare recent average to older average."""
    if len(history) < 4:
        return 0
    mid = len(history) // 2
    older_avg = sum(history[:mid]) / mid
    recent_avg = sum(history[mid:]) / (len(history) - mid)
    if older_avg == 0:
        return 0
    change_pct = (recent_avg - older_avg) / older_avg
    # ±20 points scaled by change
    return round(max(-1.0, min(1.0, change_pct * 10)) * 20)


async def compute_onchain_score(pair: str, redis) -> int:
    """Compute composite on-chain score for a pair. Returns -100 to +100.

    Returns 0 if no on-chain data is available (graceful degradation).
    """
    score = 0
    has_data = False

    # Exchange netflow
    raw = await redis.get(f"onchain:{pair}:exchange_netflow")
    if raw:
        data = json.loads(raw)
        score += _score_exchange_netflow(data.get("value", 0))
        has_data = True

    # Whale movements
    raw = await redis.get(f"onchain:{pair}:whale_tx_count")
    if raw:
        data = json.loads(raw)
        score += _score_whale_movements(data.get("value", 0))
        has_data = True

    # NUPL
    raw = await redis.get(f"onchain:{pair}:nupl")
    if raw:
        data = json.loads(raw)
        score += _score_nupl(data.get("value", 0))
        has_data = True

    # Active addresses trend (from history)
    hist_key = f"onchain_hist:{pair}:active_addresses"
    raw_hist = await redis.lrange(hist_key, -24, -1)  # Last ~2 hours
    if raw_hist and len(raw_hist) >= 4:
        values = [json.loads(h).get("v", 0) for h in raw_hist]
        score += _score_active_addresses_trend(values)
        has_data = True

    if not has_data:
        return 0

    return _clamp(score)
