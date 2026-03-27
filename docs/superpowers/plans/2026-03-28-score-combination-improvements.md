# Score Combination Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix structural bugs in score combination (double normalization, avg_confidence), wire IC pruning, split confidence into availability/conviction, add directional agreement bonus, and replace fixed ML weight with adaptive ramp.

**Architecture:** Six incremental changes to the scoring pipeline, each building on the prior. Combiner interface evolves from single `confidence` to `availability`+`conviction` per source. New tunable parameters added to param_groups for optimizer sweeps. All changes mirrored in backtester.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, pytest

**Spec:** `docs/superpowers/specs/2026-03-27-score-combination-improvements-design.md`

---

### Task 1: *(Merged into Task 5)*

The avg_confidence effective-weight fix is addressed by Task 5's full rewrite of `compute_preliminary_score`. Task 1's tests are included in Task 5 Step 2.

---

### Task 2: Eliminate Double Normalization (Section 1)

**Files:**
- Modify: `backend/app/main.py` (lines 649-669)
- Modify: `backend/app/engine/backtester.py` (lines 247-265)
- Test: `backend/tests/engine/test_combiner_confidence.py`

- [ ] **Step 1: Write failing test for raw outer weights passthrough**

Add to `backend/tests/engine/test_combiner_confidence.py`:

```python
class TestRawOuterWeights:
    def test_unavailable_source_excluded_via_zero_confidence(self):
        """Source with confidence=0 has zero effective weight even with nonzero base weight."""
        result = compute_preliminary_score(
            technical_score=80, order_flow_score=60,
            tech_weight=0.40, flow_weight=0.22,
            onchain_score=50, onchain_weight=0.23,
            pattern_score=40, pattern_weight=0.15,
            tech_confidence=0.9, flow_confidence=0.0,
            onchain_confidence=0.7, pattern_confidence=0.6,
        )
        # flow has confidence=0 so ew_flow=0, flow_score shouldn't contribute
        result_no_flow = compute_preliminary_score(
            technical_score=80, order_flow_score=0,
            tech_weight=0.40, flow_weight=0.0,
            onchain_score=50, onchain_weight=0.23,
            pattern_score=40, pattern_weight=0.15,
            tech_confidence=0.9, flow_confidence=0.0,
            onchain_confidence=0.7, pattern_confidence=0.6,
        )
        assert result["score"] == result_no_flow["score"]
```

- [ ] **Step 2: Run test to verify it passes (this validates combiner already handles it)**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner_confidence.py::TestRawOuterWeights -v`

Expected: PASS — combiner already zeros effective weight when confidence=0.

- [ ] **Step 3: Remove outer weight renormalization from main.py**

In `backend/app/main.py`, find the block starting with `# Zero unavailable sources, then renormalize` (around line 649) and replace it with:

```python
    # Pass raw regime outer weights — combiner handles unavailable sources
    # via confidence=0 producing zero effective weight
    tech_w = outer["tech"]
    flow_w = outer["flow"]
    onchain_w = outer["onchain"]
    pattern_w = outer["pattern"]
    liq_w = outer.get("liquidation", 0.0)
    conf_w = outer.get("confluence", 0.0)
```

Remove the `flow_available`, `liq_available`, `conf_available` variables and the `total_w` normalization block entirely. These variables are not used elsewhere (the availability check was only for zeroing weights).

- [ ] **Step 4: Fix confidence defaults from 0.5 to 0.0**

In `backend/app/main.py`, find the confidence extraction lines (around line 668) and change:

```python
    tech_conf = tech_result.get("confidence", 0.0)
    flow_conf = flow_result.get("confidence", 0.0)
    onchain_conf = onchain_result.get("confidence", 0.0)
    pattern_conf = pat_result.get("confidence", 0.0)
```

Both tech and flow previously defaulted to 0.5. Tech is always present when pipeline runs so the default never triggers, but it must be 0.0 for correctness.

- [ ] **Step 5: Remove backtester outer weight renormalization**

In `backend/app/engine/backtester.py`, find the regime_weights block (around line 250) and replace:

```python
        if regime_weights is not None:
            regime = tech_result.get("regime")
            outer = blend_outer_weights(regime, regime_weights)
            bt_tech_w = outer["tech"]
            bt_pattern_w = outer["pattern"]
            bt_conf_w = outer.get("confluence", 0.0)
            # flow and onchain are 0 in backtester — combiner handles via confidence=0
        else:
            bt_tech_w = config.tech_weight
            bt_pattern_w = config.pattern_weight
            bt_conf_w = 0.0
```

Remove the `bt_total` renormalization block and the `conf_available` check. The backtester passes `flow_weight=0.0`, so flow's effective weight is zero regardless of confidence default (combiner computes `ew = base_weight * confidence`, so `0.0 * anything = 0.0`).

- [ ] **Step 6: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/ -v`

Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/app/engine/backtester.py backend/tests/engine/test_combiner_confidence.py
git commit -m "fix(pipeline): eliminate double normalization, pass raw outer weights to combiner"
```

---

### Task 3: Add Per-Source Scores to raw_indicators (Section 3.1)

**Files:**
- Modify: `backend/app/main.py` (raw_indicators dict, around line 1040)

- [ ] **Step 1: Verify keys don't already exist in raw_indicators**

In `backend/app/main.py`, search the `raw_indicators` dict (around line 1040) for `tech_score`, `flow_score`, `onchain_score`, `pattern_score`. If any already exist under those exact names, skip adding them. If they exist under different names (e.g., `technical_score`), use the existing key name consistently and update `compute_daily_ic_for_sources`'s key mapping in `optimizer.py` to match.

- [ ] **Step 2: Add missing per-source scores to raw_indicators**

In `backend/app/main.py`, find the `raw_indicators` dict inside `signal_data` (around line 1040). Add these four entries alongside the existing `confluence_score` and `liquidation_score`:

```python
            "tech_score": tech_result["score"],
            "flow_score": flow_result["score"],
            "onchain_score": onchain_score,
            "pattern_score": pat_score,
```

Place them right before the existing `"confluence_score": confluence_score,` line.

- [ ] **Step 3: Run existing tests to verify nothing breaks**

Run: `docker exec krypton-api-1 python -m pytest tests/ -x -q`

Expected: ALL PASS — adding keys to a JSONB dict is non-breaking.

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(pipeline): persist per-source scores in raw_indicators for IC computation"
```

---

### Task 4: Wire IC Pruning Pipeline (Section 3)

**Files:**
- Create: `backend/app/db/models.py` (SourceICHistory model)
- Modify: `backend/app/engine/constants.py` (IC constants)
- Modify: `backend/app/engine/optimizer.py` (update IC_PRUNE_EXCLUDED_SOURCES + extract helper)
- Modify: `backend/app/main.py` (startup + check_pending_signals)
- Create: Alembic migration for SourceICHistory
- Test: `backend/tests/engine/test_ic_pipeline.py` (new)

- [ ] **Step 1: Add SourceICHistory model**

In `backend/app/db/models.py`, add the `SourceICHistory` model after the existing `OrderFlowSnapshot` model:

```python
class SourceICHistory(Base):
    __tablename__ = "source_ic_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    ic_value: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "pair", "timeframe", "date", name="uq_source_ic_per_day"),
    )
```

Ensure `Date` and `UniqueConstraint` are imported (add to the existing SQLAlchemy imports if needed).

- [ ] **Step 2: Generate and apply Alembic migration**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add source_ic_history table"
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head
```

