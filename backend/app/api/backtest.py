"""Backtest REST API endpoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, delete

from app.api.auth import require_settings_api_key
from app.db.models import BacktestRun, Candle
from app.engine.backtester import run_backtest, BacktestConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

MAX_CONCURRENT_RUNS = 2


# ---- Request / Response models ----

class ImportRequest(BaseModel):
    pairs: list[str]
    timeframes: list[str]
    lookback_days: int = Field(default=365, ge=1, le=1825)


class RunRequest(BaseModel):
    pairs: list[str]
    timeframe: str
    date_from: str
    date_to: str
    signal_threshold: int = Field(default=40, ge=1, le=100)
    tech_weight: float = Field(default=0.75, ge=0, le=1)
    pattern_weight: float = Field(default=0.25, ge=0, le=1)
    enable_patterns: bool = True
    sl_atr_multiplier: float = Field(default=1.5, gt=0)
    tp1_atr_multiplier: float = Field(default=2.0, gt=0)
    tp2_atr_multiplier: float = Field(default=3.0, gt=0)
    max_concurrent_positions: int = Field(default=3, ge=1, le=20)
    ml_mode: bool = False  # use ML model instead of rule-based scoring
    ml_confidence_threshold: float = Field(default=0.65, ge=0.1, le=1.0)


class CompareRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=4)


# ---- Import endpoints ----

@router.post("/import", dependencies=[require_settings_api_key()])
async def trigger_import(body: ImportRequest, request: Request):
    """Trigger historical candle import from OKX."""
    db = request.app.state.db
    import_jobs = _get_import_jobs(request.app)

    job_id = str(uuid4())
    import_jobs[job_id] = {"status": "running", "total_imported": 0, "errors": []}

    async def _run():
        from app.collector.history import import_historical_candles

        def on_progress(jid, status):
            import_jobs[jid].update(status)

        try:
            result = await import_historical_candles(
                db=db,
                pairs=body.pairs,
                timeframes=body.timeframes,
                lookback_days=body.lookback_days,
                progress_callback=on_progress,
                job_id=job_id,
            )
            import_jobs[job_id] = {
                "status": "completed",
                "total_imported": result["total_imported"],
                "errors": result["errors"],
            }
        except Exception as e:
            import_jobs[job_id] = {"status": "failed", "error": str(e)}

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "running"}


@router.get("/import/{job_id}", dependencies=[require_settings_api_key()])
async def get_import_status(job_id: str, request: Request):
    """Check import job progress."""
    import_jobs = _get_import_jobs(request.app)
    job = import_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return {"job_id": job_id, **job}


# ---- Run endpoints ----

@router.post("/run", dependencies=[require_settings_api_key()])
async def start_backtest(body: RunRequest, request: Request):
    """Start a backtest run."""
    db = request.app.state.db
    cancel_flags = _get_cancel_flags(request.app)

    # Check concurrent run limit
    async with db.session_factory() as session:
        result = await session.execute(
            select(BacktestRun).where(BacktestRun.status == "running")
        )
        running = result.scalars().all()
        if len(running) >= MAX_CONCURRENT_RUNS:
            raise HTTPException(status_code=429, detail="Max concurrent backtest runs reached")

    # Parse dates
    try:
        date_from = datetime.fromisoformat(body.date_from).replace(tzinfo=timezone.utc)
        date_to = datetime.fromisoformat(body.date_to).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use ISO 8601.")

    # Create BacktestRun row
    run_id = str(uuid4())
    config_snapshot = body.model_dump()

    async with db.session_factory() as session:
        run = BacktestRun(
            id=run_id,
            status="running",
            config=config_snapshot,
            pairs=body.pairs,
            timeframe=body.timeframe,
            date_from=date_from,
            date_to=date_to,
        )
        session.add(run)
        await session.commit()

    cancel_flags[run_id] = {"cancelled": False}

    async def _run():
        try:
            bt_config = BacktestConfig(
                signal_threshold=body.signal_threshold,
                tech_weight=body.tech_weight,
                pattern_weight=body.pattern_weight,
                enable_patterns=body.enable_patterns,
                sl_atr_multiplier=body.sl_atr_multiplier,
                tp1_atr_multiplier=body.tp1_atr_multiplier,
                tp2_atr_multiplier=body.tp2_atr_multiplier,
                max_concurrent_positions=body.max_concurrent_positions,
                ml_confidence_threshold=body.ml_confidence_threshold,
            )

            all_trades = []
            all_stats_parts = []

            for pair in body.pairs:
                # Load candles from Postgres
                async with db.session_factory() as session:
                    result = await session.execute(
                        select(Candle)
                        .where(Candle.pair == pair)
                        .where(Candle.timeframe == body.timeframe)
                        .where(Candle.timestamp >= date_from)
                        .where(Candle.timestamp <= date_to)
                        .order_by(Candle.timestamp)
                    )
                    candle_rows = result.scalars().all()

                candles = [
                    {
                        "timestamp": c.timestamp.isoformat(),
                        "open": float(c.open),
                        "high": float(c.high),
                        "low": float(c.low),
                        "close": float(c.close),
                        "volume": float(c.volume),
                    }
                    for c in candle_rows
                ]

                if not candles:
                    continue

                # Load per-pair ML predictor if ml_mode requested
                ml_predictor = None
                if body.ml_mode:
                    predictors = getattr(request.app.state, "ml_predictors", {})
                    pair_slug = pair.replace("-", "_").lower()
                    ml_predictor = predictors.get(pair_slug)
                    if ml_predictor is None:
                        raise ValueError(f"No ML model for {pair}. Train via POST /api/ml/train")

                result = await asyncio.to_thread(
                    run_backtest, candles, pair, bt_config, cancel_flags.get(run_id),
                    ml_predictor,
                )
                all_trades.extend(result["trades"])
                all_stats_parts.append(result["stats"])

            # Check if cancelled
            if cancel_flags.get(run_id, {}).get("cancelled"):
                final_status = "cancelled"
            else:
                final_status = "completed"

            # Merge stats from all pairs
            merged = _merge_stats(all_stats_parts, all_trades)

            async with db.session_factory() as session:
                result = await session.execute(
                    select(BacktestRun).where(BacktestRun.id == run_id)
                )
                run_row = result.scalar_one()
                run_row.status = final_status
                run_row.results = {"stats": merged, "trades": all_trades}
                await session.commit()

        except Exception as e:
            logger.error(f"Backtest run {run_id} failed: {e}")
            try:
                async with db.session_factory() as session:
                    result = await session.execute(
                        select(BacktestRun).where(BacktestRun.id == run_id)
                    )
                    run_row = result.scalar_one()
                    run_row.status = "failed"
                    run_row.results = {"error": str(e)}
                    await session.commit()
            except Exception:
                pass
        finally:
            cancel_flags.pop(run_id, None)

    asyncio.create_task(_run())
    return {"run_id": run_id, "status": "running"}


@router.get("/run/{run_id}", dependencies=[require_settings_api_key()])
async def get_run_status(run_id: str, request: Request):
    """Poll backtest run status and results."""
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            select(BacktestRun).where(BacktestRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="Backtest run not found")
        return _run_to_dict(run)


@router.post("/run/{run_id}/cancel", dependencies=[require_settings_api_key()])
async def cancel_run(run_id: str, request: Request):
    """Cancel a running backtest."""
    cancel_flags = _get_cancel_flags(request.app)
    flag = cancel_flags.get(run_id)
    if not flag:
        raise HTTPException(status_code=404, detail="Run not found or already completed")
    flag["cancelled"] = True
    return {"run_id": run_id, "status": "cancelling"}


# ---- Results / comparison endpoints ----

@router.get("/runs", dependencies=[require_settings_api_key()])
async def list_runs(request: Request):
    """List all saved backtest runs with summary stats."""
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(50)
        )
        runs = result.scalars().all()
        return [_run_summary(r) for r in runs]


@router.get("/runs/{run_id}", dependencies=[require_settings_api_key()])
async def get_run_detail(run_id: str, request: Request):
    """Get full backtest run results including trade list."""
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            select(BacktestRun).where(BacktestRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="Backtest run not found")
        return _run_to_dict(run)


@router.post("/compare", dependencies=[require_settings_api_key()])
async def compare_runs(body: CompareRequest, request: Request):
    """Compare 2-4 backtest runs side-by-side."""
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            select(BacktestRun).where(BacktestRun.id.in_(body.run_ids))
        )
        runs = result.scalars().all()

    if len(runs) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 valid runs to compare")

    return {"runs": [_run_to_dict(run) for run in runs]}


@router.delete("/runs/{run_id}", dependencies=[require_settings_api_key()])
async def delete_run(run_id: str, request: Request):
    """Delete a backtest run."""
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            delete(BacktestRun).where(BacktestRun.id == run_id)
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Backtest run not found")
    return {"deleted": run_id}


# ---- Helpers ----

def _get_import_jobs(app) -> dict:
    if not hasattr(app.state, "import_jobs"):
        app.state.import_jobs = {}
    return app.state.import_jobs


def _get_cancel_flags(app) -> dict:
    if not hasattr(app.state, "backtest_cancel_flags"):
        app.state.backtest_cancel_flags = {}
    return app.state.backtest_cancel_flags


def _run_to_dict(run: BacktestRun) -> dict:
    return {
        "id": run.id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "status": run.status,
        "config": run.config,
        "pairs": run.pairs,
        "timeframe": run.timeframe,
        "date_from": run.date_from.isoformat() if run.date_from else None,
        "date_to": run.date_to.isoformat() if run.date_to else None,
        "results": run.results,
    }


def _run_summary(run: BacktestRun) -> dict:
    stats = (run.results or {}).get("stats", {})
    return {
        "id": run.id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "status": run.status,
        "pairs": run.pairs,
        "timeframe": run.timeframe,
        "total_trades": stats.get("total_trades", 0),
        "win_rate": stats.get("win_rate", 0),
        "net_pnl": stats.get("net_pnl", 0),
        "max_drawdown": stats.get("max_drawdown", 0),
    }


def _merge_stats(stats_parts: list[dict], all_trades: list[dict]) -> dict:
    """Merge stats from multiple pairs into aggregate stats."""
    if not stats_parts:
        from app.engine.backtester import _empty_stats
        return _empty_stats()

    if len(stats_parts) == 1:
        return stats_parts[0]

    # Aggregate across pairs
    total_trades = sum(s.get("total_trades", 0) for s in stats_parts)
    if total_trades == 0:
        from app.engine.backtester import _empty_stats
        return _empty_stats()

    pnls = [t["pnl_pct"] for t in all_trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    net_pnl = round(sum(pnls), 4)
    win_rate = round(len(wins) / total_trades * 100, 2)

    # Max drawdown across merged equity curve
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(all_trades, key=lambda x: x.get("entry_time", "")):
        cumulative += t["pnl_pct"]
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    # Profit factor
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    # Equity curve
    equity_curve = []
    cumulative = 0.0
    for t in sorted(all_trades, key=lambda x: x.get("entry_time", "")):
        cumulative += t["pnl_pct"]
        equity_curve.append({"time": t.get("entry_time"), "cumulative_pnl": round(cumulative, 4)})

    # Monthly P&L
    monthly_pnl: dict[str, float] = {}
    for t in all_trades:
        month = (t.get("entry_time") or "")[:7]
        if month:
            monthly_pnl[month] = round(monthly_pnl.get(month, 0) + t["pnl_pct"], 4)

    # By pair
    by_pair: dict[str, dict] = {}
    for t in all_trades:
        pair = t.get("pair", "")
        if pair not in by_pair:
            by_pair[pair] = {"total": 0, "wins": 0}
        by_pair[pair]["total"] += 1
        if t["pnl_pct"] > 0:
            by_pair[pair]["wins"] += 1
    for v in by_pair.values():
        v["win_rate"] = round(v["wins"] / v["total"] * 100, 2) if v["total"] else 0

    return {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "net_pnl": net_pnl,
        "avg_pnl": round(net_pnl / total_trades, 4),
        "max_drawdown": round(max_dd, 4),
        "profit_factor": profit_factor,
        "equity_curve": equity_curve,
        "monthly_pnl": monthly_pnl,
        "by_pair": by_pair,
    }
