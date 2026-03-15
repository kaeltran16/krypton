# Adaptive SL/TP & Performance Feedback Loop Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace static ATR multipliers (1.5/2.0/3.0) with conviction-scaled, volatility-aware levels (Phase 1) and a rolling optimizer that learns base multipliers from resolved signal outcomes (Phase 2).

**Architecture:** Phase 1 adds a pure function `scale_atr_multipliers()` that adjusts ATR multipliers based on signal strength and BB width percentile before `calculate_levels()` is called. Phase 2 introduces a `PerformanceTracker` class backed by a new `performance_tracker` DB table that stores learned multipliers per pair/timeframe bucket, runs 1D Sortino-maximizing sweeps on a rolling 100-signal window, and auto-adjusts within guardrails.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, asyncpg, pytest

**Spec:** `docs/superpowers/specs/2026-03-15-adaptive-sl-tp-and-feedback-loop-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/engine/combiner.py` | Modify | Add `scale_atr_multipliers()`, modify `calculate_levels()` to accept base defaults + return `levels_source` |
| `backend/app/engine/performance_tracker.py` | Create | `PerformanceTracker` class: get_multipliers, optimize, replay, bootstrap, Sortino |
| `backend/app/db/models.py` | Modify | Add `PerformanceTrackerRow` model |
| `backend/app/main.py` | Modify | Wire Phase 1 scaling + Phase 2 tracker into `run_pipeline()` and `check_pending_signals()`, init tracker in lifespan |
| `backend/app/api/routes.py` | Modify | Add `GET /api/engine/tuning` and `POST /api/engine/tuning/reset` |
| `backend/tests/engine/test_combiner.py` | Modify | Add tests for `scale_atr_multipliers()` and `calculate_levels()` changes |
| `backend/tests/engine/test_performance_tracker.py` | Create | Tests for tracker: Sortino, replay, optimize, get_multipliers, bootstrap |
| `backend/tests/api/test_tuning.py` | Create | API tests for tuning endpoints |
| `backend/app/engine/backtester.py` | Modify | Wire Phase 1 scaling into backtest level calculation |
| `backend/tests/engine/test_backtester.py` | Modify | Add test for Phase 1 scaling in backtests |

---

## Chunk 1: Phase 1 — Signal Strength & Volatility Scaling

### Task 1: `scale_atr_multipliers()` function

**Files:**
- Modify: `backend/app/engine/combiner.py` (add function after line 84)
- Modify: `backend/tests/engine/test_combiner.py` (add tests at end)

- [ ] **Step 1: Write failing tests for `scale_atr_multipliers`**

Add to the bottom of `backend/tests/engine/test_combiner.py`:

```python
from app.engine.combiner import scale_atr_multipliers


# ── scale_atr_multipliers ──


def test_scale_at_threshold_minimum():
    """Score exactly at threshold → t=0 → all factors = 0.8."""
    result = scale_atr_multipliers(
        score=35, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
        signal_threshold=35,
    )
    # t=0 → sl_strength=0.8, tp_strength=0.8, vol_factor=1.0 (50th pct)
    assert result["sl_strength_factor"] == 0.8
    assert result["tp_strength_factor"] == 0.8
    assert result["vol_factor"] == 1.0
    assert round(result["sl_atr"], 4) == round(1.5 * 0.8 * 1.0, 4)
    assert round(result["tp1_atr"], 4) == round(2.0 * 0.8 * 1.0, 4)
    assert round(result["tp2_atr"], 4) == round(3.0 * 0.8 * 1.0, 4)


def test_scale_at_max_score():
    """Score=100 → t=1.0 → sl_strength=1.2, tp_strength=1.4."""
    result = scale_atr_multipliers(
        score=100, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
        signal_threshold=35,
    )
    assert result["sl_strength_factor"] == 1.2
    assert result["tp_strength_factor"] == 1.4
    assert result["vol_factor"] == 1.0


def test_scale_negative_score_uses_abs():
    """Negative score uses abs(score) for t calculation."""
    pos = scale_atr_multipliers(
        score=65, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    neg = scale_atr_multipliers(
        score=-65, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    assert pos["sl_strength_factor"] == neg["sl_strength_factor"]
    assert pos["tp_strength_factor"] == neg["tp_strength_factor"]


def test_scale_volatility_squeeze():
    """Low BB width pct → vol_factor < 1.0 (tighter levels)."""
    result = scale_atr_multipliers(
        score=50, bb_width_pct=10.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    assert result["vol_factor"] == 0.8
    assert result["vol_factor"] < 1.0


def test_scale_volatility_expansion():
    """High BB width pct → vol_factor > 1.0 (wider levels)."""
    result = scale_atr_multipliers(
        score=50, bb_width_pct=90.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    assert result["vol_factor"] > 1.0


def test_scale_combined_effect():
    """Strong signal + high vol → levels significantly wider."""
    result = scale_atr_multipliers(
        score=80, bb_width_pct=80.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
        signal_threshold=35,
    )
    # Should be noticeably larger than base
    assert result["sl_atr"] > 1.5
    assert result["tp1_atr"] > 2.0
    assert result["tp2_atr"] > 3.0
    # TP strength scales faster than SL strength
    tp_ratio = result["tp1_atr"] / 2.0
    sl_ratio = result["sl_atr"] / 1.5
    assert tp_ratio > sl_ratio


def test_scale_returns_all_keys():
    """Return dict has all expected keys."""
    result = scale_atr_multipliers(
        score=50, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    expected_keys = {"sl_atr", "tp1_atr", "tp2_atr", "sl_strength_factor", "tp_strength_factor", "vol_factor"}
    assert set(result.keys()) == expected_keys


def test_scale_below_threshold_clamps_to_zero():
    """Score below threshold → t clamped to 0 → factors = 0.8."""
    result = scale_atr_multipliers(
        score=20, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
        signal_threshold=35,
    )
    assert result["sl_strength_factor"] == 0.8
    assert result["tp_strength_factor"] == 0.8


def test_scale_threshold_100_no_division_by_zero():
    """signal_threshold=100 → t=0, no crash."""
    result = scale_atr_multipliers(
        score=100, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
        signal_threshold=100,
    )
    assert result["sl_strength_factor"] == 0.8
    assert result["tp_strength_factor"] == 0.8


def test_scale_bb_width_pct_clamped_high():
    """bb_width_pct > 100 is clamped to 100 → vol_factor caps at 1.25."""
    result = scale_atr_multipliers(
        score=50, bb_width_pct=150.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    assert result["vol_factor"] == 1.25


def test_scale_bb_width_pct_clamped_low():
    """bb_width_pct < 0 is clamped to 0 → vol_factor floors at 0.75."""
    result = scale_atr_multipliers(
        score=50, bb_width_pct=-10.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
    )
    assert result["vol_factor"] == 0.75
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py::test_scale_at_threshold_minimum -v`

Expected: FAIL — `ImportError: cannot import name 'scale_atr_multipliers'`

- [ ] **Step 3: Implement `scale_atr_multipliers` in combiner.py**

Add before `calculate_levels()` (after `_validate_llm_levels`, line 85) in `backend/app/engine/combiner.py`:

```python
def scale_atr_multipliers(
    score: int,
    bb_width_pct: float,
    sl_base: float,
    tp1_base: float,
    tp2_base: float,
    signal_threshold: int = 35,
) -> dict:
    """Apply signal strength + volatility regime scaling to ATR multipliers.

    Returns dict with effective multipliers and individual scaling factors
    for auditability.
    """
    if signal_threshold >= 100:
        t = 0.0
    else:
        t = (abs(score) - signal_threshold) / (100 - signal_threshold)
        t = max(0.0, min(1.0, t))

    sl_strength = 0.8 + (1.2 - 0.8) * t
    tp_strength = 0.8 + (1.4 - 0.8) * t

    bb_width_pct = max(0.0, min(100.0, bb_width_pct))
    vol_factor = 0.75 + (1.25 - 0.75) * (bb_width_pct / 100)

    return {
        "sl_atr": sl_base * sl_strength * vol_factor,
        "tp1_atr": tp1_base * tp_strength * vol_factor,
        "tp2_atr": tp2_base * tp_strength * vol_factor,
        "sl_strength_factor": round(sl_strength, 4),
        "tp_strength_factor": round(tp_strength, 4),
        "vol_factor": round(vol_factor, 4),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -k "scale" -v`

