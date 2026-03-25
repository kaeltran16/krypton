"""Shared data freshness computation for watchdog and health endpoint."""
import json
import logging
import time

logger = logging.getLogger(__name__)

TIMEFRAME_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1D": 86400}
ORDER_FLOW_MAX_AGE = 600       # 10 minutes
ONCHAIN_MAX_AGE = 900          # 15 minutes
LIQUIDATION_MAX_AGE = 600      # 10 minutes


async def compute_freshness(app_state) -> dict:
    """Check staleness of all data sources. Returns structured freshness report."""
    redis = app_state.redis
    pairs = app_state.settings.pairs
    timeframes = getattr(app_state.settings, "timeframes", ["15m"])
    now = time.time()

    result = {"candles": {}, "order_flow": {}, "onchain": {}, "liquidation": {}}

    for pair in pairs:
        for tf in timeframes:
            key = f"candles:{pair}:{tf}"
            max_age = TIMEFRAME_SECONDS.get(tf, 900) * 2
            age = await _redis_list_age(redis, key, now)
            result["candles"][f"{pair}:{tf}"] = {
                "seconds_ago": age,
                "stale": age is None or age > max_age,
            }

    for pair in pairs:
        flow = app_state.order_flow.get(pair, {})
        updated = flow.get("_last_updated")
        age = (now - updated) if updated else None
        result["order_flow"][pair] = {
            "seconds_ago": round(age) if age is not None else None,
            "stale": age is None or age > ORDER_FLOW_MAX_AGE,
        }

    onchain_metrics = ["exchange_netflow", "active_addresses"]
    for pair in pairs:
        present = 0
        for metric in onchain_metrics:
            exists = await redis.exists(f"onchain:{pair}:{metric}")
            if exists:
                present += 1
        result["onchain"][pair] = {
            "metrics_present": present,
            "metrics_total": len(onchain_metrics),
            "stale": present == 0,
        }

    liq = getattr(app_state, "liquidation_collector", None)
    if liq:
        poll_ts = getattr(liq, "_last_poll_ts", None)
        age = (now - poll_ts) if poll_ts else None
        result["liquidation"] = {
            "seconds_ago": round(age) if age is not None else None,
            "stale": age is None or age > LIQUIDATION_MAX_AGE,
        }

    return result


async def _redis_list_age(redis, key: str, now: float) -> int | None:
    """Seconds since the last entry in a Redis list."""
    try:
        raw = await redis.lindex(key, -1)
        if not raw:
            return None
        data = json.loads(raw)
        ts = data.get("timestamp")
        if ts is None:
            return None
        if isinstance(ts, str):
            from datetime import datetime
            ts = datetime.fromisoformat(ts).timestamp()
        return max(0, round(now - float(ts)))
    except Exception:
        return None
