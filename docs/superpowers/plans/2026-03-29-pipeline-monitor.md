# Pipeline Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every pipeline evaluation (emitted and rejected) to a new DB table, expose via REST API, and build a frontend page to browse them with summary stats.

**Architecture:** New `PipelineEvaluation` model stores one row per `run_pipeline` invocation. Two API endpoints serve list+filter and summary stats. A React feature module under `features/monitor/` renders the data in the More menu. A daily background task prunes rows older than 7 days.

**Tech Stack:** SQLAlchemy 2.0 async (model + queries), Alembic (migration), FastAPI (endpoints), React + TypeScript + Tailwind (frontend), Zustand-free (hook-only state)

**Spec:** `docs/superpowers/specs/2026-03-29-pipeline-monitor-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/app/api/monitor.py` | REST endpoints for evaluations list + summary |
| Create | `backend/tests/api/test_monitor.py` | API endpoint tests |
| Create | `web/src/features/monitor/types.ts` | TypeScript types |
| Create | `web/src/features/monitor/hooks/useMonitorData.ts` | Data fetching hook |
| Create | `web/src/features/monitor/components/MonitorPage.tsx` | Main page (filter bar + wiring) |
| Create | `web/src/features/monitor/components/SummaryCards.tsx` | Top summary metric cards |
| Create | `web/src/features/monitor/components/PairBreakdown.tsx` | Per-pair emission rate cards |
| Create | `web/src/features/monitor/components/EvaluationTable.tsx` | Filterable evaluation list with expandable rows |
| Create | `web/src/features/monitor/components/EvaluationDetail.tsx` | Expanded row detail view |
| Modify | `backend/app/db/models.py` | Add `PipelineEvaluation` model |
| Modify | `backend/app/main.py:1000-1032` | Insert eval row after threshold check |
| Modify | `backend/app/main.py:1134-1136` | Insert eval row for emitted signals with signal_id |
| Modify | `backend/app/main.py:1679-1720` | Add pruning background loop |
| Modify | `backend/app/main.py:1732-1748` | Cancel pruning task on shutdown |
| Modify | `backend/app/main.py:1784-1822` | Register monitor router |
| Modify | `web/src/shared/lib/api.ts` | Add `getMonitorEvaluations` + `getMonitorSummary` |
| Modify | `web/src/features/more/components/MorePage.tsx` | Add "monitor" to SubPage + CLUSTERS + render |

---

### Task 1: PipelineEvaluation DB Model

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add PipelineEvaluation model**

Add the model after the `Signal` class (after its `__table_args__`). No new imports needed — `Integer` is already imported:

```python
class PipelineEvaluation(Base):
    __tablename__ = "pipeline_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    emitted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    signal_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("signals.id", ondelete="SET NULL"), nullable=True
    )
    final_score: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    tech_score: Mapped[int] = mapped_column(Integer, nullable=False)
    flow_score: Mapped[int] = mapped_column(Integer, nullable=False)
    onchain_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pattern_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    liquidation_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confluence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indicator_preliminary: Mapped[int] = mapped_column(Integer, nullable=False)
    blended_score: Mapped[int] = mapped_column(Integer, nullable=False)
    ml_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ml_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_contribution: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ml_agreement: Mapped[str] = mapped_column(String(16), nullable=False)
    indicators: Mapped[dict] = mapped_column(JSONB, nullable=False)
    regime: Mapped[dict] = mapped_column(JSONB, nullable=False)
    availabilities: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_pipeline_eval_pair_time", "pair", "evaluated_at"),
        Index("ix_pipeline_eval_time", "evaluated_at"),
    )
```

- [ ] **Step 2: Add PipelineEvaluation to the main.py import**

In `backend/app/main.py` line 31, add `PipelineEvaluation` to the models import:

```python
from app.db.models import Candle, MLTrainingRun, NewsEvent, OrderFlowSnapshot, PipelineEvaluation, PipelineSettings, Signal
```

- [ ] **Step 3: Verify the model loads without errors**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python3 -c "from app.db.models import PipelineEvaluation; print('OK:', PipelineEvaluation.__tablename__)"
```
Expected: `OK: pipeline_evaluations`

---

### Task 2: Alembic Migration

**Files:**
- Create: new migration file in `backend/app/db/migrations/versions/`

- [ ] **Step 1: Generate the migration**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add pipeline_evaluations table"
```
Expected: Creates a new migration file in `backend/app/db/migrations/versions/`.

- [ ] **Step 2: Review the generated migration**

Read the generated file and confirm it contains:
- `CREATE TABLE pipeline_evaluations` with all columns
- Both indexes (`ix_pipeline_eval_pair_time`, `ix_pipeline_eval_time`)
- FK constraint on `signal_id` with `ondelete="SET NULL"`
- A `downgrade()` that drops the table

- [ ] **Step 3: Apply the migration**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head
```
Expected: Migration applies successfully.

- [ ] **Step 4: Verify the table exists**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python3 -c "
import asyncio
from app.db.database import Database
from app.config import Settings
async def check():
    s = Settings()
    db = Database(s.database_url)
    async with db.engine.connect() as conn:
        r = await conn.execute(__import__('sqlalchemy').text('SELECT count(*) FROM pipeline_evaluations'))
        print('Table exists, rows:', r.scalar())
    await db.close()
asyncio.run(check())
"
```
Expected: `Table exists, rows: 0`

