"""News sentiment scoring source for the signal pipeline.

Queries recent NewsEvent rows and produces a directional score (-100 to +100)
based on LLM-assigned sentiment, article impact, and recency.  Feeds into the
combiner alongside technical, order-flow, on-chain and other sources so that a
major macro catalyst can influence borderline signals without waiting for the
LLM gate.
"""

import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, cast, literal
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import NewsEvent

logger = logging.getLogger(__name__)

_SENTIMENT_MAP = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}
_IMPACT_MULT = {"high": 1.5, "medium": 1.0, "low": 0.5}


def _recency_weight(published_at: datetime, now: datetime, half_life_minutes: float = 60.0) -> float:
    """Exponential decay based on article age. Half-life default = 60 min."""
    age_minutes = max(0.0, (now - published_at).total_seconds() / 60)
    return math.exp(-math.log(2) * age_minutes / half_life_minutes)


async def compute_news_score(
    pair: str,
    db,
    lookback_minutes: int = 120,
    half_life_minutes: float = 60.0,
    _now: datetime | None = None,
) -> dict:
    """Compute news sentiment score for a pair from recent NewsEvent rows.

    Returns dict with score (-100 to +100), availability (0-1),
    conviction (0-1), confidence (backward compat = availability),
    and details breakdown.
    """
    symbol = pair.split("-")[0].upper()
    now = _now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=lookback_minutes)

    try:
        async with db.session_factory() as session:
            result = await session.execute(
                select(NewsEvent)
                .where(NewsEvent.published_at >= cutoff)
                .where(NewsEvent.impact.in_(["high", "medium", "low"]))
                .where(
                    NewsEvent.affected_pairs.op("@>")(cast(literal(f'["{symbol}"]'), JSONB))
                    | NewsEvent.affected_pairs.op("@>")(cast(literal(f'["ALL"]'), JSONB))
                )
                .order_by(NewsEvent.published_at.desc())
                .limit(20)
            )
            events = result.scalars().all()
    except Exception as e:
        logger.debug(f"News score query failed for {pair}: {e}")
        return {"score": 0, "availability": 0.0, "conviction": 0.0, "confidence": 0.0, "details": {}}

    if not events:
        return {"score": 0, "availability": 0.0, "conviction": 0.0, "confidence": 0.0, "details": {}}

    weighted_sum = 0.0
    weight_total = 0.0
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
    high_impact_count = 0

    for e in events:
        sentiment_val = _SENTIMENT_MAP.get(e.sentiment, 0.0)
        impact_mult = _IMPACT_MULT.get(e.impact, 0.5)
        recency = _recency_weight(e.published_at, now, half_life_minutes)

        w = impact_mult * recency
        weighted_sum += sentiment_val * w
        weight_total += w

        if sentiment_val > 0:
            bullish_count += 1
        elif sentiment_val < 0:
            bearish_count += 1
        else:
            neutral_count += 1
        if e.impact == "high":
            high_impact_count += 1

    # Score: scale weighted average sentiment to -100..+100
    # weighted_sum / weight_total gives -1..+1 average sentiment direction
    if weight_total > 0:
        avg_sentiment = weighted_sum / weight_total
    else:
        avg_sentiment = 0.0

    # Scale by article volume: more articles = higher confidence in the direction
    # Saturates at 5 articles (as per the improvement doc)
    volume_scale = min(1.0, len(events) / 5)
    raw_score = avg_sentiment * volume_scale * 100
    score = max(-100, min(100, round(raw_score)))

    # Availability: do we have relevant news at all? Based on volume and recency.
    avg_recency = weight_total / len(events) if events else 0.0
    availability = round(min(1.0, len(events) / 3) * min(1.0, avg_recency / 0.5), 4)

    # Conviction: how unanimous is the sentiment?
    directional = bullish_count + bearish_count
    if directional > 0:
        dominant = max(bullish_count, bearish_count)
        conviction = round(dominant / directional, 4)
    else:
        conviction = 0.0

    return {
        "score": score,
        "availability": availability,
        "conviction": conviction,
        "confidence": availability,
        "details": {
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "neutral_count": neutral_count,
            "high_impact_count": high_impact_count,
            "article_count": len(events),
            "avg_sentiment": round(avg_sentiment, 4),
            "volume_scale": round(volume_scale, 4),
        },
    }
