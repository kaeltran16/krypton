import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.dialects.postgresql import insert as pg_insert

from datetime import datetime, timezone
from sqlalchemy import select

from app.config import Settings
from app.exchange.okx_client import OKXClient
from app.db.database import Base, Database
from app.db.models import Candle, Signal
from app.collector.ws_client import OKXWebSocketClient
from app.collector.rest_poller import OKXRestPoller
from app.api.routes import create_router
from app.api.ws import manager as ws_manager
from app.engine.traditional import compute_technical_score, compute_order_flow_score
from app.engine.combiner import compute_preliminary_score, compute_final_score, calculate_levels
from app.engine.llm import load_prompt_template, render_prompt, call_openrouter

logger = logging.getLogger(__name__)


def _pipeline_done_callback(task: asyncio.Task, tasks: set):
    tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error(f"Pipeline task failed: {exc}", exc_info=exc)


async def persist_candle(db: Database, candle: dict):
    try:
        async with db.session_factory() as session:
            stmt = pg_insert(Candle).values(
                pair=candle["pair"],
                timeframe=candle["timeframe"],
                timestamp=candle["timestamp"],
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
            ).on_conflict_do_nothing(constraint="uq_candle")
            await session.execute(stmt)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to persist candle {candle['pair']}:{candle['timeframe']}: {e}")


async def persist_signal(db: Database, signal_data: dict):
    try:
        async with db.session_factory() as session:
            row = Signal(
                pair=signal_data["pair"],
                timeframe=signal_data["timeframe"],
                direction=signal_data["direction"],
                final_score=signal_data["final_score"],
                traditional_score=signal_data["traditional_score"],
                llm_opinion=signal_data.get("llm_opinion"),
                llm_confidence=signal_data.get("llm_confidence"),
                explanation=signal_data.get("explanation"),
                entry=signal_data["entry"],
                stop_loss=signal_data["stop_loss"],
                take_profit_1=signal_data["take_profit_1"],
                take_profit_2=signal_data["take_profit_2"],
                raw_indicators=signal_data.get("raw_indicators"),
            )
            session.add(row)
            await session.commit()
            signal_data["id"] = row.id
    except Exception as e:
        logger.error(f"Failed to persist signal {signal_data['pair']}: {e}")


async def run_pipeline(app: FastAPI, candle: dict):
    settings = app.state.settings
    redis = app.state.redis
    db = app.state.db
    manager = app.state.manager
    order_flow = app.state.order_flow
    prompt_template = app.state.prompt_template

    pair = candle["pair"]
    timeframe = candle["timeframe"]

    try:
        cache_key = f"candles:{pair}:{timeframe}"
        raw_candles = await redis.lrange(cache_key, -50, -1)
    except Exception as e:
        logger.error(f"Redis fetch failed for {pair}:{timeframe}: {e}")
        return

    if len(raw_candles) < 50:
        logger.warning(f"Not enough candles for {pair}:{timeframe} ({len(raw_candles)})")
        return

    candles_data = [json.loads(c) for c in raw_candles]
    df = pd.DataFrame(candles_data)

    try:
        tech_result = compute_technical_score(df)
    except Exception as e:
        logger.error(f"Technical scoring failed for {pair}:{timeframe}: {e}")
        return

    flow_metrics = order_flow.get(pair, {})
    flow_result = compute_order_flow_score(flow_metrics)

    preliminary = compute_preliminary_score(
        tech_result["score"],
        flow_result["score"],
        settings.engine_traditional_weight,
        1 - settings.engine_traditional_weight,
    )

    llm_response = None
    if abs(preliminary) >= settings.engine_llm_threshold and prompt_template:
        try:
            rendered = render_prompt(
                template=prompt_template,
                pair=pair,
                timeframe=timeframe,
                indicators=json.dumps(tech_result["indicators"], indent=2),
                order_flow=json.dumps(flow_result["details"], indent=2),
                preliminary_score=str(preliminary),
                direction="LONG" if preliminary > 0 else "SHORT",
                candles=json.dumps(candles_data[-20:], indent=2),
            )
            llm_response = await call_openrouter(
                prompt=rendered,
                api_key=settings.openrouter_api_key,
                model=settings.openrouter_model,
                timeout=settings.engine_llm_timeout_seconds,
            )
        except Exception as e:
            logger.error(f"LLM call failed for {pair}:{timeframe}: {e}")

    final = compute_final_score(preliminary, llm_response)
    direction = "LONG" if final > 0 else "SHORT"

    if abs(final) < settings.engine_signal_threshold:
        return

    atr = tech_result["indicators"].get("atr", 200)
    llm_levels = None
    if llm_response and llm_response.opinion == "confirm" and llm_response.levels:
        llm_levels = llm_response.levels.model_dump()
    levels = calculate_levels(direction, float(candle["close"]), atr, llm_levels)

    signal_data = {
        "pair": pair,
        "timeframe": timeframe,
        "direction": direction,
        "final_score": final,
        "traditional_score": tech_result["score"],
        "llm_opinion": llm_response.opinion if llm_response else "skipped",
        "llm_confidence": llm_response.confidence if llm_response else None,
        "explanation": llm_response.explanation if llm_response else None,
        **levels,
        "raw_indicators": tech_result["indicators"],
    }

    await persist_signal(db, signal_data)
    await manager.broadcast(signal_data)
    logger.info(f"Signal emitted: {pair} {timeframe} {direction} score={final}")


