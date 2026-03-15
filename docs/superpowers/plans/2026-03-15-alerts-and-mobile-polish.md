# Alerts & Mobile Polish Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-configurable alert system (price, signal, indicator, portfolio) with push notifications, plus mobile-native polish (gestures, haptics, transitions).

**Architecture:** Four alert types hook into existing pipeline events (ticker, candle, signal, account poll). New `alert_evaluator.py` checks conditions and fires via WebSocket broadcast + Web Push. Two new background collectors (ticker WS, account poller) provide data feeds. Frontend gets a new `features/alerts/` module accessible from the More tab.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/Zustand/Tailwind (frontend), `@use-gesture/react` (swipe gestures), Web Push API, OKX WebSocket ticker channel.

**Spec:** `docs/superpowers/specs/2026-03-14-alerts-and-mobile-polish-design.md`

---

## File Structure

### New Files — Backend

| File | Responsibility |
|------|---------------|
| `backend/app/db/models.py` | **Modify:** Add `Alert`, `AlertHistory`, `AlertSettings` models |
| `backend/app/db/migrations/versions/xxxx_create_alert_tables.py` | Alembic migration for 3 new tables |
| `backend/app/engine/alert_evaluator.py` | Evaluate all 4 alert types, cooldown/one-shot logic, quiet hours check |
| `backend/app/push/alert_dispatch.py` | Push notification dispatch for alerts (quiet hours aware) |
| `backend/app/api/alerts.py` | CRUD endpoints + settings + history |
| `backend/app/api/connections.py` | **Modify:** Add `broadcast_alert()` method |
| `backend/app/collector/ticker.py` | OKX ticker WS subscription, Redis price cache, price snapshot sampling |
| `backend/app/collector/account_poller.py` | Periodic OKX account balance polling, Redis cache |
| `backend/app/main.py` | **Modify:** Hook evaluator into pipeline events, start new collectors in lifespan |
| `backend/app/api/pipeline_settings.py` | **Modify:** Deactivate alerts when pairs removed, restart ticker collector |
| `backend/tests/test_alert_evaluator.py` | Unit + integration tests for all alert types + cooldown + one-shot + quiet hours |
| `backend/tests/test_alert_api.py` | API endpoint tests (CRUD, validation, max-50 limit, pair validation, settings, history, retention cleanup) |
| `backend/tests/test_alert_push.py` | Push dispatch tests (urgency filtering, quiet hours suppression) |

### New Files — Frontend

| File | Responsibility |
|------|---------------|
| `web/src/features/alerts/types.ts` | Alert, AlertHistory, AlertSettings TypeScript interfaces |
| `web/src/features/alerts/store.ts` | Zustand store for alerts + toast queue |
| `web/src/features/alerts/components/AlertsPage.tsx` | Main alerts page (list + create + history tabs) |
| `web/src/features/alerts/components/AlertForm.tsx` | Alert creation/edit form with type-specific fields |
| `web/src/features/alerts/components/AlertList.tsx` | Active alerts list with edit/delete |
| `web/src/features/alerts/components/AlertHistoryList.tsx` | Triggered alert history log |
| `web/src/features/alerts/components/AlertToast.tsx` | Toast notification with urgency-based styling |
| `web/src/shared/lib/haptics.ts` | `tryVibrate()` helper for Android haptic feedback |
| `web/src/features/alerts/components/QuietHoursSettings.tsx` | Quiet hours configuration controls |

### Modified Files — Frontend

| File | Change |
|------|--------|
| `web/src/shared/lib/api.ts` | Add alert CRUD + settings API methods |
| `web/src/features/signals/hooks/useSignalWebSocket.ts` | Handle `alert_triggered` WS event |
| `web/src/features/more/components/MorePage.tsx` | Add Alerts entry point + notification settings section |
| `web/src/App.tsx` | Mount `AlertToast` component |
| `web/src/shared/components/Layout.tsx` | Tab transition animations |
| `web/src/sw.ts` | Handle `"type": "alert"` push payload with urgency-based presentation |
| `web/package.json` | Add `@use-gesture/react` dependency |

---

## Dependency Graph

```
Task 1 (models) ─── Task 2 (migration)
Task 1 (models) ───┬── Task 3 (evaluator) ──────┐
                    ├── Task 4 (push dispatch)    │
                    ├── Task 8 (API) ─────────────┼── Task 9 (pipeline integration)
Task 5 (WS ext) ───┘                             │        │
Task 6 (ticker collector) ───────────────────────┘        │
Task 7 (account poller) ─────────────────────────┘        │
                                                  Task 17 (pair-removal deactivation)
                                                  Task 18 (cleanup loop fix)
                                                  Task 19 (SW alert handling)

Task 10 (FE types+api) ── Task 11 (store+WS) ── Task 12 (components) ── Task 13 (MorePage)
                                                        │                    │
                                                  Task 20 (quiet hours UI)  Task 21 (edit support)
                                                  Task 22 (history labels)

Task 14 (haptics+pull-to-refresh)  ┐
Task 15 (swipe gestures)           ├── independent of above
Task 16 (transitions+touch+PWA)    ┘
```

**Parallelizable:** Tasks {3,4,5,6,7} after Task 1. Tasks {10,14,15,16} independent of backend. Tasks 17-22 after their parent tasks.

---

## Chunk 1: Backend Data Layer

### Task 1: Alert DB Models

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add Alert model**

Add `ForeignKey` to the existing `sqlalchemy` import at the top of `backend/app/db/models.py`. The import line currently reads:

```python
from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Float, Index, Integer, String, Text,
)
```

Change it to:

```python
from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
)
```

Add after the `BacktestRun` class at the end of `backend/app/db/models.py`:

```python
class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # price, signal, indicator, portfolio
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    pair: Mapped[str | None] = mapped_column(String(32))
    timeframe: Mapped[str | None] = mapped_column(String(8))
    condition: Mapped[str | None] = mapped_column(String(32))  # crosses_above, crosses_below, pct_move, gt, lt
    threshold: Mapped[float | None] = mapped_column(Float)
    secondary_threshold: Mapped[float | None] = mapped_column(Float)  # pct_move window in minutes
    filters: Mapped[dict | None] = mapped_column(JSONB)  # signal type filters
    peak_value: Mapped[float | None] = mapped_column(Float)  # portfolio drawdown peak
    urgency: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")  # critical, normal, silent
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_one_shot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_alert_type_active", "type", "is_active"),
    )
```

- [ ] **Step 2: Add AlertHistory model**

```python
class AlertHistory(Base):
    __tablename__ = "alert_history"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    alert_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    trigger_value: Mapped[float] = mapped_column(Float, nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(32), nullable=False)  # delivered, failed, silenced_by_cooldown, silenced_by_quiet_hours

    __table_args__ = (
        Index("ix_alert_history_alert_triggered", "alert_id", "triggered_at"),
    )
```

- [ ] **Step 3: Add AlertSettings model**

```python
class AlertSettings(Base):
    __tablename__ = "alert_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    quiet_hours_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quiet_hours_start: Mapped[str] = mapped_column(String(5), nullable=False, default="22:00")
    quiet_hours_end: Mapped[str] = mapped_column(String(5), nullable=False, default="08:00")
    quiet_hours_tz: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_alert_settings_singleton"),
    )
```

- [ ] **Step 4: Verify models import cleanly**

Run: `docker exec krypton-api-1 python -c "from app.db.models import Alert, AlertHistory, AlertSettings; print('OK')"`
Expected: `OK`

---

### Task 2: Alembic Migration

**Files:**
- Create: `backend/app/db/migrations/versions/a1b2c3d4e5f7_create_alert_tables.py`

- [ ] **Step 1: Generate migration**

Run: `docker exec krypton-api-1 alembic revision --autogenerate -m "create alert tables"`

- [ ] **Step 2: Verify migration file was created**

Check the generated file creates `alerts`, `alert_history`, and `alert_settings` tables with all columns and indexes.

- [ ] **Step 3: Run migration**

Run: `docker exec krypton-api-1 alembic upgrade head`
Expected: Successfully applies migration.

---

## Chunk 2: Backend Alert Evaluator + Push Dispatch

### Task 3: Alert Evaluator

**Files:**
- Create: `backend/app/engine/alert_evaluator.py`
- Test: `backend/tests/test_alert_evaluator.py`

The evaluator is the core engine. It exposes four entry points, each called from a different pipeline hook:

```
evaluate_price_alerts(pair, price, redis, session_factory, manager, push_ctx)
evaluate_signal_alerts(signal_data, session_factory, manager, push_ctx)
evaluate_indicator_alerts(pair, timeframe, indicators, session_factory, manager, push_ctx)
evaluate_portfolio_alerts(balance_data, redis, session_factory, manager, push_ctx)
```

Note: `fire_alert` accepts an optional `redis` param to invalidate the price alert cache.
Only `evaluate_price_alerts` and `evaluate_portfolio_alerts` pass `redis` through; signal and indicator evaluators pass `redis=None` (default), which is safe since cache invalidation is guarded by `alert.type == "price"`.

Each function: queries matching active alerts → checks condition → checks cooldown → fires (WS broadcast + push + history record) → handles one-shot deactivation.

- [ ] **Step 1: Write price alert evaluation tests**

Create `backend/tests/test_alert_evaluator.py`:

```python
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from app.engine.alert_evaluator import (
    check_price_condition,
    check_cooldown,
    is_in_quiet_hours,
)


def test_crosses_above_true():
    assert check_price_condition("crosses_above", 70000, 69999, 70001) is True

def test_crosses_above_false_already_above():
    assert check_price_condition("crosses_above", 70000, 70001, 70500) is False

def test_crosses_above_false_still_below():
    assert check_price_condition("crosses_above", 70000, 69000, 69500) is False

def test_crosses_below_true():
    assert check_price_condition("crosses_below", 60000, 60001, 59999) is True

def test_crosses_below_false_already_below():
    assert check_price_condition("crosses_below", 60000, 59999, 59500) is False

def test_pct_move_true():
    # 5% move: price was 100, now 106
    assert check_price_condition("pct_move", 5.0, 100.0, 106.0) is True

def test_pct_move_false():
    # 5% move: price was 100, now 103 (only 3%)
    assert check_price_condition("pct_move", 5.0, 100.0, 103.0) is False

def test_cooldown_not_expired():
    last = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert check_cooldown(last, cooldown_minutes=15) is False

def test_cooldown_expired():
    last = datetime.now(timezone.utc) - timedelta(minutes=20)
    assert check_cooldown(last, cooldown_minutes=15) is True

def test_cooldown_never_triggered():
    assert check_cooldown(None, cooldown_minutes=15) is True

def test_quiet_hours_inside():
    # 23:00 UTC, quiet hours 22:00-08:00 UTC
    now = datetime(2026, 3, 15, 23, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, True, "22:00", "08:00", "UTC") is True

def test_quiet_hours_outside():
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, True, "22:00", "08:00", "UTC") is False

def test_quiet_hours_disabled():
    now = datetime(2026, 3, 15, 23, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now, False, "22:00", "08:00", "UTC") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/test_alert_evaluator.py -v`
Expected: ImportError — module doesn't exist yet.

- [ ] **Step 3: Implement alert evaluator core**

Create `backend/app/engine/alert_evaluator.py`:

