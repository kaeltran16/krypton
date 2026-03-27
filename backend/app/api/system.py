import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sqlalchemy import func, select, text

from app.api.auth import require_auth
from app.db.models import ErrorLog, Signal

logger = logging.getLogger(__name__)

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


def _freshness_seconds_ago(report_section: dict) -> int | None:
    """Extract the minimum seconds_ago from a freshness report section."""
    ages = [v.get("seconds_ago") for v in report_section.values() if isinstance(v, dict) and v.get("seconds_ago") is not None]
    return min(ages) if ages else None


@router.get("/health")
async def system_health(request: Request, _user: dict = require_auth()):
    app = request.app
    redis = app.state.redis
    db = app.state.db
    settings = app.state.settings
    pairs = list(settings.pairs)

    from app.collector.freshness import compute_freshness

    # Run all independent checks concurrently
    (
        redis_check, pg_check, signals_today, candle_buffer,
        freshness_report,
    ) = await asyncio.gather(
        _check_redis(redis),
        _check_postgres(db),
        _get_signals_today(db),
        _get_candle_buffer(redis, pairs),
        compute_freshness(app.state),
    )

    okx_check = _check_okx_ws(app.state.order_flow)

    # Pipeline metrics
    last_cycle = getattr(app.state, "last_pipeline_cycle", 0)
    last_cycle_seconds_ago = max(0, int(time.time() - last_cycle)) if last_cycle > 0 else None

    tech_freshness = _freshness_seconds_ago(freshness_report.get("candles", {}))
    order_flow_seconds_ago = _freshness_seconds_ago(freshness_report.get("order_flow", {}))
    onchain_section = freshness_report.get("onchain", {})
    onchain_freshness = None
    if any(v.get("stale") is False for v in onchain_section.values() if isinstance(v, dict)):
        onchain_freshness = 0  # at least some data present

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


@router.get("/errors")
async def system_errors(
    request: Request,
    _user: dict = require_auth(),
    level: str | None = None,
    module: str | None = None,
    pair: str | None = None,
    limit: int = 50,
    offset: int = 0,
    since: str | None = None,
):
    db = request.app.state.db
    limit = min(limit, 200)

    filters = []
    if level:
        filters.append(ErrorLog.level == level.upper())
    if module:
        filters.append(ErrorLog.module.contains(module))
    if pair:
        filters.append(ErrorLog.pair == pair)
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            filters.append(ErrorLog.timestamp >= since_dt)
        except ValueError:
            pass

    query = select(ErrorLog).where(*filters).order_by(ErrorLog.timestamp.desc()).offset(offset).limit(limit)
    count_query = select(func.count()).select_from(ErrorLog).where(*filters)

    try:
        async with db.session_factory() as session:
            result = await session.execute(query)
            rows = result.scalars().all()
            count_result = await session.execute(count_query)
            total = count_result.scalar() or 0
    except Exception as e:
        logger.error("Error log query failed: %s", e)
        return {"errors": [], "total": 0, "has_more": False}

    return {
        "errors": [
            {
                "id": row.id,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "level": row.level,
                "module": row.module,
                "message": row.message,
                "traceback": row.traceback,
                "pair": row.pair,
            }
            for row in rows
        ],
        "total": total,
        "has_more": (offset + limit) < total,
    }