async def handle_candle(app: FastAPI, candle: dict):
    redis = app.state.redis
    db = app.state.db

    cache_key = f"candles:{candle['pair']}:{candle['timeframe']}"
    candle_json = json.dumps({
        "timestamp": candle["timestamp"].isoformat(),
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle["volume"],
    })

    try:
        await redis.rpush(cache_key, candle_json)
        await redis.ltrim(cache_key, -200, -1)
    except Exception as e:
        logger.error(f"Redis cache failed for {candle['pair']}:{candle['timeframe']}: {e}")

    await persist_candle(db, candle)

    task = asyncio.create_task(run_pipeline(app, candle))
    app.state.pipeline_tasks.add(task)
    task.add_done_callback(
        lambda t: _pipeline_done_callback(t, app.state.pipeline_tasks)
    )


async def handle_candle_tick(app: FastAPI, candle: dict):
    """Handle all candle ticks (confirmed and unconfirmed)."""
    manager = app.state.manager

    tick = {
        "pair": candle["pair"],
        "timeframe": candle["timeframe"],
        "timestamp": candle["timestamp"].isoformat() if hasattr(candle["timestamp"], "isoformat") else candle["timestamp"],
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle["volume"],
        "confirmed": candle["confirmed"],
    }
    await manager.broadcast_candle(tick)

    if candle["confirmed"]:
        await handle_candle(app, candle)


async def handle_funding_rate(app: FastAPI, data: dict):
    flow = app.state.order_flow.setdefault(data["pair"], {})
    flow["funding_rate"] = data["funding_rate"]


async def handle_open_interest(app: FastAPI, data: dict):
    flow = app.state.order_flow.setdefault(data["pair"], {})
    prev_oi = flow.get("open_interest", data["open_interest"])
    current_oi = data["open_interest"]
    if prev_oi > 0:
        flow["open_interest_change_pct"] = (current_oi - prev_oi) / prev_oi
    flow["open_interest"] = current_oi


async def handle_long_short_data(app: FastAPI, data: dict):
    flow = app.state.order_flow.setdefault(data["pair"], {})
    flow["long_short_ratio"] = data["long_short_ratio"]