Expected: Migration creates `source_ic_history` table with unique constraint.

- [ ] **Step 3: Add IC constants**

In `backend/app/engine/constants.py`, add after the `CONFLUENCE` dict (around line 162):

```python
# -- IC pruning --
IC_WINDOW_DAYS = 7
IC_MIN_DAYS = 30
```

- [ ] **Step 4: Write tests for IC pipeline**

Create `backend/tests/engine/test_ic_pipeline.py`:

```python
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.engine.optimizer import (
    compute_daily_ic_for_sources,
    get_pruned_sources,
    should_reenable_source,
    IC_PRUNE_EXCLUDED_SOURCES,
)


def test_tech_excluded_from_pruning():
    """Tech source is never prunable."""
    assert "tech" in IC_PRUNE_EXCLUDED_SOURCES


def test_compute_daily_ic_reads_source_scores():
    """IC computation reads per-source scores from raw_indicators."""
    signals = [
        {"raw_indicators": {"tech_score": 50, "flow_score": 30, "onchain_score": 0,
                            "pattern_score": 10, "liquidation_score": 0, "confluence_score": 5},
         "outcome_pct": 2.0},
        {"raw_indicators": {"tech_score": -40, "flow_score": -20, "onchain_score": 0,
                            "pattern_score": -15, "liquidation_score": 0, "confluence_score": -5},
         "outcome_pct": -1.5},
    ] * 5  # need at least 5 for compute_ic
    ic_map = compute_daily_ic_for_sources(signals)
    assert "tech" in ic_map
    assert "flow" in ic_map
    assert "onchain" in ic_map
    assert "pattern" in ic_map
    assert "liquidation" in ic_map
    assert "confluence" in ic_map
    # tech and flow scores correlate with outcomes (positive when positive, negative when negative)
    assert ic_map["tech"] > 0
    assert ic_map["flow"] > 0


def test_get_pruned_sources_respects_min_days():
    """Sources need 30 consecutive bad days before pruning."""
    # Only 10 days of bad IC — not enough
    histories = {"flow": [-0.1] * 10}
    pruned = get_pruned_sources(histories, threshold=-0.05, min_days=30)
    assert "flow" not in pruned

    # 30 days of bad IC — should prune
    histories = {"flow": [-0.1] * 30}
    pruned = get_pruned_sources(histories, threshold=-0.05, min_days=30)
    assert "flow" in pruned


def test_reenable_checks_latest_only():
    """Re-enable checks only the latest IC value."""
    # 29 bad days then 1 good day
    history = [-0.1] * 29 + [0.05]
    assert should_reenable_source(history) is True
```

- [ ] **Step 5: Run tests to verify — expect FAIL on tech exclusion**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_ic_pipeline.py -v`

Expected: FAIL on `test_tech_excluded_from_pruning` — currently only `{"liquidation"}` is excluded.

- [ ] **Step 6: Update IC_PRUNE_EXCLUDED_SOURCES to include tech**

In `backend/app/engine/optimizer.py`, line 524:

```python
IC_PRUNE_EXCLUDED_SOURCES = {"tech", "liquidation"}
```

- [ ] **Step 7: Run IC tests again**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_ic_pipeline.py -v`

Expected: ALL PASS

- [ ] **Step 8: Extract IC pruning cycle to optimizer helper**

In `backend/app/engine/optimizer.py`, add a new async function after the existing IC functions:

```python
from app.engine.constants import IC_WINDOW_DAYS, IC_MIN_DAYS


async def run_ic_pruning_cycle(
    db, current_pruned: set[str], logger,
) -> set[str] | None:
    """Run daily IC computation and return updated pruned_sources set, or None if skipped.

    Queries resolved signals from the last IC_WINDOW_DAYS, computes per-source IC,
    persists to SourceICHistory, and determines which sources to prune/re-enable.
    Returns the new pruned set if changed, None if unchanged or insufficient data.
    """
    from datetime import timedelta
    from sqlalchemy import select
    from app.db.models import Signal, SourceICHistory

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=IC_WINDOW_DAYS)
    today = now.date()

    async with db.session_factory() as session:
        # Fetch resolved signals
        result = await session.execute(
            select(Signal)
            .where(Signal.outcome != "PENDING", Signal.outcome_at >= cutoff)
            .order_by(Signal.created_at)
        )
        resolved = result.scalars().all()

        if len(resolved) < 5:
            return None

        # Group by (pair, timeframe)
        groups: dict[tuple[str, str], list] = {}
        for sig in resolved:
            key = (sig.pair, sig.timeframe)
            raw = sig.raw_indicators or {}
            groups.setdefault(key, []).append({
                "raw_indicators": raw,
                "outcome_pct": sig.outcome_pnl_pct or 0.0,
            })

        # Compute and persist IC values
        for (pair, tf), sigs in groups.items():
            if len(sigs) < 5:
                continue
            ic_map = compute_daily_ic_for_sources(sigs)
            for source_name, ic_val in ic_map.items():
                session.add(SourceICHistory(
                    source=source_name, pair=pair,
                    timeframe=tf, date=today, ic_value=ic_val,
                ))
        await session.flush()

        # Fetch IC history for pruning decisions
        result = await session.execute(
            select(SourceICHistory)
            .where(SourceICHistory.date >= today - timedelta(days=IC_MIN_DAYS))
            .order_by(SourceICHistory.date)
        )
        all_ic = result.scalars().all()
        await session.commit()

    # Build per-source IC histories
    ic_histories: dict[str, list[float]] = {}
    for row in all_ic:
        ic_histories.setdefault(row.source, []).append(row.ic_value)

    new_pruned = get_pruned_sources(ic_histories, min_days=IC_MIN_DAYS)

    # Check re-enable for currently pruned sources
    for src in list(current_pruned):
        if src in ic_histories and should_reenable_source(ic_histories[src]):
            new_pruned.discard(src)
            logger.info(f"IC pruning: re-enabled source '{src}'")

    if new_pruned != current_pruned:
        added = new_pruned - current_pruned
        removed = current_pruned - new_pruned
        for src in added:
            logger.info(f"IC pruning: pruned source '{src}'")
        for src in removed:
            logger.info(f"IC pruning: re-enabled source '{src}'")
        return new_pruned

    return None
```

- [ ] **Step 9: Wire IC cycle into main.py**

In `backend/app/main.py`, find `app.state.pruned_sources = set()` (around line 1551) and add after it:

```python
    app.state.last_ic_computed_at = None  # populated by IC tracking
```

In `backend/app/main.py`, find the end of `check_pending_signals` (around line 1293, after the tracker block). Add before the function ends:

```python
        # ── IC pruning: daily computation ──
        last_ic = getattr(app.state, "last_ic_computed_at", None)
        now = datetime.now(timezone.utc)
        if last_ic is None or (now - last_ic).total_seconds() > 86400:
            try:
                from app.engine.optimizer import run_ic_pruning_cycle

                current_pruned = getattr(app.state, "pruned_sources", set())
                updated = await run_ic_pruning_cycle(db, current_pruned, logger)
                if updated is not None:
                    app.state.pruned_sources = updated
                app.state.last_ic_computed_at = now
            except Exception as e:
                logger.warning(f"IC pruning computation failed: {e}")
```

- [ ] **Step 10: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -x -q`

Expected: ALL PASS

- [ ] **Step 11: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/ backend/app/engine/constants.py backend/app/engine/optimizer.py backend/app/main.py backend/tests/engine/test_ic_pipeline.py
git commit -m "feat(pipeline): wire IC pruning pipeline with daily computation, SourceICHistory model, and tech exclusion"
```