```python
import logging
from datetime import datetime, timedelta, timezone

from zoneinfo import ZoneInfo
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Alert, AlertHistory, AlertSettings

logger = logging.getLogger(__name__)


def check_price_condition(
    condition: str, threshold: float, prev_price: float | None, current_price: float | None
) -> bool:
    """Check if a price condition is met.

    For crosses_above/crosses_below: prev_price was below/above threshold, current_price is
    now above/below — a crossing event.
    For pct_move: threshold is the % threshold, prev_price is the base price,
    current_price is the current price.
    """
    if condition == "crosses_above":
        # Was below threshold, now at or above
        return (
            prev_price is not None
            and current_price is not None
            and prev_price < threshold
            and current_price >= threshold
        )
    elif condition == "crosses_below":
        return (
            prev_price is not None
            and current_price is not None
            and prev_price > threshold
            and current_price <= threshold
        )
    elif condition == "pct_move":
        if prev_price is None or current_price is None or prev_price == 0:
            return False
        pct_change = abs((current_price - prev_price) / prev_price) * 100
        return pct_change >= threshold
    return False


def check_indicator_condition(condition: str, threshold: float, value: float) -> bool:
    """Check gt/lt conditions for indicator alerts."""
    if condition == "gt":
        return value > threshold
    elif condition == "lt":
        return value < threshold
    return False


def check_signal_filters(filters: dict | None, signal: dict) -> bool:
    """Check if a signal matches all non-null filters."""
    if not filters:
        return True
    if filters.get("pair") and signal.get("pair") != filters["pair"]:
        return False
    if filters.get("direction") and signal.get("direction") != filters["direction"]:
        return False
    if filters.get("min_score") is not None:
        if abs(signal.get("final_score", 0)) < filters["min_score"]:
            return False
    if filters.get("timeframe") and signal.get("timeframe") != filters["timeframe"]:
        return False
    return True


def check_cooldown(last_triggered_at: datetime | None, cooldown_minutes: int) -> bool:
    """Return True if cooldown has expired (or never triggered)."""
    if last_triggered_at is None:
        return True
    elapsed = datetime.now(timezone.utc) - last_triggered_at
    return elapsed >= timedelta(minutes=cooldown_minutes)


def is_in_quiet_hours(
    now: datetime, enabled: bool, start: str, end: str, tz_name: str
) -> bool:
    """Check if current time falls within quiet hours."""
    if not enabled:
        return False
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        return False
    local_now = now.astimezone(tz)
    current_minutes = local_now.hour * 60 + local_now.minute
    start_h, start_m = map(int, start.split(":"))
    end_h, end_m = map(int, end.split(":"))
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m
    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes < end_minutes
    else:
        # Wraps midnight (e.g., 22:00 - 08:00)
        return current_minutes >= start_minutes or current_minutes < end_minutes


async def get_quiet_hours_settings(session_factory: async_sessionmaker) -> dict:
    """Load quiet hours settings from DB."""
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(AlertSettings).where(AlertSettings.id == 1)
            )
            settings = result.scalar_one_or_none()
            if settings:
                return {
                    "enabled": settings.quiet_hours_enabled,
                    "start": settings.quiet_hours_start,
                    "end": settings.quiet_hours_end,
                    "tz": settings.quiet_hours_tz,
                }
    except Exception as e:
        logger.debug(f"Failed to load alert settings: {e}")
    return {"enabled": False, "start": "22:00", "end": "08:00", "tz": "UTC"}


async def fire_alert(
    alert: Alert,
    trigger_value: float,
    session_factory: async_sessionmaker,
    manager,
    push_ctx: dict | None,
    redis=None,
):
    """Fire an alert: record history, broadcast WS, dispatch push, handle one-shot."""
    import json as _json

    now = datetime.now(timezone.utc)

    # Check cooldown
    if not check_cooldown(alert.last_triggered_at, alert.cooldown_minutes):
        # Record silenced-by-cooldown in history
        async with session_factory() as session:
            session.add(AlertHistory(
                alert_id=alert.id,
                trigger_value=trigger_value,
                delivery_status="silenced_by_cooldown",
            ))
            await session.commit()
        return

    # Check quiet hours for non-critical alerts
    quiet = await get_quiet_hours_settings(session_factory)
    in_quiet = is_in_quiet_hours(now, quiet["enabled"], quiet["start"], quiet["end"], quiet["tz"])
    suppressed = in_quiet and alert.urgency != "critical"

    if suppressed:
        delivery_status = "silenced_by_quiet_hours"
    else:
        delivery_status = "delivered"

    # Record history
    async with session_factory() as session:
        session.add(AlertHistory(
            alert_id=alert.id,
            trigger_value=trigger_value,
            delivery_status=delivery_status,
        ))
        # Update alert last_triggered_at + one-shot deactivation
        stmt = (
            update(Alert)
            .where(Alert.id == alert.id)
            .values(
                last_triggered_at=now,
                **({"is_active": False} if alert.is_one_shot else {}),
            )
        )
        await session.execute(stmt)
        await session.commit()

    # Invalidate price alert Redis cache so cooldown/one-shot state is fresh
    if alert.type == "price" and redis:
        await redis.delete("alerts:price")

    # WebSocket broadcast (always, even during quiet hours — for in-app display)
    if manager:
        await manager.broadcast_alert({
            "type": "alert_triggered",
            "alert_id": alert.id,
            "label": alert.label,
            "trigger_value": trigger_value,
            "urgency": alert.urgency,
        })

    # Push dispatch (skip silent, skip if suppressed by quiet hours)
    if alert.urgency != "silent" and not suppressed and push_ctx:
        try:
            from app.push.alert_dispatch import dispatch_push_for_alert
            await dispatch_push_for_alert(
                session_factory=session_factory,
                alert_id=alert.id,
                label=alert.label,
                trigger_value=trigger_value,
                urgency=alert.urgency,
                vapid_private_key=push_ctx["vapid_private_key"],
                vapid_claims_email=push_ctx["vapid_claims_email"],
            )
        except Exception as e:
            logger.debug(f"Alert push dispatch failed: {e}")


async def evaluate_price_alerts(
    pair: str,
    current_price: float,
    redis,
    session_factory: async_sessionmaker,
    manager,
    push_ctx: dict | None,
):
    """Evaluate price alerts for a pair. Called at throttled 1/s cadence from ticker collector."""
    import json

    # Get previous price from Redis
    prev_price_raw = await redis.get(f"ticker_prev:{pair}")
    prev_price = float(prev_price_raw) if prev_price_raw else None

    # Load cached price alerts from Redis (invalidated on CRUD)
    cached = await redis.get("alerts:price")
    if cached:
        alert_dicts = json.loads(cached)
    else:
        # Cache miss — load from DB
        async with session_factory() as session:
            result = await session.execute(
                select(Alert).where(
                    Alert.type == "price",
                    Alert.is_active == True,
                )
            )
            alerts = result.scalars().all()
            alert_dicts = [
                {
                    "id": a.id, "pair": a.pair, "condition": a.condition,
                    "threshold": a.threshold, "secondary_threshold": a.secondary_threshold,
                    "urgency": a.urgency, "cooldown_minutes": a.cooldown_minutes,
                    "is_one_shot": a.is_one_shot, "label": a.label,
                    "last_triggered_at": a.last_triggered_at.isoformat() if a.last_triggered_at else None,
                }
                for a in alerts
            ]
            await redis.set("alerts:price", json.dumps(alert_dicts), ex=300)

    for ad in alert_dicts:
        if ad["pair"] and ad["pair"] != pair:
            continue

        triggered = False
        if ad["condition"] in ("crosses_above", "crosses_below"):
            triggered = check_price_condition(
                ad["condition"], ad["threshold"], prev_price, current_price
            )
        elif ad["condition"] == "pct_move":
            window_minutes = int(ad["secondary_threshold"] or 15)
            # Query Redis sorted set for snapshot price
            min_ts = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
            snapshots = await redis.zrangebyscore(
                f"ticker_snapshots:{pair}", min_ts.timestamp(), "+inf"
            )
            if snapshots:
                base_price = float(snapshots[0])
                # Check coverage: need ≥80% of window
                oldest_ts = await redis.zscore(f"ticker_snapshots:{pair}", snapshots[0])
                if oldest_ts:
                    coverage = (datetime.now(timezone.utc).timestamp() - oldest_ts) / (window_minutes * 60)
                    if coverage >= 0.8:
                        triggered = check_price_condition("pct_move", ad["threshold"], base_price, current_price)

        if triggered:
            # Reconstruct a minimal Alert-like object for fire_alert
            async with session_factory() as session:
                result = await session.execute(select(Alert).where(Alert.id == ad["id"]))
                alert = result.scalar_one_or_none()
                if alert and alert.is_active:
                    await fire_alert(alert, current_price, session_factory, manager, push_ctx, redis=redis)

    # Store current price as prev for next evaluation
    await redis.set(f"ticker_prev:{pair}", str(current_price), ex=10)


async def evaluate_signal_alerts(
    signal_data: dict,
    session_factory: async_sessionmaker,
    manager,
    push_ctx: dict | None,
):
    """Evaluate signal alerts when a new signal is emitted."""
    async with session_factory() as session:
        result = await session.execute(
            select(Alert).where(Alert.type == "signal", Alert.is_active == True)
        )
        alerts = result.scalars().all()

    for alert in alerts:
        if check_signal_filters(alert.filters, signal_data):
            await fire_alert(
                alert, abs(signal_data.get("final_score", 0)),
                session_factory, manager, push_ctx,
            )


async def evaluate_indicator_alerts(
    pair: str,
    timeframe: str,
    indicators: dict,
    session_factory: async_sessionmaker,
    manager,
    push_ctx: dict | None,
):
    """Evaluate indicator alerts after technical scoring completes."""
    # Explicit mapping: alert condition -> (indicator dict key, comparison operator)
    CONDITION_TO_INDICATOR: dict[str, tuple[str, str]] = {
        "rsi_above": ("rsi", "gt"),
        "rsi_below": ("rsi", "lt"),
        "adx_above": ("adx", "gt"),
        "bb_width_percentile_above": ("bb_width_pct", "gt"),
        "bb_width_percentile_below": ("bb_width_pct", "lt"),
        "funding_rate_above": ("funding_rate", "gt"),
        "funding_rate_below": ("funding_rate", "lt"),
        # Also support bare gt/lt for programmatic use
        "gt": (None, "gt"),
        "lt": (None, "lt"),
    }

    async with session_factory() as session:
        result = await session.execute(
            select(Alert).where(Alert.type == "indicator", Alert.is_active == True)
        )
        alerts = result.scalars().all()

    for alert in alerts:
        # Timeframe filter
        if alert.timeframe and alert.timeframe != timeframe:
            continue
        if alert.pair and alert.pair != pair:
            continue

        mapping = CONDITION_TO_INDICATOR.get(alert.condition or "")
        if not mapping:
            continue
        ind_key, cond = mapping
        # For bare gt/lt, ind_key is None — skip (requires specific indicator condition)
        if ind_key is None:
            continue
        value = indicators.get(ind_key)
        if value is not None:
            if check_indicator_condition(cond, alert.threshold, value):
                await fire_alert(alert, value, session_factory, manager, push_ctx)


async def evaluate_portfolio_alerts(
    balance_data: dict,
    redis,
    session_factory: async_sessionmaker,
    manager,
    push_ctx: dict | None,
):
    """Evaluate portfolio alerts on each account balance poll."""
    equity = balance_data.get("total_equity", 0)

    async with session_factory() as session:
        result = await session.execute(
            select(Alert).where(Alert.type == "portfolio", Alert.is_active == True)
        )
        alerts = result.scalars().all()

    for alert in alerts:
        if alert.condition == "drawdown_pct":
            # Track peak in Redis, fallback to alert.peak_value
            peak_key = f"portfolio_peak:{alert.id}"
            peak_raw = await redis.get(peak_key)
            peak = float(peak_raw) if peak_raw else (alert.peak_value or equity)

            if equity > peak:
                peak = equity
                await redis.set(peak_key, str(peak), ex=86400 * 7)
                # Persist to DB
                async with session_factory() as session:
                    from sqlalchemy import update as sa_update
                    await session.execute(
                        sa_update(Alert).where(Alert.id == alert.id).values(peak_value=peak)
                    )
                    await session.commit()

            if peak > 0:
                drawdown_pct = ((peak - equity) / peak) * 100
                if drawdown_pct >= alert.threshold:
                    await fire_alert(alert, drawdown_pct, session_factory, manager, push_ctx, redis=redis)

        elif alert.condition == "pnl_crosses":
            pnl = balance_data.get("unrealized_pnl", 0)
            if alert.threshold >= 0 and pnl >= alert.threshold:
                await fire_alert(alert, pnl, session_factory, manager, push_ctx, redis=redis)
            elif alert.threshold < 0 and pnl <= alert.threshold:
                await fire_alert(alert, pnl, session_factory, manager, push_ctx, redis=redis)

        elif alert.condition == "position_loss_pct":
            positions = balance_data.get("positions", [])
            for pos in positions:
                pos_pnl_pct = pos.get("unrealized_pnl_pct", 0)
                if pos_pnl_pct <= -abs(alert.threshold):
                    await fire_alert(alert, pos_pnl_pct, session_factory, manager, push_ctx, redis=redis)
                    break  # Only fire once per evaluation


async def cleanup_alert_history(session_factory: async_sessionmaker, retention_days: int = 30):
    """Delete alert history older than retention_days. Run daily."""
    from sqlalchemy import delete
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    async with session_factory() as session:
        await session.execute(
            delete(AlertHistory).where(AlertHistory.triggered_at < cutoff)
        )
        await session.commit()
    logger.info(f"Cleaned up alert history older than {retention_days} days")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/test_alert_evaluator.py -v`
