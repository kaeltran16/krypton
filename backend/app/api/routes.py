import json

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.api.auth import require_settings_api_key
from app.db.models import Signal
from app.engine.traditional import compute_technical_score, compute_order_flow_score
from app.engine.combiner import compute_preliminary_score, compute_final_score, calculate_levels


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
    }


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
    ):
        db = request.app.state.db
        async with db.session_factory() as session:
            query = select(Signal).order_by(Signal.created_at.desc())
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
        days: int = Query(7, ge=1, le=90),
    ):
        redis = request.app.state.redis
        cache_key = f"signal_stats:{days}d"

        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

        db = request.app.state.db
        async with db.session_factory() as session:
            from datetime import datetime, timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            result = await session.execute(
                select(Signal)
                .where(Signal.created_at >= cutoff)
                .where(Signal.outcome != "PENDING")
            )
            resolved = result.scalars().all()

            if not resolved:
                stats = {"win_rate": 0, "avg_rr": 0, "total_resolved": 0, "total_wins": 0, "total_losses": 0, "by_pair": {}, "by_timeframe": {}}
            else:
                wins = [s for s in resolved if s.outcome in ("TP1_HIT", "TP2_HIT")]
                losses = [s for s in resolved if s.outcome == "SL_HIT"]
                expired = [s for s in resolved if s.outcome == "EXPIRED"]

                total = len(resolved)
                win_count = len(wins)
                loss_count = len(losses)
                win_rate = round(win_count / total * 100, 1) if total > 0 else 0

                avg_win = sum(float(s.outcome_pnl_pct or 0) for s in wins) / max(len(wins), 1)
                avg_loss = abs(sum(float(s.outcome_pnl_pct or 0) for s in losses) / max(len(losses), 1))
                avg_rr = round(avg_win / max(avg_loss, 0.01), 2)

                by_pair = {}
                for s in resolved:
                    p = by_pair.setdefault(s.pair, {"wins": 0, "total": 0})
                    p["total"] += 1
                    if s.outcome in ("TP1_HIT", "TP2_HIT"):
                        p["wins"] += 1
                for p in by_pair.values():
                    p["win_rate"] = round(p["wins"] / p["total"] * 100, 1)

                by_timeframe = {}
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
                    "total_losses": loss_count,
                    "total_expired": len(expired),
                    "by_pair": by_pair,
                    "by_timeframe": by_timeframe,
                }

            await redis.set(cache_key, json.dumps(stats), ex=300)
            return stats

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
        prelim = compute_preliminary_score(tech["score"], flow["score"], 0.60, 0.40)
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

    return router
