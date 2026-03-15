"""Alert CRUD API + settings + history endpoints."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update

from app.api.auth import require_settings_api_key
from app.db.models import Alert, AlertHistory, AlertSettings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/alerts")

VALID_ALERT_TYPES = {"price", "signal", "indicator", "portfolio"}
VALID_CONDITIONS = {
    "crosses_above", "crosses_below", "pct_move", "gt", "lt",
    "drawdown_pct", "pnl_crosses", "position_loss_pct",
    "rsi_above", "rsi_below", "adx_above",
    "bb_width_percentile_above", "bb_width_percentile_below",
    "funding_rate_above", "funding_rate_below",
}
VALID_URGENCIES = {"critical", "normal", "silent"}
VALID_TIMEFRAMES = {"15m", "1h", "4h"}
MAX_ACTIVE_ALERTS = 50


class AlertCreate(BaseModel):
    type: str
    label: str | None = None
    pair: str | None = None
    timeframe: str | None = None
    condition: str | None = None
    threshold: float | None = None
    secondary_threshold: float | None = Field(None, ge=5, le=60)
    filters: dict | None = None
    urgency: str = "normal"
    cooldown_minutes: int = Field(15, ge=1, le=1440)
    is_one_shot: bool = False

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v not in VALID_ALERT_TYPES:
            raise ValueError(f"Invalid alert type: {v}")
        return v

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, v):
        if v not in VALID_URGENCIES:
            raise ValueError(f"Invalid urgency: {v}")
        return v

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, v):
        if v is not None and v not in VALID_CONDITIONS:
            raise ValueError(f"Invalid condition: {v}")
        return v

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, v):
        if v is not None and v not in VALID_TIMEFRAMES:
            raise ValueError(f"Invalid timeframe: {v}")
        return v


class AlertUpdate(BaseModel):
    label: str | None = None
    threshold: float | None = None
    secondary_threshold: float | None = Field(None, ge=5, le=60)
    urgency: str | None = None
    cooldown_minutes: int | None = Field(None, ge=1, le=1440)
    is_active: bool | None = None
    filters: dict | None = None

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, v):
        if v is not None and v not in VALID_URGENCIES:
            raise ValueError(f"Invalid urgency: {v}")
        return v


class AlertSettingsUpdate(BaseModel):
    quiet_hours_enabled: bool | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    quiet_hours_tz: str | None = None


def _alert_to_dict(a: Alert) -> dict:
    return {
        "id": a.id,
        "type": a.type,
        "label": a.label,
        "pair": a.pair,
        "timeframe": a.timeframe,
        "condition": a.condition,
        "threshold": a.threshold,
        "secondary_threshold": a.secondary_threshold,
        "filters": a.filters,
        "urgency": a.urgency,
        "cooldown_minutes": a.cooldown_minutes,
        "is_active": a.is_active,
        "is_one_shot": a.is_one_shot,
        "last_triggered_at": a.last_triggered_at.isoformat() if a.last_triggered_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _generate_label(body: AlertCreate) -> str:
    pair_part = body.pair or "Any pair"
    if body.type == "price":
        return f"{pair_part} {body.condition} {body.threshold}"
    elif body.type == "signal":
        return f"Signal alert ({pair_part})"
    elif body.type == "indicator":
        return f"{body.condition} on {pair_part}"
    elif body.type == "portfolio":
        return f"Portfolio {body.condition}"
    return "Alert"


@router.post("")
async def create_alert(
    request: Request, body: AlertCreate, _key: str = require_settings_api_key()
):
    db = request.app.state.db
    redis = getattr(request.app.state, "redis", None)

    # Validate type-specific requirements
    if body.type != "signal" and body.threshold is None:
        raise HTTPException(422, "threshold required for non-signal alerts")
    if body.type == "price" and body.threshold is not None and body.threshold <= 0:
        raise HTTPException(422, "price threshold must be positive")
    if body.type == "signal" and not body.filters:
        body.filters = {}

    # Validate pair against active pipeline pairs
    if body.pair:
        settings = request.app.state.settings
        if body.pair not in settings.pairs:
            raise HTTPException(422, f"Pair {body.pair} is not in active pairs list")

    async with db.session_factory() as session:
        # Check active alert limit
        count = await session.scalar(
            select(func.count()).select_from(Alert).where(Alert.is_active == True)
        )
        if count >= MAX_ACTIVE_ALERTS:
            raise HTTPException(409, f"Maximum {MAX_ACTIVE_ALERTS} active alerts reached")

        label = body.label or _generate_label(body)
        is_one_shot = body.is_one_shot
        if body.type == "price" and body.condition in ("crosses_above", "crosses_below"):
            is_one_shot = True  # Price crosses are always one-shot

        alert = Alert(
            type=body.type,
            label=label,
            pair=body.pair,
            timeframe=body.timeframe,
            condition=body.condition,
            threshold=body.threshold,
            secondary_threshold=body.secondary_threshold,
            filters=body.filters if body.type == "signal" else None,
            urgency=body.urgency,
            cooldown_minutes=body.cooldown_minutes,
            is_one_shot=is_one_shot,
        )
        session.add(alert)
        await session.commit()
        await session.refresh(alert)

        # Invalidate price alert cache
        if redis and body.type == "price":
            await redis.delete("alerts:price")

        return _alert_to_dict(alert)


@router.get("")
async def list_alerts(
    request: Request, _key: str = require_settings_api_key()
):
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            select(Alert).where(Alert.is_active == True).order_by(Alert.created_at.desc())
        )
        alerts = result.scalars().all()
        return [_alert_to_dict(a) for a in alerts]


@router.get("/history")
async def get_alert_history(
    request: Request,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    offset: int = 0,
    _key: str = require_settings_api_key(),
):
    db = request.app.state.db

    # LEFT JOIN Alert to include label (survives alert deletion as NULL)
    query = (
        select(AlertHistory, Alert.label)
        .outerjoin(Alert, AlertHistory.alert_id == Alert.id)
        .order_by(AlertHistory.triggered_at.desc())
    )

    if since:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        query = query.where(AlertHistory.triggered_at >= since_dt)
    else:
        # Default: last 7 days
        query = query.where(
            AlertHistory.triggered_at >= datetime.now(timezone.utc) - timedelta(days=7)
        )
    if until:
        until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
        query = query.where(AlertHistory.triggered_at <= until_dt)

    query = query.offset(offset).limit(min(limit, 200))

    async with db.session_factory() as session:
        result = await session.execute(query)
        rows = result.all()
        return [
            {
                "id": h.id,
                "alert_id": h.alert_id,
                "alert_label": label,
                "triggered_at": h.triggered_at.isoformat(),
                "trigger_value": h.trigger_value,
                "delivery_status": h.delivery_status,
            }
            for h, label in rows
        ]


@router.get("/settings")
async def get_alert_settings(
    request: Request, _key: str = require_settings_api_key()
):
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            select(AlertSettings).where(AlertSettings.id == 1)
        )
        s = result.scalar_one_or_none()
        if not s:
            # Auto-create default row
            s = AlertSettings()
            session.add(s)
            await session.commit()
            await session.refresh(s)
        return {
            "quiet_hours_enabled": s.quiet_hours_enabled,
            "quiet_hours_start": s.quiet_hours_start,
            "quiet_hours_end": s.quiet_hours_end,
            "quiet_hours_tz": s.quiet_hours_tz,
        }


@router.patch("/settings")
async def update_alert_settings(
    request: Request, body: AlertSettingsUpdate,
    _key: str = require_settings_api_key(),
):
    db = request.app.state.db
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(400, "No fields to update")

    async with db.session_factory() as session:
        result = await session.execute(
            select(AlertSettings).where(AlertSettings.id == 1)
        )
        s = result.scalar_one_or_none()
        if not s:
            s = AlertSettings()
            session.add(s)
            await session.flush()

        for field, value in update_data.items():
            setattr(s, field, value)
        await session.commit()
        await session.refresh(s)

        return {
            "quiet_hours_enabled": s.quiet_hours_enabled,
            "quiet_hours_start": s.quiet_hours_start,
            "quiet_hours_end": s.quiet_hours_end,
            "quiet_hours_tz": s.quiet_hours_tz,
        }


# /{alert_id} routes must come AFTER /history and /settings to avoid path conflicts
@router.patch("/{alert_id}")
async def update_alert(
    request: Request, alert_id: str, body: AlertUpdate,
    _key: str = require_settings_api_key(),
):
    db = request.app.state.db
    redis = getattr(request.app.state, "redis", None)

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(400, "No fields to update")

    async with db.session_factory() as session:
        result = await session.execute(select(Alert).where(Alert.id == alert_id))
        alert = result.scalar_one_or_none()
        if not alert:
            raise HTTPException(404, "Alert not found")

        for field, value in update_data.items():
            setattr(alert, field, value)
        await session.commit()
        await session.refresh(alert)

        # Invalidate price alert cache
        if redis and alert.type == "price":
            await redis.delete("alerts:price")

        return _alert_to_dict(alert)


@router.delete("/{alert_id}")
async def delete_alert(
    request: Request, alert_id: str,
    _key: str = require_settings_api_key(),
):
    db = request.app.state.db
    redis = getattr(request.app.state, "redis", None)

    async with db.session_factory() as session:
        result = await session.execute(select(Alert).where(Alert.id == alert_id))
        alert = result.scalar_one_or_none()
        if not alert:
            raise HTTPException(404, "Alert not found")

        alert_type = alert.type
        await session.execute(delete(AlertHistory).where(AlertHistory.alert_id == alert_id))
        await session.execute(delete(Alert).where(Alert.id == alert_id))
        await session.commit()

        if redis and alert_type == "price":
            await redis.delete("alerts:price")

        return {"deleted": alert_id}
