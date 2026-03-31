"""Pipeline settings API: GET/PUT for DB-backed pipeline configuration."""

import asyncio
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.auth import require_auth
from app.db.models import PipelineSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline")

VALID_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}
PAIR_PATTERN = re.compile(r"^[A-Z]+-USDT-SWAP$")

# Maps DB column names → Settings field names (where they differ)
_DB_TO_SETTINGS = {
    "signal_threshold": "engine_signal_threshold",
    "news_alerts_enabled": "news_high_impact_push_enabled",
    "news_context_window": "news_llm_context_window_minutes",
    "cooldown_max_candles": "engine_cooldown_max_candles",
}


class PipelineSettingsUpdate(BaseModel):
    pairs: list[str] | None = None
    timeframes: list[str] | None = None
    signal_threshold: int | None = Field(None, ge=0, le=100)
    onchain_enabled: bool | None = None
    news_alerts_enabled: bool | None = None
    news_context_window: int | None = Field(None, ge=1, le=1440)
    cooldown_max_candles: int | None = Field(None, ge=0, le=10)

    @field_validator("pairs")
    @classmethod
    def validate_pairs(cls, v):
        if v is not None:
            if len(v) == 0:
                raise ValueError("pairs must not be empty")
            for p in v:
                if not PAIR_PATTERN.match(p):
                    raise ValueError(f"Invalid pair format: {p}")
        return v

    @field_validator("timeframes")
    @classmethod
    def validate_timeframes(cls, v):
        if v is not None:
            if len(v) == 0:
                raise ValueError("timeframes must not be empty")
            for tf in v:
                if tf not in VALID_TIMEFRAMES:
                    raise ValueError(f"Invalid timeframe: {tf}")
        return v


def _row_to_dict(ps: PipelineSettings) -> dict:
    return {
        "pairs": ps.pairs,
        "timeframes": ps.timeframes,
        "signal_threshold": ps.signal_threshold,
        "onchain_enabled": ps.onchain_enabled,
        "news_alerts_enabled": ps.news_alerts_enabled,
        "news_context_window": ps.news_context_window,
        "cooldown_max_candles": ps.cooldown_max_candles,
        "updated_at": ps.updated_at.isoformat() if ps.updated_at else None,
    }


@router.get("/settings")
async def get_pipeline_settings(
    request: Request, _key: str = require_auth()
):
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            select(PipelineSettings).where(PipelineSettings.id == 1)
        )
        ps = result.scalar_one_or_none()
        if not ps:
            raise HTTPException(500, "Pipeline settings not initialized")
        return _row_to_dict(ps)


@router.put("/settings")
async def update_pipeline_settings(
    request: Request,
    body: PipelineSettingsUpdate,
    _key: str = require_auth(),
):
    app = request.app
    db = app.state.db
    settings = app.state.settings
    lock = app.state.pipeline_settings_lock

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(400, "No fields to update")

    async with lock:
        async with db.session_factory() as session:
            result = await session.execute(
                select(PipelineSettings).where(PipelineSettings.id == 1)
            )
            ps = result.scalar_one_or_none()
            if not ps:
                raise HTTPException(500, "Pipeline settings not initialized")

            # Track whether pairs/timeframes changed for collector restart
            old_pairs = list(ps.pairs)
            old_timeframes = list(ps.timeframes)

            for field, value in update_data.items():
                setattr(ps, field, value)
            ps.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(ps)

            # Patch app.state.settings in-memory
            for db_field, value in update_data.items():
                settings_field = _DB_TO_SETTINGS.get(db_field, db_field)
                object.__setattr__(settings, settings_field, value)

            pairs_changed = update_data.get("pairs") is not None and ps.pairs != old_pairs
            tf_changed = update_data.get("timeframes") is not None and ps.timeframes != old_timeframes

            # Deactivate alerts targeting removed pairs
            deactivated_count = 0
            if pairs_changed:
                removed_pairs = set(old_pairs) - set(ps.pairs)
                if removed_pairs:
                    from app.db.models import Alert
                    alert_result = await session.execute(
                        select(Alert).where(
                            Alert.pair.in_(removed_pairs),
                            Alert.is_active == True,
                        )
                    )
                    stale_alerts = alert_result.scalars().all()
                    for a in stale_alerts:
                        a.is_active = False
                    deactivated_count = len(stale_alerts)
                    if deactivated_count:
                        await session.commit()
                        # Invalidate price alert cache
                        redis = getattr(app.state, "redis", None)
                        if redis:
                            await redis.delete("alerts:price")

            if pairs_changed or tf_changed:
                await _restart_collectors(app, ps.pairs, ps.timeframes)

            resp = _row_to_dict(ps)
            if deactivated_count:
                resp["deactivated_alerts_count"] = deactivated_count
            return resp


async def _restart_collectors(app, new_pairs: list[str], new_timeframes: list[str]):
    """Restart/update all collectors when pairs or timeframes change."""
    from app.main import backfill_candles, handle_candle_tick, handle_funding_rate, handle_open_interest

    # 1. Restart WebSocket client (stop old, create new)
    old_client = getattr(app.state, "ws_client", None)
    old_task = getattr(app.state, "ws_task", None)
    if old_client:
        await old_client.stop()
    if old_task:
        old_task.cancel()

    from app.collector.ws_client import OKXWebSocketClient

    new_client = OKXWebSocketClient(
        pairs=new_pairs,
        timeframes=new_timeframes,
        on_candle=lambda c: handle_candle_tick(app, c),
        on_funding_rate=lambda d: handle_funding_rate(app, d),
        on_open_interest=lambda d: handle_open_interest(app, d),
    )
    app.state.ws_client = new_client
    app.state.ws_task = asyncio.create_task(new_client.connect())

    # 2. Patch REST poller pairs in-place
    rest_poller = getattr(app.state, "rest_poller", None)
    if rest_poller:
        rest_poller.pairs = new_pairs

    # 3. Patch on-chain collector pairs in-place
    onchain_collector = getattr(app.state, "onchain_collector", None)
    if onchain_collector:
        onchain_collector.pairs = new_pairs

    # 4. Patch news collector pairs in-place
    news_collector = getattr(app.state, "news_collector", None)
    if news_collector:
        news_collector.pairs = new_pairs

    # 5. Backfill candles for newly added pairs/timeframes
    redis = app.state.redis
    db = app.state.db
    await backfill_candles(redis, db, new_pairs, new_timeframes)

    # 6. Restart ticker collector with new pairs (update pairs + signal reconnect)
    ticker_collector = getattr(app.state, "ticker_collector", None)
    if ticker_collector:
        ticker_collector.pairs = new_pairs
        ticker_collector.request_reconnect()

    logger.info("Collectors restarted with pairs=%s timeframes=%s", new_pairs, new_timeframes)