Expected: all 9 `test_scale_*` tests PASS

- [ ] **Step 5: Run full combiner test suite for regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -v`

Expected: all tests PASS (no regressions — new function, no existing code changed)

---

### Task 2: Enhance `calculate_levels()` — accept base defaults + return `levels_source`

**Files:**
- Modify: `backend/app/engine/combiner.py:87-146`
- Modify: `backend/tests/engine/test_combiner.py` (add tests)

- [ ] **Step 1: Write failing tests for new `calculate_levels` behavior**

Add to `backend/tests/engine/test_combiner.py`:

```python
# ── calculate_levels enhancements ──


def test_levels_source_atr_default():
    """Path 3 returns levels_source='atr_default'."""
    result = calculate_levels("LONG", 50000.0, 500.0)
    assert result["levels_source"] == "atr_default"


def test_levels_source_ml():
    """Path 2 returns levels_source='ml'."""
    result = calculate_levels(
        "LONG", 50000.0, 500.0,
        ml_atr_multiples={"sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0},
    )
    assert result["levels_source"] == "ml"


def test_levels_source_llm():
    """Path 1 returns levels_source='llm'."""
    llm = {"entry": 50000.0, "stop_loss": 49000.0, "take_profit_1": 51000.0, "take_profit_2": 52000.0}
    result = calculate_levels("LONG", 50000.0, 500.0, llm_levels=llm)
    assert result["levels_source"] == "llm"


def test_custom_atr_defaults():
    """Path 3 uses provided defaults instead of hardcoded 1.5/2.0/3.0."""
    result = calculate_levels(
        "LONG", 50000.0, 500.0,
        sl_atr_default=2.0, tp1_atr_default=3.0, tp2_atr_default=5.0,
    )
    assert result["stop_loss"] == 50000.0 - 2.0 * 500.0
    assert result["take_profit_1"] == 50000.0 + 3.0 * 500.0
    assert result["take_profit_2"] == 50000.0 + 5.0 * 500.0


def test_atr_defaults_clamped_to_bounds():
    """Path 3 clamps provided defaults to sl_bounds/tp limits."""
    result = calculate_levels(
        "LONG", 50000.0, 500.0,
        sl_atr_default=5.0,  # exceeds sl_bounds max (3.0)
        tp1_atr_default=0.5,  # below tp1_min_atr (1.0)
        tp2_atr_default=10.0,  # exceeds tp2_max_atr (8.0)
    )
    # SL clamped to 3.0
    assert result["stop_loss"] == 50000.0 - 3.0 * 500.0
    # TP1 clamped to 1.0
    assert result["take_profit_1"] == 50000.0 + 1.0 * 500.0
    # TP2 clamped to 8.0
    assert result["take_profit_2"] == 50000.0 + 8.0 * 500.0


def test_atr_defaults_rr_floor_enforced():
    """Path 3 enforces R:R floor on provided defaults."""
    result = calculate_levels(
        "LONG", 50000.0, 500.0,
        sl_atr_default=2.5,
        tp1_atr_default=1.5,  # TP1/SL = 0.6 < rr_floor(1.0)
        tp2_atr_default=4.0,
        rr_floor=1.0,
    )
    # TP1 should be bumped to sl * rr_floor = 2.5
    assert result["take_profit_1"] == 50000.0 + 2.5 * 500.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py::test_levels_source_atr_default -v`

Expected: FAIL — `KeyError: 'levels_source'`

- [ ] **Step 3: Modify `calculate_levels` in combiner.py**

Change the function signature (line 87) to add three new parameters:

```python
def calculate_levels(
    direction: str,
    current_price: float,
    atr: float,
    llm_levels: dict | None = None,
    ml_atr_multiples: dict | None = None,
    llm_opinion: str | None = None,
    sl_bounds: tuple[float, float] = (0.5, 3.0),
    tp1_min_atr: float = 1.0,
    tp2_max_atr: float = 8.0,
    rr_floor: float = 1.0,
    caution_sl_factor: float = 0.8,
    sl_atr_default: float = 1.5,
    tp1_atr_default: float = 2.0,
    tp2_atr_default: float = 3.0,
) -> dict:
```

Change Path 1 return (line 102) to include `levels_source`:

```python
    if llm_levels and _validate_llm_levels(direction, llm_levels):
        return {**llm_levels, "levels_source": "llm"}
```

**Note:** The existing test `test_calculate_levels_llm_override` asserts `levels == llm_levels` with exact dict equality. This will break because the return now has an extra `levels_source` key. Update that test assertion to:
```python
assert levels == {**llm_levels, "levels_source": "llm"}
```

Add `levels_source` tracking to Path 2 — after line 128, before the `else`:

```python
        levels_source = "ml"
```

Replace Path 3 (lines 130-138) with clamped defaults:

```python
    else:
        # Priority 3: ATR defaults (may be Phase 2 learned values)
        sl_atr = max(sl_bounds[0], min(sl_atr_default, sl_bounds[1]))
        tp1_atr = max(tp1_min_atr, tp1_atr_default)
        tp2_atr = max(tp1_atr * 1.2, tp2_atr_default)
        tp2_atr = min(tp2_max_atr, tp2_atr)

        if sl_atr > 0 and tp1_atr / sl_atr < rr_floor:
            tp1_atr = sl_atr * rr_floor

        if llm_opinion == "caution":
            sl_atr = sl_atr * caution_sl_factor

        levels_source = "atr_default"
```

Change the return (line 141) to include `levels_source`:

```python
    sign = 1 if direction == "LONG" else -1
    return {
        "entry": current_price,
        "stop_loss": current_price - sign * sl_atr * atr,
        "take_profit_1": current_price + sign * tp1_atr * atr,
        "take_profit_2": current_price + sign * tp2_atr * atr,
        "levels_source": levels_source,
    }
```

- [ ] **Step 4: Run all combiner tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -v`

Expected: all tests PASS. Existing tests still pass because they don't assert on `levels_source` key.

---

### Task 3: Wire Phase 1 scaling into `run_pipeline()`

**Files:**
- Modify: `backend/app/main.py:489-539`

- [ ] **Step 1: Add import for `scale_atr_multipliers`**

In `backend/app/main.py` line 35, update the combiner import:

```python
from app.engine.combiner import compute_preliminary_score, compute_final_score, calculate_levels, blend_with_ml, compute_agreement, scale_atr_multipliers
```

- [ ] **Step 2: Add Phase 1 scaling before `calculate_levels()` call**

Between the `atr` extraction (line 490) and the `ml_atr_multiples` block (line 496), insert the scaling code. The full block from line 489 to the `calculate_levels` call becomes:

```python
    # ── Step 9: Calculate levels ──
    atr = tech_result["indicators"].get("atr", 200)
    bb_width_pct = tech_result["indicators"].get("bb_width_pct", 50.0)

    # Phase 1: signal strength + volatility scaling
    # Phase 2 learned base multipliers are fetched from tracker if available,
    # otherwise defaults (1.5/2.0/3.0) are used.
    sl_base, tp1_base, tp2_base = 1.5, 2.0, 3.0
    tracker = getattr(app.state, "tracker", None)
    if tracker is not None:
        sl_base, tp1_base, tp2_base = await tracker.get_multipliers(pair, timeframe)

    scaled = scale_atr_multipliers(
        score=final, bb_width_pct=bb_width_pct,
        sl_base=sl_base, tp1_base=tp1_base, tp2_base=tp2_base,
        signal_threshold=settings.engine_signal_threshold,
    )

    llm_levels = None
    if llm_response and llm_response.opinion != "contradict" and llm_response.levels:
        llm_levels = llm_response.levels.model_dump()

    ml_atr_multiples = None
    if (
        ml_available
        and ml_prediction
        and ml_confidence is not None
        and ml_confidence >= settings.ml_confidence_threshold
    ):
        # Phase 1 scaling applies to ML multiples too
        ml_atr_multiples = {
            "sl_atr": ml_prediction["sl_atr"] * scaled["sl_strength_factor"] * scaled["vol_factor"],
            "tp1_atr": ml_prediction["tp1_atr"] * scaled["tp_strength_factor"] * scaled["vol_factor"],
            "tp2_atr": ml_prediction["tp2_atr"] * scaled["tp_strength_factor"] * scaled["vol_factor"],
        }

    levels = calculate_levels(
        direction=direction,
        current_price=float(candle["close"]),
        atr=atr,
        llm_levels=llm_levels,
        ml_atr_multiples=ml_atr_multiples,
        llm_opinion=llm_opinion,
        sl_bounds=(settings.ml_sl_min_atr, settings.ml_sl_max_atr),
        tp1_min_atr=settings.ml_tp1_min_atr,
        tp2_max_atr=settings.ml_tp2_max_atr,
        rr_floor=settings.ml_rr_floor,
        caution_sl_factor=settings.llm_caution_sl_factor,
        sl_atr_default=scaled["sl_atr"],
        tp1_atr_default=scaled["tp1_atr"],
        tp2_atr_default=scaled["tp2_atr"],
    )
```

- [ ] **Step 3: Store scaling factors + levels_source in raw_indicators**

Modify the `raw_indicators` dict construction (lines 533-539) to include Phase 1 data:

```python
        "raw_indicators": {
            **tech_result["indicators"],
            "ml_score": ml_score,
            "ml_confidence": ml_confidence,
            "blended_score": blended,
            "indicator_preliminary": indicator_preliminary,
            "effective_sl_atr": scaled["sl_atr"],
            "effective_tp1_atr": scaled["tp1_atr"],
            "effective_tp2_atr": scaled["tp2_atr"],
            "sl_strength_factor": scaled["sl_strength_factor"],
            "tp_strength_factor": scaled["tp_strength_factor"],
            "vol_factor": scaled["vol_factor"],
            "levels_source": levels["levels_source"],
        },
```

- [ ] **Step 4: Run the pipeline test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/test_pipeline.py tests/test_pipeline_ml.py -v`

Expected: PASS. Note: `scale_atr_multipliers` will produce different effective values than the old hardcoded 1.5/2.0/3.0 (e.g., at threshold score with bb_width_pct=50, strength factor is 0.8x). This is fine because existing pipeline tests only check for key existence (`"stop_loss" in levels`), not specific price values. If any test does assert on specific SL/TP prices, update those assertions to account for Phase 1 scaling.

---

## Chunk 2: Phase 2 Foundation — Model, Tracker Core, Replay

### Task 4: `PerformanceTrackerRow` DB model + Alembic migration

**Files:**
- Modify: `backend/app/db/models.py` (add model at end)
- Create: Alembic migration (auto-generated)

- [ ] **Step 1: Add `PerformanceTrackerRow` model**

Add at the bottom of `backend/app/db/models.py` (after `AlertSettings`):

```python
class PerformanceTrackerRow(Base):
    __tablename__ = "performance_tracker"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    current_sl_atr: Mapped[float] = mapped_column(Float, nullable=False, default=1.5)
    current_tp1_atr: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    current_tp2_atr: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    last_optimized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_optimized_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("pair", "timeframe", name="uq_tracker_pair_timeframe"),
    )
