"""Risk management API routes: settings CRUD and risk check endpoint."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.auth import require_auth
from app.db.models import RiskSettings, Signal
from app.engine.risk import RiskGuard

router = APIRouter(prefix="/api/risk")


class RiskSettingsUpdate(BaseModel):
    risk_per_trade: float | None = Field(None, gt=0, le=0.1)
    max_position_size_usd: float | None = Field(None, gt=0)
    daily_loss_limit_pct: float | None = Field(None, gt=0, le=0.5)
    max_concurrent_positions: int | None = Field(None, ge=1, le=20)
    max_exposure_pct: float | None = Field(None, gt=0, le=5.0)
    cooldown_after_loss_minutes: int | None = Field(None, ge=0)
    max_risk_per_trade_pct: float | None = Field(None, gt=0, le=0.5)


class RiskCheckRequest(BaseModel):
    pair: str
    direction: str
    size_usd: float = Field(gt=0)


def _settings_to_dict(rs: RiskSettings) -> dict:
    return {
        "risk_per_trade": rs.risk_per_trade,
        "max_position_size_usd": rs.max_position_size_usd,
        "daily_loss_limit_pct": rs.daily_loss_limit_pct,
        "max_concurrent_positions": rs.max_concurrent_positions,
        "max_exposure_pct": rs.max_exposure_pct,
        "cooldown_after_loss_minutes": rs.cooldown_after_loss_minutes,
        "max_risk_per_trade_pct": rs.max_risk_per_trade_pct,
        "updated_at": rs.updated_at.isoformat() if rs.updated_at else None,
    }


@router.get("/settings")
async def get_risk_settings(request: Request, _key: str = require_auth()):
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(select(RiskSettings).where(RiskSettings.id == 1))
        rs = result.scalar_one_or_none()
        if not rs:
            raise HTTPException(500, "Risk settings not initialized")
        return _settings_to_dict(rs)


@router.put("/settings")
async def update_risk_settings(
    request: Request,
    body: RiskSettingsUpdate,
    _key: str = require_auth(),
):
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(select(RiskSettings).where(RiskSettings.id == 1))
        rs = result.scalar_one_or_none()
        if not rs:
            raise HTTPException(500, "Risk settings not initialized")

        update_data = body.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(rs, field, value)
        rs.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return _settings_to_dict(rs)


@router.post("/check")
async def check_risk(
    request: Request,
    body: RiskCheckRequest,
    _key: str = require_auth(),
):
    okx = request.app.state.okx_client
    if not okx:
        raise HTTPException(503, "OKX client not configured")

    db = request.app.state.db

    # Load risk settings
    async with db.session_factory() as session:
        result = await session.execute(select(RiskSettings).where(RiskSettings.id == 1))
        rs = result.scalar_one_or_none()

    if not rs:
        raise HTTPException(500, "Risk settings not initialized")

    settings_dict = {
        "daily_loss_limit_pct": rs.daily_loss_limit_pct,
        "max_concurrent_positions": rs.max_concurrent_positions,
        "max_exposure_pct": rs.max_exposure_pct,
        "cooldown_after_loss_minutes": rs.cooldown_after_loss_minutes,
        "max_risk_per_trade_pct": rs.max_risk_per_trade_pct,
    }

    try:
        balance = await okx.get_balance()
        if not balance:
            raise HTTPException(502, "Failed to fetch balance")
        equity = balance["total_equity"]

        positions = await okx.get_positions()
        total_exposure = sum(
            abs(p.get("size", 0) * p.get("mark_price", 0)) for p in positions
        )

        # Get daily P&L from fills
        daily_pnl_pct = 0.0
        try:
            redis = request.app.state.redis
            cached_fills = await redis.get("daily_fills")
            if cached_fills:
                import json
                fills = json.loads(cached_fills)
            else:
                fills = await okx.get_fills_today()
                import json
                await redis.set("daily_fills", json.dumps(fills), ex=60)

            daily_pnl = sum(f.get("pnl", 0) for f in fills)
            daily_pnl_pct = daily_pnl / equity if equity > 0 else 0
        except Exception:
            pass

        # Find last SL_HIT signal
        last_sl_hit_at = None
        if rs.cooldown_after_loss_minutes:
            async with db.session_factory() as session:
                result = await session.execute(
                    select(Signal)
                    .where(Signal.outcome == "SL_HIT")
                    .order_by(Signal.outcome_at.desc())
                    .limit(1)
                )
                last_sl = result.scalar_one_or_none()
                if last_sl and last_sl.outcome_at:
                    last_sl_hit_at = last_sl.outcome_at

        guard = RiskGuard(settings_dict)
        return guard.check(
            equity=equity,
            size_usd=body.size_usd,
            daily_pnl_pct=daily_pnl_pct,
            open_positions_count=len(positions),
            total_exposure_usd=total_exposure,
            last_sl_hit_at=last_sl_hit_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Risk check failed: {str(e)}")