---

### Task 3: Monitor API Endpoints — Tests

**Files:**
- Create: `backend/tests/api/test_monitor.py`

- [ ] **Step 1: Write tests for both endpoints**

```python
"""Tests for pipeline monitor API endpoints."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import create_app


def _make_eval_row(
    id=1, pair="BTC-USDT-SWAP", timeframe="15m", emitted=False,
    final_score=25, effective_threshold=40, tech_score=30, flow_score=15,
    minutes_ago=10,
):
    """Build a mock PipelineEvaluation row."""
    row = MagicMock()
    row.id = id
    row.pair = pair
    row.timeframe = timeframe
    row.evaluated_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    row.emitted = emitted
    row.signal_id = 99 if emitted else None
    row.final_score = final_score
    row.effective_threshold = effective_threshold
    row.tech_score = tech_score
    row.flow_score = flow_score
    row.onchain_score = None
    row.pattern_score = 5
    row.liquidation_score = None
    row.confluence_score = 8
    row.indicator_preliminary = 28
    row.blended_score = 26
    row.ml_score = 0.6 if emitted else None
    row.ml_confidence = 0.7 if emitted else None
    row.llm_contribution = 3 if emitted else 0
    row.ml_agreement = "agree" if emitted else "neutral"
    row.indicators = {"adx": 28.5, "rsi": 55.2, "atr": 350.5}
    row.regime = {"trending": 0.4, "ranging": 0.35, "volatile": 0.25}
    row.availabilities = {
        "tech": {"availability": 1.0, "conviction": 0.85},
        "flow": {"availability": 1.0, "conviction": 0.6},
    }
    return row


@pytest.fixture
async def monitor_client():
    from tests.conftest import _test_lifespan
    app = create_app(lifespan_override=_test_lifespan)
    async with _test_lifespan(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac, app


def _cookies():
    from tests.conftest import make_test_jwt
    return {"krypton_token": make_test_jwt()}


@pytest.mark.asyncio
async def test_evaluations_returns_401_without_auth(monitor_client):
    client, _ = monitor_client
    resp = await client.get("/api/monitor/evaluations")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_evaluations_returns_empty_list(monitor_client):
    client, app = monitor_client

    mock_session = AsyncMock()
    # Query for items returns empty
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = []
    # Query for count returns 0
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    mock_session.execute = AsyncMock(side_effect=[items_result, count_result])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    app.state.db.session_factory = MagicMock(return_value=mock_session)

    resp = await client.get("/api/monitor/evaluations", cookies=_cookies())
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_evaluations_returns_items_with_filters(monitor_client):
    client, app = monitor_client

    rows = [_make_eval_row(id=1, emitted=False), _make_eval_row(id=2, emitted=True, final_score=50)]

    mock_session = AsyncMock()
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = rows
    count_result = MagicMock()
    count_result.scalar.return_value = 2
    mock_session.execute = AsyncMock(side_effect=[items_result, count_result])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    app.state.db.session_factory = MagicMock(return_value=mock_session)

    resp = await client.get(
        "/api/monitor/evaluations?pair=BTC-USDT-SWAP&limit=10",
        cookies=_cookies(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] == 2
    assert data["items"][0]["pair"] == "BTC-USDT-SWAP"
    assert data["items"][0]["indicators"]["adx"] == 28.5
    assert data["items"][0]["regime"]["trending"] == 0.4


@pytest.mark.asyncio
async def test_evaluations_limit_rejects_over_200(monitor_client):
    client, _ = monitor_client

    resp = await client.get(
        "/api/monitor/evaluations?limit=500",
        cookies=_cookies(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_summary_rejects_invalid_period(monitor_client):
    client, _ = monitor_client

    resp = await client.get("/api/monitor/summary?period=2h", cookies=_cookies())
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_summary_returns_401_without_auth(monitor_client):
    client, _ = monitor_client
    resp = await client.get("/api/monitor/summary")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_summary_returns_stats(monitor_client):
    client, app = monitor_client

    mock_session = AsyncMock()
    # Main aggregation query: total, emitted_count, avg_abs
    main_result = MagicMock()
    main_result.one.return_value = (100, 5, 24.3)
    # Per-pair query: list of (pair, total, emitted, avg_abs)
    pair_result = MagicMock()
    pair_result.all.return_value = [
        MagicMock(pair="BTC-USDT-SWAP", total=50, emitted_count=3, avg_abs=26.1),
        MagicMock(pair="ETH-USDT-SWAP", total=50, emitted_count=2, avg_abs=22.5),
    ]
    mock_session.execute = AsyncMock(side_effect=[main_result, pair_result])
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    app.state.db.session_factory = MagicMock(return_value=mock_session)

    resp = await client.get("/api/monitor/summary?period=24h", cookies=_cookies())
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "24h"
    assert data["total_evaluations"] == 100
    assert data["emitted_count"] == 5
    assert data["emission_rate"] == pytest.approx(0.05)
    assert len(data["per_pair"]) >= 2


@pytest.mark.asyncio
async def test_persist_pipeline_evaluation_swallows_errors():
    """Best-effort persist must not propagate exceptions."""
    from app.main import persist_pipeline_evaluation

    mock_db = MagicMock()
    mock_session = AsyncMock()
    mock_session.add = MagicMock(side_effect=RuntimeError("db boom"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_db.session_factory = MagicMock(return_value=mock_session)

    # Must not raise
    await persist_pipeline_evaluation(
        mock_db,
        pair="BTC-USDT-SWAP", timeframe="15m",
        evaluated_at=datetime.now(timezone.utc), emitted=False, signal_id=None,
        final_score=25, effective_threshold=40, tech_score=30, flow_score=15,
        onchain_score=None, pattern_score=5, liquidation_score=None,
        confluence_score=8, indicator_preliminary=28, blended_score=26,
        ml_score=None, ml_confidence=None, llm_contribution=0,
        ml_agreement="neutral", indicators={"adx": 28.5},
        regime={"trending": 0.4, "ranging": 0.35, "volatile": 0.25},
        availabilities={"tech": {"availability": 1.0, "conviction": 0.85}},
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_monitor.py -v
```
Expected: All tests FAIL (module `app.api.monitor` does not exist yet).

