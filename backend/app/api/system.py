import asyncio
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sqlalchemy import func, select, text

from app.api.auth import require_auth
from app.db.models import Signal

router = APIRouter(prefix="/api/system")


async def _check_redis(redis) -> dict:
    try:
        start = time.monotonic()
        await asyncio.wait_for(redis.ping(), timeout=2.0)
        latency = round((time.monotonic() - start) * 1000)
        return {"status": "up", "latency_ms": latency}
    except Exception:
        return {"status": "down", "latency_ms": None}


async def _check_postgres(db) -> dict:
    try:
        start = time.monotonic()

        async def _query():
            async with db.session_factory() as session:
                await session.execute(text("SELECT 1"))

        await asyncio.wait_for(_query(), timeout=2.0)
        latency = round((time.monotonic() - start) * 1000)
        return {"status": "up", "latency_ms": latency}
    except Exception:
        return {"status": "down", "latency_ms": None}


def _check_okx_ws(order_flow: dict) -> dict:
    if not order_flow:
        return {"status": "down", "connected_pairs": 0}
    return {"status": "up", "connected_pairs": len(order_flow)}


async def _get_signals_today(db) -> int:
    try:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        async with db.session_factory() as session:
            result = await session.execute(
                select(func.count()).select_from(Signal).where(Signal.created_at >= today)
            )
            return result.scalar() or 0
    except Exception:
        return 0


async def _get_candle_buffer(redis, pairs: list[str]) -> dict:
    async def _llen(pair):
        try:
            return pair, await redis.llen(f"candles:{pair}:1m")
        except Exception:
            return pair, 0

    results = await asyncio.gather(*(_llen(p) for p in pairs))
    return dict(results)


def _get_memory_mb() -> int | None:
    """Read VmRSS from /proc/self/status (Linux/Docker only)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024  # kB -> MB
    except Exception:
        pass
    return None


def _parse_epoch(ts) -> float | None:
    """Normalize a timestamp (ISO string or numeric epoch) to seconds-since-epoch."""
    if ts is None:
        return None
    if isinstance(ts, str):
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    ts = float(ts)
    return ts / 1000 if ts > 1e12 else ts


async def _get_freshness(redis, keys: list[str], ts_field: str, use_list: bool = False) -> int | None:
    """Seconds since the most recent timestamp across a set of Redis keys.

    Reads all keys concurrently. use_list=True reads from list tail (LINDEX -1),
    use_list=False reads a plain string key (GET).
    """
    async def _read(key):
        try:
            raw = await (redis.lindex(key, -1) if use_list else redis.get(key))
            if not raw:
                return None
            data = json.loads(raw)
            return _parse_epoch(data.get(ts_field))
        except Exception:
            return None

    epochs = await asyncio.gather(*(_read(k) for k in keys))
    valid = [e for e in epochs if e is not None]
    if not valid:
        return None
    return max(0, int(time.time() - max(valid)))


@router.get("/health")
async def system_health(request: Request, _user: dict = require_auth()):
    app = request.app
    redis = app.state.redis
    db = app.state.db
    settings = app.state.settings
    pairs = list(settings.pairs)

    # Build freshness key lists
    candle_keys = [f"candles:{p}:1m" for p in pairs]
    onchain_metrics = ["whale_tx_count", "active_addresses", "exchange_netflow", "nvt_ratio"]
    onchain_keys = [f"onchain:{p}:{m}" for p in pairs for m in onchain_metrics]

    # Run all independent checks concurrently
    (
        redis_check, pg_check, signals_today, candle_buffer,
        tech_freshness, onchain_freshness,
    ) = await asyncio.gather(
        _check_redis(redis),
        _check_postgres(db),
        _get_signals_today(db),
        _get_candle_buffer(redis, pairs),
        _get_freshness(redis, candle_keys, "timestamp", use_list=True),
        _get_freshness(redis, onchain_keys, "ts"),
    )

    okx_check = _check_okx_ws(app.state.order_flow)

    # Pipeline metrics (read last_cycle once, use for both order flow and pipeline)
    last_cycle = getattr(app.state, "last_pipeline_cycle", 0)
    last_cycle_seconds_ago = max(0, int(time.time() - last_cycle)) if last_cycle > 0 else None

    order_flow_seconds_ago = None
    if app.state.order_flow and last_cycle > 0:
        order_flow_seconds_ago = last_cycle_seconds_ago

    # Resources
    engine = db.engine
    memory_mb = _get_memory_mb()

    try:
        pool_active = engine.pool.checkedout()
    except Exception:
        pool_active = 0
    try:
        pool_size = engine.pool.size()
    except Exception:
        pool_size = 0

    ws_clients = len(app.state.manager.connections)
    start_time = getattr(app.state, "start_time", time.time())
    uptime_seconds = max(0, int(time.time() - start_time))

    ml_predictors = getattr(app.state, "ml_predictors", {})

    # Overall status
    services = {
        "redis": redis_check,
        "postgres": pg_check,
        "okx_ws": okx_check,
    }
    down_count = sum(1 for s in services.values() if s["status"] == "down")
    if down_count == 0:
        overall = "healthy"
    elif down_count == 1:
        overall = "degraded"
    else:
        overall = "unhealthy"

    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": services,
        "pipeline": {
            "signals_today": signals_today,
            "last_cycle_seconds_ago": last_cycle_seconds_ago,
            "active_pairs": len(pairs),
            "candle_buffer": candle_buffer,
        },
        "resources": {
            "memory_mb": memory_mb,
            "db_pool_active": pool_active,
            "db_pool_size": pool_size,
            "ws_clients": ws_clients,
            "uptime_seconds": uptime_seconds,
        },
        "freshness": {
            "technicals_seconds_ago": tech_freshness,
            "order_flow_seconds_ago": order_flow_seconds_ago,
            "onchain_seconds_ago": onchain_freshness,
            "ml_models_loaded": len(ml_predictors),
        },
    }