---

### Task 5: Confidence Split — Combiner Interface (Section 4)

**Files:**
- Modify: `backend/app/engine/combiner.py` (compute_preliminary_score)
- Modify: `backend/app/engine/constants.py`
- Test: `backend/tests/engine/test_combiner_confidence.py`

- [ ] **Step 1: Add CONVICTION_FLOOR constant**

In `backend/app/engine/constants.py`, add after the `CONFLUENCE` dict (around line 162):

```python
# -- Blending: conviction floor --
CONVICTION_FLOOR = 0.3
```

- [ ] **Step 2: Write failing tests for effective-weight avg_confidence AND availability/conviction split**

Add to `backend/tests/engine/test_combiner_confidence.py`:

```python
from app.engine.constants import CONVICTION_FLOOR


class TestAvgConfidenceEffectiveWeights:
    """Tests from former Task 1 — validates effective-weight avg_confidence contract."""

    def test_avg_confidence_uses_effective_weights(self):
        """High-confidence source should dominate avg_confidence."""
        result = compute_preliminary_score(
            100, 0, 0.5, 0.5,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_confidence=0.9, flow_confidence=0.1,
        )
        # Tech effective weight = 0.5*0.9 = 0.45, flow = 0.5*0.1 = 0.05
        # Normalized: tech_ew = 0.9, flow_ew = 0.1
        # avg_confidence = 0.9*0.9 + 0.1*0.1 = 0.82
        assert result["avg_confidence"] > 0.8

    def test_avg_confidence_zero_confidence_excluded(self):
        """Source with 0 confidence should not drag avg_confidence down."""
        result = compute_preliminary_score(
            100, 0, 0.5, 0.5,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_confidence=0.9, flow_confidence=0.0,
        )
        # Only tech contributes: ew_tech=1.0, avg = 0.9*1.0 = 0.9
        assert result["avg_confidence"] == pytest.approx(0.9, abs=0.01)

    def test_avg_confidence_all_zero_returns_zero(self):
        """All zero confidence returns avg_confidence=0."""
        result = compute_preliminary_score(
            100, 50, 0.5, 0.5,
            tech_confidence=0.0, flow_confidence=0.0,
            onchain_confidence=0.0, pattern_confidence=0.0,
        )
        assert result["avg_confidence"] == 0.0


class TestAvailabilityConviction:
    def test_availability_gates_weight(self):
        """Source with availability=0 should not contribute regardless of conviction."""
        result = compute_preliminary_score(
            technical_score=100, order_flow_score=-100,
            tech_weight=0.5, flow_weight=0.5,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=1.0, tech_conviction=0.8,
            flow_availability=0.0, flow_conviction=1.0,
        )
        assert result["score"] == pytest.approx(100 * (CONVICTION_FLOOR + (1 - CONVICTION_FLOOR) * 0.8), abs=2)

    def test_conviction_scales_score(self):
        """Low conviction reduces score magnitude via floor."""
        high_conv = compute_preliminary_score(
            technical_score=100, order_flow_score=0,
            tech_weight=1.0, flow_weight=0.0,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=1.0, tech_conviction=1.0,
        )
        low_conv = compute_preliminary_score(
            technical_score=100, order_flow_score=0,
            tech_weight=1.0, flow_weight=0.0,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=1.0, tech_conviction=0.0,
        )
        # conviction=1.0 -> scale=1.0, conviction=0.0 -> scale=CONVICTION_FLOOR
        assert high_conv["score"] == 100
        assert low_conv["score"] == pytest.approx(100 * CONVICTION_FLOOR, abs=2)

    def test_backward_compat_confidence_still_works(self):
        """Legacy confidence param still works (mapped to availability)."""
        result = compute_preliminary_score(
            technical_score=80, order_flow_score=60,
            tech_weight=0.6, flow_weight=0.4,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_confidence=0.9, flow_confidence=0.5,
        )
        assert isinstance(result["score"], int)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner_confidence.py::TestAvailabilityConviction -v`

Expected: FAIL — `compute_preliminary_score` doesn't accept availability/conviction params yet.

- [ ] **Step 4: Rewrite compute_preliminary_score with availability/conviction**

Replace the entire `compute_preliminary_score` function in `backend/app/engine/combiner.py`:

```python
from app.engine.constants import LEVEL_DEFAULTS  # existing import, move up
from app.engine.constants import CONVICTION_FLOOR


def compute_preliminary_score(
    technical_score: int,
    order_flow_score: int,
    tech_weight: float = 0.40,
    flow_weight: float = 0.22,
    onchain_score: int = 0,
    onchain_weight: float = 0.23,
    pattern_score: int = 0,
    pattern_weight: float = 0.15,
    # New availability/conviction params (per source)
    tech_availability: float | None = None,
    tech_conviction: float | None = None,
    flow_availability: float | None = None,
    flow_conviction: float | None = None,
    onchain_availability: float | None = None,
    onchain_conviction: float | None = None,
    pattern_availability: float | None = None,
    pattern_conviction: float | None = None,
    liquidation_score: int = 0,
    liquidation_weight: float = 0.0,
    liquidation_availability: float | None = None,
    liquidation_conviction: float | None = None,
    confluence_score: int = 0,
    confluence_weight: float = 0.0,
    confluence_availability: float | None = None,
    confluence_conviction: float | None = None,
    # Legacy params — mapped to availability if new params not provided
    tech_confidence: float = 0.0,
    flow_confidence: float = 0.0,
    onchain_confidence: float = 0.0,
    pattern_confidence: float = 0.0,
    liquidation_confidence: float = 0.0,
    confluence_confidence: float = 0.0,
    conviction_floor: float = CONVICTION_FLOOR,
) -> dict:
    # Resolve availability/conviction: prefer new params, fall back to legacy confidence
    avails = [
        tech_availability if tech_availability is not None else tech_confidence,
        flow_availability if flow_availability is not None else flow_confidence,
        onchain_availability if onchain_availability is not None else onchain_confidence,
        pattern_availability if pattern_availability is not None else pattern_confidence,
        liquidation_availability if liquidation_availability is not None else liquidation_confidence,
        confluence_availability if confluence_availability is not None else confluence_confidence,
    ]
    convictions = [
        tech_conviction if tech_conviction is not None else 1.0,
        flow_conviction if flow_conviction is not None else 1.0,
        onchain_conviction if onchain_conviction is not None else 1.0,
        pattern_conviction if pattern_conviction is not None else 1.0,
        liquidation_conviction if liquidation_conviction is not None else 1.0,
        confluence_conviction if confluence_conviction is not None else 1.0,
    ]
    base_weights = [tech_weight, flow_weight, onchain_weight, pattern_weight,
                    liquidation_weight, confluence_weight]
    scores = [technical_score, order_flow_score, onchain_score, pattern_score,
              liquidation_score, confluence_score]

    # effective_weight = base_weight * availability
    ew = [w * a for w, a in zip(base_weights, avails)]
    total = sum(ew)
    if total <= 0:
        return {"score": 0, "avg_confidence": 0.0}
    ew = [e / total for e in ew]

    # scaled_score = score * (floor + (1 - floor) * conviction)
    scaled = [s * (conviction_floor + (1 - conviction_floor) * c)
              for s, c in zip(scores, convictions)]

    score = round(sum(sc * w for sc, w in zip(scaled, ew)))

    # avg_confidence = sum(availability_i * ew_i) — how confident is the blend overall
    avg_confidence = sum(a * w for a, w in zip(avails, ew))

    return {"score": score, "avg_confidence": avg_confidence}
```