---

### Task 4: Monitor API Endpoints — Implementation

**Files:**
- Create: `backend/app/api/monitor.py`

- [ ] **Step 1: Implement the monitor router**

```python
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
```

- [ ] **Step 2: Register the router in `main.py`**

In `backend/app/main.py`, in the `create_app` function, add after the optimizer router registration (around line 1817):

```python
    from app.api.monitor import router as monitor_router
    app.include_router(monitor_router)
```

- [ ] **Step 3: Run tests to verify they pass**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/api/test_monitor.py -v
```
Expected: All tests PASS.

---

### Task 5: Pipeline Integration — Persist Evaluation Rows

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add `persist_pipeline_evaluation` helper function**

Add this function after `persist_signal` (after line 337) in `backend/app/main.py`:

```python
async def persist_pipeline_evaluation(
    db: Database,
    *,
    pair: str,
    timeframe: str,
    evaluated_at: datetime,
    emitted: bool,
    signal_id: int | None,
    final_score: int,
    effective_threshold: int,
    tech_score: int,
    flow_score: int,
    onchain_score: int | None,
    pattern_score: int | None,
    liquidation_score: int | None,
    confluence_score: int | None,
    indicator_preliminary: int,
    blended_score: int,
    ml_score: float | None,
    ml_confidence: float | None,
    llm_contribution: int,
    ml_agreement: str,
    indicators: dict,
    regime: dict,
    availabilities: dict,
):
    """Best-effort persistence of a pipeline evaluation row."""
    try:
        async with db.session_factory() as session:
            row = PipelineEvaluation(
                pair=pair,
                timeframe=timeframe,
                evaluated_at=evaluated_at,
                emitted=emitted,
                signal_id=signal_id,
                final_score=final_score,
                effective_threshold=effective_threshold,
                tech_score=tech_score,
                flow_score=flow_score,
                onchain_score=onchain_score,
                pattern_score=pattern_score,
                liquidation_score=liquidation_score,
                confluence_score=confluence_score,
                indicator_preliminary=indicator_preliminary,
                blended_score=blended_score,
                ml_score=ml_score,
                ml_confidence=ml_confidence,
                llm_contribution=llm_contribution,
                ml_agreement=ml_agreement,
                indicators=indicators,
                regime=regime,
                availabilities=availabilities,
            )
            session.add(row)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to persist pipeline evaluation for {pair}:{timeframe}: {e}")
```

- [ ] **Step 2: Build eval data dict and call persist for rejected evals**

In `run_pipeline`, after `app.state.last_pipeline_cycle = time.time()` (line 1029) and before `if not emitted:` (line 1031), add the evaluation persistence block. The full edit is — replace lines 1029-1032:

Find this block:
```python
    app.state.last_pipeline_cycle = time.time()

    if not emitted:
        return
```

Replace with:
```python
    app.state.last_pipeline_cycle = time.time()

    # Build lightweight indicators dict for evaluation persistence
    eval_indicators = dict(tech_result.get("indicators", {}))
    pair_flow = order_flow.get(pair, {})
    eval_indicators.update({
        k: pair_flow[k] for k in ("funding_rate", "long_short_ratio", "open_interest_change_pct", "cvd_delta")
        if k in pair_flow
    })

    eval_regime = {
        "trending": regime.get("trending", 0) if regime else 0,
        "ranging": regime.get("ranging", 0) if regime else 0,
        "volatile": regime.get("volatile", 0) if regime else 0,
    }

    eval_availabilities = {
        "tech": {"availability": tech_avail, "conviction": tech_conv},
        "flow": {"availability": flow_avail, "conviction": flow_conv},
        "onchain": {"availability": onchain_avail, "conviction": onchain_conv},
        "pattern": {"availability": pattern_avail, "conviction": pattern_conv},
        "liquidation": {"availability": liq_avail, "conviction": liq_conv},
        "confluence": {"availability": confluence_avail, "conviction": confluence_conv},
    }

    eval_ts = candle.get("timestamp")
    if isinstance(eval_ts, str):
        eval_ts = datetime.fromisoformat(eval_ts)

    eval_kwargs = dict(
        pair=pair,
        timeframe=timeframe,
        evaluated_at=eval_ts,
        emitted=emitted,
        signal_id=None,
        final_score=round(final),
        effective_threshold=round(effective_threshold),
        tech_score=round(tech_result["score"]),
        flow_score=round(flow_result["score"]),
        onchain_score=round(onchain_score) if onchain_available else None,
        pattern_score=round(pat_score) if pat_score else None,
        liquidation_score=round(liq_score) if liq_score else None,
        confluence_score=round(confluence_score) if confluence_score else None,
        indicator_preliminary=round(indicator_preliminary),
        blended_score=round(blended),
        ml_score=ml_score,
        ml_confidence=ml_confidence,
        llm_contribution=round(llm_contribution),
        ml_agreement=agreement,
        indicators=eval_indicators,
        regime=eval_regime,
        availabilities=eval_availabilities,
    )

    if not emitted:
        await persist_pipeline_evaluation(db, **eval_kwargs)
        return
