"""ML model training and status API endpoints."""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.auth import require_auth
from app.db.models import Candle, OrderFlowSnapshot, MLTrainingRun
from app.ml.data_loader import prepare_training_data
from app.ml.labels import LabelConfig
from app.ml.trainer import Trainer, TrainConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ml", tags=["ml"])


class TrainRequest(BaseModel):
    timeframe: str = "1h"
    lookback_days: int = Field(default=365, ge=30, le=1825)
    epochs: int = Field(default=100, ge=1, le=500)
    batch_size: int = Field(default=64, ge=8, le=512)
    hidden_size: int = Field(default=128, ge=32, le=512)
    num_layers: int = Field(default=2, ge=1, le=4)
    lr: float = Field(default=1e-3, gt=0)
    seq_len: int = Field(default=50, ge=25, le=200)
    dropout: float = Field(default=0.3, ge=0.0, le=0.7)
    label_horizon: int = Field(default=24, ge=4, le=96)
    label_threshold_pct: float = Field(default=1.5, gt=0, le=10)
    preset_label: str | None = None


@router.get("/data-readiness", dependencies=[require_auth()])
async def get_data_readiness(timeframe: str, request: Request):
    """Return per-pair candle counts for a given timeframe."""
    db = request.app.state.db
    settings = request.app.state.settings

    async with db.session_factory() as session:
        result = await session.execute(
            select(
                Candle.pair,
                func.count().label("count"),
                func.min(Candle.timestamp).label("oldest"),
            )
            .where(Candle.timeframe == timeframe)
            .where(Candle.pair.in_(settings.pairs))
            .group_by(Candle.pair)
        )
        rows = result.all()

    data = {}
    for row in rows:
        data[row.pair] = {
            "count": row.count,
            "oldest": row.oldest.isoformat() if row.oldest else None,
            "sufficient": row.count >= 100,
        }

    # Include pairs with zero candles
    for pair in settings.pairs:
        if pair not in data:
            data[pair] = {"count": 0, "oldest": None, "sufficient": False}

    return data