- [ ] **Step 5: Run all combiner tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py tests/engine/test_combiner_confidence.py -v`

Expected: ALL PASS — legacy tests pass via backward-compatible `*_confidence` params (mapped to availability with conviction=1.0, which means `conviction_floor + (1-floor)*1.0 = 1.0`, so score scaling is identity).

- [ ] **Step 6: Run full test suite to check callers**

Run: `docker exec krypton-api-1 python -m pytest tests/ -x -q`

Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/engine/combiner.py backend/app/engine/constants.py backend/tests/engine/test_combiner_confidence.py
git commit -m "feat(combiner): availability/conviction split with backward-compatible confidence fallback"
```

---

### Task 6: Confidence Split — Scorers (Section 4)

**Files:**
- Modify: `backend/app/engine/traditional.py` (tech + flow scorers)
- Modify: `backend/app/engine/onchain_scorer.py`
- Modify: `backend/app/engine/patterns.py`
- Modify: `backend/app/engine/liquidation_scorer.py`
- Modify: `backend/app/engine/confluence.py`
- Test: `backend/tests/engine/test_scorer_availability.py` (new)

- [ ] **Step 1: Write tests for scorer availability/conviction return format**

Create `backend/tests/engine/test_scorer_availability.py`:

```python
import pytest
import pandas as pd
import numpy as np


def _make_df(n=100, base=67000, trend=10):
    """Minimal candle DataFrame for scorer tests."""
    data = []
    for i in range(n):
        p = base + i * trend
        data.append({
            "timestamp": f"2026-01-01T{i:04d}",
            "open": p, "high": p + 50, "low": p - 50, "close": p + 20,
            "volume": 1000 + i * 10,
        })
    return pd.DataFrame(data)


class TestTechScorerFormat:
    def test_returns_availability_and_conviction(self):
        from app.engine.traditional import compute_technical_score
        df = _make_df()
        result = compute_technical_score(df)
        assert "availability" in result
        assert "conviction" in result
        assert result["availability"] == 1.0  # candle data always present
        assert 0.0 <= result["conviction"] <= 1.0


class TestFlowScorerFormat:
    def test_returns_availability_and_conviction(self):
        from app.engine.traditional import compute_order_flow_score
        metrics = {
            "funding_rate": 0.001,
            "open_interest_change_pct": 5.0,
            "long_short_ratio": 1.2,
        }
        result = compute_order_flow_score(metrics)
        assert "availability" in result
        assert "conviction" in result
        assert 0.0 <= result["availability"] <= 1.0
        assert 0.0 <= result["conviction"] <= 1.0

    def test_empty_metrics_zero_availability(self):
        from app.engine.traditional import compute_order_flow_score
        result = compute_order_flow_score({})
        assert result["availability"] == 0.0

    def test_neutral_subsignals_contribute_half_conviction(self):
        """Sub-signals with score=0 count as 0.5 conviction, not excluded."""
        from app.engine.traditional import compute_order_flow_score
        # Only funding present with neutral value (0)
        metrics = {"funding_rate": 0.0}
        result = compute_order_flow_score(metrics)
        # 1 feed available, score=0 (neutral), conviction should be 0.5
        assert result["conviction"] == pytest.approx(0.5, abs=0.1)


class TestOnchainScorerFormat:
    @pytest.mark.asyncio
    async def test_returns_availability_and_conviction(self):
        from unittest.mock import AsyncMock
        from app.engine.onchain_scorer import compute_onchain_score
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value='{"exchange_netflow": -5000}')
        result = await compute_onchain_score("BTC-USDT-SWAP", mock_redis)
        assert "availability" in result
        assert "conviction" in result
        assert 0.0 <= result["availability"] <= 1.0
        assert 0.0 <= result["conviction"] <= 1.0


class TestPatternScorerFormat:
    def test_returns_availability_and_conviction(self):
        from app.engine.patterns import compute_pattern_score
        patterns = [
            {"name": "bullish_engulfing", "direction": "bullish", "strength": 15},
            {"name": "hammer", "direction": "bullish", "strength": 12},
        ]
        result = compute_pattern_score(patterns)
        assert "availability" in result
        assert "conviction" in result
        assert 0.0 <= result["availability"] <= 1.0
        assert 0.0 <= result["conviction"] <= 1.0

    def test_no_patterns_zero_availability(self):
        from app.engine.patterns import compute_pattern_score
        result = compute_pattern_score([])
        assert result["availability"] == 0.0


class TestLiquidationScorerFormat:
    def test_returns_availability_and_conviction(self):
        from app.engine.liquidation_scorer import compute_liquidation_score
        events = [
            {"price": 67100, "volume": 5000, "side": "buy", "timestamp": "2026-01-01T00:00:00Z"},
        ] * 5
        result = compute_liquidation_score(events, current_price=67000, atr=200)
        assert "availability" in result
        assert "conviction" in result
        assert 0.0 <= result["availability"] <= 1.0
        assert 0.0 <= result["conviction"] <= 1.0


class TestConfluenceScorerFormat:
    def test_returns_availability_and_conviction(self):
        from app.engine.confluence import compute_confluence_score
        child = {"trend_score": 30, "mean_rev_score": 0, "trend_conviction": 0.7}
        parent = [{"trend_score": 40, "adx": 25, "di_plus": 30, "di_minus": 15,
                    "trend_conviction": 0.8, "regime": {"trending": 0.7}}]
        result = compute_confluence_score(child, parent, timeframe="15m")
        assert "availability" in result
        assert "conviction" in result
        assert 0.0 <= result["availability"] <= 1.0
        assert 0.0 <= result["conviction"] <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_scorer_availability.py -v`

Expected: FAIL — scorers don't return `availability`/`conviction` keys yet.

- [ ] **Step 3: Update compute_technical_score return**

In `backend/app/engine/traditional.py`, find the return statement of `compute_technical_score` (around line 402). The existing code computes `confidence` from `thesis_conf`. Change the return to:

```python
    return {
        "score": score,
        "indicators": indicators,
        "regime": regime,
        "caps": caps,
        "availability": 1.0,  # candle data always present when pipeline runs
        "conviction": round(confidence, 4),  # thesis_conf-based conviction
        "confidence": round(confidence, 4),  # backward compat
        "mr_pressure": round(mr_pressure_val, 4),
    }
```

- [ ] **Step 4: Update compute_order_flow_score return**

In `backend/app/engine/traditional.py`, find `compute_order_flow_score`. After the existing `flow_confidence` computation (around line 587), add conviction computation before the return:

```python
    # Conviction: sub-signal directional agreement
    # Neutral sub-signals (score=0) contribute 0.5 conviction
    sub_scores = [
        details.get("funding_score", 0),
        details.get("oi_score", 0),
        details.get("ls_score", 0),
        details.get("cvd_score", 0),
        details.get("book_score", 0),
    ]
    available_subs = [s for i, s in enumerate(sub_scores)
                      if [metrics.get("funding_rate") is not None,
                          metrics.get("open_interest_change_pct") is not None,
                          metrics.get("long_short_ratio") is not None,
                          cvd_delta is not None,
                          book_imbalance is not None][i]]
    if available_subs:
        positive = sum(1 for s in available_subs if s > 0)
        negative = sum(1 for s in available_subs if s < 0)
        neutral = sum(1 for s in available_subs if s == 0)
        flow_conviction = round(
            (max(positive, negative) + 0.5 * neutral) / len(available_subs), 4
        )
    else:
        flow_conviction = 0.0

    # Availability is the freshness-decayed data presence ratio
    flow_availability = flow_confidence  # already includes freshness decay
```