```

- [ ] **Step 3: Persist eval for emitted signals with signal_id**

After the call to `await _emit_signal(app, signal_data, levels, correlated_news_ids)` (line 1136), add:

```python
    eval_kwargs["signal_id"] = signal_data.get("id")
    await persist_pipeline_evaluation(db, **eval_kwargs)
```

Note: `persist_signal` sets `signal_data["id"] = row.id` after commit (line 334), so the id is available here.

- [ ] **Step 4: Verify the pipeline still runs**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/ -v --timeout=30
```
Expected: All existing tests PASS — the eval persist is try/excepted so it won't break anything.

---

### Task 6: Pruning Background Task

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add pruning loop in the lifespan**

In `backend/app/main.py`, after the `error_log_cleanup_task = asyncio.create_task(error_log_cleanup_loop())` line (around line 1718), add:

```python
    async def pipeline_eval_prune_loop():
        while True:
            try:
                async with db.session_factory() as session:
                    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
                    await session.execute(
                        PipelineEvaluation.__table__.delete().where(
                            PipelineEvaluation.evaluated_at < cutoff
                        )
                    )
                    await session.commit()
                logger.info("Pipeline evaluation pruning completed")
            except Exception as e:
                logger.error(f"Pipeline evaluation pruning failed: {e}")
            await asyncio.sleep(86400)

    pipeline_eval_prune_task = asyncio.create_task(pipeline_eval_prune_loop())
```

- [ ] **Step 2: Cancel the task on shutdown**

In the shutdown section (around line 1746, where other tasks are cancelled), add:

```python
    pipeline_eval_prune_task.cancel()
```

Add it after `error_log_cleanup_task.cancel()`.

- [ ] **Step 3: Run the full test suite to verify nothing is broken**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v --timeout=30
```
Expected: All tests PASS.

---

### Task 7: Frontend Types + API Client

**Files:**
- Create: `web/src/features/monitor/types.ts`
- Modify: `web/src/shared/lib/api.ts`

- [ ] **Step 1: Create TypeScript types**

```typescript
export interface PipelineEvaluation {
  id: number;
  pair: string;
  timeframe: string;
  evaluated_at: string;
  emitted: boolean;
  signal_id: number | null;
  final_score: number;
  effective_threshold: number;
  tech_score: number;
  flow_score: number;
  onchain_score: number | null;
  pattern_score: number | null;
  liquidation_score: number | null;
  confluence_score: number | null;
  indicator_preliminary: number;
  blended_score: number;
  ml_score: number | null;
  ml_confidence: number | null;
  llm_contribution: number;
  ml_agreement: "agree" | "disagree" | "neutral";
  indicators: Record<string, number>;
  regime: { trending: number; ranging: number; volatile: number };
  availabilities: Record<string, { availability: number; conviction: number }>;
}

export interface MonitorSummary {
  period: string;
  total_evaluations: number;
  emitted_count: number;
  emission_rate: number;
  avg_abs_score: number;
  per_pair: PairSummary[];
}

export interface PairSummary {
  pair: string;
  total: number;
  emitted: number;
  emission_rate: number;
  avg_abs_score: number;
}

export type MonitorPeriod = "1h" | "6h" | "24h" | "7d";

export interface MonitorFilters {
  pair: string | null;
  emitted: boolean | null;
  period: MonitorPeriod;
}
```

- [ ] **Step 2: Add API client methods**

In `web/src/shared/lib/api.ts`, add inside the `api` object (at the end, before the closing `}`):

```typescript
  getMonitorEvaluations: (params?: {
    pair?: string;
    emitted?: boolean;
    after?: string;
    before?: string;
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.pair) query.set("pair", params.pair);
    if (params?.emitted !== undefined) query.set("emitted", String(params.emitted));
    if (params?.after) query.set("after", params.after);
    if (params?.before) query.set("before", params.before);
    if (params?.limit) query.set("limit", String(params.limit));
    if (params?.offset) query.set("offset", String(params.offset));
    const qs = query.toString();
    return request<{ items: import("../../../features/monitor/types").PipelineEvaluation[]; total: number }>(
      `/api/monitor/evaluations${qs ? `?${qs}` : ""}`,
    );
  },

  getMonitorSummary: (period?: string) => {
    const query = period ? `?period=${period}` : "";
    return request<import("../../../features/monitor/types").MonitorSummary>(
      `/api/monitor/summary${query}`,
    );
  },
