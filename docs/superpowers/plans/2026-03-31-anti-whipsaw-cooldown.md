# Anti-Whipsaw Signal Cooldown — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suppress signal emission after consecutive SL hits for the same pair+timeframe+direction, with graduated cooldown escalation and full observability in the monitor.

**Architecture:** Redis-backed streak counter and timestamp per (pair, timeframe, direction). Outcome resolver updates streaks atomically via Redis pipelines. `run_pipeline` checks cooldown before emission decision. Suppressed signals persist to `PipelineEvaluation` with `suppressed_reason` for monitoring. Config flows through `Settings` → `PipelineSettings` → `_OVERRIDE_MAP`.

**Tech Stack:** Redis (streak state), SQLAlchemy/Alembic (schema), FastAPI (API), React/TypeScript (monitor UI)

---

### Task 1: Cooldown Helper Module

**Files:**
- Create: `backend/app/engine/cooldown.py`
- Create: `backend/tests/engine/conftest.py`
- Create: `backend/tests/engine/test_cooldown.py`

- [ ] **Step 1: Create shared FakeRedis fixture**

```python
# backend/tests/engine/conftest.py
import pytest


class FakeRedis:
    """Minimal async Redis mock with pipeline support for engine tests."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def incr(self, key: str):
        val = int(self.store.get(key, "0")) + 1
        self.store[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int):
        pass

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops: list = []

    def incr(self, key: str):
        self._ops.append(("incr", key))

    def set(self, key: str, value: str):
        self._ops.append(("set", key, value))

    def delete(self, key: str):
        self._ops.append(("delete", key))

    def expire(self, key: str, seconds: int):
        pass

    async def execute(self):
        for op in self._ops:
            if op[0] == "incr":
                val = int(self._redis.store.get(op[1], "0")) + 1
                self._redis.store[op[1]] = str(val)
            elif op[0] == "set":
                self._redis.store[op[1]] = op[2]
            elif op[0] == "delete":
                self._redis.store.pop(op[1], None)


@pytest.fixture
def fake_redis():
    return FakeRedis()
```

- [ ] **Step 2: Write tests for streak update and reset**