Then update the return to:

```python
    return {
        "score": score,
        "details": details,
        "availability": flow_availability,
        "conviction": flow_conviction,
        "confidence": flow_confidence,  # backward compat
    }
```

- [ ] **Step 5: Update compute_onchain_score return**

In `backend/app/engine/onchain_scorer.py`, find the return (around line 100-101). Before the return, add:

```python
    # Conviction: average absolute magnitude of available metric scores / 100
    available_scores = [v for v in metric_scores.values() if v != 0]
    onchain_conviction = round(
        sum(abs(s) for s in available_scores) / (len(available_scores) * 100), 4
    ) if available_scores else 0.0
```

Where `metric_scores` is the dict of individual metric contributions. If the scorer doesn't accumulate individual scores in a dict, collect them during scoring. Update the return:

```python
    return {
        "score": max(min(round(score), 100), -100),
        "availability": confidence,  # metrics_present / total_metrics
        "conviction": onchain_conviction,
        "confidence": confidence,  # backward compat
    }
```

- [ ] **Step 6: Update compute_pattern_score return**

In `backend/app/engine/patterns.py`, find the confidence computation (around line 362-367). Split it:

```python
    non_neutral = bull_count + bear_count
    if non_neutral == 0:
        pattern_availability = 0.0
        pattern_conviction = 0.0
    else:
        pattern_availability = round(min(non_neutral / 3.0, 1.0), 4)
        pattern_conviction = round(max(bull_count, bear_count) / non_neutral, 4)
    confidence = round(pattern_availability * pattern_conviction, 4)
```

Update the return:

```python
    return {
        "score": max(min(round(total), 100), -100),
        "availability": pattern_availability,
        "conviction": pattern_conviction,
        "confidence": confidence,  # backward compat
    }
```

- [ ] **Step 7: Update compute_liquidation_score return**

In `backend/app/engine/liquidation_scorer.py`, find the final return (around line 302). The existing `combined_confidence` becomes availability. Add conviction:

```python
    # Availability: existing combined confidence (cluster/volume adequacy)
    liq_availability = min(1.0, combined_confidence)

    # Conviction: proximity strength + asymmetry magnitude blend
    cluster_proximity = cluster_result.get("avg_proximity_strength", 0.0)
    asymmetry_magnitude = asymmetry_result.get("magnitude", 0.0)
    liq_conviction = round(
        cluster_proximity * cluster_weight + asymmetry_magnitude * asym_weight, 4
    )
    liq_conviction = min(1.0, liq_conviction)
```

If `avg_proximity_strength` and `magnitude` aren't available from the sub-results, use:

```python
    liq_conviction = min(1.0, abs(combined_score) / max(cluster_max_score + asymmetry_max_score, 1))
```

Update the return to include both:

```python
    return {
        "score": combined_score,
        "availability": liq_availability,
        "conviction": liq_conviction,
        "confidence": min(1.0, combined_confidence),  # backward compat
        "clusters": cluster_result["clusters"],
        "details": { ... },
    }
```

- [ ] **Step 8: Update compute_confluence_score return**

In `backend/app/engine/confluence.py`, find the confidence computation (around line 177-179). Split it:

```python
    available_levels = len(alignments)
    avg_conviction_val = sum(convictions) / len(convictions) if convictions else 0
    conf_availability = round(available_levels / max_levels, 4) if max_levels > 0 else 0.0
    conf_conviction_val = round(avg_conviction_val, 4)
    confidence = round(conf_availability * conf_conviction_val, 4)
```

Update the return:

```python
    return {
        "score": score,
        "availability": conf_availability,
        "conviction": conf_conviction_val,
        "confidence": round(confidence, 4),  # backward compat
    }
```

- [ ] **Step 9: Run scorer tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_scorer_availability.py -v`

Expected: ALL PASS

- [ ] **Step 10: Run full test suite to verify backward compat**

Run: `docker exec krypton-api-1 python -m pytest tests/ -x -q`

Expected: ALL PASS — all existing tests use the `confidence` key which is still present.

- [ ] **Step 11: Commit**

```bash
git add backend/app/engine/traditional.py backend/app/engine/onchain_scorer.py backend/app/engine/patterns.py backend/app/engine/liquidation_scorer.py backend/app/engine/confluence.py backend/tests/engine/test_scorer_availability.py
git commit -m "feat(scorers): return availability + conviction alongside legacy confidence"
```

---

### Task 7: Wire Availability/Conviction Through Pipeline (Section 4)

**Files:**
- Modify: `backend/app/main.py` (confidence extraction → availability/conviction)
- Modify: `backend/app/engine/backtester.py`

- [ ] **Step 1: Update main.py to pass availability/conviction to combiner**

In `backend/app/main.py`, find the confidence extraction block (around line 668). Replace:

```python
    # Extract availability + conviction from scorers
    tech_avail = tech_result.get("availability", tech_result.get("confidence", 0.0))
    tech_conv = tech_result.get("conviction", 1.0)
    flow_avail = flow_result.get("availability", flow_result.get("confidence", 0.0))
    flow_conv = flow_result.get("conviction", 1.0)
    onchain_avail = onchain_result.get("availability", onchain_result.get("confidence", 0.0))
    onchain_conv = onchain_result.get("conviction", 1.0)
    pattern_avail = pat_result.get("availability", pat_result.get("confidence", 0.0))
    pattern_conv = pat_result.get("conviction", 1.0)
    liq_avail = liq_result.get("availability", liq_conf) if isinstance(liq_result, dict) else liq_conf
    liq_conv = liq_result.get("conviction", 1.0) if isinstance(liq_result, dict) else 1.0
    confluence_avail = confluence_result.get("availability", confluence_conf)
    confluence_conv = confluence_result.get("conviction", 1.0)

    # Apply IC-based source pruning: zero availability for pruned sources
    pruned = getattr(app.state, "pruned_sources", set())
    avail_vars = {"tech": tech_avail, "flow": flow_avail, "onchain": onchain_avail,
                  "pattern": pattern_avail, "liquidation": liq_avail, "confluence": confluence_avail}
    for src in pruned:
        if src in avail_vars:
            avail_vars[src] = 0.0
    tech_avail = avail_vars["tech"]
    flow_avail = avail_vars["flow"]
    onchain_avail = avail_vars["onchain"]
    pattern_avail = avail_vars["pattern"]
    liq_avail = avail_vars["liquidation"]
    confluence_avail = avail_vars["confluence"]
```

- [ ] **Step 2: Update compute_preliminary_score call**

Replace the `compute_preliminary_score` call (around line 685):

```python
    prelim_result = compute_preliminary_score(
        tech_result["score"],
        flow_result["score"],
        tech_w,
        flow_w,
        onchain_score,
        onchain_w,
        pat_score,
        pattern_w,
        tech_availability=tech_avail,
        tech_conviction=tech_conv,
        flow_availability=flow_avail,
        flow_conviction=flow_conv,
        onchain_availability=onchain_avail,
        onchain_conviction=onchain_conv,
        pattern_availability=pattern_avail,
        pattern_conviction=pattern_conv,
        liquidation_score=liq_score,
        liquidation_weight=liq_w,
        liquidation_availability=liq_avail,
        liquidation_conviction=liq_conv,
        confluence_score=confluence_score,
        confluence_weight=conf_w,
        confluence_availability=confluence_avail,
        confluence_conviction=confluence_conv,
    )