@router.post("/train", dependencies=[require_auth()])
async def start_training(body: TrainRequest, request: Request):
    """Start ML model training on historical data."""
    db = request.app.state.db
    settings = request.app.state.settings
    train_jobs = _get_train_jobs(request.app)

    # Check if already training
    for job in train_jobs.values():
        if job.get("status") == "running":
            raise HTTPException(status_code=429, detail="Training already in progress")

    job_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    train_jobs[job_id] = {"status": "running", "progress": {}}

    params_dict = body.model_dump(exclude={"preset_label"})
    run = MLTrainingRun(
        job_id=job_id,
        status="running",
        preset_label=body.preset_label,
        params=params_dict,
    )
    async with db.session_factory() as session:
        session.add(run)
        await session.commit()

    async def _run():
        start_time = time.time()

        async def _update_run(**fields):
            fields.setdefault("duration_seconds", time.time() - start_time)
            fields.setdefault("completed_at", datetime.now(timezone.utc))
            try:
                async with db.session_factory() as session:
                    await session.execute(
                        update(MLTrainingRun)
                        .where(MLTrainingRun.job_id == job_id)
                        .values(**fields)
                    )
                    await session.commit()
            except Exception:
                logger.exception(f"Failed to update training run {job_id} in DB")

        try:
            cutoff = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0
            )
            date_from = cutoff - timedelta(days=body.lookback_days)

            # Train one model per pair (avoids cross-pair boundary artifacts)
            pairs = settings.pairs
            pair_results = {}

            for pair in pairs:
                async with db.session_factory() as session:
                    result = await session.execute(
                        select(Candle)
                        .where(Candle.pair == pair)
                        .where(Candle.timeframe == body.timeframe)
                        .where(Candle.timestamp >= date_from)
                        .order_by(Candle.timestamp)
                    )
                    rows = result.scalars().all()

                candles = [{
                    "timestamp": c.timestamp.isoformat(),
                    "open": float(c.open), "high": float(c.high),
                    "low": float(c.low), "close": float(c.close),
                    "volume": float(c.volume),
                } for c in rows]

                if len(candles) < 100:
                    logger.warning(f"Skipping {pair}:{body.timeframe} — only {len(candles)} candles")
                    continue

                # Load matching order flow snapshots
                flow = None
                async with db.session_factory() as session:
                    result = await session.execute(
                        select(OrderFlowSnapshot)
                        .where(OrderFlowSnapshot.pair == pair)
                        .where(OrderFlowSnapshot.timestamp >= date_from)
                        .order_by(OrderFlowSnapshot.timestamp)
                    )
                    flow_rows = result.scalars().all()

                flow_used = False
                if flow_rows:
                    # Align flow snapshots to candles by nearest timestamp
                    from datetime import datetime as _dt
                    flow_by_ts = {}
                    for f in flow_rows:
                        # Bucket to hour to match candle timestamps
                        ts_key = f.timestamp.replace(minute=0, second=0, microsecond=0)
                        flow_by_ts[ts_key] = {
                            "funding_rate": f.funding_rate or 0,
                            "oi_change_pct": f.oi_change_pct or 0,
                            "long_short_ratio": f.long_short_ratio or 1.0,
                        }

                    zero_flow = {"funding_rate": 0, "oi_change_pct": 0, "long_short_ratio": 1.0}
                    flow = []
                    matched = 0
                    for c in candles:
                        c_ts = _dt.fromisoformat(c["timestamp"]).replace(minute=0, second=0, microsecond=0)
                        snap = flow_by_ts.get(c_ts, zero_flow)
                        if snap is not zero_flow:
                            matched += 1
                        flow.append(snap)

                    coverage = matched / len(candles) if candles else 0
                    if coverage < 0.1:
                        logger.warning(
                            f"Order flow coverage too low for {pair}: "
                            f"{matched}/{len(candles)} ({coverage:.0%}) — skipping flow features"
                        )
                        flow = None
                    else:
                        flow_used = True
                        logger.info(
                            f"Order flow aligned for {pair}: "
                            f"{matched}/{len(candles)} ({coverage:.0%}) candles matched"
                        )

                label_config = LabelConfig(
                    horizon=body.label_horizon,
                    threshold_pct=body.label_threshold_pct,
                )
                features, direction, sl, tp1, tp2 = prepare_training_data(
                    candles, order_flow=flow, label_config=label_config,
                )

                # Per-pair checkpoint directory
                pair_slug = pair.replace("-", "_").lower()
                pair_checkpoint_dir = os.path.join(settings.ml_checkpoint_dir, pair_slug)

                train_config = TrainConfig(
                    epochs=body.epochs,
                    batch_size=body.batch_size,
                    seq_len=body.seq_len,
                    hidden_size=body.hidden_size,
                    num_layers=body.num_layers,
                    dropout=body.dropout,
                    lr=body.lr,
                    checkpoint_dir=pair_checkpoint_dir,
                )

                def on_progress(info, _pair=pair):
                    train_jobs[job_id]["progress"][_pair] = info

                trainer = Trainer(train_config)
                pair_result = await asyncio.to_thread(
                    trainer.train, features, direction, sl, tp1, tp2, on_progress,
                )

                # Patch model_config.json with flow_used flag so inference
                # knows whether to include order flow features
                config_path = os.path.join(pair_checkpoint_dir, "model_config.json")
                if os.path.isfile(config_path):
                    import json as _j
                    with open(config_path) as f:
                        meta = _j.load(f)
                    meta["flow_used"] = flow_used
                    with open(config_path, "w") as f:
                        _j.dump(meta, f, indent=2)

                pair_results[pair] = {
                    "best_epoch": pair_result["best_epoch"],
                    "best_val_loss": pair_result["best_val_loss"],
                    "total_epochs": len(pair_result["train_loss"]),
                    "total_samples": len(features),
                    "flow_data_used": flow_used,
                    "version": pair_result.get("version"),
                    "direction_accuracy": pair_result.get("direction_accuracy"),
                    "precision_per_class": pair_result.get("precision_per_class"),
                    "recall_per_class": pair_result.get("recall_per_class"),
                    "loss_history": [
                        {
                            "epoch": i + 1,
                            "train_loss": pair_result["train_loss"][i],
                            "val_loss": pair_result["val_loss"][i] if i < len(pair_result["val_loss"]) else None,
                        }
                        for i in range(len(pair_result["train_loss"]))
                    ],
                }

            if not pair_results:
                train_jobs[job_id] = {"status": "failed", "error": "No pair had enough data"}
                await _update_run(
                    status="failed",
                    error="No pair had enough data",
                )
                return

            train_jobs[job_id] = {
                "status": "completed",
                "result": pair_results,
            }

            total_candles_count = sum(
                r.get("total_samples", 0) for r in pair_results.values()
            )
            await _update_run(
                status="completed",
                result=pair_results,
                pairs_trained=list(pair_results.keys()),
                total_candles=total_candles_count,
            )

            # Reload per-pair predictors if live
            _reload_predictors(request.app, settings)

        except asyncio.CancelledError:
            logger.info(f"Training job {job_id} cancelled")
            train_jobs[job_id] = {"status": "cancelled"}
            await _update_run(status="cancelled")
        except Exception as e:
            logger.error(f"Training failed: {e}", exc_info=True)
            train_jobs[job_id] = {"status": "failed", "error": str(e)}
            await _update_run(status="failed", error=str(e))

    task = asyncio.create_task(_run())
    train_jobs[job_id]["task"] = task
    _prune_old_jobs(train_jobs)
    return {"job_id": job_id, "status": "running"}