```python
# backend/tests/engine/test_cooldown.py
import pytest
from datetime import datetime, timezone, timedelta

from app.engine.cooldown import update_streak_on_sl, reset_streak, check_cooldown


PAIR = "BTC-USDT-SWAP"
TF = "1h"
DIR = "LONG"


class TestUpdateStreakOnSL:

    async def test_first_sl_sets_streak_to_1(self, fake_redis):
        ts = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts)
        key = f"cooldown:streak:{PAIR}:{TF}:{DIR}"
        assert fake_redis.store[key] == "1"

    async def test_second_sl_increments_to_2(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts2)
        key = f"cooldown:streak:{PAIR}:{TF}:{DIR}"
        assert fake_redis.store[key] == "2"

    async def test_timestamp_only_updates_if_newer(self, fake_redis):
        ts_new = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        ts_old = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts_new)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts_old)
        key = f"cooldown:last_sl:{PAIR}:{TF}:{DIR}"
        assert fake_redis.store[key] == ts_new.isoformat()
        # streak still increments even for out-of-order
        assert fake_redis.store[f"cooldown:streak:{PAIR}:{TF}:{DIR}"] == "2"


class TestResetStreak:

    async def test_reset_deletes_both_keys(self, fake_redis):
        ts = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts)
        await reset_streak(fake_redis, PAIR, TF, DIR)
        assert f"cooldown:streak:{PAIR}:{TF}:{DIR}" not in fake_redis.store
        assert f"cooldown:last_sl:{PAIR}:{TF}:{DIR}" not in fake_redis.store


class TestCheckCooldown:

    async def test_no_streak_returns_none(self, fake_redis):
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3)
        assert result is None

    async def test_streak_1_returns_none(self, fake_redis):
        ts = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts)
        now = datetime(2026, 3, 31, 12, 5, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is None

    async def test_streak_2_within_cooldown_returns_reason(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts2)
        # 1h tf, streak=2 -> cooldown=1 candle=3600s; check 30 min after last SL
        now = datetime(2026, 3, 31, 13, 30, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is not None
        assert "streak=2" in result
        assert "LONG" in result

    async def test_streak_2_after_cooldown_expires_returns_none(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts2)
        # 1h tf, streak=2 -> cooldown=1 candle=3600s; check 2h after last SL
        now = datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is None

    async def test_streak_4_caps_at_max_candles(self, fake_redis):
        base = datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc)
        for i in range(4):
            await update_streak_on_sl(fake_redis, PAIR, TF, DIR, base + timedelta(hours=i))
        # streak=4 -> cooldown = min(4-1, 3) = 3 candles = 10800s
        now = base + timedelta(hours=4)  # 4h after first, 1h after last SL
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is not None

    async def test_cooldown_max_zero_disables(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts2)
        now = datetime(2026, 3, 31, 13, 5, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=0, now=now)
        assert result is None

    async def test_corrupted_timestamp_resets_and_returns_none(self, fake_redis):
        fake_redis.store[f"cooldown:streak:{PAIR}:{TF}:{DIR}"] = "3"
        fake_redis.store[f"cooldown:last_sl:{PAIR}:{TF}:{DIR}"] = "not-a-date"
        now = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is None
        assert f"cooldown:streak:{PAIR}:{TF}:{DIR}" not in fake_redis.store

    async def test_15m_timeframe_uses_900s_per_candle(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 12, 15, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, "15m", DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, "15m", DIR, ts2)
        # 15m tf, streak=2 -> cooldown=1 candle=900s; check 10 min after last SL
        now = datetime(2026, 3, 31, 12, 25, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, "15m", DIR, cooldown_max_candles=3, now=now)
        assert result is not None
        # check 16 min after last SL (past 900s)
        now_after = datetime(2026, 3, 31, 12, 31, tzinfo=timezone.utc)
        result_after = await check_cooldown(fake_redis, PAIR, "15m", DIR, cooldown_max_candles=3, now=now_after)
        assert result_after is None

    async def test_streak_exists_but_last_sl_missing_returns_none(self, fake_redis):
        # partial state: streak key exists but last_sl was evicted
        fake_redis.store[f"cooldown:streak:{PAIR}:{TF}:{DIR}"] = "3"
        now = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is None

    async def test_unknown_timeframe_falls_back_to_3600s(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, "12h", DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, "12h", DIR, ts2)
        # unknown tf falls back to 3600s; streak=2 -> 1 candle = 3600s
        now = datetime(2026, 3, 31, 13, 30, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, "12h", DIR, cooldown_max_candles=3, now=now)
        assert result is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_cooldown.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.cooldown'`

- [ ] **Step 4: Implement cooldown module**