```

- [ ] **Step 3: Store liq_result dict properly**

Find where `liq_score` and `liq_conf` are extracted (around line 633). The liquidation scoring block sets `liq_score = liq_result["score"]` and `liq_conf = liq_result["confidence"]`. Keep `liq_result` accessible by ensuring the full dict is kept. It already is — just rename the usage in step 1 to read from `liq_result` dict keys which we already do.

- [ ] **Step 4: Update backtester to pass availability/conviction**

In `backend/app/engine/backtester.py`, find the `compute_preliminary_score` call (around line 267). The backtester doesn't have flow or onchain data, so those have availability=0. Update:

```python
        indicator_preliminary = compute_preliminary_score(
            technical_score=tech_result["score"],
            order_flow_score=0,
            tech_weight=bt_tech_w,
            flow_weight=0.0,
            onchain_score=0,
            onchain_weight=0.0,
            pattern_score=pat_score,
            pattern_weight=bt_pattern_w,
            tech_availability=tech_result.get("availability", 1.0),
            tech_conviction=tech_result.get("conviction", 1.0),
            flow_availability=0.0,
            onchain_availability=0.0,
            pattern_availability=pat_result.get("availability", 0.0) if isinstance(pat_result, dict) else 0.0,
            pattern_conviction=pat_result.get("conviction", 1.0) if isinstance(pat_result, dict) else 1.0,
            confluence_score=conf_score,
            confluence_weight=bt_conf_w,
            confluence_availability=confluence_result.get("availability", conf_confidence),
            confluence_conviction=confluence_result.get("conviction", 1.0),
        )["score"]
```

The backtester's pattern scoring calls `compute_pattern_score(...)["score"]` — change it to keep the full result:

```python
        pat_result = {"score": 0, "availability": 0.0, "conviction": 0.0}
        detected = []
        if config.enable_patterns:
            try:
                detected = detect_candlestick_patterns(df)
                indicator_ctx = {**tech_result["indicators"], "close": float(df.iloc[-1]["close"])}
                pat_result = compute_pattern_score(
                    detected, indicator_ctx,
                    strength_overrides=strength_overrides,
                    boost_overrides=boost_overrides,
                )
            except Exception:
                pass
        pat_score = pat_result["score"]
```

- [ ] **Step 5: Write tests for pipeline wiring**

Add to `backend/tests/engine/test_combiner_confidence.py`:

```python
class TestPipelineWiring:
    """Verify availability/conviction extraction logic used in main.py and backtester."""

    def test_scorer_output_with_availability_passes_through(self):
        """Scorer returning availability/conviction should produce correct combiner input."""
        # Simulate what main.py does: extract from scorer result, pass to combiner
        tech_result = {"score": 80, "availability": 1.0, "conviction": 0.7, "confidence": 0.7}
        flow_result = {"score": 40, "availability": 0.6, "conviction": 0.5, "confidence": 0.3}

        tech_avail = tech_result.get("availability", tech_result.get("confidence", 0.0))
        tech_conv = tech_result.get("conviction", 1.0)
        flow_avail = flow_result.get("availability", flow_result.get("confidence", 0.0))
        flow_conv = flow_result.get("conviction", 1.0)

        result = compute_preliminary_score(
            technical_score=80, order_flow_score=40,
            tech_weight=0.6, flow_weight=0.4,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=tech_avail, tech_conviction=tech_conv,
            flow_availability=flow_avail, flow_conviction=flow_conv,
        )
        assert isinstance(result["score"], int)
        assert result["score"] != 0  # both sources contribute

    def test_scorer_output_legacy_confidence_fallback(self):
        """Scorer without availability/conviction falls back to confidence correctly."""
        # Legacy scorer output (no availability/conviction keys)
        legacy_result = {"score": 60, "confidence": 0.8}

        avail = legacy_result.get("availability", legacy_result.get("confidence", 0.0))
        conv = legacy_result.get("conviction", 1.0)

        assert avail == 0.8  # fell back to confidence
        assert conv == 1.0   # default conviction

    def test_pruned_source_zeroed(self):
        """Pruned source gets availability=0, excluding it from blend."""
        pruned = {"flow"}
        avail_vars = {"tech": 1.0, "flow": 0.6, "onchain": 0.0,
                      "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0}
        for src in pruned:
            if src in avail_vars:
                avail_vars[src] = 0.0

        result = compute_preliminary_score(
            technical_score=80, order_flow_score=60,
            tech_weight=0.5, flow_weight=0.5,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=avail_vars["tech"], tech_conviction=0.8,
            flow_availability=avail_vars["flow"], flow_conviction=0.9,
        )
        # Flow pruned (availability=0), only tech contributes
        tech_only = compute_preliminary_score(
            technical_score=80, order_flow_score=0,
            tech_weight=1.0, flow_weight=0.0,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=1.0, tech_conviction=0.8,
        )
        assert result["score"] == tech_only["score"]
```

- [ ] **Step 6: Run all tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ -x -q`

Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/app/engine/backtester.py backend/tests/engine/test_combiner_confidence.py
git commit -m "feat(pipeline): wire availability/conviction from scorers through combiner"
```

---

### Task 8: Directional Agreement Bonus (Section 5)

**Files:**
- Modify: `backend/app/engine/combiner.py`
- Modify: `backend/app/engine/constants.py`
- Modify: `backend/app/engine/param_groups.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/engine/backtester.py`
- Test: `backend/tests/engine/test_combiner.py`

- [ ] **Step 1: Add agreement constants**

In `backend/app/engine/constants.py`, add after `CONVICTION_FLOOR`:

```python
# -- Blending: directional agreement bonus --
AGREEMENT_FLOOR = 0.85
AGREEMENT_CEILING = 1.15
```

- [ ] **Step 2: Write failing tests for agreement factor**

Add to `backend/tests/engine/test_combiner.py`:

```python
from app.engine.combiner import apply_agreement_factor


class TestAgreementFactor:
    def test_full_agreement_boosts(self):
        """5/5 same direction gets ceiling multiplier."""
        result = apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 30, 20, 10, 5],
            source_availabilities=[1.0, 1.0, 1.0, 1.0, 1.0],
        )
        assert result > 50

    def test_full_disagreement_penalizes(self):
        """3 vs 2 split gets penalty."""
        result = apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 30, 20, -10, -5],
            source_availabilities=[1.0, 1.0, 1.0, 1.0, 1.0],
        )
        # 3/5 = 0.6 agreement -> multiplier below 1.0
        assert result < 50

    def test_fewer_than_3_sources_no_change(self):
        """<3 contributing sources means no bonus/penalty."""
        result = apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 30],
            source_availabilities=[1.0, 1.0],
        )
        assert result == 50

    def test_zero_score_excluded(self):
        """Sources with score=0 don't count."""
        result = apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 0, 0, 0, 30],
            source_availabilities=[1.0, 1.0, 1.0, 1.0, 1.0],
        )
        # Only 2 non-zero sources -> no change
        assert result == 50

    def test_unavailable_excluded(self):
        """Sources with availability=0 don't count."""
        result = apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 30, 20, 10, 5],
            source_availabilities=[1.0, 1.0, 1.0, 0.0, 0.0],
        )
        # Only 3 contributing -> applies
        assert result == apply_agreement_factor(
            preliminary=50,
            source_scores=[40, 30, 20],
            source_availabilities=[1.0, 1.0, 1.0],
        )

    def test_bounded_to_100(self):
        """Result clamped to [-100, 100]."""
        result = apply_agreement_factor(
            preliminary=95,
            source_scores=[90, 80, 70, 60, 50],
            source_availabilities=[1.0, 1.0, 1.0, 1.0, 1.0],
        )
        assert result <= 100

    def test_zero_preliminary_stays_zero(self):
        """Can't create signal from nothing."""
        result = apply_agreement_factor(
            preliminary=0,
            source_scores=[40, 30, 20],
            source_availabilities=[1.0, 1.0, 1.0],
        )
        assert result == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py::TestAgreementFactor -v`

Expected: FAIL — `apply_agreement_factor` doesn't exist yet.

- [ ] **Step 4: Implement apply_agreement_factor**

Add to `backend/app/engine/combiner.py`, after `compute_agreement`:

```python
from app.engine.constants import AGREEMENT_FLOOR, AGREEMENT_CEILING


