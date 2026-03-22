"""Risk management API routes: settings CRUD and risk check endpoint."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, and_

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


class RiskStateResponse(BaseModel):
    equity: float
    daily_pnl_pct: float
    open_positions_count: int
    total_exposure_usd: float
    exposure_pct: float
    last_sl_hit_at: str | None


class RiskRuleResponse(BaseModel):
    rule: str
    status: str  # "OK" | "WARNING" | "BLOCKED"
    reason: str


class RiskStatusResponse(BaseModel):
    settings: dict
    state: RiskStateResponse
    rules: list[RiskRuleResponse]
    overall_status: str  # "OK" | "WARNING" | "BLOCKED"


@router.get("/status")
async def get_risk_status(request: Request, _user=require_auth()):
    db = request.app.state.db
    okx = request.app.state.okx_client

    # 1. Load risk settings + daily P&L + last SL hit (single session)
    async with db.session_factory() as session:
        result = await session.execute(
            select(RiskSettings).where(RiskSettings.id == 1)
        )
        rs = result.scalar_one_or_none()
        if not rs:
            raise HTTPException(500, "Risk settings not initialized")

        settings_dict = _settings_to_dict(rs)

        # Daily P&L from resolved signals
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        result = await session.execute(
            select(Signal).where(
                and_(
                    Signal.outcome.in_(["TP1_HIT", "TP2_HIT", "SL_HIT"]),
                    Signal.outcome_at >= today_start,
                )
            )
        )
        resolved = result.scalars().all()

        # Last SL hit timestamp (for cooldown)
        last_sl_hit_dt = None
        if rs.cooldown_after_loss_minutes:
            result = await session.execute(
                select(Signal)
                .where(Signal.outcome == "SL_HIT")
                .order_by(Signal.outcome_at.desc())
                .limit(1)
            )
            last_sl = result.scalar_one_or_none()
            if last_sl and last_sl.outcome_at:
                last_sl_hit_dt = last_sl.outcome_at

    # 2. Compute daily P&L
    daily_pnl_pct = 0.0
    if resolved:
        raw_sum = sum(
            float(s.outcome_pnl_pct) for s in resolved if s.outcome_pnl_pct is not None
        )
        # DB stores percentage values (e.g. -1.5 for -1.5%), convert to decimal fraction
        daily_pnl_pct = raw_sum / 100.0

    # 3. Gather live state from OKX (zeros if unavailable)
    equity = 0.0
    open_positions_count = 0
    total_exposure_usd = 0.0
    exposure_pct = 0.0

    if okx:
        try:
            balance, positions = await asyncio.gather(
                okx.get_balance(), okx.get_positions()
            )
            equity = balance["total_equity"] if balance else 0.0
            open_positions_count = len(positions)
            total_exposure_usd = sum(
                abs(p.get("size", 0) * p.get("mark_price", 0)) for p in positions
            )
            exposure_pct = total_exposure_usd / equity if equity > 0 else 0.0
        except Exception:
            pass

    # 5. Evaluate rules
    rules = []

    # daily_loss_limit
    usage_pct = abs(daily_pnl_pct) / rs.daily_loss_limit_pct if rs.daily_loss_limit_pct else 0
    remaining_pct = (rs.daily_loss_limit_pct - abs(daily_pnl_pct)) * 100
    if abs(daily_pnl_pct) >= rs.daily_loss_limit_pct:
        rules.append(RiskRuleResponse(
            rule="daily_loss_limit",
            status="BLOCKED",
            reason=f"Daily P&L {daily_pnl_pct*100:.1f}% hit {rs.daily_loss_limit_pct*100:.0f}% limit",
        ))
    elif usage_pct > 0.7:
        rules.append(RiskRuleResponse(
            rule="daily_loss_limit",
            status="WARNING",
            reason=f"Daily P&L {daily_pnl_pct*100:.1f}%, {remaining_pct:.1f}% remaining",
        ))
    else:
        rules.append(RiskRuleResponse(
            rule="daily_loss_limit",
            status="OK",
            reason=f"Daily P&L {daily_pnl_pct*100:.1f}%, {remaining_pct:.1f}% remaining",
        ))

    # max_concurrent
    if open_positions_count >= rs.max_concurrent_positions:
        rules.append(RiskRuleResponse(
            rule="max_concurrent",
            status="BLOCKED",
            reason=f"{open_positions_count}/{rs.max_concurrent_positions} positions open",
        ))
    elif (
        open_positions_count >= rs.max_concurrent_positions - 1
        and rs.max_concurrent_positions >= 3
    ):
        rules.append(RiskRuleResponse(
            rule="max_concurrent",
            status="WARNING",
            reason=f"{open_positions_count}/{rs.max_concurrent_positions} positions open",
        ))
    else:
        rules.append(RiskRuleResponse(
            rule="max_concurrent",
            status="OK",
            reason=f"{open_positions_count}/{rs.max_concurrent_positions} positions open",
        ))

    # max_exposure
    exp_usage = exposure_pct / rs.max_exposure_pct if rs.max_exposure_pct else 0
    if exposure_pct > rs.max_exposure_pct:
        rules.append(RiskRuleResponse(
            rule="max_exposure",
            status="BLOCKED",
            reason=f"Exposure {exposure_pct*100:.0f}% exceeds {rs.max_exposure_pct*100:.0f}% limit",
        ))
    elif exp_usage > 0.8:
        rules.append(RiskRuleResponse(
            rule="max_exposure",
            status="WARNING",
            reason=f"Exposure {exposure_pct*100:.0f}% approaching {rs.max_exposure_pct*100:.0f}% limit",
        ))
    else:
        rules.append(RiskRuleResponse(
            rule="max_exposure",
            status="OK",
            reason=f"Exposure {exposure_pct*100:.0f}% of {rs.max_exposure_pct*100:.0f}% limit",
        ))

    # cooldown (omitted when not configured or not triggered)
    if rs.cooldown_after_loss_minutes and last_sl_hit_dt:
        elapsed = (datetime.now(timezone.utc) - last_sl_hit_dt).total_seconds()
        remaining = rs.cooldown_after_loss_minutes * 60 - elapsed
        if remaining > 0:
            mins_left = int(remaining // 60)
            rules.append(RiskRuleResponse(
                rule="cooldown",
                status="WARNING",
                reason=f"Cooldown active, {mins_left}min remaining",
            ))

    # 6. Overall status
    statuses = [r.status for r in rules]
    if "BLOCKED" in statuses:
        overall = "BLOCKED"
    elif "WARNING" in statuses:
        overall = "WARNING"
    else:
        overall = "OK"

    return RiskStatusResponse(
        settings=settings_dict,
        state=RiskStateResponse(
            equity=equity,
            daily_pnl_pct=daily_pnl_pct,
            open_positions_count=open_positions_count,
            total_exposure_usd=total_exposure_usd,
            exposure_pct=exposure_pct,
            last_sl_hit_at=last_sl_hit_dt.isoformat() if last_sl_hit_dt else None,
        ),
        rules=rules,
        overall_status=overall,
    )
