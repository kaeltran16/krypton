# Agent Intelligence Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the chart tab with a desktop agent-annotated chart + narrative panel powered by Claude Code CLI, MCP server, and skills.

**Architecture:** MCP server (Python on host) reads Postgres/Redis and exposes tools. Claude Code skills orchestrate analysis via MCP tools and POST results to backend. Frontend renders annotated chart + narrative. Mobile shows narrative only.

**Tech Stack:** Python 3.11+, FastMCP (mcp SDK), SQLAlchemy async, Redis, FastAPI, React 19, TypeScript, lightweight-charts v5, Zustand, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-04-09-agent-intelligence-tab-design.md`

**Commit policy:** Do NOT commit after each task. Commit once at the end after the verification checklist passes.

---

## Prerequisites

The MCP server runs on the Windows host (not in Docker). Ensure Python 3.11+ is installed locally:
```bash
python --version  # must be 3.11+
```

Backend Docker services must also be running before any migration or backend test step:
```bash
cd backend
docker compose up -d
```

---

## File Structure

### New Files
```
backend/
  app/
    api/
      agent.py                    — POST + GET /api/agent/analysis endpoints
  mcp/
    server.py                     — FastMCP server with all tools
    requirements.txt              — Host-side Python dependencies

.claude/
  skills/
    market-brief.md               — Cross-pair analysis skill
    pair-dive.md                  — Single-pair deep analysis skill
    signal-explain.md             — Signal rationale skill
    position-check.md             — Open position assessment skill

web/src/features/agent/
  types.ts                        — Annotation + AgentAnalysis types
  store.ts                        — Zustand store for agent analyses
  components/
    AgentView.tsx                 — Tab entry point, responsive layout
    AgentChart.tsx                — Candlestick chart + annotation primitives
    NarrativePanel.tsx            — Analysis text + history
    AnnotationPopover.tsx         — Click-to-reveal reasoning popover
  hooks/
    useAgentAnalysis.ts           — Fetch + WS subscription
    useChartData.ts               — OKX candle streaming (simplified rewrite)
  lib/
    primitives/
      types.ts                    — Shared primitive interfaces
      HorizontalPrimitive.ts      — Price level lines
      ZonePrimitive.ts            — Price zone rectangles
      RegimeZonePrimitive.ts      — Background regime shading
      TrendLinePrimitive.ts       — Two-point trend lines
      PositionPrimitive.ts        — Entry/SL/TP level lines
```

### Modified Files
```
backend/app/config.py             — Add agent_api_key setting
backend/app/db/models.py          — Add AgentAnalysis model
backend/app/api/auth.py           — Add require_agent_key() dependency
backend/app/main.py               — Register agent router
web/src/App.tsx                   — Swap ChartView for AgentView
web/src/shared/components/Layout.tsx — Rename chart tab to agent
web/src/shared/stores/navigation.ts — Update Tab type
web/src/shared/lib/api.ts         — Add agent API methods
web/src/features/signals/hooks/useSignalWebSocket.ts — Handle agent_analysis events
web/src/shared/theme.ts           — Add annotation colors
```

### Deleted Files
```
web/src/features/chart/           — Entire directory (~1,628 lines)
```

---

## Task 1: Backend — AgentAnalysis Model + Migration

**Files:**
- Modify: `backend/app/db/models.py`
- Create: migration via `alembic revision --autogenerate`

- [ ] **Step 1: Add AgentAnalysis model to models.py**

Add at the end of `backend/app/db/models.py`, before any trailing whitespace:

```python
class AgentAnalysis(Base):
    __tablename__ = "agent_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    pair: Mapped[str | None] = mapped_column(String(32), nullable=True)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    annotations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_agent_analysis_created", "created_at"),
        Index("ix_agent_analysis_pair_type", "pair", "type"),
    )
```

Note: column named `metadata` in DB, mapped as `metadata_` in Python to avoid shadowing SQLAlchemy's `metadata` attribute.

- [ ] **Step 2: Generate Alembic migration**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add agent_analyses table"
```

Expected: New migration file created in `backend/app/db/migrations/versions/`.

- [ ] **Step 3: Run the migration**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head
```

Expected: `agent_analyses` table created with indices.

- [ ] **Step 4: Verify table exists**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "
from sqlalchemy import create_engine, inspect
engine = create_engine('postgresql://krypton:krypton@postgres:5432/krypton')
inspector = inspect(engine)
tables = inspector.get_table_names()
assert 'agent_analyses' in tables, f'Table not found. Tables: {tables}'
cols = [c['name'] for c in inspector.get_columns('agent_analyses')]
print(f'agent_analyses columns: {cols}')
"
```

Expected: `agent_analyses columns: ['id', 'type', 'pair', 'narrative', 'annotations', 'metadata', 'created_at']`

---

## Task 2: Backend — Agent Key Auth + Config

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/auth.py`

- [ ] **Step 1: Add agent_api_key to Settings**

In `backend/app/config.py`, add to the Settings class alongside other secret fields:

```python
    agent_api_key: str = ""
```

- [ ] **Step 2: Add AGENT_API_KEY to .env**

In `backend/.env`, add:

```
AGENT_API_KEY=your-secret-agent-key-here
```

- [ ] **Step 3: Add require_agent_key() to auth.py**

At the end of `backend/app/api/auth.py`, add:

```python
async def _verify_agent_key(request: Request) -> dict:
    key = request.headers.get("X-Agent-Key")
    if not key:
        raise HTTPException(401, "Agent key required")
    if key != request.app.state.settings.agent_api_key:
        raise HTTPException(403, "Invalid agent key")
    return {"agent": True}


def require_agent_key():
    return Depends(_verify_agent_key)
```

- [ ] **Step 4: Verify auth loads in test conftest**

In `backend/tests/conftest.py`, add to `_test_lifespan` mock_settings:

```python
    mock_settings.agent_api_key = "test-agent-key"
```

---

## Task 3: Backend — Agent Analysis Endpoints

**Files:**
- Create: `backend/app/api/agent.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create the agent router**

Create `backend/app/api/agent.py`:

```python
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, field_validator

from app.api.auth import require_agent_key, require_auth
from app.db.models import AgentAnalysis

router = APIRouter(prefix="/api/agent")

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MAX_ANNOTATIONS = 30
_VALID_TYPES = {"brief", "pair_dive", "signal_explain", "position_check"}
_VALID_ANNOTATION_TYPES = {"level", "zone", "signal", "regime", "trendline", "position"}


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
    def sanitize_text(cls, v):
        if isinstance(v, str):
            return _strip_html(v)
        return v


class AnalysisCreate(BaseModel):
    type: str
    pair: str | None = None
    narrative: str
    annotations: list[AnnotationIn] = []
    metadata: dict = {}

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v not in _VALID_TYPES:
            raise ValueError(f"type must be one of {_VALID_TYPES}")
        return v

    @field_validator("narrative", mode="before")
    @classmethod
    def sanitize_narrative(cls, v):
        if isinstance(v, str):
            return _strip_html(v)
        return v


class AnalysisOut(BaseModel):
    id: int
    type: str
    pair: str | None
    narrative: str
    annotations: list
    metadata: dict
    created_at: str

    model_config = {"from_attributes": True}


@router.post("/analysis")
async def post_analysis(
    request: Request,
    body: AnalysisCreate,
    _key: dict = require_agent_key(),
):
    valid_annotations = []
    for ann in body.annotations[:_MAX_ANNOTATIONS]:
        if ann.type in _VALID_ANNOTATION_TYPES:
            valid_annotations.append(ann.model_dump())

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

        result = {
            "id": row.id,
            "type": row.type,
            "pair": row.pair,
            "narrative": row.narrative,
            "annotations": row.annotations,
            "metadata": row.metadata_,
            "created_at": row.created_at.isoformat(),
        }

    manager = request.app.state.manager
    await manager.broadcast_event({"type": "agent_analysis", "data": result})

    return result


@router.get("/analysis")
async def get_analysis(
    request: Request,
    _user: dict = require_auth(),
    type: str | None = Query(None),
    pair: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    from sqlalchemy import select

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

    return [
        {
            "id": r.id,
            "type": r.type,
            "pair": r.pair,
            "narrative": r.narrative,
            "annotations": r.annotations,
            "metadata": r.metadata_,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
```

- [ ] **Step 2: Register agent router in main.py**

In `backend/app/main.py`, after the monitor router registration (around line 2401), add:

```python
    from app.api.agent import router as agent_router
    app.include_router(agent_router)
```