```

Note: The import type syntax keeps the types co-located in the monitor feature. If the project prefers top-level type imports, move the type definitions into `api.ts` imports instead. Check how existing methods handle this — if other methods use inline types (e.g. `Signal[]`), import `PipelineEvaluation` and `MonitorSummary` at the top of `api.ts`:

```typescript
import type { PipelineEvaluation, MonitorSummary } from "../../features/monitor/types";
```

Then the return types simplify to `request<{ items: PipelineEvaluation[]; total: number }>` and `request<MonitorSummary>`.

- [ ] **Step 3: Verify TypeScript compiles**

Run:
```bash
cd web && npx tsc --noEmit
```
Expected: No type errors.

---

### Task 8: useMonitorData Hook

**Files:**
- Create: `web/src/features/monitor/hooks/useMonitorData.ts`

- [ ] **Step 1: Implement the data fetching hook**

```typescript
import { useState, useCallback, useEffect, useRef } from "react";
import { api } from "../../../shared/lib/api";
import type { PipelineEvaluation, MonitorSummary, MonitorFilters, MonitorPeriod } from "../types";

const PERIOD_HOURS: Record<MonitorPeriod, number> = {
  "1h": 1, "6h": 6, "24h": 24, "7d": 168,
};

export function useMonitorData() {
  const [filters, setFilters] = useState<MonitorFilters>({
    pair: null,
    emitted: null,
    period: "24h",
  });
  const [items, setItems] = useState<PipelineEvaluation[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<MonitorSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const offsetRef = useRef(0);

  const fetchData = useCallback(async (reset: boolean) => {
    const fromOffset = reset ? 0 : offsetRef.current;
    if (reset) setLoading(true);
    setError(null);

    const hours = PERIOD_HOURS[filters.period];
    const after = new Date(Date.now() - hours * 3600_000).toISOString();

    try {
      const [evalResult, summaryResult] = await Promise.all([
        api.getMonitorEvaluations({
          pair: filters.pair ?? undefined,
          emitted: filters.emitted ?? undefined,
          after,
          limit: 50,
          offset: fromOffset,
        }),
        reset ? api.getMonitorSummary(filters.period) : Promise.resolve(null),
      ]);

      if (reset) {
        setItems(evalResult.items);
        if (summaryResult) setSummary(summaryResult);
      } else {
        setItems((prev) => [...prev, ...evalResult.items]);
      }
      setTotal(evalResult.total);
      offsetRef.current = fromOffset + evalResult.items.length;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchData(true);
  }, [fetchData]);

  const refresh = useCallback(() => fetchData(true), [fetchData]);
  const loadMore = useCallback(() => fetchData(false), [fetchData]);

  const updateFilter = useCallback(<K extends keyof MonitorFilters>(key: K, value: MonitorFilters[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  const hasMore = items.length < total;

  return {
    filters, updateFilter,
    items, total, summary,
    loading, error,
    refresh, loadMore, hasMore,
  };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run:
```bash
cd web && npx tsc --noEmit
```
Expected: No type errors.

---

### Task 9: SummaryCards + PairBreakdown Components

**Files:**
- Create: `web/src/features/monitor/components/SummaryCards.tsx`
- Create: `web/src/features/monitor/components/PairBreakdown.tsx`

- [ ] **Step 1: Implement SummaryCards**

```tsx
import { MetricCard } from "../../../shared/components";
import type { MonitorSummary } from "../types";

export function SummaryCards({ summary }: { summary: MonitorSummary | null }) {
  if (!summary) return null;

  return (
    <div className="grid grid-cols-3 gap-3">
      <MetricCard label="Evaluations" value={summary.total_evaluations} />
      <MetricCard
        label="Emitted"
        value={`${summary.emitted_count} (${(summary.emission_rate * 100).toFixed(1)}%)`}
        accent="long"
      />
      <MetricCard label="Avg |Score|" value={summary.avg_abs_score.toFixed(1)} />
    </div>
  );
}
```

- [ ] **Step 2: Implement PairBreakdown**

```tsx
import { Card, ProgressBar } from "../../../shared/components";
import type { PairSummary } from "../types";

function shortPair(pair: string) {
  return pair.split("-")[0];
}

export function PairBreakdown({ pairs }: { pairs: PairSummary[] }) {
  if (!pairs.length) return null;

  return (
    <div className="grid grid-cols-3 gap-3">
      {pairs.map((p) => (
        <Card key={p.pair} padding="sm">
          <p className="text-xs text-on-surface-variant mb-1">{shortPair(p.pair)}</p>
          <p className="text-sm font-bold text-on-surface">
            {p.emitted}
            <span className="text-on-surface-variant font-normal">/{p.total}</span>
          </p>
          <ProgressBar value={p.emission_rate * 100} height="sm" color="bg-primary" />
          <p className="text-[10px] text-on-surface-variant mt-1">
            {(p.emission_rate * 100).toFixed(1)}% rate
          </p>
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run:
```bash
cd web && npx tsc --noEmit
```
Expected: No type errors.

---

### Task 10: EvaluationDetail Component

**Files:**
- Create: `web/src/features/monitor/components/EvaluationDetail.tsx`

- [ ] **Step 1: Implement the expanded detail view**

```tsx
import { useState } from "react";
import { Badge, Card, CollapsibleSection } from "../../../shared/components";
import type { PipelineEvaluation } from "../types";

function ScoreRow({ label, value }: { label: string; value: number | null }) {
  if (value === null || value === undefined) return null;
  const color =
    value > 0 ? "text-long" : value < 0 ? "text-short" : "text-on-surface-variant";
  return (
    <div className="flex justify-between text-xs py-0.5">
      <span className="text-on-surface-variant">{label}</span>
      <span className={color}>{value > 0 ? "+" : ""}{Math.round(value)}</span>
    </div>
  );
}

const INDICATOR_LABELS: Record<string, string> = {
  adx: "ADX",
  rsi: "RSI",
  bb_upper: "BB Upper",
  bb_lower: "BB Lower",
  bb_width: "BB Width",
  bb_width_pct: "BB Width %",
  atr: "ATR",
  obv_slope: "OBV Slope",
  vol_ratio: "Vol Ratio",
};

const FLOW_LABELS: Record<string, string> = {
  funding_rate: "Funding Rate",
  long_short_ratio: "L/S Ratio",
  open_interest_change_pct: "OI Change %",
  cvd_delta: "CVD Delta",
};

export function EvaluationDetail({ evaluation: e }: { evaluation: PipelineEvaluation }) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({});
  const toggle = (key: string) =>
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));

  const techIndicators = Object.entries(e.indicators).filter(
    ([k]) => k in INDICATOR_LABELS
  );
  const flowIndicators = Object.entries(e.indicators).filter(
    ([k]) => k in FLOW_LABELS
  );

  return (
    <Card padding="sm" className="mt-1 mb-2 border border-outline-variant/10">
      <p className="text-[10px] text-on-surface-variant uppercase tracking-wider mb-2">
        Scoring Pipeline
      </p>

      {/* Sub-scores */}
      <div className="grid grid-cols-2 gap-x-4">
        <ScoreRow label="Technical" value={e.tech_score} />
        <ScoreRow label="Order Flow" value={e.flow_score} />
        <ScoreRow label="On-chain" value={e.onchain_score} />
        <ScoreRow label="Pattern" value={e.pattern_score} />
        <ScoreRow label="Liquidation" value={e.liquidation_score} />
        <ScoreRow label="Confluence" value={e.confluence_score} />
      </div>

      <div className="border-t border-outline-variant/10 my-2" />

      {/* Transformation chain */}
      <div className="grid grid-cols-2 gap-x-4">
        <ScoreRow label="Preliminary" value={e.indicator_preliminary} />
        <ScoreRow label="Blended (post-ML)" value={e.blended_score} />
        <ScoreRow label="LLM Contribution" value={e.llm_contribution} />
        <ScoreRow label="Final" value={e.final_score} />
      </div>

      <div className="flex items-center gap-2 mt-2 mb-1">
        <Badge color={e.ml_agreement === "agree" ? "long" : e.ml_agreement === "disagree" ? "short" : "muted"}>
          ML: {e.ml_agreement}
        </Badge>
        {e.ml_score !== null && (
          <span className="text-[10px] text-on-surface-variant">
            score {e.ml_score.toFixed(2)} · conf {e.ml_confidence?.toFixed(2)}
          </span>
        )}
      </div>

      {/* Regime */}
      <div className="flex gap-3 mt-2 text-[10px] text-on-surface-variant">
        <span>Trend {(e.regime.trending * 100).toFixed(0)}%</span>
        <span>Range {(e.regime.ranging * 100).toFixed(0)}%</span>
        <span>Vol {(e.regime.volatile * 100).toFixed(0)}%</span>
      </div>

      {/* Collapsible indicator sections */}
      {techIndicators.length > 0 && (
        <CollapsibleSection
          title="Technical Indicators"
          open={!!openSections.tech}
          onToggle={() => toggle("tech")}
        >
          <div className="grid grid-cols-2 gap-x-4">
            {techIndicators.map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs py-0.5">
                <span className="text-on-surface-variant">{INDICATOR_LABELS[k] ?? k}</span>
                <span className="text-on-surface">{typeof v === "number" ? v.toFixed(2) : v}</span>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {flowIndicators.length > 0 && (
        <CollapsibleSection
          title="Order Flow"
          open={!!openSections.flow}
          onToggle={() => toggle("flow")}
        >
          <div className="grid grid-cols-2 gap-x-4">
            {flowIndicators.map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs py-0.5">
                <span className="text-on-surface-variant">{FLOW_LABELS[k] ?? k}</span>
                <span className="text-on-surface">{typeof v === "number" ? v.toFixed(4) : v}</span>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}
    </Card>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run:
```bash
cd web && npx tsc --noEmit
```
Expected: No type errors.

---

### Task 11: EvaluationTable Component

**Files:**
- Create: `web/src/features/monitor/components/EvaluationTable.tsx`

- [ ] **Step 1: Implement the evaluation table with expandable rows**

```tsx
import { useState } from "react";
import { Badge, Button } from "../../../shared/components";
import { EvaluationDetail } from "./EvaluationDetail";
import type { PipelineEvaluation } from "../types";

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function shortPair(pair: string) {
  return pair.split("-")[0];
}

function isNearThreshold(e: PipelineEvaluation) {
  return !e.emitted && Math.abs(e.final_score) >= e.effective_threshold * 0.85;
}

function ScoreCell({ value }: { value: number }) {
  const color =
    value > 0 ? "text-long" : value < 0 ? "text-short" : "text-on-surface-variant";
  return <span className={`font-mono text-xs ${color}`}>{value > 0 ? "+" : ""}{value}</span>;
}

export function EvaluationTable({
  items,
  hasMore,
  onLoadMore,
}: {
  items: PipelineEvaluation[];
  hasMore: boolean;
  onLoadMore: () => void;
}) {
  const [expandedId, setExpandedId] = useState<number | null>(null);

  if (!items.length) return null;

  return (
    <div>
      {/* Header */}
      <div className="grid grid-cols-[3rem_2.5rem_1fr_1fr_1fr_3.5rem] gap-1 px-2 py-1 text-[10px] text-on-surface-variant uppercase tracking-wider">
        <span>Time</span>
        <span>Pair</span>
        <span className="text-right">Final</span>
        <span className="text-right">Tech</span>
        <span className="text-right">Flow</span>
        <span className="text-right">Status</span>
      </div>

      {/* Rows */}
      {items.map((e) => (
        <div key={e.id}>
          <button
            className={`w-full grid grid-cols-[3rem_2.5rem_1fr_1fr_1fr_3.5rem] gap-1 px-2 py-2 text-xs items-center hover:bg-surface-container-high/50 transition-colors ${
              isNearThreshold(e) ? "bg-amber-500/5" : ""
            } ${expandedId === e.id ? "bg-surface-container-high/30" : ""}`}
            onClick={() => setExpandedId(expandedId === e.id ? null : e.id)}
          >
            <span className="text-on-surface-variant font-mono">{formatTime(e.evaluated_at)}</span>
            <span className="text-on-surface font-medium">{shortPair(e.pair)}</span>
            <span className="text-right"><ScoreCell value={e.final_score} /></span>
            <span className="text-right"><ScoreCell value={e.tech_score} /></span>
            <span className="text-right"><ScoreCell value={e.flow_score} /></span>
            <span className="text-right">
              <Badge color={e.emitted ? "long" : "muted"} pill>
                {e.emitted ? "emit" : "rej"}
              </Badge>
            </span>
          </button>
          {expandedId === e.id && <EvaluationDetail evaluation={e} />}
        </div>
      ))}

      {/* Load more */}
      {hasMore && (
        <div className="flex justify-center py-4">
          <Button variant="secondary" size="sm" onClick={onLoadMore}>
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run:
```bash
cd web && npx tsc --noEmit
```
Expected: No type errors.

---

### Task 12: MonitorPage + Navigation Integration

**Files:**
- Create: `web/src/features/monitor/components/MonitorPage.tsx`
- Modify: `web/src/features/more/components/MorePage.tsx`

- [ ] **Step 1: Implement MonitorPage**

```tsx
import { Dropdown } from "../../../shared/components";
import { Button, Skeleton, Card } from "../../../shared/components";
import { EmptyState } from "../../../shared/components";
import { RefreshCw, Inbox } from "lucide-react";
import { useMonitorData } from "../hooks/useMonitorData";
import { SummaryCards } from "./SummaryCards";
import { PairBreakdown } from "./PairBreakdown";
import { EvaluationTable } from "./EvaluationTable";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import type { MonitorPeriod } from "../types";

const PAIR_OPTIONS = [
  { value: "", label: "All Pairs" },
  ...AVAILABLE_PAIRS.map((p) => ({ value: p, label: p.split("-")[0] })),
];

const STATUS_OPTIONS = [
  { value: "", label: "All" },
  { value: "true", label: "Emitted" },
  { value: "false", label: "Rejected" },
];

const PERIOD_OPTIONS = [
  { value: "1h", label: "1h" },
  { value: "6h", label: "6h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
];

export function MonitorPage() {
  const {
    filters, updateFilter,
    items, summary,
    loading, error,
    refresh, loadMore, hasMore,
  } = useMonitorData();

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <Dropdown
          options={PAIR_OPTIONS}
          value={filters.pair ?? ""}
          onChange={(v) => updateFilter("pair", v || null)}
          size="sm"
          ariaLabel="Filter by pair"
        />
        <Dropdown
          options={STATUS_OPTIONS}
          value={filters.emitted === null ? "" : String(filters.emitted)}
          onChange={(v) => updateFilter("emitted", v === "" ? null : v === "true")}
          size="sm"
          ariaLabel="Filter by status"
        />
        <Dropdown
          options={PERIOD_OPTIONS}
          value={filters.period}
          onChange={(v) => updateFilter("period", v as MonitorPeriod)}
          size="sm"
          ariaLabel="Time range"
        />
        <Button variant="ghost" size="sm" icon={<RefreshCw size={14} />} onClick={refresh} />
      </div>

      {/* Loading */}
      {loading && (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <Skeleton height="4rem" />
            <Skeleton height="4rem" />
            <Skeleton height="4rem" />
          </div>
          <Skeleton count={5} height="2.5rem" />
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <Card border={false} className="border border-error/20 text-center py-6">
          <p className="text-sm text-on-surface mb-2">{error}</p>
          <Button variant="primary" size="sm" onClick={refresh}>Retry</Button>
        </Card>
      )}

      {/* Content */}
      {!loading && !error && (
        <>
          <SummaryCards summary={summary} />
          {summary && <PairBreakdown pairs={summary.per_pair} />}

          {items.length === 0 ? (
            <EmptyState
              icon={<Inbox size={32} className="text-on-surface-variant" />}
              title="No evaluations found"
              subtitle={
                summary?.total_evaluations === 0
                  ? "Pipeline evaluations will appear here after the first candle closes."
                  : "No evaluations match your filters."
              }
            />
          ) : (
            <EvaluationTable items={items} hasMore={hasMore} onLoadMore={loadMore} />
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add "monitor" to MorePage**

In `web/src/features/more/components/MorePage.tsx`:

**a)** Add to the `SubPage` type union (line 16):
```typescript
type SubPage = "engine" | "backtest" | "ml" | "alerts" | "risk" | "settings" | "journal" | "system" | "optimizer" | "news" | "monitor" | null;
```

**b)** Add to the `PAGE_TITLES` map (around line 46-57):
```typescript
  monitor: "Pipeline Monitor",
```

**c)** Add to the appropriate cluster in `CLUSTERS` (in the cluster that contains "system" — likely "System Hub" or similar). Add an entry:
```typescript
{ key: "monitor" as SubPage, icon: Activity, label: "Pipeline Monitor", desc: "Evaluation history & stats", color: "text-primary" },
```
Import `Activity` from `lucide-react` at the top.

**d)** Add the conditional render in the `if (activePage)` block (around line 62-76):
```typescript
{activePage === "monitor" && <MonitorPage />}
```

**e)** Add the import at the top of the file:
```typescript
import { MonitorPage } from "../../monitor/components/MonitorPage";
```

- [ ] **Step 3: Verify build succeeds**

Run:
```bash
cd web && pnpm build
```
Expected: Build succeeds with no errors.

- [ ] **Step 4: Verify dev server renders the page**

Run:
```bash
cd web && pnpm dev
```
Open the app → More → Pipeline Monitor. Verify:
- The page renders with filter bar, loading skeletons (or empty state if no data)
- No console errors

- [ ] **Step 5: Commit all work**

```bash
git add backend/app/db/models.py backend/app/api/monitor.py backend/app/main.py backend/tests/api/test_monitor.py backend/app/db/migrations/versions/ web/src/features/monitor/ web/src/shared/lib/api.ts web/src/features/more/components/MorePage.tsx && git commit -m "feat(monitor): pipeline evaluation persistence, API, pruning, and frontend page"
```

---

## Self-Review Results

**Spec coverage check:**
- [x] PipelineEvaluation model with all columns, indexes, FK with ON DELETE SET NULL
- [x] Pipeline integration: persist for both emitted and rejected evals
- [x] Lightweight indicators dict (not `_build_raw_indicators`) for rejected evals
- [x] Failure handling: try/except, best-effort, never blocks signal emission
- [x] Pruning: daily background task, 7-day retention
- [x] Migration: Alembic autogenerate
- [x] GET /api/monitor/evaluations with all query params, `evaluated_at DESC` ordering, filtered total
- [x] GET /api/monitor/summary with 1h/6h/24h/7d periods, all pairs included
- [x] Router registration in create_app
- [x] Frontend feature module structure
- [x] Navigation: SubPage union + CLUSTERS + conditional render
- [x] Filter bar: pair, status, time range, refresh
- [x] Summary cards: total evals, emitted+rate, avg |score|
- [x] Per-pair breakdown with progress bars
- [x] Evaluation table with expandable rows
- [x] Expanded detail: scoring pipeline stages, ML agreement badge, collapsible indicators/flow
- [x] Near-threshold amber tint: `|final_score| >= effective_threshold * 0.85`
- [x] Load more pagination
- [x] Loading state (Skeleton), error state (inline + retry), empty state (EmptyState)
- [x] API client methods
- [x] TypeScript types with JSONB shapes
- [x] `ml_agreement` naming (not `agreement`)
- [x] Integer column types (not SmallInteger)
- [x] `period` param validated via Enum (rejects invalid values with 422)
- [x] `limit` param validated via `Query(le=200)` (rejects >200 with 422)
- [x] `persist_pipeline_evaluation` error-swallowing tested
- [x] `useMonitorData` offset uses `useRef` (no stale closure)
- [x] Single commit at end of all tasks

**Placeholder scan:** No TBD, TODO, "implement later", or vague "add appropriate handling" found.

**Type consistency check:**
- `PipelineEvaluation` — consistent between model (Task 1), API serializer (Task 4), TS type (Task 7)
- `MonitorSummary` / `PairSummary` — consistent between API response (Task 4) and TS types (Task 7)
- `MonitorFilters` / `MonitorPeriod` — used consistently in hook (Task 8) and MonitorPage (Task 12)
- `ml_agreement` field name — consistent everywhere
- `persist_pipeline_evaluation` function signature matches `eval_kwargs` construction
- `Dropdown` component props verified: `options`, `value`, `onChange`, `size="sm"`, `ariaLabel` all match