```

- [ ] **Step 2: Generate Alembic migration**

Run: `docker exec krypton-api-1 alembic revision --autogenerate -m "add performance_tracker table"`

Expected: new migration file created in `backend/app/db/migrations/versions/`

- [ ] **Step 3: Apply migration**

Run: `docker exec krypton-api-1 alembic upgrade head`

Expected: migration applies cleanly

- [ ] **Step 4: Verify model in test**

Run: `docker exec krypton-api-1 python -m pytest tests/test_db_models.py -v`

Expected: PASS (existing model tests unaffected)

---

### Task 5: `PerformanceTracker` — core methods (get_multipliers, resolved count)

**Files:**
- Create: `backend/app/engine/performance_tracker.py`
- Create: `backend/tests/engine/test_performance_tracker.py`

- [ ] **Step 1: Write failing tests for `get_multipliers` and `_get_resolved_count`**

Create `backend/tests/engine/test_performance_tracker.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.engine.performance_tracker import PerformanceTracker


@pytest.fixture
def mock_session_factory():
    """Create a mock async session factory."""
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


@pytest.mark.asyncio
async def test_get_multipliers_returns_defaults_when_no_row(mock_session_factory):
    factory, session = mock_session_factory
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    tracker = PerformanceTracker(factory)
    result = await tracker.get_multipliers("BTC-USDT-SWAP", "1h")

    assert result == (1.5, 2.0, 3.0)


