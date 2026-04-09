import re

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.auth import require_agent_key, require_auth
from app.db.models import AgentAnalysis

router = APIRouter(prefix="/api/agent")

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MAX_ANNOTATIONS = 30
_VALID_TYPES = {"brief", "pair_dive", "signal_explain", "position_check"}
_VALID_ANNOTATION_TYPES = {
    "level",
    "zone",
    "signal",
    "regime",
    "trendline",
    "position",
}


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


class AnnotationIn(BaseModel):
    type: str
    pair: str
    reasoning: str = ""
    label: str = ""

    model_config = {"extra": "allow"}

    @field_validator("reasoning", "label", mode="before")
    @classmethod
    def sanitize_text(cls, value):
        if isinstance(value, str):
            return _strip_html(value)
        return value


class AnalysisCreate(BaseModel):
    type: str
    pair: str | None = None
    narrative: str
    annotations: list[AnnotationIn] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value):
        if value not in _VALID_TYPES:
            raise ValueError(f"type must be one of {_VALID_TYPES}")
        return value

    @field_validator("narrative", mode="before")
    @classmethod
    def sanitize_narrative(cls, value):
        if isinstance(value, str):
            return _strip_html(value)
        return value


def _serialize_analysis(row: AgentAnalysis) -> dict:
    return {
        "id": row.id,
        "type": row.type,
        "pair": row.pair,
        "narrative": row.narrative,
        "annotations": row.annotations,
        "metadata": row.metadata_,
        "created_at": row.created_at.isoformat(),
    }


@router.post("/analysis")
async def post_analysis(
    request: Request,
    body: AnalysisCreate,
    _key: dict = require_agent_key(),
):
    valid_annotations = []
    for annotation in body.annotations[:_MAX_ANNOTATIONS]:
        if annotation.type in _VALID_ANNOTATION_TYPES:
            valid_annotations.append(annotation.model_dump())

    db = request.app.state.db
    async with db.session_factory() as session:
        row = AgentAnalysis(
            type=body.type,
            pair=body.pair,
            narrative=body.narrative,
            annotations=valid_annotations,
            metadata_=body.metadata,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        result = _serialize_analysis(row)

    await request.app.state.manager.broadcast_event(
        {"type": "agent_analysis", "data": result}
    )
    return result


@router.get("/analysis")
async def get_analysis(
    request: Request,
    _user: dict = require_auth(),
    type: str | None = Query(None),
    pair: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    db = request.app.state.db
    async with db.session_factory() as session:
        stmt = select(AgentAnalysis).order_by(AgentAnalysis.created_at.desc())
        if type:
            stmt = stmt.where(AgentAnalysis.type == type)
        if pair:
            stmt = stmt.where(AgentAnalysis.pair == pair)
        stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        rows = result.scalars().all()

    return [_serialize_analysis(row) for row in rows]
