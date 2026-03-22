"""Engine parameter optimizer.

Monitors global signal fitness, identifies underperforming parameter groups
via counterfactual backtesting, proposes changes, and manages shadow mode
validation before promotion.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ParameterProposal, ShadowResult, Signal
from app.engine.param_groups import PARAM_GROUPS, PRIORITY_LAYERS, validate_candidate

logger = logging.getLogger(__name__)

OPTIMIZER_CONFIG = {
    "min_signals_for_eval": 50,      # min resolved signals before any optimization
    "shadow_signal_count": 20,       # signals to shadow-test before promoting
    "improvement_threshold": 0.05,   # 5% profit factor improvement required
    "rollback_drop_pct": 0.15,       # auto-rollback if PF drops 15%
    "rollback_window": 10,           # check last N signals for rollback
    "cooldown_signals": 50,          # min signals between optimizations per group
    "window_size": 100,              # rolling window for fitness
}


class OptimizerState:
    """In-memory optimizer state tracking."""

    def __init__(self) -> None:
        self.resolved_count: int = 0
        self.global_pnl_history: list[float] = []
        self.active_shadow_proposal_id: int | None = None
        self.last_optimized: dict[str, int] = {}  # group -> resolved_count at last optimization
        self._pf_at_promotion: dict[int, float] = {}  # proposal_id -> PF when promoted

    def record_resolution(self, pnl_pct: float) -> None:
        self.resolved_count += 1
        self.global_pnl_history.append(pnl_pct)
        # Keep bounded
        if len(self.global_pnl_history) > OPTIMIZER_CONFIG["window_size"] * 2:
            self.global_pnl_history = self.global_pnl_history[-OPTIMIZER_CONFIG["window_size"]:]

    def profit_factor(self, window: int | None = None) -> float | None:
        history = self.global_pnl_history
        if window:
            history = history[-window:]
        if not history:
            return None
        return _compute_pf(history)

    def needs_eval(self, group_name: str) -> bool:
        if self.resolved_count < OPTIMIZER_CONFIG["min_signals_for_eval"]:
            return False
        last = self.last_optimized.get(group_name, 0)
        return (self.resolved_count - last) >= OPTIMIZER_CONFIG["cooldown_signals"]

    def can_propose(self, group_name: str) -> bool:
        if self.active_shadow_proposal_id is not None:
            return False
        return True

    def group_health(self) -> list[dict[str, Any]]:
        """Return health info for all groups."""
        pf = self.profit_factor()
        result = []
        for name, group in PARAM_GROUPS.items():
            last = self.last_optimized.get(name, 0)
            signals_since = self.resolved_count - last
            result.append({
                "group": name,
                "priority": group["priority"],
                "profit_factor": pf,
                "signals_since_last_opt": signals_since,
                "needs_eval": self.needs_eval(name),
                "status": "green" if not self.needs_eval(name) else "yellow",
            })
        return sorted(result, key=lambda x: x["priority"])

    def check_rollback_needed(self, proposal_id: int) -> bool:
        """Check if a recently promoted proposal should be rolled back."""
        baseline_pf = self._pf_at_promotion.get(proposal_id)
        if baseline_pf is None or baseline_pf == 0:
            return False
        current_pf = self.profit_factor(window=OPTIMIZER_CONFIG["rollback_window"])
        if current_pf is None:
            return False
        if baseline_pf == float("inf"):
            return current_pf < float("inf")
        drop = (baseline_pf - current_pf) / baseline_pf
        return drop > OPTIMIZER_CONFIG["rollback_drop_pct"]


def _compute_pf(pnls: list[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p < 0))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def evaluate_shadow_results(
    current_pnls: list[float],
    shadow_pnls: list[float],
) -> str:
    """Compare current vs shadow PnLs. Returns 'promote', 'reject', or 'inconclusive'."""
    if not current_pnls or not shadow_pnls:
        return "inconclusive"
    current_pf = _compute_pf(current_pnls)
    shadow_pf = _compute_pf(shadow_pnls)
    if current_pf == 0:
        return "promote" if shadow_pf > 0 else "inconclusive"
    relative_diff = (shadow_pf - current_pf) / current_pf if current_pf != float("inf") else 0
    if shadow_pf > current_pf:
        return "promote"
    if relative_diff < -0.10:
        return "reject"
    return "inconclusive"


async def create_proposal(
    session: AsyncSession,
    group_name: str,
    changes: dict[str, dict],
    backtest_metrics: dict,
) -> ParameterProposal:
    """Create a new parameter proposal."""
    proposal = ParameterProposal(
        status="pending",
        parameter_group=group_name,
        changes=changes,
        backtest_metrics=backtest_metrics,
    )
    session.add(proposal)
    await session.flush()
    return proposal


async def start_shadow(
    session: AsyncSession,
    proposal_id: int,
) -> None:
    """Transition a proposal to shadow mode."""
    result = await session.execute(
        select(ParameterProposal).where(ParameterProposal.id == proposal_id)
    )
    proposal = result.scalar_one()
    proposal.status = "shadow"
    proposal.shadow_started_at = datetime.now(timezone.utc)
    await session.flush()


async def promote_proposal(
    session: AsyncSession,
    proposal_id: int,
    shadow_metrics: dict | None = None,
) -> None:
    """Promote a shadow proposal to active parameters."""
    result = await session.execute(
        select(ParameterProposal).where(ParameterProposal.id == proposal_id)
    )
    proposal = result.scalar_one()
    proposal.status = "promoted"
    proposal.promoted_at = datetime.now(timezone.utc)
    if shadow_metrics:
        proposal.shadow_metrics = shadow_metrics
    await session.flush()


async def reject_proposal(
    session: AsyncSession,
    proposal_id: int,
    reason: str = "",
    shadow_metrics: dict | None = None,
) -> None:
    """Reject a proposal."""
    result = await session.execute(
        select(ParameterProposal).where(ParameterProposal.id == proposal_id)
    )
    proposal = result.scalar_one()
    proposal.status = "rejected"
    proposal.rejected_reason = reason
    if shadow_metrics:
        proposal.shadow_metrics = shadow_metrics
    await session.flush()


async def rollback_proposal(
    session: AsyncSession,
    proposal_id: int,
) -> ParameterProposal:
    """Roll back a promoted proposal."""
    result = await session.execute(
        select(ParameterProposal).where(ParameterProposal.id == proposal_id)
    )
    proposal = result.scalar_one()
    proposal.status = "rolled_back"
    await session.flush()
    return proposal


async def record_shadow_result(
    session: AsyncSession,
    proposal_id: int,
    signal_id: int,
    shadow_score: float,
    shadow_entry: float,
    shadow_sl: float,
    shadow_tp1: float,
    shadow_tp2: float,
) -> ShadowResult:
    """Store a shadow scoring result for a signal."""
    sr = ShadowResult(
        proposal_id=proposal_id,
        signal_id=signal_id,
        shadow_score=shadow_score,
        shadow_entry=shadow_entry,
        shadow_sl=shadow_sl,
        shadow_tp1=shadow_tp1,
        shadow_tp2=shadow_tp2,
    )
    session.add(sr)
    await session.flush()
    return sr


async def get_shadow_progress(
    session: AsyncSession,
    proposal_id: int,
) -> dict:
    """Get shadow mode progress for a proposal."""
    result = await session.execute(
        select(
            func.count(ShadowResult.id),
            func.count(ShadowResult.shadow_outcome),
        ).where(ShadowResult.proposal_id == proposal_id)
    )
    total, resolved = result.one()
    return {
        "total": total,
        "resolved": resolved,
        "target": OPTIMIZER_CONFIG["shadow_signal_count"],
        "complete": resolved >= OPTIMIZER_CONFIG["shadow_signal_count"],
    }


async def run_counterfactual_eval(
    app,
    group_name: str,
) -> dict | None:
    """Run counterfactual backtest for a parameter group.

    Re-runs the backtester with the group's parameters perturbed (sweep)
    while all other parameters stay fixed. Returns the best candidate
    and its metrics if it beats current by > improvement_threshold.
    """
    from app.engine.param_groups import get_group, validate_candidate

    group = get_group(group_name)
    if not group:
        return None

    db = app.state.db
    settings = app.state.settings

    # Get recent candles for backtest
    async with db.session_factory() as session:
        from app.db.models import Candle
        for pair in ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]:
            result = await session.execute(
                select(Candle)
                .where(Candle.pair == pair)
                .where(Candle.timeframe == "15m")
                .order_by(Candle.timestamp.desc())
                .limit(500)
            )
            candles = list(reversed(result.scalars().all()))
            if len(candles) < 100:
                continue

            # Build candidates based on sweep method
            if group["sweep_method"] == "grid":
                import itertools

                # Generate grid candidates
                param_names = list(group["sweep_ranges"].keys())
                param_values = []
                for name in param_names:
                    lo, hi, step = group["sweep_ranges"][name]
                    vals = []
                    v = lo
                    while v <= hi + 1e-9:
                        vals.append(round(v, 4))
                        v += step
                    param_values.append(vals)

                best_pf = 0.0
                best_candidate = None
                best_metrics = None

                for combo in itertools.product(*param_values):
                    candidate = dict(zip(param_names, combo))
                    if not validate_candidate(group_name, candidate):
                        continue

                    try:
                        from app.engine.backtester import run_backtest, BacktestConfig
                        import asyncio

                        config = BacktestConfig(
                            pair=pair,
                            timeframe="15m",
                            signal_threshold=candidate.get("signal", settings.engine_signal_threshold),
                        )
                        loop = asyncio.get_event_loop()
                        results = await loop.run_in_executor(
                            None,
                            lambda: run_backtest(
                                candles=candles,
                                pair=pair,
                                config=config,
                                cancel_flag=None,
                            ),
                        )
                        pf = results.get("profit_factor", 0) or 0
                        if pf > best_pf:
                            best_pf = pf
                            best_candidate = candidate
                            best_metrics = results
                    except Exception:
                        continue

                if best_candidate and best_metrics:
                    return {
                        "candidate": best_candidate,
                        "metrics": {
                            "profit_factor": best_metrics.get("profit_factor", 0),
                            "win_rate": best_metrics.get("win_rate", 0),
                            "avg_rr": best_metrics.get("avg_rr", 0),
                            "drawdown": best_metrics.get("max_drawdown", 0),
                            "signals_tested": best_metrics.get("total_trades", 0),
                        },
                    }
            else:
                # DE-based groups: skip for now
                logger.info("DE sweep for %s not yet wired — skipping", group_name)
                return None

    return None


async def run_optimizer_loop(app) -> None:
    """Background loop that monitors parameter fitness and manages optimization."""
    import asyncio

    state: OptimizerState = app.state.optimizer
    db = app.state.db
    manager = app.state.manager
    last_checked_count = 0

    while True:
        try:
            await asyncio.sleep(60)

            if state.resolved_count <= last_checked_count:
                continue
            last_checked_count = state.resolved_count

            # 1. Check rollback on recently promoted proposals
            async with db.session_factory() as session:
                result = await session.execute(
                    select(ParameterProposal)
                    .where(ParameterProposal.status == "promoted")
                    .order_by(ParameterProposal.promoted_at.desc())
                    .limit(3)
                )
                for proposal in result.scalars().all():
                    if state.check_rollback_needed(proposal.id):
                        await rollback_proposal(session, proposal.id)
                        await session.commit()
                        logger.warning(
                            "Auto-rolling back proposal %d (%s) — PF dropped",
                            proposal.id, proposal.parameter_group,
                        )
                        await manager.broadcast({
                            "type": "optimizer_update",
                            "event": "proposal_rolled_back",
                            "proposal_id": proposal.id,
                            "reason": "auto_rollback_pf_drop",
                        })

            # 2. Check shadow completion
            if state.active_shadow_proposal_id:
                async with db.session_factory() as session:
                    progress = await get_shadow_progress(
                        session, state.active_shadow_proposal_id
                    )
                    if progress["complete"]:
                        shadow_results = await session.execute(
                            select(ShadowResult)
                            .where(ShadowResult.proposal_id == state.active_shadow_proposal_id)
                            .where(ShadowResult.shadow_outcome.is_not(None))
                        )
                        shadows = shadow_results.scalars().all()

                        signal_ids = [sr.signal_id for sr in shadows]
                        if signal_ids:
                            real_signals = await session.execute(
                                select(Signal)
                                .where(Signal.id.in_(signal_ids))
                            )
                            real_pnl_map = {
                                s.id: s.outcome_pnl_pct or 0
                                for s in real_signals.scalars().all()
                            }

                            current_pnls = [real_pnl_map.get(sr.signal_id, 0) for sr in shadows]
                            shadow_pnls = []
                            for sr in shadows:
                                if sr.shadow_outcome in ("tp1_hit", "tp2_hit"):
                                    shadow_pnls.append(abs(sr.shadow_tp1 - sr.shadow_entry) / sr.shadow_entry * 100)
                                elif sr.shadow_outcome == "sl_hit":
                                    shadow_pnls.append(-abs(sr.shadow_sl - sr.shadow_entry) / sr.shadow_entry * 100)
                                else:
                                    shadow_pnls.append(0)

                            decision = evaluate_shadow_results(current_pnls, shadow_pnls)

                            proposal_id = state.active_shadow_proposal_id
                            shadow_metrics = {
                                "current_pf": _compute_pf(current_pnls),
                                "shadow_pf": _compute_pf(shadow_pnls),
                                "decision": decision,
                                "signals_evaluated": len(shadows),
                            }

                            if decision == "promote":
                                await promote_proposal(session, proposal_id, shadow_metrics)
                                state.active_shadow_proposal_id = None
                                pf = state.profit_factor()
                                if pf is not None:
                                    state._pf_at_promotion[proposal_id] = pf
                                logger.info("Auto-promoted proposal %d", proposal_id)
                            elif decision == "reject":
                                await reject_proposal(
                                    session, proposal_id,
                                    reason="shadow_underperformed",
                                    shadow_metrics=shadow_metrics,
                                )
                                state.active_shadow_proposal_id = None
                                logger.info("Auto-rejected proposal %d", proposal_id)

                            await session.commit()
                            await manager.broadcast({
                                "type": "optimizer_update",
                                "event": f"shadow_{decision}",
                                "proposal_id": proposal_id,
                                "shadow_metrics": shadow_metrics,
                            })

                continue

            # 3. Find groups needing evaluation (respect priority)
            for layer in PRIORITY_LAYERS:
                for group_name in sorted(layer):
                    if not state.needs_eval(group_name):
                        continue
                    if not state.can_propose(group_name):
                        continue

                    logger.info("Running counterfactual eval for group: %s", group_name)
                    result = await run_counterfactual_eval(app, group_name)

                    if result:
                        candidate = result["candidate"]
                        metrics = result["metrics"]
                        current_pf = state.profit_factor() or 0
                        proposed_pf = metrics.get("profit_factor", 0)

                        if current_pf > 0:
                            improvement = (proposed_pf - current_pf) / current_pf
                        else:
                            improvement = 1.0 if proposed_pf > 0 else 0

                        if improvement >= OPTIMIZER_CONFIG["improvement_threshold"]:
                            group = get_group(group_name)
                            changes = {}
                            for param_key, proposed_val in candidate.items():
                                changes[param_key] = {
                                    "current": None,
                                    "proposed": proposed_val,
                                }

                            async with db.session_factory() as session:
                                proposal = await create_proposal(
                                    session, group_name, changes, metrics
                                )
                                await session.commit()
                                logger.info(
                                    "Created proposal %d for %s (PF improvement: %.1f%%)",
                                    proposal.id, group_name, improvement * 100,
                                )
                                await manager.broadcast({
                                    "type": "optimizer_update",
                                    "event": "proposal_created",
                                    "proposal_id": proposal.id,
                                    "group": group_name,
                                })

                    state.last_optimized[group_name] = state.resolved_count
                    break  # Only evaluate one group per cycle
                else:
                    continue
                break

        except asyncio.CancelledError:
            logger.info("Optimizer loop cancelled")
            break
        except Exception:
            logger.exception("Optimizer loop error")
            await asyncio.sleep(300)