def _run_to_dict(r: MLTrainingRun) -> dict:
    return {
        "job_id": r.job_id,
        "status": r.status,
        "preset_label": r.preset_label,
        "params": r.params,
        "result": r.result,
        "error": r.error,
        "pairs_trained": r.pairs_trained,
        "duration_seconds": r.duration_seconds,
        "total_candles": r.total_candles,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    }


@router.get("/train/history", dependencies=[require_auth()])
async def get_training_history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Return training runs, newest first, with pagination."""
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            select(MLTrainingRun)
            .order_by(MLTrainingRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        runs = result.scalars().all()

    return [_run_to_dict(r) for r in runs]


@router.delete("/train/history/{job_id}", dependencies=[require_auth()])
async def delete_training_run(job_id: str, request: Request):
    """Delete a training run from history."""
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            delete(MLTrainingRun).where(MLTrainingRun.job_id == job_id)
        )
        await session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Training run not found")
    return {"deleted": job_id}


@router.get("/train/{job_id}", dependencies=[require_auth()])
async def get_training_status(job_id: str, request: Request):
    train_jobs = _get_train_jobs(request.app)
    job = train_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")
    # Don't expose asyncio task in response
    return {"job_id": job_id, **{k: v for k, v in job.items() if k != "task"}}


@router.post("/train/{job_id}/cancel", dependencies=[require_auth()])
async def cancel_training(job_id: str, request: Request):
    """Cancel a running training job."""
    train_jobs = _get_train_jobs(request.app)
    job = train_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")
    if job.get("status") != "running":
        raise HTTPException(status_code=409, detail="Job is not running")
    task = job.get("task")
    if task and not task.done():
        task.cancel()
    job["status"] = "cancelled"
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/status", dependencies=[require_auth()])
async def get_ml_status(request: Request):
    """Check if ML model is loaded and ready."""
    predictors = getattr(request.app.state, "ml_predictors", {})
    return {
        "ml_enabled": getattr(request.app.state.settings, "ml_enabled", False),
        "loaded_pairs": list(predictors.keys()),
    }


OKX_BAR_MAP = {"15m": "15m", "1h": "1H", "4h": "4H"}


class BackfillRequest(BaseModel):
    timeframe: str = "1h"
    lookback_days: int = Field(default=365, ge=30, le=1825)


@router.post("/backfill", dependencies=[require_auth()])
async def start_backfill(body: BackfillRequest, request: Request):
    """Deep-fetch historical candles from OKX into the database for ML training."""
    db = request.app.state.db
    settings = request.app.state.settings
    bar = OKX_BAR_MAP.get(body.timeframe)
    if not bar:
        raise HTTPException(status_code=400, detail=f"Unsupported timeframe: {body.timeframe}")

    backfill_jobs = _get_backfill_jobs(request.app)
    for job in backfill_jobs.values():
        if job.get("status") == "running":
            raise HTTPException(status_code=429, detail="Backfill already in progress")

    job_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backfill_jobs[job_id] = {"status": "running", "progress": {}}

    async def _run():
        try:
            pairs = settings.pairs
            cutoff = datetime.now(timezone.utc) - timedelta(days=body.lookback_days)
            cutoff_ms = int(cutoff.timestamp() * 1000)
            pair_results = {}

            async with httpx.AsyncClient(timeout=15) as client:
                for pair in pairs:
                    total = 0
                    # Start from now, paginate backwards using "after" cursor
                    after = ""
                    while True:
                        params = {"instId": pair, "bar": bar, "limit": "100"}
                        if after:
                            params["after"] = after

                        try:
                            resp = await client.get(
                                "https://www.okx.com/api/v5/market/candles",
                                params=params,
                            )
                            resp.raise_for_status()
                            rows = resp.json().get("data", [])
                        except Exception as e:
                            logger.error(f"Backfill fetch error for {pair}: {e}")
                            break

                        if not rows:
                            break

                        # OKX returns newest-first
                        oldest_ts = int(rows[-1][0])
                        batch_count = 0

                        batch_values = []
                        for row in rows:
                            ts_ms = int(row[0])
                            if ts_ms < cutoff_ms:
                                continue
                            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                            batch_values.append({
                                "pair": pair,
                                "timeframe": body.timeframe,
                                "timestamp": ts,
                                "open": float(row[1]),
                                "high": float(row[2]),
                                "low": float(row[3]),
                                "close": float(row[4]),
                                "volume": float(row[5]),
                            })
                        batch_count = len(batch_values)

                        if batch_values:
                            async with db.session_factory() as session:
                                stmt = pg_insert(Candle).values(batch_values).on_conflict_do_nothing(constraint="uq_candle")
                                await session.execute(stmt)
                                await session.commit()

                        total += batch_count

                        # Stop if we've reached past the cutoff
                        if oldest_ts <= cutoff_ms:
                            break

                        # Set cursor to fetch older candles
                        after = str(oldest_ts)

                        # Rate limit: OKX allows 20 req/2s on this endpoint
                        await asyncio.sleep(0.15)

                    pair_results[pair] = total
                    backfill_jobs[job_id]["progress"][pair] = total
                    logger.info(f"Backfilled {total} candles for {pair}:{body.timeframe}")

            backfill_jobs[job_id] = {"status": "completed", "result": pair_results}
        except Exception as e:
            logger.error(f"Backfill failed: {e}", exc_info=True)
            backfill_jobs[job_id] = {"status": "failed", "error": str(e)}

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "running"}


@router.get("/backfill/{job_id}", dependencies=[require_auth()])
async def get_backfill_status(job_id: str, request: Request):
    backfill_jobs = _get_backfill_jobs(request.app)
    job = backfill_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Backfill job not found")
    return {"job_id": job_id, **job}


MAX_RETAINED_JOBS = 10


def _get_train_jobs(app) -> dict:
    if not hasattr(app.state, "ml_train_jobs"):
        app.state.ml_train_jobs = {}
    return app.state.ml_train_jobs


def _get_backfill_jobs(app) -> dict:
    if not hasattr(app.state, "ml_backfill_jobs"):
        app.state.ml_backfill_jobs = {}
    return app.state.ml_backfill_jobs


def _prune_old_jobs(train_jobs: dict):
    """Keep only the most recent MAX_RETAINED_JOBS completed/failed jobs."""
    finished = [
        (k, v) for k, v in train_jobs.items()
        if v.get("status") in ("completed", "failed", "cancelled")
    ]
    if len(finished) > MAX_RETAINED_JOBS:
        # Job IDs are timestamp-sortable
        finished.sort(key=lambda x: x[0])
        for k, _ in finished[:-MAX_RETAINED_JOBS]:
            del train_jobs[k]


def _reload_predictors(app, settings):
    """Reload per-pair ML predictors from checkpoints."""
    import os
    from app.ml.predictor import Predictor
    predictors = {}
    checkpoint_dir = getattr(settings, "ml_checkpoint_dir", "models")
    if not os.path.isdir(checkpoint_dir):
        return
    for entry in os.listdir(checkpoint_dir):
        pair_dir = os.path.join(checkpoint_dir, entry)
        if not os.path.isdir(pair_dir):
            continue
        model_path = os.path.join(pair_dir, "best_model.pt")
        if os.path.isfile(model_path):
            try:
                predictors[entry] = Predictor(model_path)
                logger.info(f"ML predictor loaded for {entry}")
            except Exception as e:
                logger.error(f"Failed to load ML predictor for {entry}: {e}")
    app.state.ml_predictors = predictors