@pytest.mark.asyncio
async def test_get_multipliers_returns_learned_values(mock_session_factory):
    factory, session = mock_session_factory
    row = MagicMock()
    row.current_sl_atr = 1.8
    row.current_tp1_atr = 2.5
    row.current_tp2_atr = 4.0
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = row

    tracker = PerformanceTracker(factory)
    result = await tracker.get_multipliers("BTC-USDT-SWAP", "1h")

    assert result == (1.8, 2.5, 4.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.engine.performance_tracker'`

- [ ] **Step 3: Implement PerformanceTracker skeleton with get_multipliers**

Create `backend/app/engine/performance_tracker.py`:

```python
import asyncio
import bisect
import logging
import statistics
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import BacktestRun, Candle, PerformanceTrackerRow, Signal
from app.engine.outcome_resolver import resolve_signal_outcome

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_SL = 1.5
DEFAULT_TP1 = 2.0
DEFAULT_TP2 = 3.0

# Optimization parameters
MIN_SIGNALS = 40
WINDOW_SIZE = 100
TRIGGER_INTERVAL = 10

# Guardrails
SL_RANGE = (0.8, 2.5)
TP1_RANGE = (1.0, 4.0)
TP2_RANGE = (2.0, 6.0)
MAX_SL_ADJ = 0.3
MAX_TP_ADJ = 0.5


class PerformanceTracker:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self._tasks: set[asyncio.Task] = set()

    async def get_multipliers(self, pair: str, timeframe: str) -> tuple[float, float, float]:
        """Return learned (sl, tp1, tp2) multipliers, or defaults if no row exists."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(PerformanceTrackerRow).where(
                    PerformanceTrackerRow.pair == pair,
                    PerformanceTrackerRow.timeframe == timeframe,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return (DEFAULT_SL, DEFAULT_TP1, DEFAULT_TP2)
            return (row.current_sl_atr, row.current_tp1_atr, row.current_tp2_atr)

    async def _get_resolved_count(self, session, pair: str, timeframe: str) -> int:
        """Count resolved signals excluding LLM-leveled ones (NULL treated as atr_default)."""
        result = await session.execute(
            select(func.count(Signal.id)).where(
                Signal.pair == pair,
                Signal.timeframe == timeframe,
                Signal.outcome != "PENDING",
                func.coalesce(
                    Signal.raw_indicators["levels_source"].astext, "atr_default"
                ) != "llm",
            )
        )
        return result.scalar_one()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py -v`

Expected: PASS

---

### Task 6: Sortino helper + replay logic

**Files:**
- Modify: `backend/app/engine/performance_tracker.py` (add static methods)
- Modify: `backend/tests/engine/test_performance_tracker.py` (add tests)

- [ ] **Step 1: Write failing tests for `compute_sortino`**

Add to `backend/tests/engine/test_performance_tracker.py`:

```python
from app.engine.performance_tracker import PerformanceTracker


# ── compute_sortino ──


def test_sortino_normal():
    """Standard Sortino with mix of wins and losses."""
    pnls = [2.0, -1.0, 3.0, -0.5, 1.5]
    result = PerformanceTracker.compute_sortino(pnls)
    assert result is not None
    assert result > 0


def test_sortino_all_winners():
    """All wins → no downside deviation → return inf."""
    pnls = [1.0, 2.0, 3.0, 1.5]
    result = PerformanceTracker.compute_sortino(pnls)
    assert result == float("inf")


def test_sortino_all_losers():
    """All losses → negative Sortino."""
    pnls = [-1.0, -2.0, -0.5]
    result = PerformanceTracker.compute_sortino(pnls)
    assert result is not None
    assert result < 0


def test_sortino_single_loss():
    """One loss → uses abs(loss) as downside deviation."""
    pnls = [2.0, 3.0, -1.0, 1.5]
    result = PerformanceTracker.compute_sortino(pnls)
    mean_r = statistics.mean(pnls)
    expected = mean_r / abs(-1.0)
    assert abs(result - expected) < 0.01


def test_sortino_empty():
    """Empty pnls → None."""
    assert PerformanceTracker.compute_sortino([]) is None
```

- [ ] **Step 2: Write failing tests for `replay_signal`**

Add to the same test file:

```python
from datetime import datetime, timezone


# ── replay_signal ──


def test_replay_long_tp1_hit():
    """Replay LONG signal where TP1 is hit."""
    candles = [
        {"high": 51500.0, "low": 50500.0, "timestamp": datetime(2025, 1, 1, 1, tzinfo=timezone.utc)},
    ]
    result = PerformanceTracker.replay_signal(
        direction="LONG", entry=50000.0, atr=500.0,
        sl_atr=1.5, tp1_atr=2.0, tp2_atr=3.0,
        candles=candles, created_at=datetime(2025, 1, 1, 0, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result["outcome"] == "TP1_HIT"
    assert result["outcome_pnl_pct"] > 0


def test_replay_long_sl_hit():
    """Replay LONG signal where SL is hit."""
    candles = [
        {"high": 50100.0, "low": 49200.0, "timestamp": datetime(2025, 1, 1, 1, tzinfo=timezone.utc)},
    ]
    result = PerformanceTracker.replay_signal(
        direction="LONG", entry=50000.0, atr=500.0,
        sl_atr=1.5, tp1_atr=2.0, tp2_atr=3.0,
        candles=candles, created_at=datetime(2025, 1, 1, 0, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result["outcome"] == "SL_HIT"
    assert result["outcome_pnl_pct"] < 0


def test_replay_no_hit():
    """No candle triggers any level → returns None (expired)."""
    candles = [
        {"high": 50500.0, "low": 49800.0, "timestamp": datetime(2025, 1, 1, 1, tzinfo=timezone.utc)},
    ]
    result = PerformanceTracker.replay_signal(
        direction="LONG", entry=50000.0, atr=500.0,
        sl_atr=1.5, tp1_atr=2.0, tp2_atr=3.0,
        candles=candles, created_at=datetime(2025, 1, 1, 0, tzinfo=timezone.utc),
    )
    assert result is None


def test_replay_short_tp2_hit():
    """Replay SHORT signal where TP2 is hit."""
    candles = [
        {"high": 50100.0, "low": 48400.0, "timestamp": datetime(2025, 1, 1, 1, tzinfo=timezone.utc)},
    ]
    result = PerformanceTracker.replay_signal(
        direction="SHORT", entry=50000.0, atr=500.0,
        sl_atr=1.5, tp1_atr=2.0, tp2_atr=3.0,
        candles=candles, created_at=datetime(2025, 1, 1, 0, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result["outcome"] == "TP2_HIT"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py -k "sortino or replay" -v`

Expected: FAIL — `AttributeError: type object 'PerformanceTracker' has no attribute 'compute_sortino'`

- [ ] **Step 4: Implement `compute_sortino` and `replay_signal`**

Add to `PerformanceTracker` class in `backend/app/engine/performance_tracker.py`:

```python
    @staticmethod
    def compute_sortino(pnls: list[float]) -> float | None:
        """Compute Sortino ratio from a list of PnL percentages.

        Edge cases per spec:
        - All winners (no downside): return inf
        - Single loss: use abs(loss) as downside deviation
        - Empty: return None
        """
        if not pnls:
            return None
        downside = [p for p in pnls if p < 0]
        if not downside:
            return float("inf")
        mean_r = statistics.mean(pnls)
        downside_std = (
            statistics.stdev(downside) if len(downside) > 1 else abs(downside[0])
        )
        if downside_std == 0:
            return None
        return mean_r / downside_std

    @staticmethod
    def replay_signal(
        direction: str,
        entry: float,
        atr: float,
        sl_atr: float,
        tp1_atr: float,
        tp2_atr: float,
        candles: list[dict],
        created_at: datetime,
    ) -> dict | None:
        """Replay a signal with given ATR multipliers against candle data.

        Constructs price levels from multipliers, then delegates to
        resolve_signal_outcome for deterministic replay.
        Returns outcome dict or None if no level hit (expired).
        """
        sign = 1 if direction == "LONG" else -1
        signal_dict = {
            "direction": direction,
            "entry": entry,
            "stop_loss": entry - sign * sl_atr * atr,
            "take_profit_1": entry + sign * tp1_atr * atr,
            "take_profit_2": entry + sign * tp2_atr * atr,
            "created_at": created_at,
        }
        return resolve_signal_outcome(signal_dict, candles)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py -v`

Expected: all tests PASS

---

### Task 7: `optimize()` with guardrails

**Files:**
- Modify: `backend/app/engine/performance_tracker.py`
- Modify: `backend/tests/engine/test_performance_tracker.py`

- [ ] **Step 1: Write failing tests for `_sweep_dimension` and `_apply_guardrails`**

Add to `backend/tests/engine/test_performance_tracker.py`:

```python
from app.engine.performance_tracker import (
    PerformanceTracker, DEFAULT_SL, DEFAULT_TP1, DEFAULT_TP2,
    SL_RANGE, TP1_RANGE, TP2_RANGE, MAX_SL_ADJ, MAX_TP_ADJ,
)


# ── _apply_guardrails ──


def test_guardrails_no_change():
    """No change needed when new value is within bounds and adjustment limit."""
    result = PerformanceTracker._apply_guardrails(
        old=1.5, new=1.7, bounds=SL_RANGE, max_adj=MAX_SL_ADJ,
    )
    assert result == 1.7


def test_guardrails_clamps_to_bounds():
    """Value outside absolute bounds gets clamped."""
    result = PerformanceTracker._apply_guardrails(
        old=1.5, new=0.5, bounds=SL_RANGE, max_adj=MAX_SL_ADJ,
    )
    assert result == SL_RANGE[0]  # 0.8


def test_guardrails_clamps_to_max_adjustment():
    """Large change gets limited to max_adj per cycle."""
    result = PerformanceTracker._apply_guardrails(
        old=1.5, new=2.5, bounds=SL_RANGE, max_adj=MAX_SL_ADJ,
    )
    assert result == 1.5 + MAX_SL_ADJ  # 1.8


def test_guardrails_clamps_negative_adjustment():
    """Large downward change gets limited to max_adj per cycle."""
    result = PerformanceTracker._apply_guardrails(
        old=2.0, new=1.0, bounds=SL_RANGE, max_adj=MAX_SL_ADJ,
    )
    assert result == 2.0 - MAX_SL_ADJ  # 1.7


# ── _sweep_dimension ──


def _make_signal_data(
    direction="LONG", entry=50000.0, atr=500.0,
    sl_eff=1.5, tp1_eff=2.0, tp2_eff=3.0,
    sl_strength=1.0, tp_strength=1.0, vol_factor=1.0,
    created_at=None, outcome_at=None, outcome="TP1_HIT",
):
    """Helper to build a signal data dict for sweep tests."""
    from datetime import timedelta
    if created_at is None:
        created_at = datetime(2025, 1, 1, 0, tzinfo=timezone.utc)
    if outcome_at is None:
        outcome_at = created_at + timedelta(hours=4)
    return {
        "direction": direction, "entry": entry, "atr": atr,
        "effective_sl_atr": sl_eff, "effective_tp1_atr": tp1_eff,
        "effective_tp2_atr": tp2_eff,
        "sl_strength_factor": sl_strength, "tp_strength_factor": tp_strength,
        "vol_factor": vol_factor,
        "created_at": created_at, "outcome_at": outcome_at,
        "outcome": outcome,
    }


def test_sweep_returns_best_candidate():
    """Sweep picks candidate that maximizes Sortino."""
    # Create a simple scenario: 2 signals, candles that make tighter SL better
    t0 = datetime(2025, 1, 1, 0, tzinfo=timezone.utc)
    t1 = datetime(2025, 1, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2025, 1, 1, 4, tzinfo=timezone.utc)

    signals = [
        _make_signal_data(created_at=t0, outcome_at=t2, outcome="TP1_HIT"),
        _make_signal_data(created_at=t0, outcome_at=t2, outcome="SL_HIT"),
    ]
    # Candle that hits TP1 (entry+2*atr = 51000) and barely misses tight SL
    candles_map = {
        0: [{"high": 51100.0, "low": 49900.0, "timestamp": t1}],
        1: [{"high": 50200.0, "low": 49200.0, "timestamp": t1}],
    }
    # Sweep SL: tighter SL should improve Sortino by reducing the loss magnitude
    best, best_sortino = PerformanceTracker._sweep_dimension(
        signals_data=signals,
        candles_map=candles_map,
        dimension="sl",
        candidates=[0.8, 1.0, 1.2, 1.5, 2.0],
    )
    assert best is not None
    assert isinstance(best_sortino, (float, int))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py -k "guardrails or sweep" -v`

Expected: FAIL — `AttributeError: type object 'PerformanceTracker' has no attribute '_apply_guardrails'`

- [ ] **Step 3: Implement `_apply_guardrails`, `_sweep_dimension`, and `optimize`**

Add to `PerformanceTracker` class in `backend/app/engine/performance_tracker.py`:

```python
    @staticmethod
    def _apply_guardrails(old: float, new: float, bounds: tuple[float, float], max_adj: float) -> float:
        """Clamp new value to absolute bounds and max per-cycle adjustment."""
        clamped = max(bounds[0], min(new, bounds[1]))
        delta = clamped - old
        if abs(delta) > max_adj:
            clamped = old + max_adj * (1 if delta > 0 else -1)
        return round(clamped, 2)

    @staticmethod
    def _sweep_dimension(
        signals_data: list[dict],
        candles_map: dict[int, list[dict]],
        dimension: str,
        candidates: list[float],
    ) -> tuple[float | None, float | None]:
        """Sweep one dimension across candidates, return (best_value, best_sortino).

        For the swept dimension, computes candidate_base * strength * vol_factor.
        For other dimensions, uses stored effective values as-is.
        This intentionally evaluates "what if we changed X while keeping Y and Z
        exactly as deployed?" — the correct counterfactual for 1D optimization.
        """
        best_val = None
        best_sortino = None

        for candidate in candidates:
            pnls = []
            for idx, sig in enumerate(signals_data):
                candles = candles_map.get(idx, [])
                if not candles:
                    continue  # skip signals with no candle data

                # For the swept dimension: candidate * strength * vol
                # For other dimensions: use stored effective values
                if dimension == "sl":
                    sl = candidate * sig["sl_strength_factor"] * sig["vol_factor"]
                    tp1 = sig["effective_tp1_atr"]
                    tp2 = sig["effective_tp2_atr"]
                elif dimension == "tp1":
                    sl = sig["effective_sl_atr"]
                    tp1 = candidate * sig["tp_strength_factor"] * sig["vol_factor"]
                    tp2 = sig["effective_tp2_atr"]
                else:  # tp2
                    sl = sig["effective_sl_atr"]
                    tp1 = sig["effective_tp1_atr"]
                    tp2 = candidate * sig["tp_strength_factor"] * sig["vol_factor"]

                result = PerformanceTracker.replay_signal(
                    direction=sig["direction"],
                    entry=sig["entry"],
                    atr=sig["atr"],
                    sl_atr=sl, tp1_atr=tp1, tp2_atr=tp2,
                    candles=candles,
                    created_at=sig["created_at"],
                )
                if result is None:
                    continue  # no level hit (expired) — exclude from Sortino
                pnls.append(result["outcome_pnl_pct"])

            sortino = PerformanceTracker.compute_sortino(pnls)
            if sortino is None:
                continue
            if best_sortino is None or sortino > best_sortino:
                best_sortino = sortino
                best_val = candidate

        return best_val, best_sortino

    async def optimize(self, pair: str, timeframe: str):
        """Run 1D optimization for each multiplier dimension.

        Fetches the rolling window of resolved signals, batch-loads candles,
        validates data integrity, sweeps candidates, and applies guardrailed updates.
        """
        async with self.session_factory() as session:
            # Fetch tracker row
            result = await session.execute(
                select(PerformanceTrackerRow).where(
                    PerformanceTrackerRow.pair == pair,
                    PerformanceTrackerRow.timeframe == timeframe,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return

            # Fetch last N resolved signals (excluding LLM)
            sig_result = await session.execute(
                select(Signal)
                .where(
                    Signal.pair == pair,
                    Signal.timeframe == timeframe,
                    Signal.outcome != "PENDING",
                    func.coalesce(
                        Signal.raw_indicators["levels_source"].astext, "atr_default"
                    ) != "llm",
                )
                .order_by(Signal.created_at.desc())
                .limit(WINDOW_SIZE)
            )
            signals = sig_result.scalars().all()

            if len(signals) < MIN_SIGNALS:
                return

            # Batch fetch candles for the entire time range
            min_created = min(s.created_at for s in signals)
            max_outcome = max(
                s.outcome_at for s in signals if s.outcome_at is not None
            )
            candle_result = await session.execute(
                select(Candle)
                .where(
                    Candle.pair == pair,
                    Candle.timeframe == timeframe,
                    Candle.timestamp > min_created,
                    Candle.timestamp <= max_outcome,
                )
                .order_by(Candle.timestamp)
            )
            all_candles = candle_result.scalars().all()

            # Pre-build sorted candle dicts + timestamp index for bisect slicing
            candle_dicts = [
                {"high": float(c.high), "low": float(c.low), "timestamp": c.timestamp}
                for c in all_candles
            ]
            candle_timestamps = [c["timestamp"] for c in candle_dicts]

            # Build per-signal candle lists + signal data dicts
            signals_data = []
            candles_map = {}
            valid_idx = 0

            for signal in signals:
                if signal.outcome_at is None:
                    continue

                indicators = signal.raw_indicators or {}
                atr = indicators.get("atr")
                if atr is None or atr == 0:
                    continue

                entry = float(signal.entry)

                # Bisect for O(log N) candle slicing instead of O(N) linear scan
                lo = bisect.bisect_right(candle_timestamps, signal.created_at)
                hi = bisect.bisect_right(candle_timestamps, signal.outcome_at)
                sig_candles = candle_dicts[lo:hi]

                # Data integrity check: replay with stored levels must match stored outcome.
                # If candles are incomplete, skip this signal.
                integrity_result = resolve_signal_outcome(
                    {
                        "direction": signal.direction,
                        "entry": entry,
                        "stop_loss": float(signal.stop_loss),
                        "take_profit_1": float(signal.take_profit_1),
                        "take_profit_2": float(signal.take_profit_2),
                        "created_at": signal.created_at,
                    },
                    sig_candles,
                )
                actual_outcome = signal.outcome
                replayed_outcome = integrity_result["outcome"] if integrity_result else "EXPIRED"
                if replayed_outcome != actual_outcome:
                    continue

                # Extract Phase 1 factors (legacy signals without them use 1.0)
                sl_strength = indicators.get("sl_strength_factor", 1.0)
                tp_strength = indicators.get("tp_strength_factor", 1.0)
                vol_factor = indicators.get("vol_factor", 1.0)

                # Effective multipliers: stored if available, else back-derive from prices
                effective_sl = indicators.get("effective_sl_atr")
                effective_tp1 = indicators.get("effective_tp1_atr")
                effective_tp2 = indicators.get("effective_tp2_atr")
                if effective_sl is None:
                    effective_sl = abs(entry - float(signal.stop_loss)) / atr
                    effective_tp1 = abs(float(signal.take_profit_1) - entry) / atr
                    effective_tp2 = abs(float(signal.take_profit_2) - entry) / atr

                signals_data.append({
                    "direction": signal.direction,
                    "entry": entry,
                    "atr": atr,
                    "effective_sl_atr": effective_sl,
                    "effective_tp1_atr": effective_tp1,
                    "effective_tp2_atr": effective_tp2,
                    "sl_strength_factor": sl_strength,
                    "tp_strength_factor": tp_strength,
                    "vol_factor": vol_factor,
                    "created_at": signal.created_at,
                    "outcome_at": signal.outcome_at,
                    "outcome": signal.outcome,
                })
                candles_map[valid_idx] = sig_candles
                valid_idx += 1

            if len(signals_data) < MIN_SIGNALS:
                logger.info(
                    "Optimization skipped for %s/%s: only %d valid signals (need %d)",
                    pair, timeframe, len(signals_data), MIN_SIGNALS,
                )
                return

            # Sweep each dimension independently
            # Include current value in candidates so sweep can select "keep current"
            sl_candidates = [round(x * 0.1, 1) for x in range(8, 26, 2)] + [2.5]  # 0.8 to 2.5
            tp1_candidates = [round(x * 0.1, 1) for x in range(10, 41, 5)]  # 1.0 to 4.0 step 0.5
            tp2_candidates = [round(x * 0.1, 1) for x in range(20, 61, 5)]  # 2.0 to 6.0 step 0.5

            current_sl = row.current_sl_atr
            current_tp1 = row.current_tp1_atr
            current_tp2 = row.current_tp2_atr

            adjustments = []

            for dim, candidates, current, bounds, max_adj in [
                ("sl", sl_candidates, current_sl, SL_RANGE, MAX_SL_ADJ),
                ("tp1", tp1_candidates, current_tp1, TP1_RANGE, MAX_TP_ADJ),
                ("tp2", tp2_candidates, current_tp2, TP2_RANGE, MAX_TP_ADJ),
            ]:
                # Ensure current value is in candidate list for fair comparison
                if round(current, 1) not in candidates:
                    candidates = sorted(candidates + [round(current, 1)])

                best_val, best_sortino = self._sweep_dimension(
                    signals_data, candles_map, dim, candidates,
                )
                if best_val is None or round(best_val, 2) == round(current, 2):
                    continue
                # Only apply if best candidate actually improves over current
                _, current_sortino = self._sweep_dimension(
                    signals_data, candles_map, dim, [round(current, 1)],
                )
                if current_sortino is not None and best_sortino is not None and best_sortino <= current_sortino:
                    continue
                new_val = self._apply_guardrails(current, best_val, bounds, max_adj)
                if new_val != current:
                    adjustments.append({
                        "dimension": dim, "old": current, "new": new_val,
                        "sortino": best_sortino,
                        "clamped": new_val != best_val,
                    })

            if not adjustments:
                logger.info("Optimization for %s/%s: no changes", pair, timeframe)
                return

        # Apply adjustments in a fresh session
        async with self.session_factory() as session:
            result = await session.execute(
                select(PerformanceTrackerRow).where(
                    PerformanceTrackerRow.pair == pair,
                    PerformanceTrackerRow.timeframe == timeframe,
                )
            )
            row = result.scalar_one()

            for adj in adjustments:
                if adj["dimension"] == "sl":
                    row.current_sl_atr = adj["new"]
                elif adj["dimension"] == "tp1":
                    row.current_tp1_atr = adj["new"]
                elif adj["dimension"] == "tp2":
                    row.current_tp2_atr = adj["new"]

            # Enforce R:R floor: tp1 >= sl * 1.0
            if row.current_tp1_atr < row.current_sl_atr:
                row.current_tp1_atr = row.current_sl_atr

            row.last_optimized_at = datetime.now(timezone.utc)
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()

            for adj in adjustments:
                logger.info(
                    "Tuning %s/%s %s: %.2f → %.2f (Sortino=%.3f%s)",
                    pair, timeframe, adj["dimension"].upper(),
                    adj["old"], adj["new"], adj["sortino"] if adj["sortino"] != float("inf") else 999,
                    " CLAMPED" if adj["clamped"] else "",
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py -v`

Expected: all tests PASS

- [ ] **Step 5: Write and run `optimize()` end-to-end test**

Add to `backend/tests/engine/test_performance_tracker.py`:

```python
@pytest.mark.asyncio
async def test_optimize_updates_multipliers(mock_session_factory):
    """Full optimize flow: fetch signals, replay, sweep, apply guardrailed updates."""
    factory, session = mock_session_factory

    # Mock tracker row
    row = MagicMock()
    row.current_sl_atr = 1.5
    row.current_tp1_atr = 2.0
    row.current_tp2_atr = 3.0
    row.last_optimized_at = None
    row.updated_at = None

    # Mock 50 signals (above MIN_SIGNALS=40) — all LONG TP1_HIT with stored indicators
    from datetime import timedelta
    base_time = datetime(2025, 1, 1, 0, tzinfo=timezone.utc)
    mock_signals = []
    for i in range(50):
        sig = MagicMock()
        sig.direction = "LONG"
        sig.entry = 50000.0
        sig.stop_loss = 49250.0  # 1.5 * 500 ATR
        sig.take_profit_1 = 51000.0  # 2.0 * 500 ATR
        sig.take_profit_2 = 51500.0  # 3.0 * 500 ATR
        sig.created_at = base_time + timedelta(hours=i * 2)
        sig.outcome_at = base_time + timedelta(hours=i * 2 + 1)
        sig.outcome = "TP1_HIT" if i % 3 != 0 else "SL_HIT"
        sig.pair = "BTC-USDT-SWAP"
        sig.timeframe = "1h"
        sig.raw_indicators = {
            "atr": 500.0,
            "effective_sl_atr": 1.5,
            "effective_tp1_atr": 2.0,
            "effective_tp2_atr": 3.0,
            "sl_strength_factor": 1.0,
            "tp_strength_factor": 1.0,
            "vol_factor": 1.0,
            "levels_source": "atr_default",
        }
        mock_signals.append(sig)

    # Mock candles that produce TP1_HIT for most signals, SL_HIT for every 3rd
    mock_candles = []
    for i in range(50):
        c = MagicMock()
        c.timestamp = base_time + timedelta(hours=i * 2, minutes=30)
        if i % 3 != 0:
            c.high = 51100.0  # hits TP1
            c.low = 49900.0   # misses SL
        else:
            c.high = 50100.0  # misses TP
            c.low = 49200.0   # hits SL
        mock_candles.append(c)

    call_count = 0
    def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # First call: fetch tracker row
            result.scalar_one_or_none.return_value = row
        elif call_count == 2:
            # Second call: fetch signals
            result.scalars.return_value.all.return_value = mock_signals
        elif call_count == 3:
            # Third call: fetch candles
            result.scalars.return_value.all.return_value = mock_candles
        elif call_count == 4:
            # Fourth call (apply session): re-fetch row
            result.scalar_one.return_value = row
        return result

    session.execute = AsyncMock(side_effect=mock_execute)

    tracker = PerformanceTracker(factory)
    await tracker.optimize("BTC-USDT-SWAP", "1h")

    # Verify that commit was called (adjustments were applied)
    session.commit.assert_called()
```

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py::test_optimize_updates_multipliers -v`

Expected: PASS

---

## Chunk 3: Phase 2 — Bootstrap, Pipeline Integration, API

### Task 8: Bootstrap from backtests

**Files:**
- Modify: `backend/app/engine/performance_tracker.py`
- Modify: `backend/tests/engine/test_performance_tracker.py`

- [ ] **Step 1: Write failing test for bootstrap**

Add to `backend/tests/engine/test_performance_tracker.py`:

```python
@pytest.mark.asyncio
async def test_bootstrap_creates_rows_from_backtests(mock_session_factory):
    """Bootstrap reads best backtest config per pair/timeframe and seeds tracker rows."""
    factory, session = mock_session_factory

    # Mock backtest query: one completed run for BTC/1h
    mock_run = MagicMock()
    mock_run.pairs = ["BTC-USDT-SWAP"]
    mock_run.timeframe = "1h"
    mock_run.config = {
        "sl_atr_multiplier": 1.8,
        "tp1_atr_multiplier": 2.5,
        "tp2_atr_multiplier": 4.0,
    }

    # First call: backtest query returns one run
    # Second call: existing tracker row check returns None (no row yet)
    call_count = 0
    def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalars.return_value.all.return_value = [mock_run]
        else:
            result.scalar_one_or_none.return_value = None
        return result

    session.execute = AsyncMock(side_effect=mock_execute)

    tracker = PerformanceTracker(factory)
    await tracker.bootstrap_from_backtests()

    session.add.assert_called_once()
    added_row = session.add.call_args[0][0]
    assert added_row.pair == "BTC-USDT-SWAP"
    assert added_row.timeframe == "1h"
    assert added_row.current_sl_atr == 1.8
    assert added_row.current_tp1_atr == 2.5
    assert added_row.current_tp2_atr == 4.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py::test_bootstrap_creates_rows_from_backtests -v`

Expected: FAIL — `AttributeError: 'PerformanceTracker' object has no attribute 'bootstrap_from_backtests'`

- [ ] **Step 3: Implement `bootstrap_from_backtests`**

Add to `PerformanceTracker` class:

```python
    async def bootstrap_from_backtests(self):
        """Seed tracker rows from best completed backtests per pair/timeframe.

        Reads ATR multiplier config from the best completed backtest (by profit factor)
        for each unique pair/timeframe. Does not re-optimize — just copies starting values.
        Logs which pair/timeframes had no backtest data and were left at defaults.
        """
        async with self.session_factory() as session:
            # Get all completed backtests ordered by profit factor
            result = await session.execute(
                select(BacktestRun)
                .where(BacktestRun.status == "completed")
                .order_by(BacktestRun.created_at.desc())
            )
            runs = result.scalars().all()

            # Find best run per (pair, timeframe) by profit factor
            best_per_bucket: dict[tuple[str, str], BacktestRun] = {}
            for run in runs:
                pf = (run.results or {}).get("stats", {}).get("profit_factor") or 0
                for p in run.pairs:
                    key = (p, run.timeframe)
                    existing_pf = (
                        (best_per_bucket[key].results or {}).get("stats", {}).get("profit_factor") or 0
                        if key in best_per_bucket
                        else 0
                    )
                    if pf > existing_pf:
                        best_per_bucket[key] = run

            seeded = []

            for (pair, timeframe), run in best_per_bucket.items():
                config = run.config or {}
                sl = config.get("sl_atr_multiplier", DEFAULT_SL)
                tp1 = config.get("tp1_atr_multiplier", DEFAULT_TP1)
                tp2 = config.get("tp2_atr_multiplier", DEFAULT_TP2)

                # Check if row already exists
                existing = await session.execute(
                    select(PerformanceTrackerRow).where(
                        PerformanceTrackerRow.pair == pair,
                        PerformanceTrackerRow.timeframe == timeframe,
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                session.add(PerformanceTrackerRow(
                    pair=pair,
                    timeframe=timeframe,
                    current_sl_atr=sl,
                    current_tp1_atr=tp1,
                    current_tp2_atr=tp2,
                ))
                seeded.append(f"{pair}/{timeframe}")

            await session.commit()

            if seeded:
                logger.info("Bootstrap seeded tracker for: %s", ", ".join(seeded))
            else:
                logger.info("Bootstrap: no new pair/timeframe buckets to seed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py::test_bootstrap_creates_rows_from_backtests -v`

Expected: PASS

---

### Task 9: Pipeline integration — wire Phase 2 into `check_pending_signals` + lifespan

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add `check_optimization_triggers` to PerformanceTracker**

Add to `PerformanceTracker` class in `backend/app/engine/performance_tracker.py`:

```python
    async def check_optimization_triggers(self, session, resolved_pairs_timeframes: set[tuple[str, str]]):
        """After a batch of signals resolve, check if any buckets need optimization.

        Called once per check_pending_signals cycle (not per-signal) to avoid race conditions.
        Updates last_optimized_count and commits before scheduling async optimization.
        """
        for pair, timeframe in resolved_pairs_timeframes:
            count = await self._get_resolved_count(session, pair, timeframe)
            if count < MIN_SIGNALS:
                continue

            # Get or create tracker row
            result = await session.execute(
                select(PerformanceTrackerRow).where(
                    PerformanceTrackerRow.pair == pair,
                    PerformanceTrackerRow.timeframe == timeframe,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = PerformanceTrackerRow(pair=pair, timeframe=timeframe)
                session.add(row)
                await session.flush()

            if (count - row.last_optimized_count) >= TRIGGER_INTERVAL:
                row.last_optimized_count = count
                row.updated_at = datetime.now(timezone.utc)
                await session.commit()

                # Schedule optimization with reference tracking to prevent GC
                task = asyncio.create_task(self._optimize_safe(pair, timeframe))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _optimize_safe(self, pair: str, timeframe: str):
        """Wrapper that catches and logs optimization failures."""
        try:
            await self.optimize(pair, timeframe)
        except Exception:
            logger.exception("Optimization failed for %s/%s", pair, timeframe)
```

- [ ] **Step 1b: Write tests for `check_optimization_triggers`**

Add to `backend/tests/engine/test_performance_tracker.py`:

```python
from app.engine.performance_tracker import MIN_SIGNALS, TRIGGER_INTERVAL


@pytest.mark.asyncio
async def test_check_triggers_schedules_optimization_when_threshold_met(mock_session_factory):
    """Optimization is scheduled when resolved count crosses trigger interval."""
    factory, session = mock_session_factory

    row = MagicMock()
    row.last_optimized_count = 40
    row.updated_at = None

    call_count = 0
    def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # _get_resolved_count returns 50 (40 + TRIGGER_INTERVAL)
            result.scalar_one.return_value = 50
        else:
            # Tracker row lookup
            result.scalar_one_or_none.return_value = row
        return result

    session.execute = AsyncMock(side_effect=mock_execute)
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    tracker = PerformanceTracker(factory)
    tracker._optimize_safe = AsyncMock()

    import asyncio
    with pytest.MonkeyPatch.context() as mp:
        tasks_created = []
        original_create_task = asyncio.create_task
        def mock_create_task(coro):
            task = original_create_task(coro)
            tasks_created.append(task)
            return task
        mp.setattr(asyncio, "create_task", mock_create_task)

        await tracker.check_optimization_triggers(
            session, {("BTC-USDT-SWAP", "1h")}
        )

    assert row.last_optimized_count == 50
    session.commit.assert_called()


@pytest.mark.asyncio
async def test_check_triggers_skips_below_min_signals(mock_session_factory):
    """No optimization when resolved count is below MIN_SIGNALS."""
    factory, session = mock_session_factory

    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one=MagicMock(return_value=30))
    )
    session.commit = AsyncMock()

    tracker = PerformanceTracker(factory)
    tracker._optimize_safe = AsyncMock()

    await tracker.check_optimization_triggers(
        session, {("BTC-USDT-SWAP", "1h")}
    )

    # Should not have committed (no trigger)
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_check_triggers_skips_below_interval(mock_session_factory):
    """No optimization when delta since last optimization is below TRIGGER_INTERVAL."""
    factory, session = mock_session_factory

    row = MagicMock()
    row.last_optimized_count = 45  # count=50, delta=5 < TRIGGER_INTERVAL=10

    call_count = 0
    def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one.return_value = 50
        else:
            result.scalar_one_or_none.return_value = row
        return result

    session.execute = AsyncMock(side_effect=mock_execute)
    session.commit = AsyncMock()

    tracker = PerformanceTracker(factory)
    await tracker.check_optimization_triggers(
        session, {("BTC-USDT-SWAP", "1h")}
    )

    session.commit.assert_not_called()
```

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py -k "check_triggers" -v`

Expected: all 3 `test_check_triggers_*` tests PASS

- [ ] **Step 2: Wire tracker into `check_pending_signals`**

In `backend/app/main.py`, make three surgical insertions to `check_pending_signals()` (line 655+). Do NOT rewrite the function — only add the tracking set and trigger call:

**Insert 1:** After `pending = result.scalars().all()` (~line 666), add:

```python
        resolved_pairs_timeframes: set[tuple[str, str]] = set()
```

**Insert 2:** After the expiry block's `signal.outcome_duration_minutes = round(age / 60)` (~line 673), before `continue`, add:

```python
                resolved_pairs_timeframes.add((signal.pair, signal.timeframe))
```

**Insert 3:** After the outcome resolution block's `signal.outcome_duration_minutes = outcome["outcome_duration_minutes"]` (~line 714), add:

```python
                resolved_pairs_timeframes.add((signal.pair, signal.timeframe))
```

**Insert 4:** After the existing `await session.commit()` (~line 716), add:

```python
        # Phase 2: check optimization triggers after batch resolution
        tracker = getattr(app.state, "tracker", None)
        if resolved_pairs_timeframes and tracker is not None:
            async with db.session_factory() as trigger_session:
                await tracker.check_optimization_triggers(
                    trigger_session, resolved_pairs_timeframes
                )
```

- [ ] **Step 2b: Write integration test for `check_pending_signals` tracker wiring**

Add to `backend/tests/test_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_check_pending_signals_triggers_tracker(app):
    """Resolving a signal triggers tracker.check_optimization_triggers with the correct pair/timeframe."""
    from unittest.mock import AsyncMock, patch

    mock_tracker = AsyncMock()
    app.state.tracker = mock_tracker

    # Create a pending signal that will expire (age > 24h)
    from datetime import datetime, timezone, timedelta
    from app.db.models import Signal

    async with app.state.db.session_factory() as session:
        signal = Signal(
            pair="BTC-USDT-SWAP", timeframe="1h", direction="LONG",
            score=50, entry=50000.0, stop_loss=49250.0,
            take_profit_1=51000.0, take_profit_2=51500.0,
            created_at=datetime.now(timezone.utc) - timedelta(hours=25),
            outcome="PENDING",
        )
        session.add(signal)
        await session.commit()

    await check_pending_signals(app)

    mock_tracker.check_optimization_triggers.assert_called_once()
    call_args = mock_tracker.check_optimization_triggers.call_args
    resolved_set = call_args[0][1]  # second positional arg
    assert ("BTC-USDT-SWAP", "1h") in resolved_set
```

Run: `docker exec krypton-api-1 python -m pytest tests/test_pipeline.py::test_check_pending_signals_triggers_tracker -v`

Expected: PASS

- [ ] **Step 3: Initialize tracker in lifespan**

In `backend/app/main.py`, after `app.state.pipeline_settings_lock = asyncio.Lock()` (line 793), add:

```python
    from app.engine.performance_tracker import PerformanceTracker
    app.state.tracker = PerformanceTracker(db.session_factory)

    try:
        await app.state.tracker.bootstrap_from_backtests()
    except Exception as e:
        logger.warning("Tracker bootstrap failed: %s", e)
```

- [ ] **Step 4: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=30`

Expected: all tests PASS

---

### Task 10: API endpoints — tuning view/reset

**Files:**
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/api/test_tuning.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/api/test_tuning.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import create_router


def _mock_db():
    db = MagicMock()
    session = AsyncMock()
    db.session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
    db.session_factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return db, session


@pytest.fixture
def app_with_routes():
    app = FastAPI()
    settings = MagicMock()
    settings.krypton_api_key = "test-key"
    app.state.settings = settings
    db, session = _mock_db()
    app.state.db = db
    app.state.session = session
    router = create_router()
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_get_tuning_returns_all_rows(app_with_routes):
    session = app_with_routes.state.session
    row = MagicMock()
    row.pair = "BTC-USDT-SWAP"
    row.timeframe = "1h"
    row.current_sl_atr = 1.8
    row.current_tp1_atr = 2.5
    row.current_tp2_atr = 4.0
    row.last_optimized_at = None
    row.last_optimized_count = 0
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = [row]

    async with AsyncClient(
        transport=ASGITransport(app=app_with_routes), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/engine/tuning",
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["pair"] == "BTC-USDT-SWAP"
    assert data[0]["current_sl_atr"] == 1.8


@pytest.mark.asyncio
async def test_get_tuning_requires_auth(app_with_routes):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_routes), base_url="http://test"
    ) as client:
        resp = await client.get("/api/engine/tuning")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_reset_tuning(app_with_routes):
    session = app_with_routes.state.session
    row = MagicMock()
    row.current_sl_atr = 1.8
    row.current_tp1_atr = 2.5
    row.current_tp2_atr = 4.0
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = row

    async with AsyncClient(
        transport=ASGITransport(app=app_with_routes), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/engine/tuning/reset",
            headers={"X-API-Key": "test-key"},
            json={"pair": "BTC-USDT-SWAP", "timeframe": "1h"},
        )
    assert resp.status_code == 200
    from app.engine.performance_tracker import DEFAULT_SL, DEFAULT_TP1, DEFAULT_TP2
    assert row.current_sl_atr == DEFAULT_SL
    assert row.current_tp1_atr == DEFAULT_TP1
    assert row.current_tp2_atr == DEFAULT_TP2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_tuning.py -v`

Expected: FAIL — 404 (endpoints don't exist yet)

- [ ] **Step 3: Add tuning endpoints to routes.py**

In `backend/app/api/routes.py`, add imports at the top:

```python
from app.db.models import Signal, PerformanceTrackerRow
from app.engine.performance_tracker import DEFAULT_SL, DEFAULT_TP1, DEFAULT_TP2
```

Add inside `create_router()`, after existing endpoints:

```python
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
```

- [ ] **Step 4: Run API tests**

Run: `docker exec krypton-api-1 python -m pytest tests/api/test_tuning.py -v`

Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=30`

Expected: all tests PASS

---

### Task 11: Wire Phase 1 scaling into backtester

**Files:**
- Modify: `backend/app/engine/backtester.py:148-160`
- Modify: `backend/tests/engine/test_backtester.py` (add test)

The backtester computes SL/TP levels inline using config multipliers (not via `calculate_levels()`). Phase 1 scaling must be applied here too. Phase 2 learned multipliers are NOT used — backtests use whatever ATR multipliers are passed in the request config, then Phase 1 scales on top.

- [ ] **Step 1: Write failing test for Phase 1 scaling in backtests**

Add to `backend/tests/engine/test_backtester.py`:

```python
def test_backtester_applies_phase1_scaling():
    """Backtest level calculation applies signal strength + volatility scaling."""
    from app.engine.combiner import scale_atr_multipliers

    # Simulate what the backtester should do: apply Phase 1 scaling to config multipliers
    score = 80
    bb_width_pct = 70.0
    sl_base, tp1_base, tp2_base = 1.5, 2.0, 3.0

    scaled = scale_atr_multipliers(
        score=score, bb_width_pct=bb_width_pct,
        sl_base=sl_base, tp1_base=tp1_base, tp2_base=tp2_base,
        signal_threshold=35,
    )

    # Phase 1 scaling should modify the multipliers (score=80, bb_width=70 → not default)
    assert scaled["sl_atr"] != sl_base
    assert scaled["tp1_atr"] != tp1_base

    # TP should scale more aggressively than SL
    tp_ratio = scaled["tp1_atr"] / tp1_base
    sl_ratio = scaled["sl_atr"] / sl_base
    assert tp_ratio > sl_ratio
```

- [ ] **Step 2: Add Phase 1 scaling to backtester level calculation**

In `backend/app/engine/backtester.py`, add import at top:

```python
from app.engine.combiner import scale_atr_multipliers
```

Replace the inline level calculation (lines 148-160) with:

```python
        atr = tech_result["indicators"].get("atr", 0)
        if atr <= 0:
            continue

        price = float(current["close"])
        bb_width_pct = tech_result["indicators"].get("bb_width_pct", 50.0)

        # Phase 1: apply signal strength + volatility scaling to config multipliers
        # Phase 2 learned multipliers are NOT used in backtests — backtests use
        # whatever ATR multipliers are passed in the request config
        scaled = scale_atr_multipliers(
            score=score, bb_width_pct=bb_width_pct,
            sl_base=config.sl_atr_multiplier,
            tp1_base=config.tp1_atr_multiplier,
            tp2_base=config.tp2_atr_multiplier,
            signal_threshold=config.signal_threshold,
        )

        if direction == "LONG":
            sl = price - scaled["sl_atr"] * atr
            tp1 = price + scaled["tp1_atr"] * atr
            tp2 = price + scaled["tp2_atr"] * atr
        else:
            sl = price + scaled["sl_atr"] * atr
            tp1 = price - scaled["tp1_atr"] * atr
            tp2 = price - scaled["tp2_atr"] * atr
```

**Note:** `score` is the blended score variable from `blend_with_ml()` at backtester.py line 138 (named `score`, not `final` as in `run_pipeline`). `config.signal_threshold` already exists on `BacktestConfig` (line 23, default 35).

- [ ] **Step 3: Run backtester tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester.py -v`

Expected: PASS

- [ ] **Step 4: Run full test suite + commit**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=30`

Expected: all tests PASS

```bash
git add backend/app/engine/combiner.py backend/tests/engine/test_combiner.py
git add backend/app/engine/performance_tracker.py backend/tests/engine/test_performance_tracker.py
git add backend/app/engine/backtester.py backend/tests/engine/test_backtester.py
git add backend/app/db/models.py backend/app/db/migrations/versions/
git add backend/app/main.py backend/app/api/routes.py backend/tests/api/test_tuning.py
git commit -m "feat: add adaptive SL/TP scaling and rolling performance tracker"
```