```python
# backend/app/engine/cooldown.py
"""Anti-whipsaw cooldown: per-(pair, timeframe, direction) streak tracking."""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TTL = 7 * 86400  # 7 days

_CANDLE_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400}


async def update_streak_on_sl(redis, pair: str, tf: str, direction: str, outcome_at: datetime):
    """Increment SL streak. Only update timestamp if newer than existing."""
    streak_key = f"cooldown:streak:{pair}:{tf}:{direction}"
    last_sl_key = f"cooldown:last_sl:{pair}:{tf}:{direction}"

    existing = await redis.get(last_sl_key)
    if existing and datetime.fromisoformat(existing) >= outcome_at:
        # out-of-order resolution: increment streak but keep newer timestamp
        await redis.incr(streak_key)
        await redis.expire(streak_key, _TTL)
        return

    pipe = redis.pipeline()
    pipe.incr(streak_key)
    pipe.set(last_sl_key, outcome_at.isoformat())
    pipe.expire(streak_key, _TTL)
    pipe.expire(last_sl_key, _TTL)
    await pipe.execute()


async def reset_streak(redis, pair: str, tf: str, direction: str):
    """Delete streak on win or expiry."""
    pipe = redis.pipeline()
    pipe.delete(f"cooldown:streak:{pair}:{tf}:{direction}")
    pipe.delete(f"cooldown:last_sl:{pair}:{tf}:{direction}")
    await pipe.execute()


async def check_cooldown(
    redis, pair: str, tf: str, direction: str,
    cooldown_max_candles: int, now: datetime | None = None,
) -> str | None:
    """Return suppression reason string if cooldown active, else None."""
    if cooldown_max_candles <= 0:
        return None

    streak_key = f"cooldown:streak:{pair}:{tf}:{direction}"
    streak_raw = await redis.get(streak_key)
    if not streak_raw:
        return None

    streak = int(streak_raw)
    if streak < 2:
        return None

    cooldown = min(streak - 1, cooldown_max_candles)
    last_sl_raw = await redis.get(f"cooldown:last_sl:{pair}:{tf}:{direction}")
    if not last_sl_raw:
        return None

    try:
        last_sl_dt = datetime.fromisoformat(last_sl_raw)
    except (ValueError, TypeError):
        logger.warning("Corrupted cooldown timestamp for %s:%s:%s, resetting", pair, tf, direction)
        await reset_streak(redis, pair, tf, direction)
        return None

    if now is None:
        now = datetime.now(timezone.utc)

    candle_seconds = _CANDLE_SECONDS.get(tf, 3600)
    elapsed = (now - last_sl_dt).total_seconds()
    remaining = cooldown * candle_seconds - elapsed
    if remaining > 0:
        return f"cooldown: streak={streak}, {remaining:.0f}s remaining ({direction} SL_HIT)"
    return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_cooldown.py -v`
Expected: All 13 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/cooldown.py backend/tests/engine/conftest.py backend/tests/engine/test_cooldown.py
git commit -m "feat(engine): add anti-whipsaw cooldown helper module"
```

---

### Task 2: Database Schema — Migration + Models

**Files:**
- Modify: `backend/app/db/models.py:138` (PipelineEvaluation — add `suppressed_reason` after `availabilities`)
- Modify: `backend/app/db/models.py:277` (PipelineSettings — add `cooldown_max_candles` after `correlation_dampening_floor`)
- Create: migration via `alembic revision --autogenerate`

- [ ] **Step 1: Add `suppressed_reason` to PipelineEvaluation model**

In `backend/app/db/models.py`, after line 138 (`availabilities: Mapped[dict] = ...`), add:

```python
    suppressed_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
```

- [ ] **Step 2: Add `cooldown_max_candles` to PipelineSettings model**

In `backend/app/db/models.py`, after line 278 (`correlation_dampening_floor: ...`), add:

```python
    cooldown_max_candles: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 3: Generate Alembic migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add cooldown columns"`

Expected: A new migration file created in `backend/app/db/migrations/versions/` with:
- `op.add_column('pipeline_evaluations', sa.Column('suppressed_reason', sa.String(128), nullable=True))`
- `op.add_column('pipeline_settings', sa.Column('cooldown_max_candles', sa.Integer(), nullable=True))`

