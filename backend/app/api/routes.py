import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pandas as pd
from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.auth import require_settings_api_key
from app.db.models import Signal, PerformanceTrackerRow
from app.engine.performance_tracker import DEFAULT_SL, DEFAULT_TP1, DEFAULT_TP2
from app.engine.combiner import (
    calculate_levels,
    compute_final_score,
    compute_preliminary_score,
)
from app.engine.traditional import compute_order_flow_score, compute_technical_score

VALID_USER_STATUSES = {"OBSERVED", "TRADED", "SKIPPED"}


def _signal_to_dict(signal: Signal) -> dict:
    return {
        "id": signal.id,
        "pair": signal.pair,
        "timeframe": signal.timeframe,
        "direction": signal.direction,
        "final_score": signal.final_score,
        "traditional_score": signal.traditional_score,
        "confidence": signal.llm_confidence or "LOW",
        "llm_opinion": signal.llm_opinion,
        "explanation": signal.explanation,
        "levels": {
            "entry": float(signal.entry),
            "stop_loss": float(signal.stop_loss),
            "take_profit_1": float(signal.take_profit_1),
            "take_profit_2": float(signal.take_profit_2),
        },
        "outcome": signal.outcome,
        "outcome_pnl_pct": float(signal.outcome_pnl_pct) if signal.outcome_pnl_pct else None,
        "outcome_duration_minutes": signal.outcome_duration_minutes,
        "outcome_at": signal.outcome_at.isoformat() if signal.outcome_at else None,
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
        "user_note": signal.user_note,
        "user_status": signal.user_status,
        "risk_metrics": signal.risk_metrics,
        "detected_patterns": signal.detected_patterns,
        "correlated_news_ids": signal.correlated_news_ids,
    }


def _compute_streaks(resolved: list[Signal]) -> dict:
    """Compute current, best_win, and worst_loss streaks from time-ordered signals."""
    sorted_signals = sorted(resolved, key=lambda s: s.created_at)
    current = 0
    best_win = 0
    worst_loss = 0
    streak = 0
    prev_is_win = None

    for s in sorted_signals:
        is_win = s.outcome in ("TP1_HIT", "TP2_HIT")
        if prev_is_win is None or is_win == prev_is_win:
            streak += 1 if is_win else -1
        else:
            streak = 1 if is_win else -1
        prev_is_win = is_win

        if streak > 0:
            best_win = max(best_win, streak)
        elif streak < 0:
            worst_loss = min(worst_loss, streak)

    current = streak

    return {"current": current, "best_win": best_win, "worst_loss": worst_loss}


def _compute_equity_curve(resolved: list[Signal], downsample: bool) -> list[dict]:
    """Build cumulative P&L curve from resolved signals, ordered by outcome time."""
    with_pnl = [s for s in resolved if s.outcome_pnl_pct is not None and s.outcome_at is not None]
    if not with_pnl:
        return []

    sorted_signals = sorted(with_pnl, key=lambda s: s.outcome_at)

    if downsample:
        daily: dict[str, float] = {}
        for s in sorted_signals:
            day = s.outcome_at.strftime("%Y-%m-%d")
            daily[day] = daily.get(day, 0) + float(s.outcome_pnl_pct)
        cumulative = 0.0
        curve = []
        for day, pnl in daily.items():
            cumulative += pnl
            curve.append({"date": day, "cumulative_pnl": round(cumulative, 4)})
        return curve
    else:
        cumulative = 0.0
        curve = []
        for s in sorted_signals:
            cumulative += float(s.outcome_pnl_pct)
            curve.append({
                "date": s.outcome_at.strftime("%Y-%m-%d"),
                "cumulative_pnl": round(cumulative, 4),
            })
        return curve


def _compute_hourly_performance(resolved: list[Signal]) -> list[dict]:
    """Compute average P&L and count per hour of day."""
    buckets: dict[int, list[float]] = defaultdict(list)
    for s in resolved:
        if s.outcome_pnl_pct is not None:
            hour = s.created_at.hour
            buckets[hour].append(float(s.outcome_pnl_pct))

    result = []
    for hour in range(24):
        pnls = buckets.get(hour, [])
        result.append({
            "hour": hour,
            "avg_pnl": round(sum(pnls) / len(pnls), 4) if pnls else 0,
            "count": len(pnls),
        })
    return result