Expected: All pure function tests pass.

- [ ] **Step 5: Write signal filter tests**

Add to `backend/tests/test_alert_evaluator.py`:

```python
from app.engine.alert_evaluator import check_signal_filters

def test_signal_filter_all_null_matches():
    assert check_signal_filters({}, {"pair": "BTC", "direction": "LONG"}) is True

def test_signal_filter_pair_match():
    assert check_signal_filters({"pair": "BTC-USDT-SWAP"}, {"pair": "BTC-USDT-SWAP", "final_score": 50}) is True

def test_signal_filter_pair_mismatch():
    assert check_signal_filters({"pair": "BTC-USDT-SWAP"}, {"pair": "ETH-USDT-SWAP"}) is False

def test_signal_filter_min_score():
    assert check_signal_filters({"min_score": 60}, {"final_score": 70}) is True
    assert check_signal_filters({"min_score": 60}, {"final_score": 50}) is False

def test_signal_filter_direction():
    assert check_signal_filters({"direction": "LONG"}, {"direction": "LONG", "final_score": 0}) is True
    assert check_signal_filters({"direction": "LONG"}, {"direction": "SHORT", "final_score": 0}) is False

def test_signal_filter_combined():
    filters = {"pair": "BTC-USDT-SWAP", "direction": "LONG", "min_score": 50}
    assert check_signal_filters(filters, {"pair": "BTC-USDT-SWAP", "direction": "LONG", "final_score": 60}) is True
    assert check_signal_filters(filters, {"pair": "BTC-USDT-SWAP", "direction": "SHORT", "final_score": 60}) is False
```

- [ ] **Step 6: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/test_alert_evaluator.py -v`
Expected: All tests pass.

- [ ] **Step 7: Write indicator condition tests**

Add to `backend/tests/test_alert_evaluator.py`:

```python
from app.engine.alert_evaluator import check_indicator_condition

def test_indicator_gt():
    assert check_indicator_condition("gt", 70, 75) is True
    assert check_indicator_condition("gt", 70, 65) is False

def test_indicator_lt():
    assert check_indicator_condition("lt", 30, 25) is True
    assert check_indicator_condition("lt", 30, 35) is False
```

- [ ] **Step 8: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/test_alert_evaluator.py -v`
Expected: All tests pass.

---

### Task 4: Alert Push Dispatch

**Files:**
- Create: `backend/app/push/alert_dispatch.py`
- Test: `backend/tests/test_alert_push.py`

- [ ] **Step 1: Write push dispatch tests**

Create `backend/tests/test_alert_push.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.push.alert_dispatch import dispatch_push_for_alert


@pytest.mark.asyncio
async def test_dispatch_sends_to_all_subscriptions():
    mock_session_factory = AsyncMock()
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    sub = MagicMock()
    sub.endpoint = "https://push.example.com/sub1"
    sub.p256dh_key = "key1"
    sub.auth_key = "auth1"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [sub]
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("app.push.alert_dispatch.webpush") as mock_wp:
        with patch("asyncio.to_thread", new_callable=lambda: AsyncMock) as mock_thread:
            mock_thread.return_value = None
            await dispatch_push_for_alert(
                session_factory=mock_session_factory,
                alert_id="test-id",
                label="BTC above 70k",
                trigger_value=70200,
                urgency="critical",
                vapid_private_key="test-key",
                vapid_claims_email="test@example.com",
            )
            mock_thread.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_skips_without_vapid_key():
    await dispatch_push_for_alert(
        session_factory=AsyncMock(),
        alert_id="test",
        label="test",
        trigger_value=0,
        urgency="normal",
        vapid_private_key="",
        vapid_claims_email="",
    )
    # Should return immediately without error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/test_alert_push.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement push dispatch**

Create `backend/app/push/alert_dispatch.py`:

```python
import asyncio
import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import PushSubscription

logger = logging.getLogger(__name__)


async def dispatch_push_for_alert(
    session_factory: async_sessionmaker,
    alert_id: str,
    label: str,
    trigger_value: float,
    urgency: str,
    vapid_private_key: str,
    vapid_claims_email: str,
):
    """Send Web Push for an alert to all subscribers.

    Unlike signal push, alert push does NOT filter by pair/timeframe/threshold —
    the alert definition itself is the filter.
    """
    if not vapid_private_key:
        return

    async with session_factory() as session:
        result = await session.execute(select(PushSubscription))
        subscriptions = result.scalars().all()

    payload = json.dumps({
        "type": "alert",
        "alert_id": alert_id,
        "label": label,
        "trigger_value": trigger_value,
        "urgency": urgency,
    })

    for sub in subscriptions:
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
                },
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": vapid_claims_email},
            )
        except WebPushException as e:
            logger.warning("Alert push failed for %s: %s", sub.endpoint, e)
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/test_alert_push.py -v`
Expected: All tests pass.

---

### Task 5: WebSocket broadcast_alert

**Files:**
- Modify: `backend/app/api/connections.py`

- [ ] **Step 1: Add broadcast_alert method**

Add to `ConnectionManager` class in `backend/app/api/connections.py`, after the `broadcast_news` method:

```python
    async def broadcast_alert(self, alert: dict):
        """Broadcast an alert to all connected clients (no filtering)."""
        dead = []
        for ws, sub in list(self.connections.items()):
            try:
                await ws.send_json(alert)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
```

- [ ] **Step 2: Verify import**

Run: `docker exec krypton-api-1 python -c "from app.api.connections import ConnectionManager; m = ConnectionManager(); assert hasattr(m, 'broadcast_alert'); print('OK')"`
Expected: `OK`

---

## Chunk 3: Backend Infrastructure

### Task 6: Ticker Collector

**Files:**
- Create: `backend/app/collector/ticker.py`

- [ ] **Step 1: Implement ticker collector**

Create `backend/app/collector/ticker.py`:

```python
import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import websockets

logger = logging.getLogger(__name__)

OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"


