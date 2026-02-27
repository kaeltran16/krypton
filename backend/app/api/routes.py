from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.api.auth import require_settings_api_key
from app.db.models import Signal


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

    return router