def apply_agreement_factor(
    preliminary: int,
    source_scores: list[int],
    source_availabilities: list[float],
    floor: float = AGREEMENT_FLOOR,
    ceiling: float = AGREEMENT_CEILING,
) -> int:
    """Apply directional agreement bonus/penalty to preliminary score."""
    contributing = [(s, a) for s, a in zip(source_scores, source_availabilities)
                    if a > 0 and s != 0]
    if len(contributing) < 3:
        return preliminary
    positive = sum(1 for s, _ in contributing if s > 0)
    negative = sum(1 for s, _ in contributing if s < 0)
    agreement_ratio = max(positive, negative) / len(contributing)
    # Linear interpolation: floor at 50% agreement, ceiling at 100%
    multiplier = floor + (ceiling - floor) * (agreement_ratio - 0.5) / 0.5
    multiplier = max(floor, min(ceiling, multiplier))
    return max(-100, min(100, round(preliminary * multiplier)))
```

- [ ] **Step 5: Run agreement tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py::TestAgreementFactor -v`

Expected: ALL PASS

- [ ] **Step 6: Add agreement param group**

In `backend/app/engine/param_groups.py`, add after the last `PARAM_GROUPS[...]` entry (after the confluence block):

```python
def _agreement_ok(c: dict) -> bool:
    return c["floor"] < 1.0 < c["ceiling"]


PARAM_GROUPS["agreement"] = {
    "params": {
        "floor": "blending.agreement.floor",
        "ceiling": "blending.agreement.ceiling",
    },
    "sweep_method": "grid",
    "sweep_ranges": {
        "floor": (0.70, 0.95, 0.05),
        "ceiling": (1.05, 1.25, 0.05),
    },
    "constraints": _agreement_ok,
    "priority": _priority_for("agreement"),
}
```

- [ ] **Step 7: Wire agreement factor into main.py**

In `backend/app/main.py`, after the `compute_preliminary_score` call and before `blend_with_ml`, add:

```python
    # Directional agreement bonus
    source_scores = [
        tech_result["score"], flow_result["score"], onchain_score,
        pat_score, liq_score, confluence_score,
    ]
    source_avails = [tech_avail, flow_avail, onchain_avail,
                     pattern_avail, liq_avail, confluence_avail]
    indicator_preliminary = apply_agreement_factor(
        indicator_preliminary, source_scores, source_avails,
    )
```

Add `apply_agreement_factor` to the combiner import at the top of main.py.

- [ ] **Step 8: Wire agreement factor into backtester**

In `backend/app/engine/backtester.py`, after the `compute_preliminary_score` call (around line 267), add:

```python
        # Directional agreement bonus
        # NOTE: In backtesting, typically only 2 sources are available (tech + pattern
        # or tech + confluence), so the 3-source minimum means the agreement factor
        # rarely fires here. This is intentional — keeps backtester consistent with
        # live pipeline without inflating backtest scores.
        bt_scores = [tech_result["score"], 0, 0, pat_score, 0, conf_score]
        bt_avails = [
            tech_result.get("availability", 1.0), 0.0, 0.0,
            pat_result.get("availability", 0.0) if isinstance(pat_result, dict) else 0.0,
            0.0,
            confluence_result.get("availability", conf_confidence),
        ]
        indicator_preliminary = apply_agreement_factor(
            indicator_preliminary, bt_scores, bt_avails,
        )
```

Add `apply_agreement_factor` to the combiner import in backtester.py.

- [ ] **Step 9: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -x -q`

Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/engine/combiner.py backend/app/engine/constants.py backend/app/engine/param_groups.py backend/app/main.py backend/app/engine/backtester.py backend/tests/engine/test_combiner.py
git commit -m "feat(combiner): directional agreement bonus with min 3 contributing sources"
```

---

### Task 9: Adaptive ML Weight Ramp (Section 6)

**Files:**
- Modify: `backend/app/engine/combiner.py` (blend_with_ml)
- Modify: `backend/app/engine/constants.py`
- Modify: `backend/app/engine/param_groups.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/engine/backtester.py`
- Test: `backend/tests/engine/test_combiner.py`

- [ ] **Step 1: Add ML weight constants**

In `backend/app/engine/constants.py`, add after `AGREEMENT_CEILING`:

```python
# -- Blending: adaptive ML weight ramp --
ML_WEIGHT_MIN = 0.05
ML_WEIGHT_MAX = 0.30
```

- [ ] **Step 2: Write failing tests for adaptive ML ramp**

Add to `backend/tests/engine/test_combiner.py`:

```python
class TestAdaptiveMLRamp:
    def test_at_threshold_gets_min_weight(self):
        """At exactly the threshold, ML gets minimum weight."""
        result = blend_with_ml(
            indicator_preliminary=60, ml_score=80.0, ml_confidence=0.65,
            ml_weight_min=0.05, ml_weight_max=0.30,
            ml_confidence_threshold=0.65,
        )
        # weight = 0.05, blended = 60*0.95 + 80*0.05 = 57+4 = 61
        assert result == round(60 * 0.95 + 80 * 0.05)

    def test_at_max_confidence_gets_max_weight(self):
        """At confidence=1.0, ML gets maximum weight."""
        result = blend_with_ml(
            indicator_preliminary=60, ml_score=80.0, ml_confidence=1.0,
            ml_weight_min=0.05, ml_weight_max=0.30,
            ml_confidence_threshold=0.65,
        )
        assert result == round(60 * 0.70 + 80 * 0.30)

    def test_mid_confidence_gets_interpolated_weight(self):
        """Midpoint confidence gets interpolated weight."""
        # ml_confidence=0.825, t=(0.825-0.65)/(1.0-0.65)=0.5
        # weight = 0.05 + 0.25*0.5 = 0.175
        result = blend_with_ml(
            indicator_preliminary=60, ml_score=80.0, ml_confidence=0.825,
            ml_weight_min=0.05, ml_weight_max=0.30,
            ml_confidence_threshold=0.65,
        )
        assert result == round(60 * 0.825 + 80 * 0.175)

    def test_below_threshold_excluded(self):
        """Below threshold, ML doesn't participate."""
        result = blend_with_ml(
            indicator_preliminary=60, ml_score=80.0, ml_confidence=0.50,
            ml_weight_min=0.05, ml_weight_max=0.30,
            ml_confidence_threshold=0.65,
        )
        assert result == 60

    def test_threshold_1_0_returns_preliminary(self):
        """Threshold of 1.0 means ML never participates (division by zero guard)."""
        result = blend_with_ml(
            indicator_preliminary=60, ml_score=80.0, ml_confidence=1.0,
            ml_weight_min=0.05, ml_weight_max=0.30,
            ml_confidence_threshold=1.0,
        )
        assert result == 60
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py::TestAdaptiveMLRamp -v`