class TickerCollector:
    """Subscribe to OKX ticker channel for live prices.

    Caches latest price in Redis, samples snapshots for pct_move alerts,
    and invokes price alert evaluation at throttled 1/s/pair cadence.
    """

    def __init__(
        self,
        pairs: list[str],
        redis,
        session_factory,
        manager,
        push_ctx: dict | None,
        evaluate_fn=None,
    ):
        self.pairs = pairs
        self.redis = redis
        self.session_factory = session_factory
        self.manager = manager
        self.push_ctx = push_ctx
        self._evaluate_fn = evaluate_fn
        self._running = True
        self._reconnect = False
        self._last_eval: dict[str, float] = {}  # pair -> last evaluation timestamp
        self._last_snapshot: dict[str, float] = {}  # pair -> last snapshot timestamp

    def stop(self):
        self._running = False

    def request_reconnect(self):
        """Signal the collector to reconnect with updated pairs."""
        self._reconnect = True

    async def run(self):
        """Connect to OKX public WS and subscribe to ticker channels."""
        backoff = 1
        while self._running:
            try:
                self._reconnect = False
                async with websockets.connect(OKX_WS_PUBLIC, ping_interval=20) as ws:
                    backoff = 1
                    # Subscribe to tickers for all pairs
                    sub_msg = {
                        "op": "subscribe",
                        "args": [{"channel": "tickers", "instId": p} for p in self.pairs],
                    }
                    await ws.send(json.dumps(sub_msg))
                    logger.info("Ticker collector connected for %d pairs", len(self.pairs))

                    async for raw in ws:
                        if not self._running or self._reconnect:
                            break
                        try:
                            msg = json.loads(raw)
                            await self._handle_message(msg)
                        except Exception as e:
                            logger.debug(f"Ticker message error: {e}")

                    if self._reconnect:
                        logger.info("Ticker collector reconnecting for pairs change")

            except Exception as e:
                if not self._running:
                    break
                logger.warning(f"Ticker WS error: {e}, reconnecting in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _handle_message(self, msg: dict):
        data = msg.get("data")
        if not data:
            return

        for tick in data:
            pair = tick.get("instId")
            last_price = tick.get("last")
            if not pair or not last_price:
                continue

            price = float(last_price)
            now = time.monotonic()

            # Cache latest price in Redis
            await self.redis.set(f"ticker:{pair}", str(price), ex=30)

            # Sample snapshot once per minute for pct_move alerts
            last_snap = self._last_snapshot.get(pair, 0)
            if now - last_snap >= 60:
                self._last_snapshot[pair] = now
                ts = datetime.now(timezone.utc).timestamp()
                await self.redis.zadd(f"ticker_snapshots:{pair}", {str(price): ts})
                # Trim snapshots older than 90 minutes
                cutoff = ts - (90 * 60)
                await self.redis.zremrangebyscore(f"ticker_snapshots:{pair}", "-inf", cutoff)

            # Throttle alert evaluation to 1/s per pair
            last_eval = self._last_eval.get(pair, 0)
            if now - last_eval >= 1.0 and self._evaluate_fn:
                self._last_eval[pair] = now
                try:
                    await self._evaluate_fn(
                        pair, price, self.redis,
                        self.session_factory, self.manager, self.push_ctx,
                    )
                except Exception as e:
                    logger.debug(f"Price alert evaluation error for {pair}: {e}")
```

- [ ] **Step 2: Verify import**

Run: `docker exec krypton-api-1 python -c "from app.collector.ticker import TickerCollector; print('OK')"`
Expected: `OK`

---

### Task 7: Account Poller

**Files:**
- Create: `backend/app/collector/account_poller.py`

- [ ] **Step 1: Implement account poller**

Create `backend/app/collector/account_poller.py`:

```python
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class AccountPoller:
    """Poll OKX account balance every 60s for portfolio alert evaluation."""

    def __init__(
        self,
        okx_client,
        redis,
        session_factory,
        manager,
        push_ctx: dict | None,
        evaluate_fn=None,
        interval: int = 60,
    ):
        self.okx_client = okx_client
        self.redis = redis
        self.session_factory = session_factory
        self.manager = manager
        self.push_ctx = push_ctx
        self._evaluate_fn = evaluate_fn
        self.interval = interval
        self._running = True

    def stop(self):
        self._running = False

    async def run(self):
        while self._running:
            try:
                await self._poll()
            except Exception as e:
                logger.error(f"Account poll failed: {e}")
            await asyncio.sleep(self.interval)

    async def _poll(self):
        if not self.okx_client:
            return

        balance = await self.okx_client.get_balance()
        if not balance:
            return

        # Cache in Redis
        await self.redis.set(
            "account:balance", json.dumps(balance), ex=self.interval * 2
        )

        # Evaluate portfolio alerts
        if self._evaluate_fn:
            try:
                # Also fetch positions for position-level alerts
                positions = await self.okx_client.get_positions()
                balance_data = {**balance, "positions": positions or []}
                await self._evaluate_fn(
                    balance_data, self.redis,
                    self.session_factory, self.manager, self.push_ctx,
                )
            except Exception as e:
                logger.debug(f"Portfolio alert evaluation error: {e}")
```

- [ ] **Step 2: Verify import**

Run: `docker exec krypton-api-1 python -c "from app.collector.account_poller import AccountPoller; print('OK')"`
Expected: `OK`

---

## Chunk 4: Backend API + Pipeline Integration

### Task 8: Alert API Endpoints

**Files:**
- Create: `backend/app/api/alerts.py`
- Test: `backend/tests/test_alert_api.py`

- [ ] **Step 1: Write API tests**

Create `backend/tests/test_alert_api.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

AUTH = {"X-API-Key": "test-key"}


@pytest.mark.asyncio
async def test_create_price_alert(client):
    resp = await client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "crosses_above",
        "threshold": 70000,
        "urgency": "normal",
    }, headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "price"
    assert data["is_one_shot"] is True  # crosses_above is always one-shot
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_create_alert_missing_threshold(client):
    resp = await client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "crosses_above",
    }, headers=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_alert_requires_auth(client):
    resp = await client.post("/api/alerts", json={
        "type": "price",
        "condition": "crosses_above",
        "threshold": 70000,
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_alert_invalid_type(client):
    resp = await client.post("/api/alerts", json={
        "type": "invalid",
        "condition": "gt",
        "threshold": 70,
    }, headers=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_alert_negative_price_threshold(client):
    resp = await client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "crosses_above",
        "threshold": -100,
    }, headers=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_alert_invalid_pair(client):
    resp = await client.post("/api/alerts", json={
        "type": "price",
        "pair": "INVALID-PAIR",
        "condition": "crosses_above",
        "threshold": 70000,
    }, headers=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_alert_pct_move_window_out_of_range(client):
    resp = await client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "pct_move",
        "threshold": 5,
        "secondary_threshold": 120,  # max is 60
    }, headers=AUTH)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_alert_max_limit(client):
    """Create 50 alerts, then verify 51st is rejected with 409."""
    for i in range(50):
        resp = await client.post("/api/alerts", json={
            "type": "indicator",
            "condition": "rsi_above",
            "threshold": 70 + (i * 0.01),
            "urgency": "silent",
        }, headers=AUTH)
        assert resp.status_code == 200

    resp = await client.post("/api/alerts", json={
        "type": "indicator",
        "condition": "rsi_above",
        "threshold": 99,
    }, headers=AUTH)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_alerts(client):
    # Create one alert
    await client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "crosses_above",
        "threshold": 70000,
    }, headers=AUTH)
    resp = await client.get("/api/alerts", headers=AUTH)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_delete_alert(client):
    create_resp = await client.post("/api/alerts", json={
        "type": "price",
        "pair": "BTC-USDT-SWAP",
        "condition": "crosses_above",
        "threshold": 80000,
    }, headers=AUTH)
    alert_id = create_resp.json()["id"]
    resp = await client.delete(f"/api/alerts/{alert_id}", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["deleted"] == alert_id


@pytest.mark.asyncio
async def test_update_alert(client):
    create_resp = await client.post("/api/alerts", json={
        "type": "indicator",
        "condition": "rsi_above",
        "threshold": 70,
    }, headers=AUTH)
    alert_id = create_resp.json()["id"]
    resp = await client.patch(f"/api/alerts/{alert_id}", json={
        "threshold": 75,
        "urgency": "critical",
    }, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["threshold"] == 75
    assert resp.json()["urgency"] == "critical"


@pytest.mark.asyncio
async def test_alert_settings_crud(client):
    # Get defaults
    resp = await client.get("/api/alerts/settings", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["quiet_hours_enabled"] is False

    # Update
    resp = await client.patch("/api/alerts/settings", json={
        "quiet_hours_enabled": True,
        "quiet_hours_start": "23:00",
        "quiet_hours_tz": "America/New_York",
    }, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["quiet_hours_enabled"] is True
    assert resp.json()["quiet_hours_start"] == "23:00"


@pytest.mark.asyncio
async def test_alert_history_default_window(client):
    resp = await client.get("/api/alerts/history", headers=AUTH)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_alert_history_with_date_filter(client):
    resp = await client.get(
        "/api/alerts/history?since=2026-01-01T00:00:00Z&until=2026-12-31T23:59:59Z",
        headers=AUTH,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_signal_filter_validation(client):
    resp = await client.post("/api/alerts", json={
        "type": "signal",
        "filters": {"min_score": 60, "direction": "LONG"},
        "urgency": "normal",
    }, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["filters"]["min_score"] == 60
```

- [ ] **Step 2: Implement alert API**

Create `backend/app/api/alerts.py`:

```python
"""Alert CRUD API + settings + history endpoints."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update

from app.api.auth import require_settings_api_key
from app.db.models import Alert, AlertHistory, AlertSettings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/alerts")

VALID_ALERT_TYPES = {"price", "signal", "indicator", "portfolio"}
VALID_CONDITIONS = {"crosses_above", "crosses_below", "pct_move", "gt", "lt", "drawdown_pct", "pnl_crosses", "position_loss_pct"}
VALID_URGENCIES = {"critical", "normal", "silent"}
VALID_TIMEFRAMES = {"15m", "1h", "4h"}
MAX_ACTIVE_ALERTS = 50


class AlertCreate(BaseModel):
    type: str
    label: str | None = None
    pair: str | None = None
    timeframe: str | None = None
    condition: str | None = None
    threshold: float | None = None
    secondary_threshold: float | None = Field(None, ge=5, le=60)
    filters: dict | None = None
    urgency: str = "normal"
    cooldown_minutes: int = Field(15, ge=1, le=1440)
    is_one_shot: bool = False

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v not in VALID_ALERT_TYPES:
            raise ValueError(f"Invalid alert type: {v}")
        return v

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, v):
        if v not in VALID_URGENCIES:
            raise ValueError(f"Invalid urgency: {v}")
        return v

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, v):
        if v is not None and v not in VALID_CONDITIONS:
            raise ValueError(f"Invalid condition: {v}")
        return v

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, v):
        if v is not None and v not in VALID_TIMEFRAMES:
            raise ValueError(f"Invalid timeframe: {v}")
        return v


class AlertUpdate(BaseModel):
    label: str | None = None
    threshold: float | None = None
    secondary_threshold: float | None = Field(None, ge=5, le=60)
    urgency: str | None = None
    cooldown_minutes: int | None = Field(None, ge=1, le=1440)
    is_active: bool | None = None
    filters: dict | None = None

    @field_validator("urgency")
    @classmethod
    def validate_urgency(cls, v):
        if v is not None and v not in VALID_URGENCIES:
            raise ValueError(f"Invalid urgency: {v}")
        return v


class AlertSettingsUpdate(BaseModel):
    quiet_hours_enabled: bool | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    quiet_hours_tz: str | None = None


def _alert_to_dict(a: Alert) -> dict:
    return {
        "id": a.id,
        "type": a.type,
        "label": a.label,
        "pair": a.pair,
        "timeframe": a.timeframe,
        "condition": a.condition,
        "threshold": a.threshold,
        "secondary_threshold": a.secondary_threshold,
        "filters": a.filters,
        "urgency": a.urgency,
        "cooldown_minutes": a.cooldown_minutes,
        "is_active": a.is_active,
        "is_one_shot": a.is_one_shot,
        "last_triggered_at": a.last_triggered_at.isoformat() if a.last_triggered_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _generate_label(body: AlertCreate) -> str:
    pair_part = body.pair or "Any pair"
    if body.type == "price":
        return f"{pair_part} {body.condition} {body.threshold}"
    elif body.type == "signal":
        return f"Signal alert ({pair_part})"
    elif body.type == "indicator":
        return f"{body.condition} on {pair_part}"
    elif body.type == "portfolio":
        return f"Portfolio {body.condition}"
    return "Alert"


@router.post("")
async def create_alert(
    request: Request, body: AlertCreate, _key: str = require_settings_api_key()
):
    db = request.app.state.db
    redis = getattr(request.app.state, "redis", None)

    # Validate type-specific requirements
    if body.type != "signal" and body.threshold is None:
        raise HTTPException(422, "threshold required for non-signal alerts")
    if body.type == "price" and body.threshold is not None and body.threshold <= 0:
        raise HTTPException(422, "price threshold must be positive")
    if body.type == "signal" and not body.filters:
        body.filters = {}

    # Validate pair against active pipeline pairs
    if body.pair:
        settings = request.app.state.settings
        if body.pair not in settings.pairs:
            raise HTTPException(422, f"Pair {body.pair} is not in active pairs list")

    async with db.session_factory() as session:
        # Check active alert limit
        count = await session.scalar(
            select(func.count()).select_from(Alert).where(Alert.is_active == True)
        )
        if count >= MAX_ACTIVE_ALERTS:
            raise HTTPException(409, f"Maximum {MAX_ACTIVE_ALERTS} active alerts reached")

        label = body.label or _generate_label(body)
        is_one_shot = body.is_one_shot
        if body.type == "price" and body.condition in ("crosses_above", "crosses_below"):
            is_one_shot = True  # Price crosses are always one-shot

        alert = Alert(
            type=body.type,
            label=label,
            pair=body.pair,
            timeframe=body.timeframe,
            condition=body.condition,
            threshold=body.threshold,
            secondary_threshold=body.secondary_threshold,
            filters=body.filters if body.type == "signal" else None,
            urgency=body.urgency,
            cooldown_minutes=body.cooldown_minutes,
            is_one_shot=is_one_shot,
        )
        session.add(alert)
        await session.commit()
        await session.refresh(alert)

        # Invalidate price alert cache
        if redis and body.type == "price":
            await redis.delete("alerts:price")

        return _alert_to_dict(alert)


@router.get("")
async def list_alerts(
    request: Request, _key: str = require_settings_api_key()
):
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            select(Alert).where(Alert.is_active == True).order_by(Alert.created_at.desc())
        )
        alerts = result.scalars().all()
        return [_alert_to_dict(a) for a in alerts]


@router.patch("/{alert_id}")
async def update_alert(
    request: Request, alert_id: str, body: AlertUpdate,
    _key: str = require_settings_api_key(),
):
    db = request.app.state.db
    redis = getattr(request.app.state, "redis", None)

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(400, "No fields to update")

    async with db.session_factory() as session:
        result = await session.execute(select(Alert).where(Alert.id == alert_id))
        alert = result.scalar_one_or_none()
        if not alert:
            raise HTTPException(404, "Alert not found")

        for field, value in update_data.items():
            setattr(alert, field, value)
        await session.commit()
        await session.refresh(alert)

        # Invalidate price alert cache
        if redis and alert.type == "price":
            await redis.delete("alerts:price")

        return _alert_to_dict(alert)


@router.delete("/{alert_id}")
async def delete_alert(
    request: Request, alert_id: str,
    _key: str = require_settings_api_key(),
):
    db = request.app.state.db
    redis = getattr(request.app.state, "redis", None)

    async with db.session_factory() as session:
        result = await session.execute(select(Alert).where(Alert.id == alert_id))
        alert = result.scalar_one_or_none()
        if not alert:
            raise HTTPException(404, "Alert not found")

        alert_type = alert.type
        await session.execute(delete(AlertHistory).where(AlertHistory.alert_id == alert_id))
        await session.execute(delete(Alert).where(Alert.id == alert_id))
        await session.commit()

        if redis and alert_type == "price":
            await redis.delete("alerts:price")

        return {"deleted": alert_id}


@router.get("/history")
async def get_alert_history(
    request: Request,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    offset: int = 0,
    _key: str = require_settings_api_key(),
):
    db = request.app.state.db

    # LEFT JOIN Alert to include label (survives alert deletion as NULL)
    query = (
        select(AlertHistory, Alert.label)
        .outerjoin(Alert, AlertHistory.alert_id == Alert.id)
        .order_by(AlertHistory.triggered_at.desc())
    )

    if since:
        query = query.where(AlertHistory.triggered_at >= since)
    else:
        # Default: last 7 days
        query = query.where(
            AlertHistory.triggered_at >= datetime.now(timezone.utc) - timedelta(days=7)
        )
    if until:
        query = query.where(AlertHistory.triggered_at <= until)

    query = query.offset(offset).limit(min(limit, 200))

    async with db.session_factory() as session:
        result = await session.execute(query)
        rows = result.all()
        return [
            {
                "id": h.id,
                "alert_id": h.alert_id,
                "alert_label": label,
                "triggered_at": h.triggered_at.isoformat(),
                "trigger_value": h.trigger_value,
                "delivery_status": h.delivery_status,
            }
            for h, label in rows
        ]


@router.get("/settings")
async def get_alert_settings(
    request: Request, _key: str = require_settings_api_key()
):
    db = request.app.state.db
    async with db.session_factory() as session:
        result = await session.execute(
            select(AlertSettings).where(AlertSettings.id == 1)
        )
        s = result.scalar_one_or_none()
        if not s:
            # Auto-create default row
            s = AlertSettings()
            session.add(s)
            await session.commit()
            await session.refresh(s)
        return {
            "quiet_hours_enabled": s.quiet_hours_enabled,
            "quiet_hours_start": s.quiet_hours_start,
            "quiet_hours_end": s.quiet_hours_end,
            "quiet_hours_tz": s.quiet_hours_tz,
        }


@router.patch("/settings")
async def update_alert_settings(
    request: Request, body: AlertSettingsUpdate,
    _key: str = require_settings_api_key(),
):
    db = request.app.state.db
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(400, "No fields to update")

    async with db.session_factory() as session:
        result = await session.execute(
            select(AlertSettings).where(AlertSettings.id == 1)
        )
        s = result.scalar_one_or_none()
        if not s:
            s = AlertSettings()
            session.add(s)
            await session.flush()

        for field, value in update_data.items():
            setattr(s, field, value)
        await session.commit()
        await session.refresh(s)

        return {
            "quiet_hours_enabled": s.quiet_hours_enabled,
            "quiet_hours_start": s.quiet_hours_start,
            "quiet_hours_end": s.quiet_hours_end,
            "quiet_hours_tz": s.quiet_hours_tz,
        }
```

- [ ] **Step 3: Register router in create_app**

In `backend/app/main.py`, inside `create_app()`, add after the last `app.include_router(...)` call (the ML router include):

```python
    from app.api.alerts import router as alerts_router
    app.include_router(alerts_router)
```

- [ ] **Step 4: Run API tests**

Run: `docker exec krypton-api-1 python -m pytest tests/test_alert_api.py -v`
Expected: Auth test passes, CRUD tests may need mock adjustments.

---

### Task 9: Pipeline Integration + Lifespan

**Files:**
- Modify: `backend/app/main.py`

This task hooks the alert evaluator into the existing pipeline events and starts the new collectors in the lifespan.

- [ ] **Step 1: Add signal alert evaluation to _emit_signal**

In `backend/app/main.py`, at the end of the `_emit_signal` function (after the push dispatch try/except block, before the function returns), add:

```python
    # Evaluate signal alerts
    try:
        from app.engine.alert_evaluator import evaluate_signal_alerts
        push_ctx = {
            "vapid_private_key": settings.vapid_private_key,
            "vapid_claims_email": settings.vapid_claims_email,
        }
        await evaluate_signal_alerts(
            signal_data, db.session_factory, manager, push_ctx,
        )
    except Exception as e:
        logger.debug(f"Signal alert evaluation skipped: {e}")
```

- [ ] **Step 2: Add indicator alert evaluation to run_pipeline**

In `backend/app/main.py`, inside `run_pipeline`, after `tech_result = compute_technical_score(df)` succeeds, add:

```python
    # Evaluate indicator alerts on this candle's indicators
    try:
        from app.engine.alert_evaluator import evaluate_indicator_alerts
        push_ctx = {
            "vapid_private_key": settings.vapid_private_key,
            "vapid_claims_email": settings.vapid_claims_email,
        }
        await evaluate_indicator_alerts(
            pair, timeframe, tech_result["indicators"],
            db.session_factory, app.state.manager, push_ctx,
        )
    except Exception as e:
        logger.debug(f"Indicator alert evaluation skipped: {e}")
```

- [ ] **Step 3: Add funding rate indicator alert hook**

In the `handle_funding_rate` function, after updating the `app.state.order_flow` dict, add:

```python
    try:
        from app.engine.alert_evaluator import evaluate_indicator_alerts
        push_ctx = {
            "vapid_private_key": app.state.settings.vapid_private_key,
            "vapid_claims_email": app.state.settings.vapid_claims_email,
        }
        await evaluate_indicator_alerts(
            data["pair"], None,
            {"funding_rate": data["funding_rate"]},
            app.state.db.session_factory, app.state.manager, push_ctx,
        )
    except Exception as e:
        logger.debug(f"Funding rate alert evaluation skipped: {e}")
```

- [ ] **Step 4: Start ticker collector and account poller in lifespan**

In the `lifespan` function, after the news collector task is created, add:

```python
    # Ticker collector (for price alerts)
    from app.collector.ticker import TickerCollector
    from app.engine.alert_evaluator import evaluate_price_alerts, evaluate_portfolio_alerts, cleanup_alert_history

    push_ctx = {
        "vapid_private_key": settings.vapid_private_key,
        "vapid_claims_email": settings.vapid_claims_email,
    }

    ticker_collector = TickerCollector(
        pairs=settings.pairs,
        redis=redis,
        session_factory=db.session_factory,
        manager=ws_manager,
        push_ctx=push_ctx,
        evaluate_fn=evaluate_price_alerts,
    )
    app.state.ticker_collector = ticker_collector
    ticker_task = asyncio.create_task(ticker_collector.run())

    # Account poller (for portfolio alerts)
    from app.collector.account_poller import AccountPoller
    account_poller = AccountPoller(
        okx_client=app.state.okx_client,
        redis=redis,
        session_factory=db.session_factory,
        manager=ws_manager,
        push_ctx=push_ctx,
        evaluate_fn=evaluate_portfolio_alerts,
    )
    app.state.account_poller = account_poller
    account_task = asyncio.create_task(account_poller.run())

    # Alert history cleanup (daily — run immediately then every 24h)
    async def alert_cleanup_loop():
        while True:
            try:
                await cleanup_alert_history(db.session_factory)
            except Exception as e:
                logger.error(f"Alert history cleanup failed: {e}")
            await asyncio.sleep(86400)  # 24 hours

    alert_cleanup_task = asyncio.create_task(alert_cleanup_loop())
```

- [ ] **Step 5: Add shutdown cleanup for new tasks**

In the shutdown section of `lifespan` (in the `yield` cleanup block, alongside existing task cancellations), add:

```python
    ticker_collector.stop()
    ticker_task.cancel()
    account_poller.stop()
    account_task.cancel()
    alert_cleanup_task.cancel()
```

- [ ] **Step 6: Verify backend starts cleanly**

Run: `docker compose up -d && docker logs krypton-api-1 --tail 20`
Expected: No import errors or crashes. New collectors log connection messages.

- [ ] **Step 7: Run all backend tests**

Run: `docker exec krypton-api-1 python -m pytest -v`
Expected: All existing + new tests pass.

---

## Chunk 5: Frontend Alert Feature

### Task 10: Alert Types + API Client

**Files:**
- Create: `web/src/features/alerts/types.ts`
- Modify: `web/src/shared/lib/api.ts`

- [ ] **Step 1: Create alert types**

Create `web/src/features/alerts/types.ts`:

```typescript
export type AlertType = "price" | "signal" | "indicator" | "portfolio";
export type AlertUrgency = "critical" | "normal" | "silent";
export type DeliveryStatus = "delivered" | "failed" | "silenced_by_cooldown" | "silenced_by_quiet_hours";

export interface Alert {
  id: string;
  type: AlertType;
  label: string;
  pair: string | null;
  timeframe: string | null;
  condition: string | null;
  threshold: number | null;
  secondary_threshold: number | null;
  filters: SignalFilters | null;
  urgency: AlertUrgency;
  cooldown_minutes: number;
  is_active: boolean;
  is_one_shot: boolean;
  last_triggered_at: string | null;
  created_at: string | null;
}

export interface SignalFilters {
  pair?: string | null;
  direction?: "LONG" | "SHORT" | null;
  min_score?: number | null;
  timeframe?: string | null;
}

export interface AlertHistoryEntry {
  id: string;
  alert_id: string;
  alert_label: string | null;
  triggered_at: string;
  trigger_value: number;
  delivery_status: DeliveryStatus;
}

export interface AlertSettings {
  quiet_hours_enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
  quiet_hours_tz: string;
}

export interface AlertCreateRequest {
  type: AlertType;
  label?: string;
  pair?: string | null;
  timeframe?: string | null;
  condition?: string;
  threshold?: number;
  secondary_threshold?: number;
  filters?: SignalFilters;
  urgency?: AlertUrgency;
  cooldown_minutes?: number;
  is_one_shot?: boolean;
}

export interface AlertUpdateRequest {
  label?: string;
  threshold?: number;
  secondary_threshold?: number;
  urgency?: AlertUrgency;
  cooldown_minutes?: number;
  is_active?: boolean;
  filters?: SignalFilters;
}

export interface AlertTriggeredEvent {
  type: "alert_triggered";
  alert_id: string;
  label: string;
  trigger_value: number;
  urgency: AlertUrgency;
}
```

- [ ] **Step 2: Add API methods**

Add to `web/src/shared/lib/api.ts`, inside the `api` object (before the closing `}`):

```typescript
  // Alerts
  getAlerts: () => request<Alert[]>("/api/alerts"),

  createAlert: (body: AlertCreateRequest) =>
    request<Alert>("/api/alerts", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateAlert: (id: string, body: AlertUpdateRequest) =>
    request<Alert>(`/api/alerts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deleteAlert: (id: string) =>
    request<{ deleted: string }>(`/api/alerts/${id}`, {
      method: "DELETE",
    }),

  getAlertHistory: (params?: { since?: string; until?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.since) query.set("since", params.since);
    if (params?.until) query.set("until", params.until);
    if (params?.limit) query.set("limit", String(params.limit));
    const qs = query.toString();
    return request<AlertHistoryEntry[]>(`/api/alerts/history${qs ? `?${qs}` : ""}`);
  },

  getAlertSettings: () => request<AlertSettings>("/api/alerts/settings"),

  updateAlertSettings: (body: Partial<AlertSettings>) =>
    request<AlertSettings>("/api/alerts/settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
```

Add imports at top of `api.ts`:

```typescript
import type { Alert, AlertCreateRequest, AlertUpdateRequest, AlertHistoryEntry, AlertSettings } from "../../features/alerts/types";
```

- [ ] **Step 3: Verify build**

Run: `cd web && pnpm build`
Expected: No type errors.

---

### Task 11: Alert Store + WebSocket Handling

**Files:**
- Create: `web/src/features/alerts/store.ts`
- Modify: `web/src/features/signals/hooks/useSignalWebSocket.ts`

- [ ] **Step 1: Create alert store**

Create `web/src/features/alerts/store.ts`:

```typescript
import { create } from "zustand";
import type { Alert, AlertHistoryEntry, AlertTriggeredEvent, AlertSettings } from "./types";
import { api } from "../../shared/lib/api";

interface AlertToast {
  id: string;
  label: string;
  triggerValue: number;
  urgency: "critical" | "normal" | "silent";
  dismissedAt?: number;
}

interface AlertState {
  alerts: Alert[];
  history: AlertHistoryEntry[];
  settings: AlertSettings | null;
  loading: boolean;
  toasts: AlertToast[];

  fetchAlerts: () => Promise<void>;
  fetchHistory: () => Promise<void>;
  fetchSettings: () => Promise<void>;
  addTriggeredAlert: (event: AlertTriggeredEvent) => void;
  dismissToast: (id: string) => void;
  removeAlert: (id: string) => void;
  updateAlertInList: (alert: Alert) => void;
  addAlert: (alert: Alert) => void;
}

export const useAlertStore = create<AlertState>()((set, get) => ({
  alerts: [],
  history: [],
  settings: null,
  loading: false,
  toasts: [],

  fetchAlerts: async () => {
    set({ loading: true });
    try {
      const alerts = await api.getAlerts();
      set({ alerts, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  fetchHistory: async () => {
    try {
      const history = await api.getAlertHistory({ limit: 50 });
      set({ history });
    } catch {}
  },

  fetchSettings: async () => {
    try {
      const settings = await api.getAlertSettings();
      set({ settings });
    } catch {}
  },

  addTriggeredAlert: (event) => {
    if (event.urgency === "silent") return; // No toast for silent
    const toast: AlertToast = {
      id: event.alert_id + "-" + Date.now(),
      label: event.label,
      triggerValue: event.trigger_value,
      urgency: event.urgency,
    };
    set((s) => ({ toasts: [toast, ...s.toasts].slice(0, 5) }));

    // Auto-dismiss non-critical after 3s
    if (event.urgency !== "critical") {
      setTimeout(() => get().dismissToast(toast.id), 3000);
    }
  },

  dismissToast: (id) => {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },

  removeAlert: (id) => {
    set((s) => ({ alerts: s.alerts.filter((a) => a.id !== id) }));
  },

  updateAlertInList: (alert) => {
    set((s) => ({
      alerts: s.alerts.map((a) => (a.id === alert.id ? alert : a)),
    }));
  },

  addAlert: (alert) => {
    set((s) => ({ alerts: [alert, ...s.alerts] }));
  },
}));
```

- [ ] **Step 2: Add alert_triggered handler to WebSocket**

In `web/src/features/signals/hooks/useSignalWebSocket.ts`, add import at top:

```typescript
import { useAlertStore } from "../../alerts/store";
```

In the `ws.onMessage` handler, add a new `else if` branch after the `news_alert` handler:

```typescript
      } else if (data.type === "alert_triggered") {
        useAlertStore.getState().addTriggeredAlert(data);
      }
```

- [ ] **Step 3: Verify build**

Run: `cd web && pnpm build`
Expected: No type errors.

---

### Task 12: Alert Components

**Files:**
- Create: `web/src/features/alerts/components/AlertsPage.tsx`
- Create: `web/src/features/alerts/components/AlertForm.tsx`
- Create: `web/src/features/alerts/components/AlertList.tsx`
- Create: `web/src/features/alerts/components/AlertHistoryList.tsx`
- Create: `web/src/features/alerts/components/AlertToast.tsx`

- [ ] **Step 1: Create AlertList component**

Create `web/src/features/alerts/components/AlertList.tsx`:

```typescript
import { useState } from "react";
import { useAlertStore } from "../store";
import { api } from "../../../shared/lib/api";
import type { Alert } from "../types";

const URGENCY_BADGE: Record<string, string> = {
  critical: "bg-short/20 text-short",
  normal: "bg-accent/20 text-accent",
  silent: "bg-border text-dim",
};

export function AlertList({ onEdit }: { onEdit: (alert: Alert) => void }) {
  const { alerts, loading, removeAlert } = useAlertStore();
  const [error, setError] = useState<string | null>(null);

  async function handleDelete(id: string) {
    setError(null);
    try {
      await api.deleteAlert(id);
      removeAlert(id);
    } catch (e) {
      setError("Failed to delete alert");
    }
  }

  async function handleToggle(alert: Alert) {
    setError(null);
    try {
      const updated = await api.updateAlert(alert.id, { is_active: !alert.is_active });
      useAlertStore.getState().updateAlertInList(updated);
    } catch (e) {
      setError("Failed to update alert");
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 bg-card rounded-lg animate-pulse border border-border" />
        ))}
      </div>
    );
  }

  if (alerts.length === 0) {
    return (
      <div className="text-center py-12 text-muted">
        <p className="text-lg mb-2">No alerts configured</p>
        <p className="text-sm">Create your first alert to get started</p>
      </div>
    );
  }

  const errorBanner = error ? (
    <p className="text-short text-xs bg-short/10 rounded-lg p-2 mb-2">{error}</p>
  ) : null;

  return (
    <div className="space-y-2">
      {errorBanner}
      {alerts.map((alert) => (
        <div
          key={alert.id}
          className="bg-card border border-border rounded-lg p-3 flex items-center justify-between gap-3"
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-medium uppercase text-dim">{alert.type}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${URGENCY_BADGE[alert.urgency]}`}>
                {alert.urgency}
              </span>
            </div>
            <p className="text-sm font-medium truncate">{alert.label}</p>
            {alert.last_triggered_at && (
              <p className="text-[11px] text-dim mt-0.5">
                Last: {new Date(alert.last_triggered_at).toLocaleString()}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onEdit(alert)}
              className="text-xs text-muted hover:text-foreground p-2 min-w-[44px] min-h-[44px] flex items-center justify-center"
            >
              Edit
            </button>
            <button
              onClick={() => handleToggle(alert)}
              className={`text-xs p-2 min-w-[44px] min-h-[44px] flex items-center justify-center ${
                alert.is_active ? "text-long" : "text-dim"
              }`}
            >
              {alert.is_active ? "On" : "Off"}
            </button>
            <button
              onClick={() => handleDelete(alert.id)}
              className="text-xs text-short/70 hover:text-short p-2 min-w-[44px] min-h-[44px] flex items-center justify-center"
            >
              Del
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create AlertForm component**

Create `web/src/features/alerts/components/AlertForm.tsx`:

```typescript
import { useState } from "react";
import { api } from "../../../shared/lib/api";
import { useAlertStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import type { AlertType, AlertUrgency, AlertCreateRequest } from "../types";

const ALERT_TYPES: { value: AlertType; label: string }[] = [
  { value: "price", label: "Price" },
  { value: "signal", label: "Signal" },
  { value: "indicator", label: "Indicator" },
  { value: "portfolio", label: "Portfolio" },
];

const PRICE_CONDITIONS = [
  { value: "crosses_above", label: "Crosses above" },
  { value: "crosses_below", label: "Crosses below" },
  { value: "pct_move", label: "% move in window" },
];

const INDICATOR_CONDITIONS = [
  { value: "rsi_above", label: "RSI above" },
  { value: "rsi_below", label: "RSI below" },
  { value: "adx_above", label: "ADX above" },
  { value: "bb_width_percentile_above", label: "BB width above" },
  { value: "bb_width_percentile_below", label: "BB width below" },
  { value: "funding_rate_above", label: "Funding rate above" },
  { value: "funding_rate_below", label: "Funding rate below" },
];

const PORTFOLIO_CONDITIONS = [
  { value: "drawdown_pct", label: "Drawdown exceeds %" },
  { value: "pnl_crosses", label: "PnL crosses threshold" },
  { value: "position_loss_pct", label: "Position loss exceeds %" },
];

const URGENCIES: AlertUrgency[] = ["critical", "normal", "silent"];

export function AlertForm({ onClose }: { onClose: () => void }) {
  const [type, setType] = useState<AlertType>("price");
  const [pair, setPair] = useState<string>("");
  const [condition, setCondition] = useState("");
  const [threshold, setThreshold] = useState("");
  const [secondaryThreshold, setSecondaryThreshold] = useState("");
  const [urgency, setUrgency] = useState<AlertUrgency>("normal");
  const [cooldown, setCooldown] = useState("15");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Signal filter fields
  const [filterDirection, setFilterDirection] = useState("");
  const [filterMinScore, setFilterMinScore] = useState("");
  const [filterTimeframe, setFilterTimeframe] = useState("");

  const conditions =
    type === "price" ? PRICE_CONDITIONS :
    type === "indicator" ? INDICATOR_CONDITIONS :
    type === "portfolio" ? PORTFOLIO_CONDITIONS : [];

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    const body: AlertCreateRequest = {
      type,
      pair: pair || null,
      urgency,
      cooldown_minutes: parseInt(cooldown) || 15,
    };

    if (type === "signal") {
      body.filters = {
        pair: pair || null,
        direction: (filterDirection || null) as "LONG" | "SHORT" | null,
        min_score: filterMinScore ? parseInt(filterMinScore) : null,
        timeframe: filterTimeframe || null,
      };
    } else {
      body.condition = condition;
      body.threshold = parseFloat(threshold);
      if (type === "price" && condition === "pct_move") {
        body.secondary_threshold = parseInt(secondaryThreshold) || 15;
      }
    }

    try {
      const alert = await api.createAlert(body);
      useAlertStore.getState().addAlert(alert);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create alert");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="flex gap-2">
        {ALERT_TYPES.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => { setType(t.value); setCondition(""); }}
            className={`flex-1 py-2 text-xs font-medium rounded-lg border min-h-[44px] ${
              type === t.value
                ? "bg-accent/20 border-accent text-accent"
                : "bg-card border-border text-muted"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {type !== "portfolio" && (
        <select
          value={pair}
          onChange={(e) => setPair(e.target.value)}
          className="w-full bg-card border border-border rounded-lg p-3 text-sm min-h-[44px]"
        >
          <option value="">All pairs</option>
          {AVAILABLE_PAIRS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      )}

      {type !== "signal" && conditions.length > 0 && (
        <select
          value={condition}
          onChange={(e) => setCondition(e.target.value)}
          className="w-full bg-card border border-border rounded-lg p-3 text-sm min-h-[44px]"
          required
        >
          <option value="">Select condition</option>
          {conditions.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
      )}

      {type !== "signal" && (
        <input
          type="number"
          placeholder="Threshold"
          value={threshold}
          onChange={(e) => setThreshold(e.target.value)}
          className="w-full bg-card border border-border rounded-lg p-3 text-sm min-h-[44px]"
          required
          step="any"
        />
      )}

      {type === "price" && condition === "pct_move" && (
        <input
          type="number"
          placeholder="Window (minutes, 5-60)"
          value={secondaryThreshold}
          onChange={(e) => setSecondaryThreshold(e.target.value)}
          className="w-full bg-card border border-border rounded-lg p-3 text-sm min-h-[44px]"
          min={5}
          max={60}
          required
        />
      )}

      {type === "signal" && (
        <div className="space-y-3">
          <select
            value={filterDirection}
            onChange={(e) => setFilterDirection(e.target.value)}
            className="w-full bg-card border border-border rounded-lg p-3 text-sm min-h-[44px]"
          >
            <option value="">Any direction</option>
            <option value="LONG">LONG</option>
            <option value="SHORT">SHORT</option>
          </select>
          <input
            type="number"
            placeholder="Min score (0-100)"
            value={filterMinScore}
            onChange={(e) => setFilterMinScore(e.target.value)}
            className="w-full bg-card border border-border rounded-lg p-3 text-sm min-h-[44px]"
            min={0}
            max={100}
          />
          <select
            value={filterTimeframe}
            onChange={(e) => setFilterTimeframe(e.target.value)}
            className="w-full bg-card border border-border rounded-lg p-3 text-sm min-h-[44px]"
          >
            <option value="">Any timeframe</option>
            <option value="15m">15m</option>
            <option value="1h">1H</option>
            <option value="4h">4H</option>
          </select>
        </div>
      )}

      <div className="flex gap-2">
        {URGENCIES.map((u) => (
          <button
            key={u}
            type="button"
            onClick={() => setUrgency(u)}
            className={`flex-1 py-2 text-xs font-medium rounded-lg border min-h-[44px] ${
              urgency === u
                ? u === "critical" ? "bg-short/20 border-short text-short"
                : u === "normal" ? "bg-accent/20 border-accent text-accent"
                : "bg-card border-dim text-dim"
                : "bg-card border-border text-muted"
            }`}
          >
            {u}
          </button>
        ))}
      </div>

      <input
        type="number"
        placeholder="Cooldown (minutes)"
        value={cooldown}
        onChange={(e) => setCooldown(e.target.value)}
        className="w-full bg-card border border-border rounded-lg p-3 text-sm min-h-[44px]"
        min={1}
        max={1440}
      />

      {error && (
        <p className="text-short text-xs">{error}</p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onClose}
          className="flex-1 py-3 text-sm bg-card border border-border rounded-lg min-h-[44px]"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="flex-1 py-3 text-sm bg-accent text-surface font-medium rounded-lg min-h-[44px] disabled:opacity-50"
        >
          {submitting ? "Creating..." : "Create Alert"}
        </button>
      </div>
    </form>
  );
}
```

- [ ] **Step 3: Create AlertHistoryList component**

Create `web/src/features/alerts/components/AlertHistoryList.tsx`:

```typescript
import { useEffect } from "react";
import { useAlertStore } from "../store";

const STATUS_STYLES: Record<string, string> = {
  delivered: "text-long",
  failed: "text-short",
  silenced_by_cooldown: "text-dim",
  silenced_by_quiet_hours: "text-muted",
};

export function AlertHistoryList() {
  const { history, fetchHistory } = useAlertStore();

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  if (history.length === 0) {
    return (
      <div className="text-center py-12 text-muted">
        <p className="text-lg mb-2">No alerts triggered yet</p>
        <p className="text-sm">Alert history will appear here</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {history.map((h) => (
        <div key={h.id} className="bg-card border border-border rounded-lg p-3">
          <p className="text-sm font-medium mb-1">{h.alert_label ?? "Deleted alert"}</p>
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted">
              Value: {h.trigger_value.toLocaleString()}
            </span>
            <span className={`text-[11px] ${STATUS_STYLES[h.delivery_status] ?? "text-muted"}`}>
              {h.delivery_status.replace(/_/g, " ")}
            </span>
          </div>
          <p className="text-[11px] text-dim mt-1">
            {new Date(h.triggered_at).toLocaleString()}
          </p>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Create AlertsPage component**

Create `web/src/features/alerts/components/AlertsPage.tsx`:

```typescript
import { useState, useEffect } from "react";
import { useAlertStore } from "../store";
import { AlertList } from "./AlertList";
import { AlertForm } from "./AlertForm";
import { AlertHistoryList } from "./AlertHistoryList";
import type { Alert } from "../types";

type Tab = "active" | "create" | "history";

export function AlertsPage({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("active");
  const [editingAlert, setEditingAlert] = useState<Alert | null>(null);
  const { fetchAlerts } = useAlertStore();

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  return (
    <div className="p-3 space-y-4">
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="text-muted text-sm p-2 min-w-[44px] min-h-[44px] flex items-center justify-center"
        >
          Back
        </button>
        <h2 className="text-lg font-semibold flex-1">Alerts</h2>
      </div>

      <div className="flex gap-1 bg-card rounded-lg p-1 border border-border">
        {(["active", "create", "history"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2 text-xs font-medium rounded-md min-h-[44px] ${
              tab === t ? "bg-surface text-foreground" : "text-muted"
            }`}
          >
            {t === "active" ? "Active" : t === "create" ? "Create" : "History"}
          </button>
        ))}
      </div>

      {tab === "active" && (
        <AlertList onEdit={(a) => { setEditingAlert(a); setTab("create"); }} />
      )}
      {tab === "create" && (
        <AlertForm onClose={() => { setEditingAlert(null); setTab("active"); fetchAlerts(); }} />
      )}
      {tab === "history" && <AlertHistoryList />}
    </div>
  );
}
```

- [ ] **Step 5: Create AlertToast component**

Create `web/src/features/alerts/components/AlertToast.tsx`:

```typescript
import { useAlertStore } from "../store";

const URGENCY_STYLES: Record<string, string> = {
  critical: "border-short/60 bg-short/15",
  normal: "border-accent/40 bg-accent/10",
};

export function AlertToast() {
  const toasts = useAlertStore((s) => s.toasts);
  const dismiss = useAlertStore((s) => s.dismissToast);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-50 p-3 space-y-2 pointer-events-none">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`rounded-lg border p-3 shadow-lg backdrop-blur-md pointer-events-auto animate-slide-down ${
            URGENCY_STYLES[toast.urgency] ?? URGENCY_STYLES.normal
          }`}
          onClick={() => dismiss(toast.id)}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex-1 min-w-0">
              <span className={`text-[10px] font-bold uppercase ${
                toast.urgency === "critical" ? "text-short" : "text-accent"
              }`}>
                {toast.urgency} alert
              </span>
              <p className="text-sm font-medium mt-0.5">{toast.label}</p>
              <p className="text-xs text-muted">
                Value: {toast.triggerValue.toLocaleString()}
              </p>
            </div>
            <button className="text-dim text-xs p-1">&times;</button>
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 6: Verify build**

Run: `cd web && pnpm build`
Expected: No type errors.

---

### Task 13: MorePage + App Integration

**Files:**
- Modify: `web/src/features/more/components/MorePage.tsx`
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Add Alerts entry in MorePage**

In `web/src/features/more/components/MorePage.tsx`:

Add import at top:
```typescript
import { AlertsPage } from "../../alerts/components/AlertsPage";
```

Add state:
```typescript
const [showAlerts, setShowAlerts] = useState(false);
```

Add conditional render (before the `showBacktest` check around line 44):
```typescript
  if (showAlerts) {
    return <AlertsPage onBack={() => setShowAlerts(false)} />;
  }
```

Add button in the Tools section (alongside Backtest and ML Training buttons):
```html
<button
  onClick={() => setShowAlerts(true)}
  className="w-full text-left bg-card border border-border rounded-lg p-4 min-h-[44px]"
>
  <span className="text-sm font-medium">Alerts</span>
  <p className="text-xs text-muted mt-0.5">Configure price, signal, indicator & portfolio alerts</p>
</button>
```

- [ ] **Step 2: Add notification settings section**

Add a "Notifications" section in MorePage (after the existing Notifications checkbox), with quiet hours controls:

```typescript
// In the Notifications section, after the push toggle:
<div className="mt-3 space-y-2">
  <QuietHoursSettings />
</div>
```

Create inline `QuietHoursSettings` component or add directly. This fetches from `useAlertStore().settings` and calls `api.updateAlertSettings()`.

- [ ] **Step 3: Mount AlertToast in App.tsx**

In `web/src/App.tsx`, add import and render `<AlertToast />` alongside `<NewsAlertToast />`:

```typescript
import { AlertToast } from "./features/alerts/components/AlertToast";
```

```tsx
<AlertToast />
```

- [ ] **Step 4: Verify build and test**

Run: `cd web && pnpm build`
Expected: Clean build, no errors.

---

## Chunk 6: Mobile Polish

### Task 14: Haptic Feedback Helper

**Files:**
- Create: `web/src/shared/lib/haptics.ts`

- [ ] **Step 1: Create tryVibrate helper**

Create `web/src/shared/lib/haptics.ts`:

```typescript
/**
 * Haptic feedback via navigator.vibrate (Android only, no-ops elsewhere).
 * Purely additive — UX never depends on vibration.
 */
export function tryVibrate(pattern: number | number[] = 50): void {
  try {
    navigator?.vibrate?.(pattern);
  } catch {}
}

/** Short tap — tab switch, pull-to-refresh trigger */
export function hapticTap(): void {
  tryVibrate(15);
}

/** Signal arrival pulse */
export function hapticPulse(): void {
  tryVibrate(50);
}

/** Critical alert — double pulse */
export function hapticDoublePulse(): void {
  tryVibrate([50, 50, 50]);
}
```

- [ ] **Step 2: Add haptic calls to alert toast**

In `AlertToast.tsx`, call `hapticDoublePulse()` for critical, `hapticPulse()` for normal alerts when a toast appears.

In `useSignalWebSocket.ts`, call `hapticPulse()` when a new signal is received.

---

### Task 15: Pull-to-Refresh + Swipe Gestures

**Files:**
- Modify: `web/package.json` (add `@use-gesture/react`)
- Modify: Signal card components for swipe

- [ ] **Step 1: Install gesture library**

Run: `cd web && pnpm add @use-gesture/react`

- [ ] **Step 2: Add pull-to-refresh to Home/Signals/News tabs**

Create a reusable `usePullToRefresh` hook that tracks touch drag and triggers a refetch callback when pulled past a threshold. Apply to `HomeView`, `SignalsView`, and `NewsView`.

Pattern:
```typescript
function usePullToRefresh(onRefresh: () => Promise<void>) {
  const [pulling, setPulling] = useState(false);
  const startY = useRef(0);

  const handlers = {
    onTouchStart: (e: React.TouchEvent) => {
      if (window.scrollY === 0) startY.current = e.touches[0].clientY;
    },
    onTouchMove: (e: React.TouchEvent) => {
      const dy = e.touches[0].clientY - startY.current;
      if (dy > 60 && window.scrollY === 0) setPulling(true);
    },
    onTouchEnd: async () => {
      if (pulling) {
        await onRefresh();
        setPulling(false);
      }
      startY.current = 0;
    },
  };

  return { pulling, handlers };
}
```

- [ ] **Step 3: Add swipe gestures to signal cards**

Use `@use-gesture/react`'s `useDrag` on signal cards in the Signals list view. Partial swipe reveals colored background (green=win, red=loss). Full swipe calls `api.patchSignalJournal()`.

---

### Task 16: Transitions, Touch Targets, PWA

**Files:**
- Modify: `web/src/shared/components/Layout.tsx` (tab transitions)
- Modify: Various component files (touch targets)
- Modify: `web/tailwind.config.ts` (animation keyframes)

- [ ] **Step 1: Add tab cross-fade transition**

In `Layout.tsx`, wrap the tab content area with a CSS transition:

```tsx
<main className="transition-opacity duration-150 ease-in-out">
  {/* current tab content */}
</main>
```

- [ ] **Step 2: Add slide-up animation for signal cards**

Add keyframes to `tailwind.config.ts`:

```javascript
animation: {
  'slide-down': 'slideDown 0.3s ease-out',
  'slide-up': 'slideUp 0.3s ease-out',
  'fade-in': 'fadeIn 0.15s ease-in-out',
},
keyframes: {
  slideDown: { '0%': { transform: 'translateY(-100%)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
  slideUp: { '0%': { transform: 'translateY(20px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
  fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
},
```

Apply `animate-slide-up` to signal cards when they appear.

- [ ] **Step 3: Touch target audit**

Audit all interactive elements and ensure minimum 44x44px tap targets. Key areas:
- Chart timeframe selector buttons
- Pair selector chips in ticker bar
- Signal card action buttons
- Bottom nav buttons
- Settings toggle buttons

Add `min-h-[44px] min-w-[44px]` to buttons that are too small.

- [ ] **Step 4: Responsive refinements**

Add to global CSS (`index.css`):
```css
html {
  overscroll-behavior: none;
}
input, select, textarea {
  font-size: 16px; /* Prevent iOS zoom */
}
```

Verify safe area insets on bottom nav (`pb-safe` / `env(safe-area-inset-bottom)`).

- [ ] **Step 5: Final build verification**

Run: `cd web && pnpm build`
Expected: Clean build.

---

## Chunk 7: Review Fixes (Missing from initial plan, caught by review)

### Task 17: Pair-Removal Alert Deactivation

**Files:**
- Modify: `backend/app/api/pipeline_settings.py`

Per spec: "When pairs are removed from PipelineSettings, alerts targeting removed pairs are automatically deactivated."

- [ ] **Step 1: Add alert deactivation to update_pipeline_settings**

In `backend/app/api/pipeline_settings.py`, inside the `async with lock:` block after `await session.commit()`, add:

```python
            # Deactivate alerts targeting removed pairs
            deactivated_count = 0
            if pairs_changed:
                removed_pairs = set(old_pairs) - set(ps.pairs)
                if removed_pairs:
                    from app.db.models import Alert
                    result = await session.execute(
                        select(Alert).where(
                            Alert.pair.in_(removed_pairs),
                            Alert.is_active == True,
                        )
                    )
                    stale_alerts = result.scalars().all()
                    for a in stale_alerts:
                        a.is_active = False
                    deactivated_count = len(stale_alerts)
                    if deactivated_count:
                        await session.commit()
                        # Invalidate price alert cache
                        redis = getattr(app.state, "redis", None)
                        if redis:
                            await redis.delete("alerts:price")
```

Update the return dict to include `deactivated_alerts_count`:

```python
            resp = _row_to_dict(ps)
            if deactivated_count:
                resp["deactivated_alerts_count"] = deactivated_count
            return resp
```

- [ ] **Step 2: Restart ticker collector on pairs change**

In `_restart_collectors` function, add after patching the news collector:

```python
    # 6. Restart ticker collector with new pairs (update pairs + signal reconnect)
    ticker_collector = getattr(app.state, "ticker_collector", None)
    if ticker_collector:
        ticker_collector.pairs = new_pairs
        ticker_collector.request_reconnect()

    # 7. Account poller doesn't need pair restart (portfolio alerts aren't pair-specific)
```

---

### Task 18: Alert Cleanup Loop Fix

**Files:**
- Modify: `backend/app/main.py`

The cleanup loop should run immediately on startup, then every 24 hours.

- [ ] **Step 1: Fix cleanup loop order**

Change the `alert_cleanup_loop` in lifespan from:

```python
    async def alert_cleanup_loop():
        while True:
            await asyncio.sleep(86400)
            try:
                await cleanup_alert_history(db.session_factory)
            except Exception as e:
                logger.error(f"Alert history cleanup failed: {e}")
```

To:

```python
    async def alert_cleanup_loop():
        while True:
            try:
                await cleanup_alert_history(db.session_factory)
            except Exception as e:
                logger.error(f"Alert history cleanup failed: {e}")
            await asyncio.sleep(86400)
```

---

### Task 19: Service Worker Alert Handling

**Files:**
- Modify: `web/src/sw.ts`

- [ ] **Step 1: Update push event handler for alert payloads**

In the service worker's push event handler, add handling for the `"type": "alert"` payload:

```typescript
self.addEventListener("push", (event) => {
  const data = event.data?.json() ?? {};

  let title: string;
  let options: NotificationOptions;

  if (data.type === "alert") {
    const urgencyPrefix = data.urgency === "critical" ? "[CRITICAL] " : "";
    title = `${urgencyPrefix}Alert`;
    options = {
      body: `${data.label} — Value: ${data.trigger_value}`,
      icon: "/icon-192.png",
      tag: `alert-${data.alert_id}`,
      requireInteraction: data.urgency === "critical",
    };
  } else {
    // Existing signal/news push handling
    title = data.title ?? "Krypton";
    options = {
      body: data.body ?? "",
      icon: "/icon-192.png",
    };
  }

  event.waitUntil(self.registration.showNotification(title, options));
});
```

---

### Task 20: QuietHoursSettings Component

**Files:**
- Create: `web/src/features/alerts/components/QuietHoursSettings.tsx`

- [ ] **Step 1: Implement QuietHoursSettings**

```typescript
import { useState, useEffect } from "react";
import { useAlertStore } from "../store";
import { api } from "../../../shared/lib/api";

export function QuietHoursSettings() {
  const settings = useAlertStore((s) => s.settings);
  const fetchSettings = useAlertStore((s) => s.fetchSettings);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  if (!settings) return null;

  async function update(patch: Record<string, unknown>) {
    setSaving(true);
    try {
      const updated = await api.updateAlertSettings(patch as any);
      useAlertStore.setState({ settings: updated });
    } catch {}
    setSaving(false);
  }

  return (
    <div className="space-y-3">
      <label className="flex items-center justify-between min-h-[44px]">
        <span className="text-sm">Quiet Hours</span>
        <input
          type="checkbox"
          checked={settings.quiet_hours_enabled}
          onChange={(e) => update({ quiet_hours_enabled: e.target.checked })}
          className="w-5 h-5"
          disabled={saving}
        />
      </label>

      {settings.quiet_hours_enabled && (
        <>
          <div className="flex gap-3">
            <label className="flex-1">
              <span className="text-xs text-muted">Start</span>
              <input
                type="time"
                value={settings.quiet_hours_start}
                onChange={(e) => update({ quiet_hours_start: e.target.value })}
                className="w-full bg-card border border-border rounded-lg p-2 text-sm min-h-[44px]"
              />
            </label>
            <label className="flex-1">
              <span className="text-xs text-muted">End</span>
              <input
                type="time"
                value={settings.quiet_hours_end}
                onChange={(e) => update({ quiet_hours_end: e.target.value })}
                className="w-full bg-card border border-border rounded-lg p-2 text-sm min-h-[44px]"
              />
            </label>
          </div>
          <label>
            <span className="text-xs text-muted">Timezone</span>
            <select
              value={settings.quiet_hours_tz}
              onChange={(e) => update({ quiet_hours_tz: e.target.value })}
              className="w-full bg-card border border-border rounded-lg p-2 text-sm min-h-[44px]"
            >
              {Intl.supportedValuesOf("timeZone").filter(tz =>
                ["America/", "Europe/", "Asia/", "Pacific/", "UTC"].some(p => tz.startsWith(p))
              ).map((tz) => (
                <option key={tz} value={tz}>{tz}</option>
              ))}
            </select>
          </label>
        </>
      )}
    </div>
  );
}
```

---

### Task 21: AlertForm Edit Support

**Files:**
- Modify: `web/src/features/alerts/components/AlertForm.tsx`

- [ ] **Step 1: Accept optional alert prop for editing**

Change `AlertForm` props to:

```typescript
export function AlertForm({ onClose, alert: editAlert }: { onClose: () => void; alert?: Alert | null }) {
```

Pre-fill fields from `editAlert` when provided. On submit, call `api.updateAlert(editAlert.id, ...)` instead of `api.createAlert(...)`.

- [ ] **Step 2: Update AlertsPage to pass editingAlert**

In `AlertsPage.tsx`, change the `AlertForm` render:

```tsx
{tab === "create" && (
  <AlertForm
    onClose={() => { setEditingAlert(null); setTab("active"); fetchAlerts(); }}
    alert={editingAlert}
  />
)}
```

---

### Task 22: AlertHistoryList Label Display

**Files:**
- Modify: `web/src/features/alerts/components/AlertHistoryList.tsx`

- [ ] **Step 1: Use server-provided `alert_label` in history rows**

The `GET /api/alerts/history` response now includes `alert_label` via a LEFT JOIN (see Task 8). Use it directly in the render:

```typescript
// In the render for each history entry:
<p className="text-sm font-medium">{h.alert_label ?? "Deleted alert"}</p>
```

No client-side store lookup needed — the label is provided by the API and survives alert deletion.

---

## Commit Strategy

Per CLAUDE.md: commit once at the end, not incrementally per task.

- [ ] **Final: Commit all changes**

Stage all new and modified files. Single commit:

```
feat: add alert system with price/signal/indicator/portfolio alerts and mobile polish
```
