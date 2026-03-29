"""Pipeline monitor API — evaluation history and summary stats."""

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.api.auth import require_auth
from app.db.models import PipelineEvaluation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


class Period(str, Enum):
    h1 = "1h"
    h6 = "6h"
    h24 = "24h"
    d7 = "7d"


PERIOD_HOURS = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}


def _eval_to_dict(e: PipelineEvaluation) -> dict:
    return {
        "id": e.id,
        "pair": e.pair,
        "timeframe": e.timeframe,
        "evaluated_at": e.evaluated_at.isoformat(),
        "emitted": e.emitted,
        "signal_id": e.signal_id,
        "final_score": e.final_score,
        "effective_threshold": e.effective_threshold,
        "tech_score": e.tech_score,
        "flow_score": e.flow_score,
        "onchain_score": e.onchain_score,
        "pattern_score": e.pattern_score,
        "liquidation_score": e.liquidation_score,
        "confluence_score": e.confluence_score,
        "indicator_preliminary": e.indicator_preliminary,
        "blended_score": e.blended_score,
        "ml_score": round(e.ml_score, 4) if e.ml_score is not None else None,
        "ml_confidence": round(e.ml_confidence, 4) if e.ml_confidence is not None else None,
        "llm_contribution": e.llm_contribution,
        "ml_agreement": e.ml_agreement,
        "indicators": e.indicators,
        "regime": e.regime,
        "availabilities": e.availabilities,
    }


@router.get("/evaluations")
async def list_evaluations(
    request: Request,
    _user: dict = require_auth(),
    pair: str | None = Query(None),
    emitted: bool | None = Query(None),
    after: datetime | None = Query(None),
    before: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    db = request.app.state.db
    async with db.session_factory() as session:
        q = select(PipelineEvaluation)
        count_q = select(func.count()).select_from(PipelineEvaluation)

        if pair is not None:
            q = q.where(PipelineEvaluation.pair == pair)
            count_q = count_q.where(PipelineEvaluation.pair == pair)
        if emitted is not None:
            q = q.where(PipelineEvaluation.emitted == emitted)
            count_q = count_q.where(PipelineEvaluation.emitted == emitted)
        if after is not None:
            q = q.where(PipelineEvaluation.evaluated_at >= after)
            count_q = count_q.where(PipelineEvaluation.evaluated_at >= after)
        if before is not None:
            q = q.where(PipelineEvaluation.evaluated_at <= before)
            count_q = count_q.where(PipelineEvaluation.evaluated_at <= before)

        q = q.order_by(PipelineEvaluation.evaluated_at.desc()).offset(offset).limit(limit)

        result = await session.execute(q)
        items = result.scalars().all()
        total = (await session.execute(count_q)).scalar()

    return {"items": [_eval_to_dict(e) for e in items], "total": total}


@router.get("/summary")
async def get_summary(
    request: Request,
    _user: dict = require_auth(),
    period: Period = Query(Period.h24),
):
    hours = PERIOD_HOURS[period.value]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    db = request.app.state.db
    pairs = request.app.state.settings.pairs

    async with db.session_factory() as session:
        base = PipelineEvaluation.evaluated_at >= cutoff

        main = await session.execute(
            select(
                func.count().label("total"),
                func.count().filter(PipelineEvaluation.emitted == True).label("emitted_count"),
                func.avg(func.abs(PipelineEvaluation.final_score)).label("avg_abs"),
            ).where(base)
        )
        row = main.one()
        total = row.total or 0
        emitted_count = row.emitted_count or 0
        avg_abs = round(float(row.avg_abs), 1) if row.avg_abs else 0.0

        pair_rows = await session.execute(
            select(
                PipelineEvaluation.pair,
                func.count().label("total"),
                func.count().filter(PipelineEvaluation.emitted == True).label("emitted_count"),
                func.avg(func.abs(PipelineEvaluation.final_score)).label("avg_abs"),
            ).where(base).group_by(PipelineEvaluation.pair)
        )
        pair_map = {r.pair: r for r in pair_rows.all()}

    per_pair = []
    for p in pairs:
        r = pair_map.get(p)
        if r:
            p_total = r.total or 0
            p_emitted = r.emitted_count or 0
            per_pair.append({
                "pair": p,
                "total": p_total,
                "emitted": p_emitted,
                "emission_rate": round(p_emitted / p_total, 4) if p_total else 0.0,
                "avg_abs_score": round(float(r.avg_abs), 1) if r.avg_abs else 0.0,
            })
        else:
            per_pair.append({
                "pair": p, "total": 0, "emitted": 0,
                "emission_rate": 0.0, "avg_abs_score": 0.0,
            })

    return {
        "period": period.value,
        "total_evaluations": total,
        "emitted_count": emitted_count,
        "emission_rate": round(emitted_count / total, 4) if total else 0.0,
        "avg_abs_score": avg_abs,
        "per_pair": per_pair,
    }