def _compute_performance_metrics(resolved: list[Signal]) -> dict:
    """Compute advanced performance metrics: Sharpe, max drawdown, profit factor, etc."""
    metrics: dict = {
        "sharpe_ratio": None,
        "max_drawdown_pct": 0,
        "profit_factor": None,
        "expectancy": None,
        "avg_hold_time_minutes": None,
        "best_trade": None,
        "worst_trade": None,
    }

    with_pnl = [s for s in resolved if s.outcome_pnl_pct is not None]
    if not with_pnl:
        return metrics

    pnl_values = [float(s.outcome_pnl_pct) for s in with_pnl]

    # Best/worst trade
    best_idx = max(range(len(pnl_values)), key=lambda i: pnl_values[i])
    worst_idx = min(range(len(pnl_values)), key=lambda i: pnl_values[i])
    best_s = with_pnl[best_idx]
    worst_s = with_pnl[worst_idx]
    metrics["best_trade"] = {
        "pnl_pct": round(pnl_values[best_idx], 2),
        "pair": best_s.pair,
        "timeframe": best_s.timeframe,
        "direction": best_s.direction,
    }
    metrics["worst_trade"] = {
        "pnl_pct": round(pnl_values[worst_idx], 2),
        "pair": worst_s.pair,
        "timeframe": worst_s.timeframe,
        "direction": worst_s.direction,
    }

    # Profit factor
    winning_pnl = sum(p for p in pnl_values if p > 0)
    losing_pnl = sum(p for p in pnl_values if p < 0)
    if losing_pnl != 0:
        metrics["profit_factor"] = round(winning_pnl / abs(losing_pnl), 2)

    # Expectancy
    wins = [p for p in pnl_values if p > 0]
    losses = [p for p in pnl_values if p <= 0]
    total = len(pnl_values)
    if total > 0:
        win_rate = len(wins) / total
        loss_rate = 1 - win_rate
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0
        metrics["expectancy"] = round((win_rate * avg_win) - (loss_rate * avg_loss), 4)

    # Avg hold time
    hold_times = [s.outcome_duration_minutes for s in with_pnl if s.outcome_duration_minutes is not None]
    if hold_times:
        metrics["avg_hold_time_minutes"] = round(sum(hold_times) / len(hold_times), 1)

    # Max drawdown from cumulative P&L
    sorted_signals = sorted(
        [s for s in with_pnl if s.outcome_at is not None],
        key=lambda s: s.outcome_at,
    )
    if sorted_signals:
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for s in sorted_signals:
            cumulative += float(s.outcome_pnl_pct)
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        metrics["max_drawdown_pct"] = round(max_dd, 2)

    # Sharpe ratio (annualized from daily returns)
    daily_returns: dict[str, float] = {}
    for s in sorted_signals:
        day = s.outcome_at.strftime("%Y-%m-%d")
        daily_returns[day] = daily_returns.get(day, 0) + float(s.outcome_pnl_pct)

    if len(daily_returns) >= 7:
        returns = list(daily_returns.values())
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        std_r = math.sqrt(variance)
        if std_r > 0:
            metrics["sharpe_ratio"] = round((mean_r / std_r) * math.sqrt(365), 2)

    return metrics


def _compute_drawdown_series(resolved: list[Signal]) -> list[dict]:
    """Compute drawdown % over time for charting."""
    sorted_signals = sorted(
        [s for s in resolved if s.outcome_pnl_pct is not None and s.outcome_at is not None],
        key=lambda s: s.outcome_at,
    )
    if not sorted_signals:
        return []

    cumulative = 0.0
    peak = 0.0
    series = []
    for s in sorted_signals:
        cumulative += float(s.outcome_pnl_pct)
        if cumulative > peak:
            peak = cumulative
        dd = -(peak - cumulative)
        series.append({
            "date": s.outcome_at.strftime("%Y-%m-%d"),
            "drawdown": round(dd, 4),
        })
    return series


