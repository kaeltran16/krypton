from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request
from sqlalchemy import select, cast, literal
from sqlalchemy.dialects.postgresql import JSONB

from app.api.auth import require_auth
from app.db.models import NewsEvent

router = APIRouter(prefix="/api")
auth = require_auth()


def _news_to_dict(n: NewsEvent) -> dict:
    return {
        "id": n.id,
        "headline": n.headline,
        "source": n.source,
        "url": n.url,
        "category": n.category,
        "impact": n.impact,
        "sentiment": n.sentiment,
        "affected_pairs": n.affected_pairs,
        "llm_summary": n.llm_summary,
        "content_text": n.content_text,
        "published_at": n.published_at.isoformat() if n.published_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("/news")
async def get_news(
    request: Request,
    _key: str = auth,
    category: str | None = Query(None, pattern="^(crypto|macro)$"),
    impact: str | None = Query(None, pattern="^(high|medium|low)$"),
    sentiment: str | None = Query(None, pattern="^(bullish|bearish|neutral)$"),
    pair: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Paginated news feed with filters."""
    db = request.app.state.db
    async with db.session_factory() as session:
        query = select(NewsEvent).order_by(NewsEvent.published_at.desc())
        if category:
            query = query.where(NewsEvent.category == category)
        if impact:
            query = query.where(NewsEvent.impact == impact)
        if sentiment:
            query = query.where(NewsEvent.sentiment == sentiment)
        if pair:
            # Match pair symbol in affected_pairs JSONB array
            symbol = pair.split("-")[0].upper()
            query = query.where(
                NewsEvent.affected_pairs.op("@>")(cast(literal(f'["{symbol}"]'), JSONB))
                | NewsEvent.affected_pairs.op("@>")(cast(literal(f'["ALL"]'), JSONB))
            )
        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        return [_news_to_dict(n) for n in result.scalars().all()]


@router.get("/news/recent")
async def get_recent_news(
    request: Request,
    _key: str = auth,
    limit: int = Query(20, ge=1, le=100),
):
    """Last 24h of high + medium impact headlines (lightweight, for dashboard)."""
    db = request.app.state.db
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    async with db.session_factory() as session:
        query = (
            select(NewsEvent)
            .where(NewsEvent.published_at >= cutoff)
            .where(NewsEvent.impact.in_(["high", "medium"]))
            .order_by(NewsEvent.published_at.desc())
            .limit(limit)
        )
        result = await session.execute(query)
        return [_news_to_dict(n) for n in result.scalars().all()]