async def check_pending_signals(app: FastAPI):
    """Check all PENDING signals against recent candles for outcome resolution."""
    db = app.state.db
    redis = app.state.redis

    from app.engine.outcome_resolver import resolve_signal_outcome

    async with db.session_factory() as session:
        result = await session.execute(
            select(Signal).where(Signal.outcome == "PENDING").order_by(Signal.created_at.desc()).limit(50)
        )
        pending = result.scalars().all()

        for signal in pending:
            # Check expiry (24h)
            age = (datetime.now(timezone.utc) - signal.created_at).total_seconds()
            if age > 86400:
                signal.outcome = "EXPIRED"
                signal.outcome_at = datetime.now(timezone.utc)
                signal.outcome_duration_minutes = round(age / 60)
                continue

            cache_key = f"candles:{signal.pair}:{signal.timeframe}"
            raw_candles = await redis.lrange(cache_key, -200, -1)
            if not raw_candles:
                continue

            import json as _json
            candles_data = [_json.loads(c) for c in raw_candles]

            # Only check candles after signal creation
            signal_ts = signal.created_at.isoformat()
            candles_after = [c for c in candles_data if c["timestamp"] > signal_ts]
            if not candles_after:
                continue

            signal_dict = {
                "direction": signal.direction,
                "entry": float(signal.entry),
                "stop_loss": float(signal.stop_loss),
                "take_profit_1": float(signal.take_profit_1),
                "take_profit_2": float(signal.take_profit_2),
                "created_at": signal.created_at,
            }

            # Parse candle floats
            parsed = []
            for c in candles_after:
                parsed.append({
                    "high": float(c.get("high", c.get("h", 0))),
                    "low": float(c.get("low", c.get("l", 0))),
                    "close": float(c.get("close", c.get("c", 0))),
                    "timestamp": c["timestamp"],
                })

            outcome = resolve_signal_outcome(signal_dict, parsed)
            if outcome:
                signal.outcome = outcome["outcome"]
                signal.outcome_at = outcome["outcome_at"]
                signal.outcome_pnl_pct = outcome["outcome_pnl_pct"]
                signal.outcome_duration_minutes = outcome["outcome_duration_minutes"]

        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db = Database(settings.database_url)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    # Create tables if they don't exist
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.settings = settings
    app.state.db = db
    app.state.session_factory = db.session_factory
    app.state.redis = redis
    app.state.manager = ws_manager
    app.state.order_flow = {}
    app.state.pipeline_tasks = set()

    prompt_path = Path(__file__).parent / "prompts" / "signal_analysis.txt"
    app.state.prompt_template = load_prompt_template(prompt_path) if prompt_path.exists() else ""

    if settings.okx_api_key:
        app.state.okx_client = OKXClient(
            api_key=settings.okx_api_key,
            api_secret=settings.okx_api_secret,
            passphrase=settings.okx_passphrase,
            demo=settings.okx_demo,
        )
    else:
        app.state.okx_client = None

    ws_client = OKXWebSocketClient(
        pairs=settings.pairs,
        timeframes=settings.timeframes,
        on_candle=lambda c: handle_candle_tick(app, c),
        on_funding_rate=lambda d: handle_funding_rate(app, d),
        on_open_interest=lambda d: handle_open_interest(app, d),
    )
    rest_poller = OKXRestPoller(
        pairs=settings.pairs,
        interval_seconds=settings.collector_rest_poll_interval_seconds,
        on_data=lambda d: handle_long_short_data(app, d),
    )

    ws_task = asyncio.create_task(ws_client.connect())
    poller_task = asyncio.create_task(rest_poller.run())

    async def outcome_loop():
        while True:
            try:
                await check_pending_signals(app)
            except Exception as e:
                logger.error(f"Outcome check failed: {e}")
            await asyncio.sleep(60)

    outcome_task = asyncio.create_task(outcome_loop())

    yield

    await ws_client.stop()
    rest_poller.stop()
    ws_task.cancel()
    poller_task.cancel()
    outcome_task.cancel()
    await redis.close()
    await db.close()


def create_app(lifespan_override=None) -> FastAPI:
    app = FastAPI(title="Krypton", version="0.1.0", lifespan=lifespan_override or lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    router = create_router()
    app.include_router(router)

    from app.api.ws import router as ws_router
    app.include_router(ws_router)

    from app.api.push import router as push_router
    app.include_router(push_router)

    from app.api.candles import router as candles_router
    app.include_router(candles_router)

    from app.api.account import router as account_router
    app.include_router(account_router)

    return app


app = create_app()
