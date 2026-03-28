"""Optimizer API — status, proposals, approve/reject/promote/rollback."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, desc

from app.api.auth import require_auth
from app.db.models import ParameterProposal, Signal, ShadowResult
from app.engine.optimizer import (
    OptimizerState,
    start_shadow,
    promote_proposal,
    reject_proposal,
    rollback_proposal,
    get_shadow_progress,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/optimizer", tags=["optimizer"])


async def _get_proposal(session, proposal_id: int) -> ParameterProposal:
    """Fetch a proposal or raise 404."""
    result = await session.execute(
        select(ParameterProposal).where(ParameterProposal.id == proposal_id)
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(404, "Proposal not found")
    return proposal


@router.get("/status")
async def get_status(request: Request, _key: str = require_auth()):
    """Return optimizer status: group health, global PF, active shadow."""
    optimizer: OptimizerState = request.app.state.optimizer
    groups = optimizer.group_health()
    active_shadow = None

    if optimizer.active_shadow_proposal_id:
        db = request.app.state.db
        async with db.session_factory() as session:
            progress = await get_shadow_progress(
                session, optimizer.active_shadow_proposal_id
            )
            result = await session.execute(
                select(ParameterProposal)
                .where(ParameterProposal.id == optimizer.active_shadow_proposal_id)
            )
            proposal = result.scalar_one_or_none()
            if proposal:
                active_shadow = {
                    "proposal_id": proposal.id,
                    "group": proposal.parameter_group,
                    "progress": progress,
                    "changes": proposal.changes,
                }

    return {
        "global_profit_factor": optimizer.profit_factor(),
        "resolved_count": optimizer.resolved_count,
        "groups": groups,
        "active_shadow": active_shadow,
    }


@router.get("/proposals")
async def get_proposals(
    request: Request,
    _key: str = require_auth(),
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
):
    """Return paginated proposal history."""
    db = request.app.state.db
    async with db.session_factory() as session:
        query = select(ParameterProposal).order_by(
            desc(ParameterProposal.created_at)
        )
        if status:
            query = query.where(ParameterProposal.status == status)
        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        proposals = result.scalars().all()
        return {
            "proposals": [
                {
                    "id": p.id,
                    "status": p.status,
                    "parameter_group": p.parameter_group,
                    "changes": p.changes,
                    "backtest_metrics": p.backtest_metrics,
                    "shadow_metrics": p.shadow_metrics,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "shadow_started_at": p.shadow_started_at.isoformat() if p.shadow_started_at else None,
                    "promoted_at": p.promoted_at.isoformat() if p.promoted_at else None,
                    "rejected_reason": p.rejected_reason,
                }
                for p in proposals
            ]
        }


class RejectBody(BaseModel):
    reason: str = ""


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: int,
    request: Request,
    _key: str = require_auth(),
):
    """Approve a pending proposal — starts shadow mode."""
    optimizer: OptimizerState = request.app.state.optimizer
    db = request.app.state.db

    if optimizer.active_shadow_proposal_id is not None:
        raise HTTPException(409, "Another shadow proposal is already active")

    async with db.session_factory() as session:
        proposal = await _get_proposal(session, proposal_id)
        if proposal.status != "pending":
            raise HTTPException(400, f"Proposal is {proposal.status}, not pending")

        await start_shadow(session, proposal_id)
        await session.commit()
        optimizer.active_shadow_proposal_id = proposal_id

    manager = request.app.state.manager
    await manager.broadcast({
        "type": "optimizer_update",
        "event": "shadow_started",
        "proposal_id": proposal_id,
    })

    return {"status": "shadow", "proposal_id": proposal_id}


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal_endpoint(
    proposal_id: int,
    body: RejectBody,
    request: Request,
    _key: str = require_auth(),
):
    """Reject a proposal."""
    optimizer: OptimizerState = request.app.state.optimizer
    db = request.app.state.db

    async with db.session_factory() as session:
        proposal = await _get_proposal(session, proposal_id)
        if proposal.status not in ("pending", "shadow"):
            raise HTTPException(400, f"Cannot reject proposal in {proposal.status} status")

        await reject_proposal(session, proposal_id, reason=body.reason)
        await session.commit()

        if optimizer.active_shadow_proposal_id == proposal_id:
            optimizer.active_shadow_proposal_id = None

    manager = request.app.state.manager
    await manager.broadcast({
        "type": "optimizer_update",
        "event": "proposal_rejected",
        "proposal_id": proposal_id,
    })

    return {"status": "rejected", "proposal_id": proposal_id}


@router.post("/proposals/{proposal_id}/promote")
async def promote_proposal_endpoint(
    proposal_id: int,
    request: Request,
    _key: str = require_auth(),
):
    """Manually promote a shadow proposal early."""
    optimizer: OptimizerState = request.app.state.optimizer
    db = request.app.state.db

    async with db.session_factory() as session:
        proposal = await _get_proposal(session, proposal_id)
        if proposal.status != "shadow":
            raise HTTPException(400, f"Cannot promote proposal in {proposal.status} status")

        progress = await get_shadow_progress(session, proposal_id)
        await promote_proposal(session, proposal_id, shadow_metrics=progress)
        await session.commit()

        if optimizer.active_shadow_proposal_id == proposal_id:
            optimizer.active_shadow_proposal_id = None
            optimizer.last_optimized[proposal.parameter_group] = optimizer.resolved_count
            pf = optimizer.profit_factor()
            if pf is not None:
                optimizer._pf_at_promotion[proposal_id] = pf

    manager = request.app.state.manager
    await manager.broadcast({
        "type": "optimizer_update",
        "event": "proposal_promoted",
        "proposal_id": proposal_id,
    })

    return {"status": "promoted", "proposal_id": proposal_id}


@router.post("/proposals/{proposal_id}/rollback")
async def rollback_proposal_endpoint(
    proposal_id: int,
    request: Request,
    _key: str = require_auth(),
):
    """Roll back a promoted proposal to previous parameter values."""
    db = request.app.state.db

    async with db.session_factory() as session:
        proposal = await _get_proposal(session, proposal_id)
        if proposal.status != "promoted":
            raise HTTPException(400, f"Cannot rollback proposal in {proposal.status} status")

        await rollback_proposal(session, proposal_id)
        await session.commit()

    manager = request.app.state.manager
    await manager.broadcast({
        "type": "optimizer_update",
        "event": "proposal_rolled_back",
        "proposal_id": proposal_id,
    })

    return {"status": "rolled_back", "proposal_id": proposal_id}


class OptimizeFromSignalsRequest(BaseModel):
    pair: str
    timeframe: str | None = None
    lookback_days: int = 90
    max_signals: int = 500
    min_signals: int = 20
    max_iterations: int = 300


@router.post("/optimize-from-signals")
async def optimize_from_signals_endpoint(
    request: Request,
    body: OptimizeFromSignalsRequest,
    _key: str = require_auth(),
):
    app = request.app

    if app.state.active_signal_optimization is not None:
        raise HTTPException(409, detail={
            "error": "optimization_running",
            "pair": app.state.active_signal_optimization["pair"],
        })

    since = datetime.now(timezone.utc) - timedelta(days=body.lookback_days)
    async with app.state.db.session_factory() as session:
        query = (
            select(Signal)
            .where(Signal.pair == body.pair)
            .where(Signal.outcome != "PENDING")
            .where(Signal.created_at >= since)
        )
        if body.timeframe:
            query = query.where(Signal.timeframe == body.timeframe)
        query = query.order_by(Signal.created_at.desc()).limit(body.max_signals)
        result = await session.execute(query)
        rows = result.scalars().all()

    signals = []
    for s in rows:
        ri = s.raw_indicators or {}
        if not ri.get("regime_trending"):
            continue  # need at least regime data
        if "tech_score" not in ri:
            ri = {
                **ri,
                "tech_score": s.traditional_score,
                "tech_confidence": ri.get("tech_confidence", 0.5),
                "flow_score": ri.get("flow_score", 0),
                "flow_confidence": ri.get("flow_confidence", 0.0),
                "onchain_score": ri.get("onchain_score", 0),
                "onchain_confidence": ri.get("onchain_confidence", 0.0),
                "pattern_score": ri.get("pattern_score", 0),
                "pattern_confidence": ri.get("pattern_confidence", 0.0),
                "liquidation_score": ri.get("liquidation_score", 0),
                "liquidation_confidence": ri.get("liquidation_confidence", 0.0),
                "confluence_score": ri.get("confluence_score", 0),
                "confluence_confidence": ri.get("confluence_confidence", 0.0),
                "regime_steady": ri.get("regime_steady", 0),
            }
        signals.append({
            "outcome": s.outcome,
            "outcome_pnl_pct": float(s.outcome_pnl_pct) if s.outcome_pnl_pct else 0.0,
            "entry": float(s.entry),
            "stop_loss": float(s.stop_loss),
            "take_profit_1": float(s.take_profit_1),
            "raw_indicators": ri,
        })

    if len(signals) < body.min_signals:
        raise HTTPException(400, detail={
            "error": "insufficient_signals",
            "available": len(signals),
            "required": body.min_signals,
        })

    cancel_flag = {"cancelled": False}
    app.state.active_signal_optimization = {"pair": body.pair, "cancel_flag": cancel_flag}

    manager = app.state.manager
    await manager.broadcast({
        "type": "optimizer_update",
        "event": "optimization_started",
        "pair": body.pair,
        "mode": "live_signals",
    })

    async def _run():
        from app.engine.regime_optimizer import optimize_from_signals

        try:
            opt_result = await asyncio.to_thread(
                optimize_from_signals,
                signals, body.pair,
                signal_threshold=app.state.settings.engine_signal_threshold,
                max_iterations=body.max_iterations,
                cancel_flag=cancel_flag,
            )

            # Create proposal
            async with app.state.db.session_factory() as session:
                proposal = ParameterProposal(
                    status="pending",
                    parameter_group="regime_outer_weights",
                    changes=opt_result["weights"],
                    backtest_metrics={
                        "optimization_mode": "live_signals",
                        "fitness": opt_result["fitness"],
                        "evaluations": opt_result["evaluations"],
                        "signals_used": len(signals),
                        "pair": body.pair,
                        "profit_factor": 0,
                        "win_rate": 0,
                        "avg_rr": 0,
                        "drawdown": 0,
                        "signals_tested": len(signals),
                    },
                )
                session.add(proposal)
                await session.commit()
                await session.refresh(proposal)
                proposal_id = proposal.id

            await manager.broadcast({
                "type": "optimizer_update",
                "event": "optimization_completed",
                "proposal_id": proposal_id,
                "mode": "live_signals",
            })
        except Exception as e:
            logger.exception("Signal optimization failed: %s", e)
            await manager.broadcast({
                "type": "optimizer_update",
                "event": "optimization_failed",
                "pair": body.pair,
                "mode": "live_signals",
                "error": str(e),
            })
        finally:
            app.state.active_signal_optimization = None

    asyncio.create_task(_run())

    return {"status": "started", "pair": body.pair, "signals_queued": len(signals)}