- [ ] **Step 3: Verify endpoints load**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "
from app.main import create_app
app = create_app()
routes = [r.path for r in app.routes]
assert '/api/agent/analysis' in routes, f'Route missing: {routes}'
print('Agent routes registered OK')
"
```

- [ ] **Step 4: Write endpoint tests**

Create `backend/tests/api/test_agent.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_post_analysis_requires_agent_key(client):
    resp = await client.post("/api/agent/analysis", json={
        "type": "brief", "narrative": "test"
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_analysis_rejects_invalid_key(client):
    resp = await client.post(
        "/api/agent/analysis",
        json={"type": "brief", "narrative": "test"},
        headers={"X-Agent-Key": "wrong-key"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_analysis_validates_type(client):
    resp = await client.post(
        "/api/agent/analysis",
        json={"type": "invalid_type", "narrative": "test"},
        headers={"X-Agent-Key": "test-agent-key"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_analysis_strips_html_from_reasoning(client, app):
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    saved_row = MagicMock()
    saved_row.id = 1
    saved_row.type = "brief"
    saved_row.pair = None
    saved_row.narrative = "clean text"
    saved_row.annotations = [{"type": "level", "pair": "BTC-USDT-SWAP",
                               "reasoning": "safe text", "label": "Support"}]
    saved_row.metadata_ = {}
    saved_row.created_at = datetime.now(timezone.utc)

    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock(side_effect=lambda r: setattr(r, '__dict__', saved_row.__dict__) or None)

    app.state.db.session_factory = MagicMock(return_value=mock_session)

    resp = await client.post(
        "/api/agent/analysis",
        json={
            "type": "brief",
            "narrative": "<script>alert('xss')</script>clean text",
            "annotations": [{
                "type": "level",
                "pair": "BTC-USDT-SWAP",
                "reasoning": "<img onerror=alert(1)>safe text",
                "label": "Support",
                "price": 65000,
                "style": "solid",
                "color": "#ff0000",
            }],
        },
        headers={"X-Agent-Key": "test-agent-key"},
    )
    assert resp.status_code == 200

    call_args = mock_session.add.call_args[0][0]
    assert "<script>" not in call_args.narrative
    assert "<img" not in call_args.annotations[0]["reasoning"]


@pytest.mark.asyncio
async def test_get_analysis_requires_auth(client):
    resp = await client.get("/api/agent/analysis")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_analysis_success(client, app):
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    saved_row = MagicMock()
    saved_row.id = 1
    saved_row.type = "brief"
    saved_row.pair = None
    saved_row.narrative = "Market is bullish"
    saved_row.annotations = []
    saved_row.metadata_ = {"focus": "BTC"}
    saved_row.created_at = datetime.now(timezone.utc)

    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock(side_effect=lambda r: setattr(r, '__dict__', saved_row.__dict__) or None)

    app.state.db.session_factory = MagicMock(return_value=mock_session)
    app.state.manager.broadcast_event = AsyncMock()

    resp = await client.post(
        "/api/agent/analysis",
        json={
            "type": "brief",
            "narrative": "Market is bullish",
            "annotations": [],
            "metadata": {"focus": "BTC"},
        },
        headers={"X-Agent-Key": "test-agent-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "brief"
    assert data["narrative"] == "Market is bullish"

    # verify WS broadcast was called
    app.state.manager.broadcast_event.assert_awaited_once()
    broadcast_payload = app.state.manager.broadcast_event.call_args[0][0]
    assert broadcast_payload["type"] == "agent_analysis"


@pytest.mark.asyncio
async def test_post_analysis_caps_annotations_at_30(client, app):
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    saved_row = MagicMock()
    saved_row.id = 1
    saved_row.type = "brief"
    saved_row.pair = None
    saved_row.narrative = "test"
    saved_row.annotations = [{"type": "level", "pair": "BTC-USDT-SWAP", "reasoning": "x"}] * 30
    saved_row.metadata_ = {}
    saved_row.created_at = datetime.now(timezone.utc)

    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock(side_effect=lambda r: setattr(r, '__dict__', saved_row.__dict__) or None)

    app.state.db.session_factory = MagicMock(return_value=mock_session)
    app.state.manager.broadcast_event = AsyncMock()

    annotations = [{"type": "level", "pair": "BTC-USDT-SWAP", "reasoning": f"level {i}",
                     "label": f"L{i}", "price": 60000 + i, "style": "solid", "color": "#fff"}
                    for i in range(35)]

    resp = await client.post(
        "/api/agent/analysis",
        json={"type": "brief", "narrative": "test", "annotations": annotations},
        headers={"X-Agent-Key": "test-agent-key"},
    )
    assert resp.status_code == 200
    call_args = mock_session.add.call_args[0][0]
    assert len(call_args.annotations) <= 30
```

- [ ] **Step 5: Run tests**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_agent.py -v
```

Expected: All tests pass.

---

## Task 4: MCP Server — Base + Smoke Test

**Files:**
- Create: `backend/mcp/server.py`
- Create: `backend/mcp/requirements.txt`

- [ ] **Step 1: Create requirements.txt**

Create `backend/mcp/requirements.txt`:

```
mcp[cli]>=1.0.0
sqlalchemy[asyncio]>=2.0
asyncpg>=0.29
redis>=5.0
httpx>=0.27
pandas>=2.0
numpy>=1.24
```

- [ ] **Step 2: Install MCP server dependencies on host**

```bash
pip install -r backend/mcp/requirements.txt
```

- [ ] **Step 3: Create the MCP server with get_regime smoke test tool**

Do **not** create `backend/mcp/__init__.py`. That turns the local folder into a package named `mcp`, which shadows the external `mcp` dependency and breaks `from mcp.server.fastmcp import FastMCP`.

Create `backend/mcp/server.py`:

```python
import json
import os
import sys

# add backend/ to path so we can import app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import redis.asyncio as aioredis

from app.db.database import Base
from app.db.models import (
    AgentAnalysis,
    OrderFlowSnapshot,
    PipelineEvaluation,
    Signal,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://krypton:krypton@localhost:5432/krypton"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "")
KRYPTON_API_URL = os.environ.get("KRYPTON_API_URL", "http://localhost:8000")
OKX_API_KEY = os.environ.get("OKX_API_KEY", "")
OKX_SECRET_KEY = os.environ.get("OKX_SECRET_KEY", "")
OKX_PASSPHRASE = os.environ.get("OKX_PASSPHRASE", "")

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
redis_client = aioredis.from_url(REDIS_URL)

mcp = FastMCP("krypton", instructions=(
    "Krypton trading engine MCP server. "
    "Provides tools to read market regime, signals, order flow, "
    "candles, indicators, positions, and to post analysis results."
))


@mcp.tool()
async def get_regime(pair: str | None = None) -> str:
    """Get current market regime for one or all pairs.

    Returns regime mix (trending/ranging/volatile/steady weights)
    plus raw indicators (ADX, BB width) from the latest pipeline evaluation.

    Args:
        pair: e.g. "BTC-USDT-SWAP". If omitted, returns all pairs.
    """
    async with SessionLocal() as session:
        stmt = (
            select(PipelineEvaluation)
            .order_by(PipelineEvaluation.evaluated_at.desc())
        )
        if pair:
            stmt = stmt.where(PipelineEvaluation.pair == pair).limit(1)
        else:
            # latest per pair using distinct on
            from sqlalchemy import distinct
            pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "WIF-USDT-SWAP"]
            results = []
            for p in pairs:
                row = (await session.execute(
                    stmt.where(PipelineEvaluation.pair == p).limit(1)
                )).scalar_one_or_none()
                if row:
                    results.append(row)
            return json.dumps([
                {
                    "pair": r.pair,
                    "timeframe": r.timeframe,
                    "regime": r.regime,
                    "indicators": {
                        k: r.indicators.get(k)
                        for k in ("adx", "bb_width_pct", "rsi", "atr")
                        if k in r.indicators
                    },
                    "evaluated_at": r.evaluated_at.isoformat(),
                }
                for r in results
            ], indent=2)

        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return json.dumps({"error": f"No evaluation found for {pair}"})
        return json.dumps({
            "pair": row.pair,
            "timeframe": row.timeframe,
            "regime": row.regime,
            "indicators": {
                k: row.indicators.get(k)
                for k in ("adx", "bb_width_pct", "rsi", "atr")
                if k in row.indicators
            },
            "evaluated_at": row.evaluated_at.isoformat(),
        }, indent=2)


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Smoke test — verify MCP server starts**

```bash
cd backend && python -c "
import importlib.util
spec = importlib.util.spec_from_file_location('krypton_mcp_server', 'mcp/server.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mcp = mod.mcp
print('MCP server created OK, tools:', [t.name for t in mcp._tool_manager.list_tools()])
"
```

Expected: `MCP server created OK, tools: ['get_regime']`

- [ ] **Step 5: Configure MCP for Claude Code**

Create or update `.claude/mcp.json` (this file is gitignored):

```json
{
  "mcpServers": {
    "krypton": {
      "command": "python",
      "args": ["backend/mcp/server.py"],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://krypton:krypton@localhost:5432/krypton",
        "REDIS_URL": "redis://localhost:6379/0",
        "OKX_API_KEY": "",
        "OKX_SECRET_KEY": "",
        "OKX_PASSPHRASE": "",
        "AGENT_API_KEY": "",
        "KRYPTON_API_URL": "http://localhost:8000"
      }
    }
  }
}
```

Fill in actual credentials from `backend/.env`.

- [ ] **Step 6: Smoke test via Claude Code CLI**

Restart Claude Code so it picks up the MCP config. Then run:

```
claude -p "Use the get_regime tool to check BTC-USDT-SWAP regime"
```

Expected: Claude calls `get_regime`, returns regime data from Postgres.

---

## Task 5: MCP Server — All Read Tools

**Files:**
- Modify: `backend/mcp/server.py`

- [ ] **Step 1: Add get_candles tool**

Add to `backend/mcp/server.py`, after the `get_regime` tool:

```python
@mcp.tool()
async def get_candles(pair: str, timeframe: str = "1h", limit: int = 100) -> str:
    """Get recent OHLCV candles from Redis cache.

    Args:
        pair: e.g. "BTC-USDT-SWAP"
        timeframe: "15m", "1h", "4h", "1d"
        limit: Number of candles (max 200)
    """
    cache_key = f"candles:{pair}:{timeframe}"
    raw = await redis_client.lrange(cache_key, -min(limit, 200), -1)
    if not raw:
        return json.dumps({"error": f"No candles cached for {cache_key}"})
    candles = [json.loads(c) for c in raw]
    return json.dumps(candles)
```

- [ ] **Step 2: Add get_signals tool**

```python
@mcp.tool()
async def get_signals(
    pair: str | None = None,
    outcome: str | None = None,
    limit: int = 10,
) -> str:
    """Get recent trading signals from the engine.

    Args:
        pair: Filter by pair. Omit for all pairs.
        outcome: Filter by outcome (PENDING, TP1_HIT, TP2_HIT, SL_HIT, TP1_TRAIL, TP1_TP2, EXPIRED). Omit for all.
        limit: Max results (default 10).
    """
    async with SessionLocal() as session:
        stmt = select(Signal).order_by(Signal.created_at.desc())
        if pair:
            stmt = stmt.where(Signal.pair == pair)
        if outcome:
            stmt = stmt.where(Signal.outcome == outcome)
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    return json.dumps([
        {
            "id": r.id,
            "pair": r.pair,
            "timeframe": r.timeframe,
            "direction": r.direction,
            "final_score": r.final_score,
            "traditional_score": r.traditional_score,
            "outcome": r.outcome,
            "entry": float(r.entry) if r.entry else None,
            "stop_loss": float(r.stop_loss) if r.stop_loss else None,
            "take_profit_1": float(r.take_profit_1) if r.take_profit_1 else None,
            "take_profit_2": float(r.take_profit_2) if r.take_profit_2 else None,
            "explanation": r.explanation,
            "raw_indicators": r.raw_indicators,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ], indent=2, default=str)
```

- [ ] **Step 3: Add get_signal_scores tool**

```python
@mcp.tool()
async def get_signal_scores(pair: str) -> str:
    """Get the latest pipeline score breakdown for a pair.

    Returns tech, flow, onchain, pattern, ML, blended, and final scores
    from the most recent pipeline evaluation.

    Args:
        pair: e.g. "BTC-USDT-SWAP"
    """
    async with SessionLocal() as session:
        stmt = (
            select(PipelineEvaluation)
            .where(PipelineEvaluation.pair == pair)
            .order_by(PipelineEvaluation.evaluated_at.desc())
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return json.dumps({"error": f"No evaluation found for {pair}"})

    return json.dumps({
        "pair": row.pair,
        "timeframe": row.timeframe,
        "tech_score": row.tech_score,
        "flow_score": row.flow_score,
        "onchain_score": row.onchain_score,
        "pattern_score": row.pattern_score,
        "liquidation_score": row.liquidation_score,
        "confluence_score": row.confluence_score,
        "news_score": row.news_score,
        "ml_score": row.ml_score,
        "ml_confidence": row.ml_confidence,
        "blended_score": row.blended_score,
        "final_score": row.final_score,
        "emitted": row.emitted,
        "evaluated_at": row.evaluated_at.isoformat(),
    }, indent=2)
```

- [ ] **Step 4: Add get_order_flow tool**

```python
@mcp.tool()
async def get_order_flow(pair: str) -> str:
    """Get latest order flow data: funding rate, open interest, long/short ratio.

    Returns the most recent OrderFlowSnapshot plus trend over last 5 snapshots.

    Args:
        pair: e.g. "BTC-USDT-SWAP"
    """
    async with SessionLocal() as session:
        stmt = (
            select(OrderFlowSnapshot)
            .where(OrderFlowSnapshot.pair == pair)
            .order_by(OrderFlowSnapshot.timestamp.desc())
            .limit(5)
        )
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            return json.dumps({"error": f"No order flow data for {pair}"})

    latest = rows[0]
    trend = None
    if len(rows) >= 2:
        oldest = rows[-1]
        trend = {
            "funding_direction": (
                "rising" if (latest.funding_rate or 0) > (oldest.funding_rate or 0)
                else "falling"
            ),
            "oi_direction": (
                "rising" if (latest.open_interest or 0) > (oldest.open_interest or 0)
                else "falling"
            ),
            "snapshots_compared": len(rows),
        }

    return json.dumps({
        "pair": pair,
        "funding_rate": latest.funding_rate,
        "open_interest": latest.open_interest,
        "oi_change_pct": latest.oi_change_pct,
        "long_short_ratio": latest.long_short_ratio,
        "cvd_delta": latest.cvd_delta,
        "timestamp": latest.timestamp.isoformat(),
        "trend": trend,
    }, indent=2)
```

- [ ] **Step 5: Add get_indicators tool**

```python
@mcp.tool()
async def get_indicators(pair: str, timeframe: str = "1h") -> str:
    """Get computed indicator values from the latest pipeline evaluation.

    Returns raw indicator values (RSI, ADX, BB position, MACD, etc.)
    stored during the most recent pipeline run.

    Args:
        pair: e.g. "BTC-USDT-SWAP"
        timeframe: "15m", "1h", "4h". Defaults to "1h".
    """
    async with SessionLocal() as session:
        stmt = (
            select(PipelineEvaluation)
            .where(PipelineEvaluation.pair == pair)
            .where(PipelineEvaluation.timeframe == timeframe)
            .order_by(PipelineEvaluation.evaluated_at.desc())
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return json.dumps({"error": f"No evaluation for {pair} {timeframe}"})

    return json.dumps({
        "pair": pair,
        "timeframe": timeframe,
        "indicators": row.indicators,
        "regime": row.regime,
        "evaluated_at": row.evaluated_at.isoformat(),
    }, indent=2)
```

- [ ] **Step 6: Add get_performance tool**

```python
@mcp.tool()
async def get_performance(pair: str | None = None) -> str:
    """Get recent signal performance — hit rates, P&L stats.

    Args:
        pair: Filter by pair. Omit for overall stats.
    """
    async with SessionLocal() as session:
        stmt = (
            select(Signal)
            .where(Signal.outcome.in_(["TP1_HIT", "TP2_HIT", "SL_HIT", "TP1_TRAIL", "TP1_TP2", "EXPIRED"]))
            .order_by(Signal.created_at.desc())
            .limit(50)
        )
        if pair:
            stmt = stmt.where(Signal.pair == pair)
        rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        return json.dumps({"message": "No resolved signals found"})

    total = len(rows)
    wins = sum(1 for r in rows if r.outcome in ("TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2"))
    losses = sum(1 for r in rows if r.outcome == "SL_HIT")
    expired = sum(1 for r in rows if r.outcome == "EXPIRED")

    return json.dumps({
        "pair": pair or "all",
        "total_signals": total,
        "wins": wins,
        "losses": losses,
        "expired": expired,
        "win_rate": round(wins / max(total - expired, 1) * 100, 1),
    }, indent=2)
```

- [ ] **Step 7: Add get_positions tool**

```python
@mcp.tool()
async def get_positions() -> str:
    """Get current open positions from OKX.

    Returns position details: pair, side, size, entry price, unrealized PnL, leverage.
    Returns empty list if OKX credentials not configured or API error.
    """
    if not OKX_API_KEY:
        return json.dumps({"error": "OKX credentials not configured", "positions": []})

    try:
        from app.exchange.okx_client import OKXClient
        client = OKXClient(
            api_key=OKX_API_KEY,
            api_secret=OKX_SECRET_KEY,
            passphrase=OKX_PASSPHRASE,
        )
        positions = await client.get_positions()
        return json.dumps({"positions": positions}, indent=2)
    except Exception as e:
        return json.dumps({"error": f"OKX API error: {str(e)}", "positions": []})
```

- [ ] **Step 8: Add get_last_analysis tool**

```python
@mcp.tool()
async def get_last_analysis(type: str | None = None, pair: str | None = None) -> str:
    """Get the most recent agent analysis for comparison with current state.

    Args:
        type: Filter by analysis type (brief, pair_dive, signal_explain, position_check).
        pair: Filter by pair.
    """
    async with SessionLocal() as session:
        stmt = select(AgentAnalysis).order_by(AgentAnalysis.created_at.desc())
        if type:
            stmt = stmt.where(AgentAnalysis.type == type)
        if pair:
            stmt = stmt.where(AgentAnalysis.pair == pair)
        stmt = stmt.limit(1)
        row = (await session.execute(stmt)).scalar_one_or_none()

    if not row:
        return json.dumps({"message": "No previous analysis found"})

    return json.dumps({
        "id": row.id,
        "type": row.type,
        "pair": row.pair,
        "narrative": row.narrative,
        "annotations": row.annotations,
        "metadata": row.metadata_,
        "created_at": row.created_at.isoformat(),
    }, indent=2)
```

- [ ] **Step 9: Verify all tools registered**

```bash
cd backend && python -c "
import sys; sys.path.insert(0, '.')
from mcp.server import mcp
tools = [t.name for t in mcp._tool_manager.list_tools()]
expected = ['get_regime', 'get_candles', 'get_signals', 'get_signal_scores',
            'get_order_flow', 'get_indicators', 'get_performance',
            'get_positions', 'get_last_analysis']
missing = [t for t in expected if t not in tools]
assert not missing, f'Missing tools: {missing}'
print(f'All {len(tools)} tools registered: {tools}')
"
```

---

## Task 6: MCP Server — post_analysis Tool

**Files:**
- Modify: `backend/mcp/server.py`

- [ ] **Step 1: Add post_analysis tool**

Add to `backend/mcp/server.py`:

```python
import httpx as _httpx


@mcp.tool()
async def post_analysis(
    type: str,
    narrative: str,
    annotations: list[dict] | None = None,
    metadata: dict | None = None,
    pair: str | None = None,
) -> str:
    """Post an analysis to the Krypton backend for display in the Agent tab.

    This is how analysis results get from the CLI to the frontend.

    Args:
        type: One of "brief", "pair_dive", "signal_explain", "position_check".
        narrative: The analysis text (3-5 sentences).
        annotations: List of chart annotation objects. Each must have: type, pair, reasoning.
        metadata: Additional structured data (score breakdowns, regime states).
        pair: Target pair. Required for pair_dive/signal_explain/position_check. Null for brief.
    """
    body = {
        "type": type,
        "pair": pair,
        "narrative": narrative,
        "annotations": annotations or [],
        "metadata": metadata or {},
    }

    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{KRYPTON_API_URL}/api/agent/analysis",
                json=body,
                headers={"X-Agent-Key": AGENT_API_KEY},
            )
            if resp.status_code != 200:
                return json.dumps({
                    "error": f"Backend returned {resp.status_code}: {resp.text}"
                })
            return json.dumps({"success": True, "analysis": resp.json()})
    except Exception as e:
        return json.dumps({"error": f"Failed to post analysis: {str(e)}"})
```

- [ ] **Step 2: Verify post_analysis is registered**

```bash
cd backend && python -c "
import importlib.util
spec = importlib.util.spec_from_file_location('krypton_mcp_server', 'mcp/server.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mcp = mod.mcp
tools = [t.name for t in mcp._tool_manager.list_tools()]
assert 'post_analysis' in tools, f'post_analysis missing. Tools: {tools}'
print('post_analysis registered OK')
"
```

---

## Task 7: Claude Code Skills

**Files:**
- Create: `.claude/skills/market-brief.md`
- Create: `.claude/skills/pair-dive.md`
- Create: `.claude/skills/signal-explain.md`
- Create: `.claude/skills/position-check.md`

- [ ] **Step 1: Create market-brief skill**

Create `.claude/skills/market-brief.md`:

```markdown
---
name: market-brief
description: Generate a cross-pair market analysis with chart annotations. Analyzes regime, scores, and order flow across all pairs.
---

# Market Brief

You are analyzing the current crypto market state across all monitored pairs using the Krypton trading engine's data.

## Instructions

1. Call `get_regime` (no pair arg) to get regime state for all pairs.
2. Call `get_signal_scores` for each pair: BTC-USDT-SWAP, ETH-USDT-SWAP, WIF-USDT-SWAP.
3. Call `get_order_flow` for each pair.
4. Identify the "focus pair" — the pair with the highest absolute `final_score`.
5. Call `get_indicators` for the focus pair.
6. Call `get_last_analysis` with type "brief" to compare with previous state.

## Analysis

Reason over all the data. Consider:
- Which pairs are trending vs ranging? How confident is the regime?
- Are scores approaching signal threshold? Any score decay or buildup?
- Order flow: any funding rate extremes, OI spikes, L/S ratio imbalances?
- For the focus pair: what do raw indicators say? RSI overbought/oversold? ADX trend strength?
- What changed since the last brief?

## Output

Call `post_analysis` with:
- `type`: "brief"
- `pair`: null (this is cross-pair)
- `narrative`: 3-5 sentence market read covering all pairs. Lead with the most important observation. Be specific — use numbers, not vague language.
- `annotations`: Array of chart annotations for ALL pairs. Each annotation MUST have a `pair` field. Include:
  - Key support/resistance levels (type: "level") for each pair showing interesting structure
  - Current regime zones (type: "regime") for each pair
  - Signal markers (type: "signal") if any signals are pending
  - Every annotation MUST have a `reasoning` field explaining WHY you drew it
- `metadata`: Object with score breakdowns per pair, regime states, focus pair name

## Annotation Format Examples

```json
{"type": "level", "pair": "BTC-USDT-SWAP", "price": 65200, "label": "Support", "style": "dashed", "color": "#2DD4A0", "reasoning": "Tested 3x in 48h, holding above EMA21"}
{"type": "regime", "pair": "ETH-USDT-SWAP", "from_time": 1712600000, "to_time": 1712688000, "regime": "ranging", "confidence": 0.65, "reasoning": "ADX at 18, tight BB squeeze suggests breakout imminent"}
```
```

- [ ] **Step 2: Create pair-dive skill**

Create `.claude/skills/pair-dive.md`:

```markdown
---
name: pair-dive
description: Deep analysis of a single trading pair with full chart annotations. Usage - /pair-dive BTC-USDT-SWAP
---

# Pair Deep Dive

You are performing a deep analysis of a single trading pair.

## Arguments

The user provides a pair name (e.g., "BTC-USDT-SWAP"). If not provided, ask which pair to analyze.

## Instructions

1. Call `get_regime` for the specified pair.
2. Call `get_signal_scores` for the pair.
3. Call `get_order_flow` for the pair.
4. Call `get_indicators` for the pair (try both "1h" and "4h" timeframes).
5. Call `get_candles` for the pair (limit 50) to see recent price action.
6. Call `get_signals` for the pair (limit 5) to see recent signal history.
7. Call `get_performance` for the pair to check signal track record.
8. Call `get_last_analysis` with type "pair_dive" and the pair to compare.

## Analysis

Build a comprehensive picture:
- Regime: trending/ranging/volatile? How strong? Transitioning?
- Key levels: where are support/resistance based on recent price action?
- Order flow: is smart money confirming or diverging from price?
- Indicators: RSI extremes? MACD crossover? BB squeeze/expansion?
- Recent signals: did they hit TP or SL? What's the engine's track record on this pair?
- What to watch for: what conditions would trigger the next signal?

## Output

Call `post_analysis` with:
- `type`: "pair_dive"
- `pair`: the analyzed pair
- `narrative`: 5-8 sentence detailed analysis. Be specific with numbers and levels.
- `annotations`: Full annotation set for this pair. Include:
  - Support/resistance levels (type: "level")
  - Price zones of interest (type: "zone") — accumulation, distribution, liquidity areas
  - Trend lines (type: "trendline") if clear trend structure exists
  - Regime zones (type: "regime") showing recent regime periods
  - Recent signal markers (type: "signal") if any
  - Every annotation MUST have `pair` set to the analyzed pair and `reasoning` explaining why
- `metadata`: Full score breakdown, indicator values, regime details
```

- [ ] **Step 3: Create signal-explain skill**

Create `.claude/skills/signal-explain.md`:

```markdown
---
name: signal-explain
description: Explain why a specific signal fired, with annotated chart context. Usage - /signal-explain <signal_id>
---

# Signal Explain

You are explaining why the Krypton engine generated a specific trading signal.

## Arguments

The user provides a signal ID (integer). If not provided, call `get_signals` with limit 5 to show recent signals and ask which one to explain.

## Instructions

1. Call `get_signals` — if the user gave an ID, look for it in the results. If not found, try increasing the limit.
2. From the signal data, note: pair, timeframe, direction, scores, entry/SL/TP levels, raw_indicators, explanation.
3. Call `get_candles` for the signal's pair and timeframe (limit 100) to see context around when it fired.
4. Call `get_indicators` for the pair and timeframe.
5. Call `get_order_flow` for the pair.
6. Call `get_regime` for the pair.

## Analysis

Reconstruct what the engine saw:
- What was the regime at signal time?
- Which score components were strongest? Which were weak?
- What indicators drove the technical score?
- Did order flow confirm or conflict?
- Did ML agree or disagree? What was the confidence?
- Were the entry/SL/TP levels reasonable given ATR and structure?
- If the signal has resolved: did it hit TP or SL? Why?

## Output

Call `post_analysis` with:
- `type`: "signal_explain"
- `pair`: the signal's pair
- `narrative`: 5-8 sentence explanation of why this signal fired and how it resolved (if resolved).
- `annotations`: Annotations around the signal. Include:
  - Signal marker at entry (type: "signal") with direction and entry price
  - Entry/SL/TP levels (type: "level") showing the risk/reward setup
  - Key support/resistance that informed the levels (type: "level")
  - Regime zone around signal time (type: "regime")
  - Every annotation MUST have `pair` and `reasoning`
- `metadata`: Full signal data including raw_indicators and score breakdown
```

- [ ] **Step 4: Create position-check skill**

Create `.claude/skills/position-check.md`:

```markdown
---
name: position-check
description: Assess current open OKX positions against engine state. Recommends hold/scale/exit.
---

# Position Check

You are assessing the user's current open positions against live market conditions.

## Instructions

1. Call `get_positions` to get current open OKX positions.
2. If no positions open, report that and exit (still call `post_analysis` with a brief narrative).
3. For each position's pair:
   a. Call `get_regime` for the pair.
   b. Call `get_order_flow` for the pair.
   c. Call `get_indicators` for the pair.
   d. Call `get_signal_scores` for the pair.

## Analysis

For each position, assess:
- Is the regime still favorable for this direction? (trending for trend-following, ranging for mean-reversion)
- Is order flow confirming or diverging? (funding against position = crowded, OI rising = conviction)
- Has the engine's score decayed since entry? Is conviction fading?
- Where is price relative to entry? Close to SL? Approaching TP?
- Risk: any red flags (regime transition, flow divergence, extreme funding)?

Provide a clear recommendation per position: HOLD, SCALE (add), REDUCE, or EXIT with reasoning.

## Output

Call `post_analysis` with:
- `type`: "position_check"
- `pair`: the primary position's pair (or first pair if multiple)
- `narrative`: Per-position assessment. Lead with the recommendation. Be direct.
- `annotations`: For each position, include:
  - Position entry level (type: "position") with entry_price, sl_price, tp_price, direction
  - Current key levels around the position (type: "level")
  - Current regime zone (type: "regime")
  - Every annotation MUST have `pair` and `reasoning`
- `metadata`: Position details, per-pair scores, regime states
```

---

## Task 8: Frontend — Remove Chart + Types + API Client

**Files:**
- Create: `web/src/features/agent/types.ts`
- Modify: `web/src/shared/lib/api.ts`
- Modify: `web/src/shared/stores/navigation.ts`
- Modify: `web/src/shared/components/Layout.tsx`
- Modify: `web/src/shared/theme.ts`

- [ ] **Step 1: Create agent types**

Create `web/src/features/agent/types.ts`:

```typescript
export interface HorizontalLevel {
  type: "level";
  pair: string;
  price: number;
  label: string;
  style: "solid" | "dashed";
  color: string;
  reasoning: string;
}

export interface Zone {
  type: "zone";
  pair: string;
  from_price: number;
  to_price: number;
  from_time?: number;
  to_time?: number;
  label: string;
  color: string;
  reasoning: string;
}

export interface SignalMarker {
  type: "signal";
  pair: string;
  time: number;
  price: number;
  direction: "long" | "short";
  label: string;
  reasoning: string;
}

export interface RegimeZone {
  type: "regime";
  pair: string;
  from_time: number;
  to_time: number;
  regime: "trending" | "ranging" | "volatile" | "steady";
  confidence: number;
  reasoning: string;
}

export interface TrendLine {
  type: "trendline";
  pair: string;
  from: { time: number; price: number };
  to: { time: number; price: number };
  label: string;
  color: string;
  reasoning: string;
}

export interface PositionMarker {
  type: "position";
  pair: string;
  entry_price: number;
  sl_price?: number;
  tp_price?: number;
  direction: "long" | "short";
  reasoning: string;
}

export type Annotation =
  | HorizontalLevel
  | Zone
  | SignalMarker
  | RegimeZone
  | TrendLine
  | PositionMarker;

export interface AgentAnalysis {
  id: number;
  type: "brief" | "pair_dive" | "signal_explain" | "position_check";
  pair: string | null;
  narrative: string;
  annotations: Annotation[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export type StalenessLevel = "fresh" | "aging" | "stale";

export function getStaleness(createdAt: string): StalenessLevel {
  const ageMs = Date.now() - new Date(createdAt).getTime();
  const hours = ageMs / (1000 * 60 * 60);
  if (hours < 4) return "fresh";
  if (hours < 24) return "aging";
  return "stale";
}

export function getAnnotationOpacity(staleness: StalenessLevel): number {
  if (staleness === "fresh") return 1;
  if (staleness === "aging") return 0.6;
  return 0.3;
}
```

- [ ] **Step 2: Add agent API methods**

In `web/src/shared/lib/api.ts`, add the `AgentAnalysis` import and API methods. After the existing `getCandles` method, add:

```typescript
  getAgentAnalyses: (params?: { type?: string; pair?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.type) query.set("type", params.type);
    if (params?.pair) query.set("pair", params.pair);
    if (params?.limit) query.set("limit", String(params.limit));
    const qs = query.toString();
    return request<AgentAnalysis[]>(`/api/agent/analysis${qs ? `?${qs}` : ""}`);
  },
```

Also add the `AgentAnalysis` interface import at the top of the api object's types section (or inline):

```typescript
export interface AgentAnalysis {
  id: number;
  type: string;
  pair: string | null;
  narrative: string;
  annotations: unknown[];
  metadata: Record<string, unknown>;
  created_at: string;
}
```

- [ ] **Step 3: Update Tab type and navigation store**

In `web/src/shared/stores/navigation.ts`, change:

```typescript
export type Tab = "home" | "chart" | "signals" | "positions" | "more";
```

to:

```typescript
export type Tab = "home" | "agent" | "signals" | "positions" | "more";
```

- [ ] **Step 4: Update Layout.tsx**

In `web/src/shared/components/Layout.tsx`, update the tab definitions:

Change `TAB_ICONS`:
```typescript
import { Home, BrainCircuit, Zap, Layers, MoreHorizontal } from "lucide-react";
// If BrainCircuit is unavailable in your lucide-react version, use Brain instead
```
and:
```typescript
const TAB_ICONS = {
  home: Home,
  agent: BrainCircuit,
  signals: Zap,
  positions: Layers,
  more: MoreHorizontal,
} as const;
```

Change `TAB_LABELS`:
```typescript
const TAB_LABELS: Record<Tab, string> = {
  home: "Home",
  agent: "Agent",
  signals: "Signals",
  positions: "Positions",
  more: "More",
};
```

Change `TABS`:
```typescript
const TABS: Tab[] = ["home", "agent", "signals", "positions", "more"];
```

Update the props interface and views object — rename `chart` to `agent`:
```typescript
// in props:
agent: React.ReactNode;
// in views:
const views = { home, agent, signals, positions, more } as const;
```

- [ ] **Step 5: Add annotation colors to theme**

In `web/src/shared/theme.ts`, add an `annotations` section to the theme object:

```typescript
  annotations: {
    level: "#2DD4A0",
    zone: "#F0B90B",
    signal_long: "#2DD4A0",
    signal_short: "#FB7185",
    regime_trending: "#2DD4A0",
    regime_ranging: "#F0B90B",
    regime_volatile: "#FB7185",
    regime_steady: "#8B9AFF",
    trendline: "#8E9AAD",
    position_long: "#2DD4A0",
    position_short: "#FB7185",
    sl: "#FB7185",
    tp: "#2DD4A0",
  },
```

- [ ] **Step 6: Verify build compiles**

```bash
cd web && pnpm build
```

Expected: Build succeeds while the legacy chart feature remains in place. Do not delete `web/src/features/chart/` until Task 14 switches `App.tsx` to `AgentView` and no imports remain.

---

## Task 9: Frontend — Agent Store + WS Handler

**Files:**
- Create: `web/src/features/agent/store.ts`
- Modify: `web/src/features/signals/hooks/useSignalWebSocket.ts`

- [ ] **Step 1: Create the agent Zustand store**

Create `web/src/features/agent/store.ts`:

```typescript
import { create } from "zustand";
import type { AgentAnalysis } from "./types";

interface AgentStore {
  analyses: AgentAnalysis[];
  selectedId: number | null;
  loading: boolean;

  setAnalyses: (analyses: AgentAnalysis[]) => void;
  addAnalysis: (analysis: AgentAnalysis) => void;
  selectAnalysis: (id: number | null) => void;
  setLoading: (loading: boolean) => void;

  getSelected: () => AgentAnalysis | undefined;
  getLatest: () => AgentAnalysis | undefined;
}

export const useAgentStore = create<AgentStore>((set, get) => ({
  analyses: [],
  selectedId: null,
  loading: false,

  setAnalyses: (analyses) => set({ analyses }),

  addAnalysis: (analysis) =>
    set((state) => ({
      analyses: [analysis, ...state.analyses].slice(0, 50),
      selectedId: analysis.id,
    })),

  selectAnalysis: (id) => set({ selectedId: id }),

  setLoading: (loading) => set({ loading }),

  getSelected: () => {
    const { analyses, selectedId } = get();
    if (selectedId === null) return analyses[0];
    return analyses.find((a) => a.id === selectedId) ?? analyses[0];
  },

  getLatest: () => get().analyses[0],
}));
```

- [ ] **Step 2: Add agent_analysis WS event handler**

In `web/src/features/signals/hooks/useSignalWebSocket.ts`, add the import at the top:

```typescript
import { useAgentStore } from "../../agent/store";
```

Then in the `ws.onMessage` handler, add a new `else if` branch (before the closing brace):

```typescript
      } else if (data.type === "agent_analysis" && data.data) {
        useAgentStore.getState().addAnalysis(data.data);
```

---

## Task 10: Frontend — Hooks (useChartData + useAgentAnalysis)

**Files:**
- Create: `web/src/features/agent/hooks/useChartData.ts`
- Create: `web/src/features/agent/hooks/useAgentAnalysis.ts`

- [ ] **Step 1: Create useChartData hook (simplified rewrite)**

Create `web/src/features/agent/hooks/useChartData.ts`:

```typescript
import { useEffect, useRef, useState } from "react";
import { api, type CandleData } from "../../../shared/lib/api";

const OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/business";
const TF_MAP: Record<string, string> = {
  "15m": "candle15m",
  "1h": "candle1H",
  "4h": "candle4H",
  "1D": "candle1D",
};

export type TickCallback = (candle: CandleData) => void;

export function useChartData(pair: string, timeframe: string) {
  const [candles, setCandles] = useState<CandleData[]>([]);
  const [loading, setLoading] = useState(true);
  const onTickRef = useRef<TickCallback | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    async function loadInitial() {
      setLoading(true);
      try {
        const resp = await fetch(
          `https://www.okx.com/api/v5/market/candles?instId=${pair}&bar=${timeframe === "1D" ? "1D" : timeframe.toUpperCase()}&limit=200`
        );
        const json = await resp.json();
        if (!cancelled && json.data) {
          const parsed: CandleData[] = json.data
            .map((d: string[]) => ({
              timestamp: Math.floor(Number(d[0]) / 1000),
              open: Number(d[1]),
              high: Number(d[2]),
              low: Number(d[3]),
              close: Number(d[4]),
              volume: Number(d[5]),
            }))
            .reverse();
          setCandles(parsed);
        }
      } catch {
        try {
          const data = await api.getCandles(pair, timeframe);
          if (!cancelled) setCandles(data);
        } catch { /* both failed */ }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    function connectWs() {
      const channel = TF_MAP[timeframe];
      if (!channel) return;

      ws = new WebSocket(OKX_WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ op: "subscribe", args: [{ channel, instId: pair }] }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (!msg.data?.[0]) return;
          const raw = msg.data[0];
          const candle: CandleData = {
            timestamp: Math.floor(Number(raw[0]) / 1000),
            open: Number(raw[1]),
            high: Number(raw[2]),
            low: Number(raw[3]),
            close: Number(raw[4]),
            volume: Number(raw[5]),
          };

          // tick bypass: update chart directly without React render
          onTickRef.current?.(candle);

          // confirmed candle: update React state
          if (raw[8] === "1") {
            setCandles((prev) => {
              const last = prev[prev.length - 1];
              if (last && last.timestamp === candle.timestamp) {
                return [...prev.slice(0, -1), candle];
              }
              return [...prev, candle];
            });
          }
        } catch { /* ignore parse errors */ }
      };

      ws.onclose = () => {
        if (!cancelled) reconnectTimer = setTimeout(connectWs, 3000);
      };
      ws.onerror = () => ws.close();
    }

    loadInitial().then(connectWs);

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [pair, timeframe]);

  return { candles, loading, onTickRef };
}
```

- [ ] **Step 2: Create useAgentAnalysis hook**

Create `web/src/features/agent/hooks/useAgentAnalysis.ts`:

```typescript
import { useEffect } from "react";
import { api } from "../../../shared/lib/api";
import { useAgentStore } from "../store";

export function useAgentAnalysis() {
  const { analyses, loading, setAnalyses, setLoading, getSelected, getLatest } =
    useAgentStore();

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const data = await api.getAgentAnalyses({ limit: 10 });
        if (!cancelled) setAnalyses(data);
      } catch {
        // no analyses yet — expected on first run
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [setAnalyses, setLoading]);

  return { analyses, loading, selected: getSelected(), latest: getLatest() };
}
```

---

## Task 11: Frontend — Annotation Primitives

**Files:**
- Create: `web/src/features/agent/lib/primitives/types.ts`
- Create: `web/src/features/agent/lib/primitives/HorizontalPrimitive.ts`
- Create: `web/src/features/agent/lib/primitives/ZonePrimitive.ts`
- Create: `web/src/features/agent/lib/primitives/RegimeZonePrimitive.ts`
- Create: `web/src/features/agent/lib/primitives/TrendLinePrimitive.ts`
- Create: `web/src/features/agent/lib/primitives/PositionPrimitive.ts`

- [ ] **Step 1: Create shared primitive types**

Create `web/src/features/agent/lib/primitives/types.ts`:

```typescript
import type {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  PrimitiveHoveredItem,
  Time,
} from "lightweight-charts";

export type { ISeriesPrimitive, ISeriesPrimitivePaneView, ISeriesPrimitivePaneRenderer, PrimitiveHoveredItem, Time };

export interface CoordinateProvider {
  priceToCoordinate(price: number): number | null;
  timeToCoordinate(time: Time): number | null;
  width(): number;
  height(): number;
}

export interface PrimitiveState {
  externalId: string;
  opacity: number;
}
```

- [ ] **Step 2: Create HorizontalPrimitive**

Create `web/src/features/agent/lib/primitives/HorizontalPrimitive.ts`:

```typescript
import type {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  PrimitiveHoveredItem,
  Time,
  SeriesAttachedParameter,
} from "lightweight-charts";
import type { HorizontalLevel } from "../../types";

const HIT_MARGIN = 6;

interface HorizontalData {
  annotation: HorizontalLevel;
  externalId: string;
  opacity: number;
}

class HorizontalRenderer implements ISeriesPrimitivePaneRenderer {
  private _data: HorizontalData;
  private _y: number | null = null;

  constructor(data: HorizontalData) {
    this._data = data;
  }

  draw(target: any) {
    const ctx = target.context;
    const { annotation, opacity } = this._data;
    const series = target.bitmapSize ? null : null; // unused; y set externally
    const y = this._y;
    if (y === null) return;
    const w = target.mediaSize?.width ?? target.bitmapSize?.width ?? 800;

    ctx.save();
    ctx.globalAlpha = opacity;
    ctx.strokeStyle = annotation.color;
    ctx.lineWidth = 1;
    if (annotation.style === "dashed") ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();

    // label
    ctx.font = "11px sans-serif";
    ctx.fillStyle = annotation.color;
    ctx.fillText(annotation.label, 8, y - 4);
    ctx.restore();
  }

  setY(y: number | null) { this._y = y; }
}

class HorizontalView implements ISeriesPrimitivePaneView {
  private _renderer: HorizontalRenderer;
  constructor(data: HorizontalData) {
    this._renderer = new HorizontalRenderer(data);
  }
  renderer() { return this._renderer; }
  setY(y: number | null) { this._renderer.setY(y); }
}

export class HorizontalPrimitive implements ISeriesPrimitive<Time> {
  private _view: HorizontalView;
  private _data: HorizontalData;
  private _y: number | null = null;
  private _requestUpdate?: () => void;

  constructor(annotation: HorizontalLevel, externalId: string, opacity: number = 1) {
    this._data = { annotation, externalId, opacity };
    this._view = new HorizontalView(this._data);
  }

  attached(param: SeriesAttachedParameter<Time>) {
    this._requestUpdate = param.requestUpdate;
  }

  paneViews() { return [this._view]; }

  updateAllViews() {
    this._view.setY(this._y);
  }

  priceAxisViews() { return []; }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    if (this._y === null) return null;
    if (Math.abs(y - this._y) < HIT_MARGIN) {
      return { externalId: this._data.externalId, cursorStyle: "pointer", zOrder: "top" };
    }
    return null;
  }

  setCoordinate(y: number | null) {
    this._y = y;
    this._requestUpdate?.();
  }
}
```

- [ ] **Step 3: Create ZonePrimitive**

Create `web/src/features/agent/lib/primitives/ZonePrimitive.ts`:

```typescript
import type {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  PrimitiveHoveredItem,
  Time,
  SeriesAttachedParameter,
} from "lightweight-charts";
import type { Zone } from "../../types";

interface ZoneData {
  annotation: Zone;
  externalId: string;
  opacity: number;
}

class ZoneRenderer implements ISeriesPrimitivePaneRenderer {
  private _data: ZoneData;
  private _coords: { y1: number; y2: number; x1?: number; x2?: number } | null = null;

  constructor(data: ZoneData) { this._data = data; }

  draw(target: any) {
    if (!this._coords) return;
    const ctx = target.context;
    const { annotation, opacity } = this._data;
    const { y1, y2, x1, x2 } = this._coords;
    const w = target.mediaSize?.width ?? 800;

    ctx.save();
    ctx.globalAlpha = opacity * 0.15;
    const color = annotation.color;
    ctx.fillStyle = color;
    ctx.fillRect(x1 ?? 0, Math.min(y1, y2), (x2 ?? w) - (x1 ?? 0), Math.abs(y2 - y1));

    ctx.globalAlpha = opacity * 0.5;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 3]);
    ctx.strokeRect(x1 ?? 0, Math.min(y1, y2), (x2 ?? w) - (x1 ?? 0), Math.abs(y2 - y1));

    ctx.globalAlpha = opacity;
    ctx.font = "10px sans-serif";
    ctx.fillStyle = color;
    ctx.fillText(annotation.label, (x1 ?? 4) + 4, Math.min(y1, y2) - 3);
    ctx.restore();
  }

  setCoords(coords: typeof this._coords) { this._coords = coords; }
}

class ZoneView implements ISeriesPrimitivePaneView {
  private _renderer: ZoneRenderer;
  constructor(data: ZoneData) { this._renderer = new ZoneRenderer(data); }
  renderer() { return this._renderer; }
  setCoords(c: Parameters<ZoneRenderer["setCoords"]>[0]) { this._renderer.setCoords(c); }
}

export class ZonePrimitive implements ISeriesPrimitive<Time> {
  private _view: ZoneView;
  private _data: ZoneData;
  private _coords: { y1: number; y2: number; x1?: number; x2?: number } | null = null;
  private _requestUpdate?: () => void;

  constructor(annotation: Zone, externalId: string, opacity: number = 1) {
    this._data = { annotation, externalId, opacity };
    this._view = new ZoneView(this._data);
  }

  attached(param: SeriesAttachedParameter<Time>) { this._requestUpdate = param.requestUpdate; }
  paneViews() { return [this._view]; }
  updateAllViews() { this._view.setCoords(this._coords); }
  priceAxisViews() { return []; }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    if (!this._coords) return null;
    const { y1, y2, x1, x2 } = this._coords;
    const inY = y >= Math.min(y1, y2) && y <= Math.max(y1, y2);
    const inX = x >= (x1 ?? 0) && x <= (x2 ?? 9999);
    if (inY && inX) {
      return { externalId: this._data.externalId, cursorStyle: "pointer", zOrder: "top" };
    }
    return null;
  }

  setCoordinates(coords: typeof this._coords) {
    this._coords = coords;
    this._requestUpdate?.();
  }
}
```

- [ ] **Step 4: Create RegimeZonePrimitive**

Create `web/src/features/agent/lib/primitives/RegimeZonePrimitive.ts`:

```typescript
import type {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  PrimitiveHoveredItem,
  Time,
  SeriesAttachedParameter,
} from "lightweight-charts";
import type { RegimeZone } from "../../types";
import { theme } from "../../../../shared/theme";

const REGIME_COLORS: Record<string, string> = {
  trending: theme.annotations.regime_trending,
  ranging: theme.annotations.regime_ranging,
  volatile: theme.annotations.regime_volatile,
  steady: theme.annotations.regime_steady,
};

interface RegimeData {
  annotation: RegimeZone;
  externalId: string;
  opacity: number;
}

class RegimeRenderer implements ISeriesPrimitivePaneRenderer {
  private _data: RegimeData;
  private _coords: { x1: number; x2: number } | null = null;

  constructor(data: RegimeData) { this._data = data; }

  draw(target: any) {
    if (!this._coords) return;
    const ctx = target.context;
    const { annotation, opacity } = this._data;
    const h = target.mediaSize?.height ?? 600;
    const { x1, x2 } = this._coords;
    const color = REGIME_COLORS[annotation.regime] ?? "#8E9AAD";

    ctx.save();
    ctx.globalAlpha = opacity * 0.08;
    ctx.fillStyle = color;
    ctx.fillRect(x1, 0, x2 - x1, h);

    ctx.globalAlpha = opacity * 0.6;
    ctx.font = "9px sans-serif";
    ctx.fillStyle = color;
    ctx.fillText(
      `${annotation.regime} (${Math.round(annotation.confidence * 100)}%)`,
      x1 + 4, 14
    );
    ctx.restore();
  }

  setCoords(c: typeof this._coords) { this._coords = c; }
}

class RegimeView implements ISeriesPrimitivePaneView {
  private _renderer: RegimeRenderer;
  constructor(data: RegimeData) { this._renderer = new RegimeRenderer(data); }
  renderer() { return this._renderer; }
  setCoords(c: Parameters<RegimeRenderer["setCoords"]>[0]) { this._renderer.setCoords(c); }
}

export class RegimeZonePrimitive implements ISeriesPrimitive<Time> {
  private _view: RegimeView;
  private _data: RegimeData;
  private _coords: { x1: number; x2: number } | null = null;
  private _requestUpdate?: () => void;

  constructor(annotation: RegimeZone, externalId: string, opacity: number = 1) {
    this._data = { annotation, externalId, opacity };
    this._view = new RegimeView(this._data);
  }

  attached(param: SeriesAttachedParameter<Time>) { this._requestUpdate = param.requestUpdate; }
  paneViews() { return [this._view]; }
  updateAllViews() { this._view.setCoords(this._coords); }
  priceAxisViews() { return []; }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    if (!this._coords) return null;
    if (x >= this._coords.x1 && x <= this._coords.x2 && y < 24) {
      return { externalId: this._data.externalId, cursorStyle: "pointer", zOrder: "normal" };
    }
    return null;
  }

  setCoordinates(x1: number, x2: number) {
    this._coords = { x1, x2 };
    this._requestUpdate?.();
  }
}
```

- [ ] **Step 5: Create TrendLinePrimitive**

Create `web/src/features/agent/lib/primitives/TrendLinePrimitive.ts`:

```typescript
import type {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  PrimitiveHoveredItem,
  Time,
  SeriesAttachedParameter,
} from "lightweight-charts";
import type { TrendLine } from "../../types";

const HIT_MARGIN = 8;

interface TrendData {
  annotation: TrendLine;
  externalId: string;
  opacity: number;
}

function distToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

class TrendRenderer implements ISeriesPrimitivePaneRenderer {
  private _data: TrendData;
  private _coords: { x1: number; y1: number; x2: number; y2: number } | null = null;

  constructor(data: TrendData) { this._data = data; }

  draw(target: any) {
    if (!this._coords) return;
    const ctx = target.context;
    const { annotation, opacity } = this._data;
    const { x1, y1, x2, y2 } = this._coords;

    ctx.save();
    ctx.globalAlpha = opacity;
    ctx.strokeStyle = annotation.color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();

    ctx.font = "10px sans-serif";
    ctx.fillStyle = annotation.color;
    ctx.fillText(annotation.label, x2 + 4, y2 - 4);
    ctx.restore();
  }

  setCoords(c: typeof this._coords) { this._coords = c; }
}

class TrendView implements ISeriesPrimitivePaneView {
  private _renderer: TrendRenderer;
  constructor(data: TrendData) { this._renderer = new TrendRenderer(data); }
  renderer() { return this._renderer; }
  setCoords(c: Parameters<TrendRenderer["setCoords"]>[0]) { this._renderer.setCoords(c); }
}

export class TrendLinePrimitive implements ISeriesPrimitive<Time> {
  private _view: TrendView;
  private _data: TrendData;
  private _coords: { x1: number; y1: number; x2: number; y2: number } | null = null;
  private _requestUpdate?: () => void;

  constructor(annotation: TrendLine, externalId: string, opacity: number = 1) {
    this._data = { annotation, externalId, opacity };
    this._view = new TrendView(this._data);
  }

  attached(param: SeriesAttachedParameter<Time>) { this._requestUpdate = param.requestUpdate; }
  paneViews() { return [this._view]; }
  updateAllViews() { this._view.setCoords(this._coords); }
  priceAxisViews() { return []; }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    if (!this._coords) return null;
    const d = distToSegment(x, y, this._coords.x1, this._coords.y1, this._coords.x2, this._coords.y2);
    if (d < HIT_MARGIN) {
      return { externalId: this._data.externalId, cursorStyle: "pointer", zOrder: "top" };
    }
    return null;
  }

  setCoordinates(coords: typeof this._coords) {
    this._coords = coords;
    this._requestUpdate?.();
  }
}
```

- [ ] **Step 6: Create PositionPrimitive**

Create `web/src/features/agent/lib/primitives/PositionPrimitive.ts`:

```typescript
import type {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  PrimitiveHoveredItem,
  Time,
  SeriesAttachedParameter,
} from "lightweight-charts";
import type { PositionMarker } from "../../types";
import { theme } from "../../../../shared/theme";

const HIT_MARGIN = 6;

interface PositionData {
  annotation: PositionMarker;
  externalId: string;
  opacity: number;
}

class PositionRenderer implements ISeriesPrimitivePaneRenderer {
  private _data: PositionData;
  private _ys: { entry: number | null; sl: number | null; tp: number | null } = { entry: null, sl: null, tp: null };

  constructor(data: PositionData) { this._data = data; }

  draw(target: any) {
    const ctx = target.context;
    const { annotation, opacity } = this._data;
    const w = target.mediaSize?.width ?? 800;
    const isLong = annotation.direction === "long";
    const entryColor = isLong ? theme.annotations.position_long : theme.annotations.position_short;

    ctx.save();
    ctx.globalAlpha = opacity;

    // entry line (solid)
    if (this._ys.entry !== null) {
      ctx.strokeStyle = entryColor;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(0, this._ys.entry);
      ctx.lineTo(w, this._ys.entry);
      ctx.stroke();
      ctx.font = "11px sans-serif";
      ctx.fillStyle = entryColor;
      ctx.fillText(`Entry ${isLong ? "LONG" : "SHORT"}`, 8, this._ys.entry - 4);
    }

    // SL line (dashed red)
    if (this._ys.sl !== null) {
      ctx.strokeStyle = theme.annotations.sl;
      ctx.lineWidth = 1;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(0, this._ys.sl);
      ctx.lineTo(w, this._ys.sl);
      ctx.stroke();
      ctx.font = "10px sans-serif";
      ctx.fillStyle = theme.annotations.sl;
      ctx.fillText("SL", 8, this._ys.sl - 3);
    }

    // TP line (dashed green)
    if (this._ys.tp !== null) {
      ctx.strokeStyle = theme.annotations.tp;
      ctx.lineWidth = 1;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(0, this._ys.tp);
      ctx.lineTo(w, this._ys.tp);
      ctx.stroke();
      ctx.font = "10px sans-serif";
      ctx.fillStyle = theme.annotations.tp;
      ctx.fillText("TP", 8, this._ys.tp - 3);
    }

    ctx.restore();
  }

  setYs(ys: typeof this._ys) { this._ys = ys; }
}

class PositionView implements ISeriesPrimitivePaneView {
  private _renderer: PositionRenderer;
  constructor(data: PositionData) { this._renderer = new PositionRenderer(data); }
  renderer() { return this._renderer; }
  setYs(ys: Parameters<PositionRenderer["setYs"]>[0]) { this._renderer.setYs(ys); }
}

export class PositionPrimitive implements ISeriesPrimitive<Time> {
  private _view: PositionView;
  private _data: PositionData;
  private _ys: { entry: number | null; sl: number | null; tp: number | null } = { entry: null, sl: null, tp: null };
  private _requestUpdate?: () => void;

  constructor(annotation: PositionMarker, externalId: string, opacity: number = 1) {
    this._data = { annotation, externalId, opacity };
    this._view = new PositionView(this._data);
  }

  attached(param: SeriesAttachedParameter<Time>) { this._requestUpdate = param.requestUpdate; }
  paneViews() { return [this._view]; }
  updateAllViews() { this._view.setYs(this._ys); }
  priceAxisViews() { return []; }

  hitTest(_x: number, y: number): PrimitiveHoveredItem | null {
    for (const val of [this._ys.entry, this._ys.sl, this._ys.tp]) {
      if (val !== null && Math.abs(y - val) < HIT_MARGIN) {
        return { externalId: this._data.externalId, cursorStyle: "pointer", zOrder: "top" };
      }
    }
    return null;
  }

  setCoordinates(ys: typeof this._ys) {
    this._ys = ys;
    this._requestUpdate?.();
  }
}
```

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd web && npx tsc --noEmit --pretty 2>&1 | head -30
```

Expected: No errors in the primitives files.

---

## Task 12: Frontend — AgentChart + AnnotationPopover

**Files:**
- Create: `web/src/features/agent/components/AnnotationPopover.tsx`
- Create: `web/src/features/agent/components/AgentChart.tsx`

- [ ] **Step 1: Create AnnotationPopover**

Create `web/src/features/agent/components/AnnotationPopover.tsx`:

```tsx
import { useEffect, useRef } from "react";
import type { Annotation } from "../types";

interface Props {
  annotation: Annotation;
  x: number;
  y: number;
  onClose: () => void;
}

const TYPE_LABELS: Record<string, string> = {
  level: "Level",
  zone: "Zone",
  signal: "Signal",
  regime: "Regime",
  trendline: "Trend",
  position: "Position",
};

export function AnnotationPopover({ annotation, x, y, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  const label = "label" in annotation ? annotation.label : TYPE_LABELS[annotation.type];

  return (
    <div
      ref={ref}
      className="absolute z-50 w-72 rounded-lg border border-white/10 bg-surface/95 p-3 shadow-xl backdrop-blur-sm"
      style={{ left: Math.min(x, window.innerWidth - 320), top: y + 12 }}
    >
      <div className="mb-1 flex items-center gap-2">
        <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] uppercase text-white/50">
          {TYPE_LABELS[annotation.type]}
        </span>
        <span className="text-sm font-medium text-white/90">{label}</span>
      </div>
      <p className="text-xs leading-relaxed text-white/70">{annotation.reasoning}</p>
    </div>
  );
}
```

- [ ] **Step 2: Create AgentChart**

Create `web/src/features/agent/components/AgentChart.tsx`:

```tsx
import { useEffect, useRef, useCallback, useState, Component, type ReactNode } from "react";
import {
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type Time,
  CrosshairMode,
} from "lightweight-charts";
import type { CandleData } from "../../../shared/lib/api";
import type { Annotation, AgentAnalysis } from "../types";
import { getStaleness, getAnnotationOpacity } from "../types";
import { theme } from "../../../shared/theme";
import { AnnotationPopover } from "./AnnotationPopover";
import { HorizontalPrimitive } from "../lib/primitives/HorizontalPrimitive";
import { ZonePrimitive } from "../lib/primitives/ZonePrimitive";
import { RegimeZonePrimitive } from "../lib/primitives/RegimeZonePrimitive";
import { TrendLinePrimitive } from "../lib/primitives/TrendLinePrimitive";
import { PositionPrimitive } from "../lib/primitives/PositionPrimitive";
import type { TickCallback } from "../hooks/useChartData";

class ChartErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError() { return { hasError: true }; }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full items-center justify-center text-xs text-white/40">
          Failed to render annotations. Chart data is still available.
        </div>
      );
    }
    return this.props.children;
  }
}

interface Props {
  candles: CandleData[];
  pair: string;
  analysis: AgentAnalysis | undefined;
  onTickRef: React.MutableRefObject<TickCallback | null>;
}

export function AgentChart({ candles, pair, analysis, onTickRef }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const primitivesRef = useRef<{ prim: any; ann: Annotation }[]>([]);
  const annotationMapRef = useRef<Map<string, Annotation>>(new Map());
  const [popover, setPopover] = useState<{ annotation: Annotation; x: number; y: number } | null>(null);

  // create chart
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { color: theme.colors.surface }, textColor: "#8E9AAD" },
      grid: {
        vertLines: { color: "rgba(28, 36, 48, 0.3)" },
        horzLines: { color: "rgba(28, 36, 48, 0.3)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: "rgba(28, 36, 48, 0.3)" },
    });
    chartRef.current = chart;

    const candleSeries = chart.addCandlestickSeries({
      upColor: theme.colors.long,
      downColor: theme.colors.short,
      borderUpColor: theme.colors.long,
      borderDownColor: theme.colors.short,
      wickUpColor: theme.colors.long,
      wickDownColor: theme.colors.short,
    });
    seriesRef.current = candleSeries;

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volumeRef.current = volumeSeries;

    // click handler for annotations
    chart.subscribeClick((param) => {
      const id = param.hoveredObjectId as string;
      if (id && annotationMapRef.current.has(id)) {
        const ann = annotationMapRef.current.get(id)!;
        setPopover({
          annotation: ann,
          x: param.point?.x ?? 200,
          y: param.point?.y ?? 200,
        });
      } else {
        setPopover(null);
      }
    });

    const observer = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  // tick handler
  useEffect(() => {
    if (!seriesRef.current || !volumeRef.current) return;
    const series = seriesRef.current;
    const volume = volumeRef.current;

    onTickRef.current = (candle: CandleData) => {
      const bar: CandlestickData<Time> = {
        time: candle.timestamp as Time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      };
      series.update(bar);
      volume.update({
        time: candle.timestamp as Time,
        value: candle.volume,
        color: candle.close >= candle.open
          ? "rgba(14, 203, 129, 0.3)"
          : "rgba(246, 70, 93, 0.3)",
      });
    };

    return () => { onTickRef.current = null; };
  }, [onTickRef]);

  // set candle data
  useEffect(() => {
    if (!seriesRef.current || !volumeRef.current || !candles.length) return;
    const bars: CandlestickData<Time>[] = candles.map((c) => ({
      time: c.timestamp as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    seriesRef.current.setData(bars);
    volumeRef.current.setData(
      candles.map((c) => ({
        time: c.timestamp as Time,
        value: c.volume,
        color: c.close >= c.open
          ? "rgba(14, 203, 129, 0.3)"
          : "rgba(246, 70, 93, 0.3)",
      }))
    );
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  // helper: recompute pixel coordinates for all attached primitives
  const recomputeCoordinates = useCallback(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;

    for (const { prim, ann } of primitivesRef.current) {
      try {
        if (ann.type === "level") {
          prim.setCoordinate(series.priceToCoordinate(ann.price));
        } else if (ann.type === "zone") {
          const ts = chart.timeScale();
          prim.setCoordinates({
            y1: series.priceToCoordinate(ann.from_price) ?? 0,
            y2: series.priceToCoordinate(ann.to_price) ?? 0,
            x1: ann.from_time ? ts.timeToCoordinate(ann.from_time as Time) ?? undefined : undefined,
            x2: ann.to_time ? ts.timeToCoordinate(ann.to_time as Time) ?? undefined : undefined,
          });
        } else if (ann.type === "regime") {
          const ts = chart.timeScale();
          const x1 = ts.timeToCoordinate(ann.from_time as Time);
          const x2 = ts.timeToCoordinate(ann.to_time as Time);
          if (x1 !== null && x2 !== null) prim.setCoordinates(x1, x2);
        } else if (ann.type === "trendline") {
          const ts = chart.timeScale();
          const x1 = ts.timeToCoordinate(ann.from.time as Time);
          const y1 = series.priceToCoordinate(ann.from.price);
          const x2 = ts.timeToCoordinate(ann.to.time as Time);
          const y2 = series.priceToCoordinate(ann.to.price);
          if (x1 !== null && y1 !== null && x2 !== null && y2 !== null) {
            prim.setCoordinates({ x1, y1, x2, y2 });
          }
        } else if (ann.type === "position") {
          prim.setCoordinates({
            entry: series.priceToCoordinate(ann.entry_price),
            sl: ann.sl_price ? series.priceToCoordinate(ann.sl_price) : null,
            tp: ann.tp_price ? series.priceToCoordinate(ann.tp_price) : null,
          });
        }
      } catch {
        // malformed annotation — skip, don't crash
      }
    }
  }, []);

  // render annotations
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;

    // clear old primitives
    for (const { prim } of primitivesRef.current) {
      series.detachPrimitive(prim);
    }
    primitivesRef.current = [];
    annotationMapRef.current.clear();
    setPopover(null);

    if (!analysis) return;

    const staleness = getStaleness(analysis.created_at);
    const opacity = getAnnotationOpacity(staleness);
    const filtered = analysis.annotations.filter((a) => a.pair === pair);

    const markers: any[] = [];

    for (let i = 0; i < filtered.length; i++) {
      const ann = filtered[i];
      const extId = `ann-${analysis.id}-${i}`;
      annotationMapRef.current.set(extId, ann);

      try {
        if (ann.type === "level") {
          const prim = new HorizontalPrimitive(ann, extId, opacity);
          series.attachPrimitive(prim);
          primitivesRef.current.push({ prim, ann });
        } else if (ann.type === "zone") {
          const prim = new ZonePrimitive(ann, extId, opacity);
          series.attachPrimitive(prim);
          primitivesRef.current.push({ prim, ann });
        } else if (ann.type === "signal") {
          markers.push({
            time: ann.time as Time,
            position: ann.direction === "long" ? "belowBar" : "aboveBar",
            color: ann.direction === "long" ? theme.annotations.signal_long : theme.annotations.signal_short,
            shape: ann.direction === "long" ? "arrowUp" : "arrowDown",
            text: ann.label,
            id: extId,
          });
        } else if (ann.type === "regime") {
          const prim = new RegimeZonePrimitive(ann, extId, opacity);
          series.attachPrimitive(prim);
          primitivesRef.current.push({ prim, ann });
        } else if (ann.type === "trendline") {
          const prim = new TrendLinePrimitive(ann, extId, opacity);
          series.attachPrimitive(prim);
          primitivesRef.current.push({ prim, ann });
        } else if (ann.type === "position") {
          const prim = new PositionPrimitive(ann, extId, opacity);
          series.attachPrimitive(prim);
          primitivesRef.current.push({ prim, ann });
        }
      } catch {
        // malformed annotation from LLM — skip it, don't crash the chart
      }
    }

    if (markers.length) {
      createSeriesMarkers(series, markers);
    }

    // compute initial coordinates
    recomputeCoordinates();

    // recompute when the user scrolls or zooms the chart
    const unsubscribe = chart.timeScale().subscribeVisibleLogicalRangeChange(recomputeCoordinates);
    return () => unsubscribe();
  }, [analysis, pair, recomputeCoordinates]);

  return (
    <ChartErrorBoundary>
      <div className="relative h-full w-full">
        <div ref={containerRef} className="h-full w-full" />
        {popover && (
          <AnnotationPopover
            annotation={popover.annotation}
            x={popover.x}
            y={popover.y}
            onClose={() => setPopover(null)}
          />
        )}
      </div>
    </ChartErrorBoundary>
  );
}
```

---

## Task 13: Frontend — NarrativePanel

**Files:**
- Create: `web/src/features/agent/components/NarrativePanel.tsx`

- [ ] **Step 1: Create NarrativePanel**

Create `web/src/features/agent/components/NarrativePanel.tsx`:

```tsx
import { useAgentStore } from "../store";
import type { AgentAnalysis } from "../types";
import { getStaleness, type StalenessLevel } from "../types";

const TYPE_LABELS: Record<string, string> = {
  brief: "Market Brief",
  pair_dive: "Pair Dive",
  signal_explain: "Signal Explain",
  position_check: "Position Check",
};

function relativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function stalenessColor(s: StalenessLevel): string {
  if (s === "fresh") return "text-white/50";
  if (s === "aging") return "text-yellow-400/80";
  return "text-red-400/70";
}

function ScoreBreakdown({ metadata }: { metadata: Record<string, unknown> }) {
  const scores = metadata as Record<string, number | Record<string, number>>;
  if (!scores || typeof scores !== "object") return null;

  const entries = Object.entries(scores).filter(
    ([, v]) => typeof v === "number"
  ) as [string, number][];
  if (!entries.length) return null;

  return (
    <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
      {entries.slice(0, 8).map(([key, val]) => (
        <div key={key} className="flex justify-between">
          <span className="text-white/40">{key.replace(/_/g, " ")}</span>
          <span className="text-white/70">{typeof val === "number" ? val : String(val)}</span>
        </div>
      ))}
    </div>
  );
}

function AnalysisCard({ analysis, isSelected, onSelect }: {
  analysis: AgentAnalysis;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const staleness = getStaleness(analysis.created_at);
  const isExpanded = isSelected;

  return (
    <button
      onClick={onSelect}
      className={`w-full rounded-lg border p-3 text-left transition-colors ${
        isSelected
          ? "border-accent/30 bg-white/5"
          : "border-white/5 bg-white/[0.02] hover:bg-white/[0.04]"
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] uppercase text-white/50">
            {TYPE_LABELS[analysis.type] ?? analysis.type}
          </span>
          {analysis.pair && (
            <span className="text-[10px] text-white/40">{analysis.pair}</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {staleness === "stale" && (
            <span className="text-[9px] text-red-400/60">(stale)</span>
          )}
          <span className={`text-[10px] ${stalenessColor(staleness)}`}>
            {relativeTime(analysis.created_at)}
          </span>
        </div>
      </div>

      {isExpanded && (
        <div className="mt-2">
          <p className="text-xs leading-relaxed text-white/70">{analysis.narrative}</p>
          <ScoreBreakdown metadata={analysis.metadata} />
        </div>
      )}
    </button>
  );
}

interface Props {
  onRefresh: () => void;
}

export function NarrativePanel({ onRefresh }: Props) {
  const { analyses, selectedId, selectAnalysis, loading, getSelected } = useAgentStore();
  const selected = getSelected();

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-accent" />
      </div>
    );
  }

  if (!analyses.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="text-sm text-white/50">No analyses yet</p>
        <p className="text-xs text-white/30">
          Run <code className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-white/50">/market-brief</code> from Claude Code CLI to generate your first analysis.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* header */}
      <div className="flex items-center justify-between border-b border-white/5 px-4 py-2">
        <span className="text-xs text-white/40">Analyses</span>
        <button
          onClick={onRefresh}
          className="rounded px-2 py-0.5 text-[10px] text-white/40 hover:bg-white/5 hover:text-white/60"
        >
          Refresh
        </button>
      </div>

      {/* analysis list */}
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {analyses.map((a) => (
          <AnalysisCard
            key={a.id}
            analysis={a}
            isSelected={selected?.id === a.id}
            onSelect={() => selectAnalysis(a.id)}
          />
        ))}
      </div>

      {/* footer */}
      {selected && (
        <div className="border-t border-white/5 px-4 py-2">
          <span className="text-[10px] text-white/30">
            Updated {relativeTime(selected.created_at)}
          </span>
        </div>
      )}
    </div>
  );
}
```

---

## Task 14: Frontend — AgentView + Tab Integration

**Files:**
- Create: `web/src/features/agent/components/AgentView.tsx`
- Modify: `web/src/App.tsx`
- Delete: `web/src/features/chart/` (entire directory)

- [ ] **Step 1: Create AgentView**

Create `web/src/features/agent/components/AgentView.tsx`:

```tsx
import { lazy, Suspense, useState, useCallback, useEffect } from "react";
import { useLivePrice } from "../../../shared/hooks/useLivePrice";
import { useChartData } from "../hooks/useChartData";
import { useAgentAnalysis } from "../hooks/useAgentAnalysis";
import { useAgentStore } from "../store";
import { NarrativePanel } from "./NarrativePanel";
import { api } from "../../../shared/lib/api";
import { formatPricePrecision } from "../../../shared/lib/format";

const AgentChart = lazy(() =>
  import("./AgentChart").then((m) => ({ default: m.AgentChart }))
);

const TIMEFRAMES = ["15m", "1h", "4h", "1D"] as const;

interface Props {
  pair: string;
}

function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(window.innerWidth >= 1024);
  useEffect(() => {
    const handler = () => setIsDesktop(window.innerWidth >= 1024);
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, []);
  return isDesktop;
}

export function AgentView({ pair }: Props) {
  const [timeframe, setTimeframe] = useState("1h");
  const { candles, loading: candlesLoading, onTickRef } = useChartData(pair, timeframe);
  const { selected } = useAgentAnalysis();
  const { price, change24h } = useLivePrice(pair);
  const isDesktop = useIsDesktop();
  const setAnalyses = useAgentStore((s) => s.setAnalyses);
  const setLoading = useAgentStore((s) => s.setLoading);

  const handleRefresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getAgentAnalyses({ limit: 10 });
      setAnalyses(data);
    } catch { /* ignore */ }
    setLoading(false);
  }, [setAnalyses, setLoading]);

  return (
    <div className="flex h-full flex-col bg-surface">
      {/* header */}
      <div className="flex items-center gap-3 border-b border-white/5 px-4 py-2">
        <span className="text-sm font-medium text-white/90">{pair.replace("-SWAP", "")}</span>
        {price !== null && (
          <span className="text-sm text-white/70">
            {formatPricePrecision(price, pair)}
          </span>
        )}
        {change24h !== null && (
          <span className={`text-xs ${change24h >= 0 ? "text-long" : "text-short"}`}>
            {change24h >= 0 ? "+" : ""}{change24h.toFixed(2)}%
          </span>
        )}
        <div className="ml-auto flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`rounded px-2 py-0.5 text-xs transition-colors ${
                timeframe === tf
                  ? "bg-accent/20 text-accent"
                  : "text-white/40 hover:text-white/60"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* main content */}
      {isDesktop ? (
        <div className="flex flex-1 overflow-hidden">
          {/* chart — 70% */}
          <div className="relative w-[70%] border-r border-white/5">
            {candlesLoading && (
              <div className="absolute right-3 top-3 z-10 flex items-center gap-1.5 rounded bg-surface/90 px-2 py-1">
                <div className="h-3 w-3 animate-spin rounded-full border border-white/20 border-t-accent" />
                <span className="text-[10px] text-white/40">Loading</span>
              </div>
            )}
            <Suspense fallback={
              <div className="flex h-full items-center justify-center">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-accent" />
              </div>
            }>
              <AgentChart
                candles={candles}
                pair={pair}
                analysis={selected}
                onTickRef={onTickRef}
              />
            </Suspense>
          </div>

          {/* narrative panel — 30% */}
          <div className="w-[30%]">
            <NarrativePanel onRefresh={handleRefresh} />
          </div>
        </div>
      ) : (
        /* mobile: narrative only */
        <div className="flex-1 overflow-hidden">
          <NarrativePanel onRefresh={handleRefresh} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Update App.tsx**

In `web/src/App.tsx`, replace the chart import and usage:

Change:
```typescript
import { ChartView } from "./features/chart/components/ChartView";
```
to:
```typescript
import { AgentView } from "./features/agent/components/AgentView";
```

Change:
```typescript
chart={<ChartView pair={selectedPair} />}
```
to:
```typescript
agent={<AgentView pair={selectedPair} />}
```

- [ ] **Step 3: Verify build**

```bash
cd web && pnpm build
```

Expected: Build succeeds with no errors.

- [ ] **Step 4: Run frontend tests**

```bash
cd web && pnpm exec vitest run
```

Expected: All existing tests pass (chart tests were deleted with the feature).

- [ ] **Step 5: Delete the legacy chart feature directory**

After `App.tsx` and any shared imports no longer reference the old chart implementation:

```bash
rm -rf web/src/features/chart
```

---

## Task 15: Frontend — Agent Store + Types Tests

**Files:**
- Create: `web/src/features/agent/__tests__/store.test.ts`
- Create: `web/src/features/agent/__tests__/types.test.ts`

- [ ] **Step 1: Create store tests**

Create `web/src/features/agent/__tests__/store.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useAgentStore } from "../store";
import type { AgentAnalysis } from "../types";

function createAnalysis(overrides: Partial<AgentAnalysis> = {}): AgentAnalysis {
  return {
    id: 1,
    type: "brief",
    pair: null,
    narrative: "Test narrative",
    annotations: [],
    metadata: {},
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("useAgentStore", () => {
  beforeEach(() => {
    useAgentStore.setState({ analyses: [], selectedId: null, loading: false });
  });

  it("adds analysis to front of list", () => {
    const a1 = createAnalysis({ id: 1 });
    const a2 = createAnalysis({ id: 2 });
    useAgentStore.getState().addAnalysis(a1);
    useAgentStore.getState().addAnalysis(a2);
    expect(useAgentStore.getState().analyses[0].id).toBe(2);
  });

  it("caps analyses at 50", () => {
    for (let i = 0; i < 55; i++) {
      useAgentStore.getState().addAnalysis(createAnalysis({ id: i }));
    }
    expect(useAgentStore.getState().analyses.length).toBeLessThanOrEqual(50);
  });

  it("selects analysis by id", () => {
    const a1 = createAnalysis({ id: 1 });
    const a2 = createAnalysis({ id: 2 });
    useAgentStore.getState().setAnalyses([a1, a2]);
    useAgentStore.getState().selectAnalysis(2);
    expect(useAgentStore.getState().getSelected()?.id).toBe(2);
  });

  it("returns first analysis when no selection", () => {
    const a1 = createAnalysis({ id: 1 });
    useAgentStore.getState().setAnalyses([a1]);
    expect(useAgentStore.getState().getSelected()?.id).toBe(1);
  });

  it("auto-selects new analysis on add", () => {
    const a1 = createAnalysis({ id: 1 });
    useAgentStore.getState().addAnalysis(a1);
    expect(useAgentStore.getState().selectedId).toBe(1);
  });
});
```

- [ ] **Step 2: Create types utility tests**

Create `web/src/features/agent/__tests__/types.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { getStaleness, getAnnotationOpacity } from "../types";

describe("getStaleness", () => {
  it("returns fresh for recent analyses", () => {
    expect(getStaleness(new Date().toISOString())).toBe("fresh");
  });

  it("returns aging for 4-24h old analyses", () => {
    const sixHoursAgo = new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString();
    expect(getStaleness(sixHoursAgo)).toBe("aging");
  });

  it("returns stale for >24h analyses", () => {
    const twoDaysAgo = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
    expect(getStaleness(twoDaysAgo)).toBe("stale");
  });
});

describe("getAnnotationOpacity", () => {
  it("returns 1 for fresh", () => expect(getAnnotationOpacity("fresh")).toBe(1));
  it("returns 0.6 for aging", () => expect(getAnnotationOpacity("aging")).toBe(0.6));
  it("returns 0.3 for stale", () => expect(getAnnotationOpacity("stale")).toBe(0.3));
});
```

- [ ] **Step 3: Run tests**

```bash
cd web && pnpm exec vitest run
```

Expected: New tests pass alongside existing tests.

---

## Task 16: Verification — JSONB Key Validation

Before proceeding with MCP tools that read `PipelineEvaluation.indicators` JSONB, verify the actual key names stored in the database match what the tools extract.

- [ ] **Step 1: Check indicator JSONB keys**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "
import asyncio
from sqlalchemy import select, text
from app.db.database import Database

async def check():
    db = Database('postgresql+asyncpg://krypton:krypton@postgres:5432/krypton')
    await db.connect()
    async with db.session_factory() as session:
        row = await session.execute(text(
            'SELECT indicators FROM pipeline_evaluations ORDER BY evaluated_at DESC LIMIT 1'
        ))
        result = row.scalar_one_or_none()
        if result:
            print('Indicator keys:', sorted(result.keys()))
        else:
            print('No pipeline evaluations yet — verify after first pipeline run')

asyncio.run(check())
"
```

If keys differ from what `get_regime` or `get_indicators` extract (e.g., `bb_width` vs `bb_width_pct`), update the MCP tool to use the correct keys.

---

## Verification Checklist

After all tasks complete:

- [ ] Backend: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest` — all tests pass
- [ ] Backend: POST `/api/agent/analysis` with valid agent key stores and broadcasts
- [ ] Backend: GET `/api/agent/analysis` returns stored analyses
- [ ] MCP: `claude -p "Use get_regime tool for BTC-USDT-SWAP"` returns data
- [ ] MCP: All 10 tools visible in Claude Code (`/mcp` command)
- [ ] Skills: `/market-brief` runs end-to-end, analysis appears in frontend
- [ ] Frontend: `pnpm build` succeeds
- [ ] Frontend: `pnpm exec vitest run` passes (including new store/types tests)
- [ ] Frontend: Agent tab shows on desktop with chart + narrative panel
- [ ] Frontend: Agent tab shows on mobile with narrative only
- [ ] Frontend: Clicking annotations shows popover with reasoning
- [ ] Frontend: Scrolling/zooming chart keeps annotations aligned with price levels
- [ ] Frontend: Stale analyses render with reduced opacity
- [ ] Frontend: Empty state shows "No analyses yet" message
- [ ] JSONB keys validated (Task 16)