def _compute_pnl_distribution(resolved: list[Signal]) -> list[dict]:
    """Compute P&L distribution histogram buckets."""
    pnl_values = [float(s.outcome_pnl_pct) for s in resolved if s.outcome_pnl_pct is not None]
    if not pnl_values:
        return []

    min_pnl = min(pnl_values)
    max_pnl = max(pnl_values)
    if min_pnl == max_pnl:
        return [{"bucket": round(min_pnl, 1), "count": len(pnl_values)}]

    bucket_size = max((max_pnl - min_pnl) / 10, 0.5)
    buckets: dict[float, int] = {}
    for pnl in pnl_values:
        key = round(math.floor(pnl / bucket_size) * bucket_size, 2)
        buckets[key] = buckets.get(key, 0) + 1

    return [{"bucket": k, "count": v} for k, v in sorted(buckets.items())]


class JournalPatch(BaseModel):
    status: str | None = Field(None)
    note: str | None = Field(None, max_length=500)


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api")
    auth = require_settings_api_key()

    @router.get("/signals")
    async def get_signals(
        request: Request,
        _key: str = auth,
        pair: str | None = Query(None),
        timeframe: str | None = Query(None),
        limit: int = Query(50, ge=1, le=200),
        since: datetime | None = Query(None),
    ):
        db = request.app.state.db
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
        async with db.session_factory() as session:
            query = select(Signal).order_by(Signal.created_at.desc())
            query = query.where(Signal.created_at >= since)
            if pair:
                query = query.where(Signal.pair == pair)
            if timeframe:
                query = query.where(Signal.timeframe == timeframe)
            query = query.limit(limit)
            result = await session.execute(query)
            return [_signal_to_dict(s) for s in result.scalars().all()]

    @router.get("/signals/stats")
    async def get_signal_stats(
        request: Request,
        _key: str = auth,
        days: int = Query(7, ge=1, le=365),
    ):
        redis = request.app.state.redis
        cache_key = f"signal_stats:{days}d"

        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

        db = request.app.state.db
        async with db.session_factory() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            result = await session.execute(
                select(Signal)
                .where(Signal.created_at >= cutoff)
                .where(Signal.outcome != "PENDING")
            )
            resolved = result.scalars().all()

            if not resolved:
                stats = {
                    "win_rate": 0, "avg_rr": 0, "total_resolved": 0,
                    "total_wins": 0, "total_losses": 0, "total_expired": 0,
                    "by_pair": {}, "by_timeframe": {},
                    "equity_curve": [], "hourly_performance": _compute_hourly_performance([]),
                    "streaks": {"current": 0, "best_win": 0, "worst_loss": 0},
                    "performance": _compute_performance_metrics([]),
                    "drawdown_series": [],
                    "pnl_distribution": [],
                }
            else:
                wins = [s for s in resolved if s.outcome in ("TP1_HIT", "TP2_HIT")]
                losses = [s for s in resolved if s.outcome == "SL_HIT"]
                expired = [s for s in resolved if s.outcome == "EXPIRED"]

                total = len(resolved)
                win_count = len(wins)
                win_rate = round(win_count / total * 100, 1) if total > 0 else 0

                avg_win = sum(float(s.outcome_pnl_pct or 0) for s in wins) / max(len(wins), 1)
                avg_loss = abs(sum(float(s.outcome_pnl_pct or 0) for s in losses) / max(len(losses), 1))
                avg_rr = round(avg_win / max(avg_loss, 0.01), 2)

                by_pair: dict[str, dict] = {}
                for s in resolved:
                    p = by_pair.setdefault(s.pair, {"wins": 0, "losses": 0, "total": 0, "pnl_sum": 0.0})
                    p["total"] += 1
                    pnl = float(s.outcome_pnl_pct or 0)
                    p["pnl_sum"] += pnl
                    if s.outcome in ("TP1_HIT", "TP2_HIT"):
                        p["wins"] += 1
                    elif s.outcome == "SL_HIT":
                        p["losses"] += 1
                for p in by_pair.values():
                    p["win_rate"] = round(p["wins"] / p["total"] * 100, 1)
                    p["avg_pnl"] = round(p["pnl_sum"] / p["total"], 4)
                    del p["pnl_sum"]

                by_timeframe: dict[str, dict] = {}
                for s in resolved:
                    t = by_timeframe.setdefault(s.timeframe, {"wins": 0, "total": 0})
                    t["total"] += 1
                    if s.outcome in ("TP1_HIT", "TP2_HIT"):
                        t["wins"] += 1
                for t in by_timeframe.values():
                    t["win_rate"] = round(t["wins"] / t["total"] * 100, 1)

                stats = {
                    "win_rate": win_rate,
                    "avg_rr": avg_rr,
                    "total_resolved": total,
                    "total_wins": win_count,
                    "total_losses": len(losses),
                    "total_expired": len(expired),
                    "by_pair": by_pair,
                    "by_timeframe": by_timeframe,
                    "equity_curve": _compute_equity_curve(resolved, downsample=days > 90),
                    "hourly_performance": _compute_hourly_performance(resolved),
                    "streaks": _compute_streaks(resolved),
                    "performance": _compute_performance_metrics(resolved),
                    "drawdown_series": _compute_drawdown_series(resolved),
                    "pnl_distribution": _compute_pnl_distribution(resolved),
                }

            await redis.set(cache_key, json.dumps(stats), ex=300)
            return stats

    @router.get("/signals/calendar")
    async def get_signal_calendar(
        request: Request,
        _key: str = auth,
        month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    ):
        year, mon = map(int, month.split("-"))
        start = datetime(year, mon, 1, tzinfo=timezone.utc)
        if mon == 12:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(year, mon + 1, 1, tzinfo=timezone.utc)

        db = request.app.state.db
        async with db.session_factory() as session:
            result = await session.execute(
                select(Signal)
                .where(Signal.created_at >= start)
                .where(Signal.created_at < end)
                .where(Signal.outcome != "PENDING")
            )
            resolved = result.scalars().all()

        day_buckets: dict[str, dict] = {}
        for s in resolved:
            day = s.created_at.strftime("%Y-%m-%d")
            bucket = day_buckets.setdefault(day, {"date": day, "signal_count": 0, "net_pnl": 0.0, "wins": 0, "losses": 0})
            bucket["signal_count"] += 1
            bucket["net_pnl"] += float(s.outcome_pnl_pct or 0)
            if s.outcome in ("TP1_HIT", "TP2_HIT"):
                bucket["wins"] += 1
            elif s.outcome == "SL_HIT":
                bucket["losses"] += 1

        days_list = sorted(day_buckets.values(), key=lambda d: d["date"])
        for d in days_list:
            d["net_pnl"] = round(d["net_pnl"], 4)

        total_signals = sum(d["signal_count"] for d in days_list)
        net_pnl = round(sum(d["net_pnl"] for d in days_list), 4)
        best_day = max(days_list, key=lambda d: d["net_pnl"])["date"] if days_list else None
        worst_day = min(days_list, key=lambda d: d["net_pnl"])["date"] if days_list else None

        return {
            "days": days_list,
            "monthly_summary": {
                "total_signals": total_signals,
                "net_pnl": net_pnl,
                "best_day": best_day,
                "worst_day": worst_day,
            },
        }

    @router.patch("/signals/{signal_id}/journal")
    async def patch_signal_journal(
        request: Request,
        signal_id: int,
        body: JournalPatch = Body(...),
        _key: str = auth,
    ):
        if body.status is not None and body.status not in VALID_USER_STATUSES:
            raise HTTPException(400, f"Invalid status. Must be one of: {', '.join(VALID_USER_STATUSES)}")

        db = request.app.state.db
        async with db.session_factory() as session:
            result = await session.execute(
                select(Signal).where(Signal.id == signal_id)
            )
            signal = result.scalar_one_or_none()
            if not signal:
                raise HTTPException(404, "Signal not found")

            if body.status is not None:
                signal.user_status = body.status
            if body.note is not None:
                signal.user_note = body.note

            await session.commit()

        # Invalidate stats cache
        redis = request.app.state.redis
        keys = await redis.keys("signal_stats:*")
        if keys:
            await redis.delete(*keys)

        return _signal_to_dict(signal)

    @router.get("/signals/{signal_id}")
    async def get_signal(request: Request, signal_id: int, _key: str = auth):
        db = request.app.state.db
        async with db.session_factory() as session:
            result = await session.execute(
                select(Signal).where(Signal.id == signal_id)
            )
            signal = result.scalar_one_or_none()
            if not signal:
                raise HTTPException(status_code=404, detail="Signal not found")
            return _signal_to_dict(signal)

    @router.post("/test-signal")
    async def test_signal(
        request: Request,
        _key: str = auth,
        pair: str = Query("BTC-USDT-SWAP"),
        timeframe: str = Query("1h"),
    ):
        redis = request.app.state.redis
        manager = request.app.state.manager
        db = request.app.state.db

        cache_key = f"candles:{pair}:{timeframe}"
        raw_candles = await redis.lrange(cache_key, -50, -1)
        if len(raw_candles) < 50:
            raise HTTPException(400, f"Not enough candles: {len(raw_candles)}/50")

        candles_data = [json.loads(c) for c in raw_candles]
        df = pd.DataFrame(candles_data)
        tech = compute_technical_score(df)
        flow = compute_order_flow_score(request.app.state.order_flow.get(pair, {}))
        prelim = compute_preliminary_score(tech["score"], flow["score"], 0.50, 0.25)
        final = compute_final_score(prelim, None)
        direction = "LONG" if final > 0 else "SHORT"
        atr = tech["indicators"].get("atr", 200)
        levels = calculate_levels(direction, float(candles_data[-1]["close"]), atr, None)

        signal_data = {
            "pair": pair,
            "timeframe": timeframe,
            "direction": direction,
            "final_score": final,
            "traditional_score": tech["score"],
            "llm_opinion": "skipped",
            "llm_confidence": None,
            "explanation": None,
            **levels,
            "raw_indicators": tech["indicators"],
        }

        from app.main import persist_signal
        await persist_signal(db, signal_data)
        await manager.broadcast(signal_data)
        return signal_data

    @router.get("/engine/tuning")
    async def get_tuning(request: Request, _key: str = auth):
        db = request.app.state.db
        async with db.session_factory() as session:
            result = await session.execute(
                select(PerformanceTrackerRow).order_by(
                    PerformanceTrackerRow.pair, PerformanceTrackerRow.timeframe
                )
            )
            rows = result.scalars().all()
            return [
                {
                    "pair": r.pair,
                    "timeframe": r.timeframe,
                    "current_sl_atr": r.current_sl_atr,
                    "current_tp1_atr": r.current_tp1_atr,
                    "current_tp2_atr": r.current_tp2_atr,
                    "last_optimized_at": r.last_optimized_at.isoformat() if r.last_optimized_at else None,
                    "last_optimized_count": r.last_optimized_count,
                }
                for r in rows
            ]

    class TuningResetRequest(BaseModel):
        pair: str
        timeframe: str

    @router.post("/engine/tuning/reset")
    async def reset_tuning(request: Request, body: TuningResetRequest, _key: str = auth):
        db = request.app.state.db
        async with db.session_factory() as session:
            result = await session.execute(
                select(PerformanceTrackerRow).where(
                    PerformanceTrackerRow.pair == body.pair,
                    PerformanceTrackerRow.timeframe == body.timeframe,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                raise HTTPException(404, f"No tracker row for {body.pair}/{body.timeframe}")

            row.current_sl_atr = DEFAULT_SL
            row.current_tp1_atr = DEFAULT_TP1
            row.current_tp2_atr = DEFAULT_TP2
            row.last_optimized_count = 0
            row.last_optimized_at = None
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return {"status": "reset", "pair": body.pair, "timeframe": body.timeframe}

    return router