Expected: FAIL — `blend_with_ml` doesn't accept `ml_weight_min`/`ml_weight_max` params.

- [ ] **Step 4: Rewrite blend_with_ml**

Replace `blend_with_ml` in `backend/app/engine/combiner.py`:

```python
from app.engine.constants import ML_WEIGHT_MIN, ML_WEIGHT_MAX


def blend_with_ml(
    indicator_preliminary: int,
    ml_score: float | None,
    ml_confidence: float | None,
    ml_weight_min: float = ML_WEIGHT_MIN,
    ml_weight_max: float = ML_WEIGHT_MAX,
    ml_confidence_threshold: float = 0.65,
    # Legacy param — ignored if min/max provided
    ml_weight: float | None = None,
) -> int:
    """Blend indicator preliminary score with ML score using adaptive weight ramp.

    ML weight ramps linearly from ml_weight_min at threshold to ml_weight_max at 1.0.
    Returns integer -100 to +100.
    """
    if ml_confidence_threshold >= 1.0:
        return indicator_preliminary
    if (
        ml_score is not None
        and ml_confidence is not None
        and ml_confidence >= ml_confidence_threshold
    ):
        t = (ml_confidence - ml_confidence_threshold) / (1.0 - ml_confidence_threshold)
        effective_weight = ml_weight_min + (ml_weight_max - ml_weight_min) * t
        blended = indicator_preliminary * (1 - effective_weight) + ml_score * effective_weight
        return max(min(round(blended), 100), -100)
    return indicator_preliminary
```

- [ ] **Step 5: Run all blend_with_ml tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -k "blend_with_ml or AdaptiveML" -v`

Expected: Existing tests may need updating. The test `test_blend_with_ml_score_contributes` passes `ml_weight=0.25` — since the new function accepts `ml_weight` as a legacy param but ignores it, this test now uses the default ramp. Update that test:

```python
def test_blend_with_ml_score_contributes():
    """ML score blends with indicator preliminary when confidence is above threshold."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=80.0, ml_confidence=0.80,
        ml_weight_min=0.25, ml_weight_max=0.25,  # fixed weight for backward compat test
        ml_confidence_threshold=0.65,
    )
    expected = round(60 * 0.75 + 80.0 * 0.25)
    assert result == expected
```

Similarly update `test_blend_with_ml_zero_weight`:

```python
def test_blend_with_ml_zero_weight():
    """Zero ML weight means no contribution."""
    result = blend_with_ml(
        indicator_preliminary=60, ml_score=80.0, ml_confidence=0.80,
        ml_weight_min=0.0, ml_weight_max=0.0, ml_confidence_threshold=0.65,
    )
    assert result == 60
```

And `test_blend_with_ml_bounded`, `test_blend_with_ml_negative_scores`, `test_blend_with_ml_disagreement` — update to use `ml_weight_min`/`ml_weight_max` matching the old `ml_weight=0.25` behavior where needed.

- [ ] **Step 6: Run all combiner tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py tests/engine/test_combiner_confidence.py -v`

Expected: ALL PASS

- [ ] **Step 7: Add ml_blending param group and conviction param group**

In `backend/app/engine/param_groups.py`, add:

```python
def _conviction_ok(c: dict) -> bool:
    return 0 <= c["floor"] < 1.0


PARAM_GROUPS["conviction"] = {
    "params": {
        "floor": "blending.conviction.floor",
    },
    "sweep_method": "grid",
    "sweep_ranges": {
        "floor": (0.0, 0.5, 0.1),
    },
    "constraints": _conviction_ok,
    "priority": _priority_for("conviction"),
}


def _ml_blending_ok(c: dict) -> bool:
    return c["weight_max"] > c["weight_min"] >= 0


PARAM_GROUPS["ml_blending"] = {
    "params": {
        "weight_min": "blending.ml.weight_min",
        "weight_max": "blending.ml.weight_max",
    },
    "sweep_method": "grid",
    "sweep_ranges": {
        "weight_min": (0.0, 0.15, 0.05),
        "weight_max": (0.15, 0.40, 0.05),
    },
    "constraints": _ml_blending_ok,
    "priority": _priority_for("ml_blending"),
}
```

- [ ] **Step 8: Add config fields for ml_weight_min/max**

In `backend/app/config.py`, find `engine_ml_weight` and add alongside it:

```python
    engine_ml_weight_min: float = 0.05
    engine_ml_weight_max: float = 0.30
```

- [ ] **Step 9: Update main.py blend_with_ml call**

In `backend/app/main.py`, find the `blend_with_ml` call (around line 844). Replace:

```python
    blended = blend_with_ml(
        indicator_preliminary,
        ml_score,
        ml_confidence,
        ml_weight_min=settings.engine_ml_weight_min,
        ml_weight_max=settings.engine_ml_weight_max,
        ml_confidence_threshold=settings.ml_confidence_threshold,
    )
```

- [ ] **Step 10: Update backtester blend_with_ml call**

In `backend/app/engine/backtester.py`, find the `blend_with_ml` call (around line 297). Replace:

```python
        score = blend_with_ml(
            indicator_preliminary, ml_score, ml_confidence,
            ml_confidence_threshold=config.ml_confidence_threshold,
        )
```

The backtester uses config defaults which now include the ramp. No further changes needed.

- [ ] **Step 11: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -x -q`

Expected: ALL PASS

- [ ] **Step 12: Commit**

```bash
git add backend/app/engine/combiner.py backend/app/engine/constants.py backend/app/engine/param_groups.py backend/app/config.py backend/app/main.py backend/app/engine/backtester.py backend/tests/engine/test_combiner.py
git commit -m "feat(combiner): adaptive ML weight ramp, conviction + agreement param groups"
```

---

### Task 10: PipelineSettings Migration (Section 6)

**Files:**
- Modify: `backend/app/db/models.py`
- Create: Alembic migration

- [ ] **Step 1: Add new columns to PipelineSettings model**

In `backend/app/db/models.py`, find the PipelineSettings class. Add after the existing `ml_blend_weight` column:

```python
    ml_weight_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    ml_weight_max: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 2: Generate Alembic migration**

Run: `docker exec krypton-api-1 alembic revision --autogenerate -m "add ml_weight_min and ml_weight_max to pipeline_settings"`

- [ ] **Step 3: Apply migration**

Run: `docker exec krypton-api-1 alembic upgrade head`

Expected: Migration applies cleanly. New nullable columns added with NULL default.

- [ ] **Step 4: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -x -q`

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/
git commit -m "feat(db): add ml_weight_min/max columns to PipelineSettings"
```

---

### Task 11: Final Integration Verification

**Files:**
- Test: all test files

- [ ] **Step 1: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --tb=short`

Expected: ALL PASS

- [ ] **Step 2: Run backtester tests specifically**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester.py -v`

Expected: ALL PASS — backtester uses the same combiner functions with updated signatures.

- [ ] **Step 3: Verify combiner backward compatibility**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py tests/engine/test_combiner_confidence.py -v`

Expected: ALL PASS — legacy `confidence` params still work via backward-compat mapping.

- [ ] **Step 4: Verify scorer tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_liquidation_scorer.py tests/engine/test_onchain_scorer.py -v`

Expected: ALL PASS — existing tests check `confidence` key which is still present.