Verify the generated migration looks correct. The migration will run automatically on next container restart via `entrypoint.sh`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/app/db/migrations/versions/*cooldown*
git commit -m "feat(db): add suppressed_reason and cooldown_max_candles columns"
```

---

### Task 3: Config Plumbing — Settings + Override Map

**Files:**
- Modify: `backend/app/config.py:95` (add `engine_cooldown_max_candles` after `engine_correlation_dampening_floor`)
- Modify: `backend/app/main.py:54-77` (add to `_OVERRIDE_MAP`)

- [ ] **Step 1: Add setting to config.py**

In `backend/app/config.py`, after line 95 (`engine_correlation_dampening_floor: float = 0.4`), add:

```python
    engine_cooldown_max_candles: int = 3
```

- [ ] **Step 2: Add to `_OVERRIDE_MAP` in main.py**

In `backend/app/main.py`, inside the `_OVERRIDE_MAP` dict (after the `"liquidation_asymmetry_steepness"` entry, before the closing `}`), add:

```python
    "cooldown_max_candles": "engine_cooldown_max_candles",
```

- [ ] **Step 3: Add to conftest mock settings**

In `backend/tests/conftest.py`, after the existing `mock_settings` attributes (around line 53, near the `llm_factor_total_cap` line), add:

```python
    mock_settings.engine_cooldown_max_candles = 3
```

- [ ] **Step 4: Verify existing tests still pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q --timeout=30`
Expected: All tests PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/main.py backend/tests/conftest.py
git commit -m "feat(config): wire cooldown_max_candles through settings and override map"
```

---

### Task 4: Pipeline Settings API

**Files:**
- Modify: `backend/app/api/pipeline_settings.py:30-36` (add `cooldown_max_candles` to `PipelineSettingsUpdate`)
- Modify: `backend/app/api/pipeline_settings.py:61-70` (add to `_row_to_dict`)
- Modify: `backend/app/api/pipeline_settings.py:23-27` (add to `_DB_TO_SETTINGS`)

- [ ] **Step 1: Add to `PipelineSettingsUpdate` pydantic model**

In `backend/app/api/pipeline_settings.py`, after line 36 (`news_context_window: int | None = ...`), add:

```python
    cooldown_max_candles: int | None = Field(None, ge=0, le=10)
```

- [ ] **Step 2: Add to `_row_to_dict`**

In `backend/app/api/pipeline_settings.py`, inside `_row_to_dict`, after the `"news_context_window"` entry (line 68) and before the `"updated_at"` entry (line 69), add:

```python
        "cooldown_max_candles": ps.cooldown_max_candles,
```

- [ ] **Step 3: Add to `_DB_TO_SETTINGS` map**

In `backend/app/api/pipeline_settings.py`, inside `_DB_TO_SETTINGS` (after line 26), add:

```python
    "cooldown_max_candles": "engine_cooldown_max_candles",
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/pipeline_settings.py
git commit -m "feat(api): expose cooldown_max_candles in pipeline settings API"
```

---

### Task 5: Outcome Resolver Integration — Streak Updates

**Files:**
- Modify: `backend/app/main.py:1560-1578` (add streak calls in `check_pending_signals`)

- [ ] **Step 1: Write test for streak integration in outcome resolution**

```python
# backend/tests/engine/test_cooldown_integration.py
# Uses fake_redis fixture from tests/engine/conftest.py
import pytest
from datetime import datetime, timezone, timedelta

from app.engine.cooldown import update_streak_on_sl, reset_streak, check_cooldown


PAIR = "BTC-USDT-SWAP"
TF = "1h"


class TestOutcomeStreakFlow:
    """Tests the full lifecycle: SL builds streak, win resets it, cooldown activates."""

    async def test_sl_sl_triggers_cooldown_then_win_resets(self, fake_redis):
        # 2 consecutive SL hits build streak
        t1 = datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 3, 31, 11, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, "LONG", t1)
        await update_streak_on_sl(fake_redis, PAIR, TF, "LONG", t2)

        # cooldown active 5min after last SL
        now = t2 + timedelta(minutes=5)
        reason = await check_cooldown(fake_redis, PAIR, TF, "LONG", cooldown_max_candles=3, now=now)
        assert reason is not None

        # win resets streak
        await reset_streak(fake_redis, PAIR, TF, "LONG")
        reason = await check_cooldown(fake_redis, PAIR, TF, "LONG", cooldown_max_candles=3, now=now)
        assert reason is None

    async def test_independent_directions(self, fake_redis):
        t1 = datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 3, 31, 11, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, "LONG", t1)
        await update_streak_on_sl(fake_redis, PAIR, TF, "LONG", t2)

        now = t2 + timedelta(minutes=5)
        # LONG is under cooldown
        assert await check_cooldown(fake_redis, PAIR, TF, "LONG", cooldown_max_candles=3, now=now) is not None
        # SHORT is free
        assert await check_cooldown(fake_redis, PAIR, TF, "SHORT", cooldown_max_candles=3, now=now) is None
```

- [ ] **Step 2: Run test to verify it fails (module exists but integration not wired)**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_cooldown_integration.py -v`
Expected: PASS (these test the helper functions directly, confirming the lifecycle)

- [ ] **Step 3: Wire streak updates into `check_pending_signals`**

In `backend/app/main.py`, add the import near the top of `check_pending_signals` (after line 1491):

```python
    from app.engine.cooldown import update_streak_on_sl, reset_streak
```

After the outcome resolution block (after line 1573 `resolved_pairs_timeframes.add(...)`), add streak updates:

```python
                # update anti-whipsaw cooldown streak
                if outcome["outcome"] == "SL_HIT":
                    await update_streak_on_sl(
                        redis, signal.pair, signal.timeframe,
                        signal.direction, outcome["outcome_at"],
                    )
                else:
                    await reset_streak(redis, signal.pair, signal.timeframe, signal.direction)
```

After the expiry blocks (lines 1516-1519 and 1527-1530 where `signal.outcome = "EXPIRED"` is set), add:

```python
                    await reset_streak(redis, signal.pair, signal.timeframe, signal.direction)
```

There are two expiry paths:
1. After line 1519 (no candle data, age > 86400)
2. After line 1530 (no candles after signal, age > 86400)

Add `await reset_streak(...)` after each.

- [ ] **Step 4: Verify all tests pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q --timeout=30`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/engine/test_cooldown_integration.py
git commit -m "feat(engine): wire cooldown streak updates into outcome resolver"
```

---

### Task 6: Pipeline Cooldown Check — Signal Suppression

**Files:**
- Modify: `backend/app/main.py:1144` (add cooldown check before emission decision)
- Modify: `backend/app/main.py:1159-1172` (add `suppressed` fields to broadcast payload)
- Modify: `backend/app/main.py:1204-1228` (add `suppressed_reason` to `eval_kwargs`)

- [ ] **Step 1: Add cooldown check in `run_pipeline`**

In `backend/app/main.py`, add import at the top of `run_pipeline` (after line 547, near where `redis = app.state.redis` is set):

```python
    from app.engine.cooldown import check_cooldown
```

Replace line 1144 (`emitted = abs(final) >= effective_threshold`) with:

```python
    suppressed_reason = None
    if abs(final) >= effective_threshold:
        suppressed_reason = await check_cooldown(
            redis, pair, timeframe, direction,
            cooldown_max_candles=settings.engine_cooldown_max_candles,
        )
    emitted = abs(final) >= effective_threshold and suppressed_reason is None
```

- [ ] **Step 2: Add suppressed fields to broadcast_scores payload**

In `backend/app/main.py`, inside the `broadcast_scores` call (lines 1159-1172), after the `"emitted": emitted,` entry, add:

```python
        "suppressed": suppressed_reason is not None,
        "suppressed_reason": suppressed_reason,
```

- [ ] **Step 3: Add `suppressed_reason` to `eval_kwargs`**

In `backend/app/main.py`, inside the `eval_kwargs` dict (lines 1204-1228), after `availabilities=eval_availabilities,` add:

```python
        suppressed_reason=suppressed_reason,
```

- [ ] **Step 4: Verify all tests pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q --timeout=30`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(engine): add cooldown check in run_pipeline before signal emission"
```

---

### Task 7: Monitor API — Serialization + Filter

**Files:**
- Modify: `backend/app/api/monitor.py:28-53` (add `suppressed_reason` to `_eval_to_dict`)
- Modify: `backend/app/api/monitor.py:56-91` (add `suppressed` query filter)

- [ ] **Step 1: Add `suppressed_reason` and fix missing `news_score` in `_eval_to_dict`**

In `backend/app/api/monitor.py`, inside `_eval_to_dict`, after the `"confluence_score"` entry (line 43), add the missing `news_score`:

```python
        "news_score": e.news_score,
```

Then after the `"availabilities"` entry (line 52), add:

```python
        "suppressed_reason": e.suppressed_reason,
```

- [ ] **Step 2: Add `suppressed` query parameter to evaluations endpoint**

In `backend/app/api/monitor.py`, add a new query parameter to `list_evaluations` (after line 61, the `emitted` parameter):

```python
    suppressed: bool | None = Query(None),
```

Then add the filter logic after the `emitted` filter block (after line 77):

```python
        if suppressed is not None:
            if suppressed:
                q = q.where(PipelineEvaluation.suppressed_reason.isnot(None))
                count_q = count_q.where(PipelineEvaluation.suppressed_reason.isnot(None))
            else:
                q = q.where(PipelineEvaluation.suppressed_reason.is_(None))
                count_q = count_q.where(PipelineEvaluation.suppressed_reason.is_(None))
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/monitor.py
git commit -m "feat(api): add suppressed_reason to monitor evaluation serialization and filter"
```

---

### Task 8: Frontend — Types + API Client

**Files:**
- Modify: `web/src/features/monitor/types.ts:1-25` (add `suppressed_reason` to interface)
- Modify: `web/src/features/monitor/types.ts:46-50` (add `suppressed` to `MonitorFilters`)
- Modify: `web/src/shared/lib/api.ts:616-634` (add `suppressed` param)

- [ ] **Step 1: Add `suppressed_reason` and fix missing `news_score` in PipelineEvaluation interface**

In `web/src/features/monitor/types.ts`, after line 14 (`confluence_score: number | null;`), add the missing field:

```typescript
  news_score: number | null;
```

Then after line 24 (`availabilities: ...`), add:

```typescript
  suppressed_reason: string | null;
```

- [ ] **Step 2: Update MonitorFilters type**

In `web/src/features/monitor/types.ts`, replace the `MonitorFilters` interface (lines 46-50):

```typescript
export interface MonitorFilters {
  pair: string | null;
  emitted: boolean | null;
  suppressed: boolean | null;
  period: MonitorPeriod;
}
```

- [ ] **Step 3: Add `suppressed` param to API client**

In `web/src/shared/lib/api.ts`, add `suppressed` to the `getMonitorEvaluations` params type (after the `emitted` param):

```typescript
    suppressed?: boolean;
```

Then add the query string logic after the `emitted` line (after line 626):

```typescript
    if (params?.suppressed !== undefined) query.set("suppressed", String(params.suppressed));
```

- [ ] **Step 4: Commit**

```bash
git add web/src/features/monitor/types.ts web/src/shared/lib/api.ts
git commit -m "feat(web): add suppressed_reason types and API param"
```

---

### Task 9: Frontend — Monitor Data Hook + Filter

**Files:**
- Modify: `web/src/features/monitor/hooks/useMonitorData.ts:10-14` (add `suppressed` to initial state)
- Modify: `web/src/features/monitor/hooks/useMonitorData.ts:31-38` (pass `suppressed` to API)

- [ ] **Step 1: Add `suppressed` to filter state**

In `web/src/features/monitor/hooks/useMonitorData.ts`, update the initial `filters` state (line 10-14):

```typescript
  const [filters, setFilters] = useState<MonitorFilters>({
    pair: null,
    emitted: null,
    suppressed: null,
    period: "24h",
  });
```

- [ ] **Step 2: Pass `suppressed` to API call**

In `web/src/features/monitor/hooks/useMonitorData.ts`, update the `api.getMonitorEvaluations` call (inside `fetchData`, around line 32-38):

```typescript
        api.getMonitorEvaluations({
          pair: filters.pair ?? undefined,
          emitted: filters.emitted ?? undefined,
          suppressed: filters.suppressed ?? undefined,
          after,
          limit: 50,
          offset: fromOffset,
        }),
```

- [ ] **Step 3: Commit**

```bash
git add web/src/features/monitor/hooks/useMonitorData.ts
git commit -m "feat(web): pass suppressed filter through monitor data hook"
```

---

### Task 10: Frontend — Monitor UI (Filter Dropdown + Badge + Detail)

**Files:**
- Modify: `web/src/features/monitor/components/MonitorPage.tsx:16-20` (update STATUS_OPTIONS)
- Modify: `web/src/features/monitor/components/EvaluationTable.tsx:56-59` (add cooldown badge)
- Modify: `web/src/features/monitor/components/EvaluationDetail.tsx:48-52` (show suppressed_reason)

- [ ] **Step 1: Update status filter dropdown in MonitorPage**

In `web/src/features/monitor/components/MonitorPage.tsx`, replace `STATUS_OPTIONS` (lines 16-20):

```typescript
const STATUS_OPTIONS = [
  { value: "", label: "All" },
  { value: "emitted", label: "Emitted" },
  { value: "rejected", label: "Rejected" },
  { value: "suppressed", label: "Suppressed" },
];
```

Update the Dropdown `onChange` handler for status (around line 50-51). Replace:

```typescript
          onChange={(v) => updateFilter("emitted", v === "" ? null : v === "true")}
```

with:

```typescript
          onChange={(v) => {
            if (v === "suppressed") {
              updateFilter("emitted", null);
              updateFilter("suppressed", true);
            } else if (v === "") {
              updateFilter("emitted", null);
              updateFilter("suppressed", null);
            } else {
              updateFilter("suppressed", null);
              updateFilter("emitted", v === "emitted");
            }
          }}
```

Update the Dropdown `value` prop. Replace:

```typescript
          value={filters.emitted === null ? "" : String(filters.emitted)}
```

with:

```typescript
          value={filters.suppressed ? "suppressed" : filters.emitted === null ? "" : filters.emitted ? "emitted" : "rejected"}
```

- [ ] **Step 2: Add cooldown badge to EvaluationTable**

In `web/src/features/monitor/components/EvaluationTable.tsx`, replace the Badge rendering (lines 56-59):

```typescript
            <span className="text-right">
              <Badge color={e.emitted ? "long" : e.suppressed_reason ? "accent" : "muted"} pill>
                {e.emitted ? "emit" : e.suppressed_reason ? "cool" : "rej"}
              </Badge>
            </span>
```

- [ ] **Step 3: Show suppressed_reason in EvaluationDetail**

In `web/src/features/monitor/components/EvaluationDetail.tsx`, after the opening `<Card>` tag (after line 49), add:

```typescript
      {e.suppressed_reason && (
        <div className="mb-2 px-2 py-1 rounded bg-accent/10 text-xs text-accent">
          {e.suppressed_reason}
        </div>
      )}
```

- [ ] **Step 4: Run frontend build to verify no type errors**

Run: `cd web && pnpm build`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 5: Commit**

```bash
git add web/src/features/monitor/components/MonitorPage.tsx web/src/features/monitor/components/EvaluationTable.tsx web/src/features/monitor/components/EvaluationDetail.tsx
git commit -m "feat(web): add cooldown badge, suppressed filter, and detail display"
```

---

### Task 11: Final Verification

- [ ] **Step 1: Run all backend tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 2: Run frontend build**

Run: `cd web && pnpm build`
Expected: Build succeeds

- [ ] **Step 3: Verify migration applies cleanly**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head`
Expected: Migration applies (or is already at head if container restarted)

- [ ] **Step 4: Spot-check the full flow mentally**

Verify the chain:
1. Signal resolves as SL_HIT → `update_streak_on_sl` called → Redis keys set
2. Second SL_HIT → streak=2 → `check_cooldown` returns reason string
3. `run_pipeline` sets `suppressed_reason` → `emitted=False` → evaluation persisted with reason
4. `broadcast_scores` includes `suppressed: true` → frontend receives it
5. Monitor page shows "cool" badge → detail shows reason text
6. Win/expiry → `reset_streak` called → cooldown clears

