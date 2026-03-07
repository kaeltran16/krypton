# Mobile UI Redesign + Signal Accuracy Tracking — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign the PWA into a polished, OKX-style mobile-first trading copilot with signal accuracy tracking.

**Architecture:** Four-tab mobile layout (Home, Chart, Signals, More) with a sticky top bar showing live price. Backend adds signal outcome resolution and stats endpoint. Frontend gets a complete visual overhaul with data-dense, touch-friendly components.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Zustand, lightweight-charts, FastAPI, SQLAlchemy, Redis

---

## Task 1: Add outcome fields to Signal DB model

**Files:**
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_db_models.py`

**Step 1: Write the failing test**

Add to `backend/tests/test_db_models.py`:

```python
def test_signal_outcome_fields():
    signal = Signal(
        pair="BTC-USDT-SWAP",
        timeframe="15m",
        direction="LONG",
        final_score=78,
        traditional_score=72,
        entry=Decimal("67420"),
        stop_loss=Decimal("66890"),
        take_profit_1=Decimal("67950"),
        take_profit_2=Decimal("68480"),
        outcome="PENDING",
    )
    assert signal.outcome == "PENDING"
    assert signal.outcome_at is None
    assert signal.outcome_pnl_pct is None
    assert signal.outcome_duration_minutes is None
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_db_models.py::test_signal_outcome_fields -v`
Expected: FAIL — `outcome` column doesn't exist on Signal model

**Step 3: Write minimal implementation**

In `backend/app/db/models.py`, add to the Signal class after `created_at`:

```python
    # outcome tracking
    outcome: Mapped[str] = mapped_column(
        String(16), default="PENDING", server_default="PENDING", nullable=False
    )
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome_pnl_pct: Mapped[float | None] = mapped_column(Numeric(10, 4))
    outcome_duration_minutes: Mapped[int | None] = mapped_column(Integer)
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_db_models.py -v`
Expected: All tests PASS

**Step 5: Create Alembic migration (or raw SQL)**

Since there's no Alembic setup, create a migration SQL file:

Create `backend/migrations/add_signal_outcome.sql`:
```sql
ALTER TABLE signals ADD COLUMN outcome VARCHAR(16) NOT NULL DEFAULT 'PENDING';
ALTER TABLE signals ADD COLUMN outcome_at TIMESTAMPTZ;
ALTER TABLE signals ADD COLUMN outcome_pnl_pct NUMERIC(10, 4);
ALTER TABLE signals ADD COLUMN outcome_duration_minutes INTEGER;
CREATE INDEX ix_signal_outcome ON signals (outcome) WHERE outcome = 'PENDING';
```

**Step 6: Commit**

```bash
git add backend/app/db/models.py backend/tests/test_db_models.py backend/migrations/add_signal_outcome.sql
git commit -m "feat: add outcome tracking fields to Signal model"
```

---

## Task 2: Add signal outcome resolver background task

**Files:**
- Create: `backend/app/engine/outcome_resolver.py`
- Create: `backend/tests/engine/test_outcome_resolver.py`
- Modify: `backend/app/main.py`

**Step 1: Write the failing test**

Create `backend/tests/engine/test_outcome_resolver.py`:

```python
import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from app.engine.outcome_resolver import resolve_signal_outcome


def test_long_tp1_hit():
    signal = {
        "direction": "LONG",
        "entry": 67000.0,
        "stop_loss": 66500.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68000.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }
    candles = [
        {"high": 67100.0, "low": 66900.0, "close": 67050.0, "timestamp": "2026-03-01T12:15:00+00:00"},
        {"high": 67600.0, "low": 67000.0, "close": 67550.0, "timestamp": "2026-03-01T12:30:00+00:00"},
    ]
    result = resolve_signal_outcome(signal, candles)
    assert result["outcome"] == "TP1_HIT"
    assert result["outcome_pnl_pct"] == pytest.approx(0.7463, rel=0.01)


def test_long_sl_hit():
    signal = {
        "direction": "LONG",
        "entry": 67000.0,
        "stop_loss": 66500.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68000.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }
    candles = [
        {"high": 67050.0, "low": 66400.0, "close": 66450.0, "timestamp": "2026-03-01T12:15:00+00:00"},
    ]
    result = resolve_signal_outcome(signal, candles)
    assert result["outcome"] == "SL_HIT"
    assert result["outcome_pnl_pct"] < 0


def test_short_tp1_hit():
    signal = {
        "direction": "SHORT",
        "entry": 67000.0,
        "stop_loss": 67500.0,
        "take_profit_1": 66500.0,
        "take_profit_2": 66000.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }
    candles = [
        {"high": 67050.0, "low": 66400.0, "close": 66450.0, "timestamp": "2026-03-01T12:15:00+00:00"},
    ]
    result = resolve_signal_outcome(signal, candles)
    assert result["outcome"] == "TP1_HIT"


def test_no_resolution_yet():
    signal = {
        "direction": "LONG",
        "entry": 67000.0,
        "stop_loss": 66500.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68000.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }
    candles = [
        {"high": 67200.0, "low": 66800.0, "close": 67100.0, "timestamp": "2026-03-01T12:15:00+00:00"},
    ]
    result = resolve_signal_outcome(signal, candles)
    assert result is None
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/engine/test_outcome_resolver.py -v`
Expected: FAIL — `app.engine.outcome_resolver` module not found

**Step 3: Write minimal implementation**

Create `backend/app/engine/outcome_resolver.py`:

```python
from datetime import datetime, timezone


def resolve_signal_outcome(signal: dict, candles: list[dict]) -> dict | None:
    """Check if signal hit TP1, TP2, or SL based on candle data.

    Returns outcome dict if resolved, None if still pending.
    """
    direction = signal["direction"]
    entry = signal["entry"]
    sl = signal["stop_loss"]
    tp1 = signal["take_profit_1"]
    tp2 = signal["take_profit_2"]
    created_at = signal["created_at"]

    for candle in candles:
        high = candle["high"]
        low = candle["low"]
        ts = candle["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        if direction == "LONG":
            # Check SL first (worst case)
            if low <= sl:
                pnl_pct = (sl - entry) / entry * 100
                return _result("SL_HIT", sl, pnl_pct, created_at, ts)
            if high >= tp2:
                pnl_pct = (tp2 - entry) / entry * 100
                return _result("TP2_HIT", tp2, pnl_pct, created_at, ts)
            if high >= tp1:
                pnl_pct = (tp1 - entry) / entry * 100
                return _result("TP1_HIT", tp1, pnl_pct, created_at, ts)
        else:  # SHORT
            if high >= sl:
                pnl_pct = (entry - sl) / entry * 100
                return _result("SL_HIT", sl, pnl_pct, created_at, ts)
            if low <= tp2:
                pnl_pct = (entry - tp2) / entry * 100
                return _result("TP2_HIT", tp2, pnl_pct, created_at, ts)
            if low <= tp1:
                pnl_pct = (entry - tp1) / entry * 100
                return _result("TP1_HIT", tp1, pnl_pct, created_at, ts)

    return None


def _result(outcome: str, price: float, pnl_pct: float, created_at: datetime, resolved_at: datetime) -> dict:
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    if isinstance(resolved_at, str):
        resolved_at = datetime.fromisoformat(resolved_at)
    duration = (resolved_at - created_at).total_seconds() / 60
    return {
        "outcome": outcome,
        "outcome_pnl_pct": round(pnl_pct, 4),
        "outcome_duration_minutes": round(duration),
        "outcome_at": resolved_at,
    }
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/engine/test_outcome_resolver.py -v`
Expected: All 4 tests PASS

**Step 5: Integrate resolver into pipeline**

In `backend/app/main.py`, add after the `run_pipeline` function:

```python
async def check_pending_signals(app: FastAPI):
    """Check all PENDING signals against recent candles for outcome resolution."""
    db = app.state.db
    redis = app.state.redis

    from app.engine.outcome_resolver import resolve_signal_outcome

    async with db.session_factory() as session:
        result = await session.execute(
            select(Signal).where(Signal.outcome == "PENDING").order_by(Signal.created_at.desc()).limit(50)
        )
        pending = result.scalars().all()

        for signal in pending:
            # Check expiry (24h)
            age = (datetime.now(timezone.utc) - signal.created_at).total_seconds()
            if age > 86400:
                signal.outcome = "EXPIRED"
                signal.outcome_at = datetime.now(timezone.utc)
                signal.outcome_duration_minutes = round(age / 60)
                continue

            cache_key = f"candles:{signal.pair}:{signal.timeframe}"
            raw_candles = await redis.lrange(cache_key, -200, -1)
            if not raw_candles:
                continue

            import json as _json
            candles_data = [_json.loads(c) for c in raw_candles]

            # Only check candles after signal creation
            signal_ts = signal.created_at.isoformat()
            candles_after = [c for c in candles_data if c["timestamp"] > signal_ts]
            if not candles_after:
                continue

            signal_dict = {
                "direction": signal.direction,
                "entry": float(signal.entry),
                "stop_loss": float(signal.stop_loss),
                "take_profit_1": float(signal.take_profit_1),
                "take_profit_2": float(signal.take_profit_2),
                "created_at": signal.created_at,
            }

            # Parse candle floats
            parsed = []
            for c in candles_after:
                parsed.append({
                    "high": float(c.get("high", c.get("h", 0))),
                    "low": float(c.get("low", c.get("l", 0))),
                    "close": float(c.get("close", c.get("c", 0))),
                    "timestamp": c["timestamp"],
                })

            outcome = resolve_signal_outcome(signal_dict, parsed)
            if outcome:
                signal.outcome = outcome["outcome"]
                signal.outcome_at = outcome["outcome_at"]
                signal.outcome_pnl_pct = outcome["outcome_pnl_pct"]
                signal.outcome_duration_minutes = outcome["outcome_duration_minutes"]

        await session.commit()
```

Add the periodic task in the `lifespan` function, after `poller_task`:

```python
    async def outcome_loop():
        while True:
            try:
                await check_pending_signals(app)
            except Exception as e:
                logger.error(f"Outcome check failed: {e}")
            await asyncio.sleep(60)

    outcome_task = asyncio.create_task(outcome_loop())
```

And cancel it during shutdown (before `await redis.close()`):

```python
    outcome_task.cancel()
```

**Step 6: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add backend/app/engine/outcome_resolver.py backend/tests/engine/test_outcome_resolver.py backend/app/main.py
git commit -m "feat: add signal outcome resolver with background task"
```

---

## Task 3: Add signal stats API endpoint

**Files:**
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/api/test_signal_stats.py`

**Step 1: Write the failing test**

Create `backend/tests/api/test_signal_stats.py`:

```python
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.mark.asyncio
async def test_signal_stats_endpoint(client):
    # Mock redis to return cached stats
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value='{"win_rate": 67.5, "avg_rr": 1.8, "total_resolved": 20, "total_wins": 13, "total_losses": 7, "by_pair": {}, "by_timeframe": {}}')

    client._transport.app.state.redis = mock_redis

    response = await client.get("/api/signals/stats", headers={"X-API-Key": "test-key"})
    assert response.status_code == 200
    data = response.json()
    assert "win_rate" in data
    assert "avg_rr" in data
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/api/test_signal_stats.py -v`
Expected: FAIL — 404 (route doesn't exist)

**Step 3: Write minimal implementation**

In `backend/app/api/routes.py`, add the `_signal_to_dict` function update and the stats endpoint.

Update `_signal_to_dict` to include outcome fields:

```python
def _signal_to_dict(signal: Signal) -> dict:
    return {
        "id": signal.id,
        "pair": signal.pair,
        "timeframe": signal.timeframe,
        "direction": signal.direction,
        "final_score": signal.final_score,
        "traditional_score": signal.traditional_score,
        "confidence": signal.llm_confidence or "LOW",
        "llm_opinion": signal.llm_opinion,
        "explanation": signal.explanation,
        "levels": {
            "entry": float(signal.entry),
            "stop_loss": float(signal.stop_loss),
            "take_profit_1": float(signal.take_profit_1),
            "take_profit_2": float(signal.take_profit_2),
        },
        "outcome": signal.outcome,
        "outcome_pnl_pct": float(signal.outcome_pnl_pct) if signal.outcome_pnl_pct else None,
        "outcome_duration_minutes": signal.outcome_duration_minutes,
        "outcome_at": signal.outcome_at.isoformat() if signal.outcome_at else None,
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
    }
```

Add stats endpoint inside `create_router()`:

```python
    @router.get("/signals/stats")
    async def get_signal_stats(
        request: Request,
        _key: str = auth,
        days: int = Query(7, ge=1, le=90),
    ):
        redis = request.app.state.redis
        cache_key = f"signal_stats:{days}d"

        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

        db = request.app.state.db
        async with db.session_factory() as session:
            from datetime import datetime, timezone, timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            result = await session.execute(
                select(Signal)
                .where(Signal.created_at >= cutoff)
                .where(Signal.outcome != "PENDING")
            )
            resolved = result.scalars().all()

            if not resolved:
                stats = {"win_rate": 0, "avg_rr": 0, "total_resolved": 0, "total_wins": 0, "total_losses": 0, "by_pair": {}, "by_timeframe": {}}
            else:
                wins = [s for s in resolved if s.outcome in ("TP1_HIT", "TP2_HIT")]
                losses = [s for s in resolved if s.outcome == "SL_HIT"]
                expired = [s for s in resolved if s.outcome == "EXPIRED"]

                total = len(resolved)
                win_count = len(wins)
                loss_count = len(losses)
                win_rate = round(win_count / total * 100, 1) if total > 0 else 0

                # avg R:R = avg win pnl / avg loss pnl (absolute)
                avg_win = sum(float(s.outcome_pnl_pct or 0) for s in wins) / max(len(wins), 1)
                avg_loss = abs(sum(float(s.outcome_pnl_pct or 0) for s in losses) / max(len(losses), 1))
                avg_rr = round(avg_win / max(avg_loss, 0.01), 2)

                # by_pair breakdown
                by_pair = {}
                for s in resolved:
                    p = by_pair.setdefault(s.pair, {"wins": 0, "total": 0})
                    p["total"] += 1
                    if s.outcome in ("TP1_HIT", "TP2_HIT"):
                        p["wins"] += 1
                for p in by_pair.values():
                    p["win_rate"] = round(p["wins"] / p["total"] * 100, 1)

                # by_timeframe breakdown
                by_timeframe = {}
                for s in resolved:
                    t = by_timeframe.setdefault(s.timeframe, {"wins": 0, "total": 0})
                    t["total"] += 1
                    if s.outcome in ("TP1_HIT", "TP2_HIT"):
                        t["wins"] += 1
                for t in by_timeframe.values():
                    t["win_rate"] = round(t["wins"] / t["total"] * 100, 1)

                stats = {
                    "win_rate": win_rate,
                    "avg_rr": avg_rr,
                    "total_resolved": total,
                    "total_wins": win_count,
                    "total_losses": loss_count,
                    "total_expired": len(expired),
                    "by_pair": by_pair,
                    "by_timeframe": by_timeframe,
                }

            await redis.set(cache_key, json.dumps(stats), ex=300)
            return stats
```

**Important:** The `/signals/stats` route must be registered BEFORE `/signals/{signal_id}` to avoid the path parameter capturing "stats". Move the route above the `get_signal` endpoint.

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/api/test_signal_stats.py -v`
Expected: PASS

**Step 5: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/api/test_signal_stats.py
git commit -m "feat: add signal stats API endpoint with outcome in signal response"
```

---

## Task 4: Update frontend types and API for outcomes + stats

**Files:**
- Modify: `web/src/features/signals/types.ts`
- Modify: `web/src/shared/lib/api.ts`

**Step 1: Update signal types**

In `web/src/features/signals/types.ts`:

```typescript
export type Direction = "LONG" | "SHORT";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";
export type LlmOpinion = "confirm" | "caution" | "contradict";
export type Timeframe = "15m" | "1h" | "4h";
export type SignalOutcome = "PENDING" | "TP1_HIT" | "TP2_HIT" | "SL_HIT" | "EXPIRED";

export interface SignalLevels {
  entry: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
}

export interface Signal {
  id: number;
  pair: string;
  timeframe: Timeframe;
  direction: Direction;
  final_score: number;
  confidence: Confidence;
  traditional_score: number;
  llm_opinion: LlmOpinion | null;
  explanation: string | null;
  levels: SignalLevels;
  outcome: SignalOutcome;
  outcome_pnl_pct: number | null;
  outcome_duration_minutes: number | null;
  outcome_at: string | null;
  created_at: string;
}

export interface SignalStats {
  win_rate: number;
  avg_rr: number;
  total_resolved: number;
  total_wins: number;
  total_losses: number;
  total_expired?: number;
  by_pair: Record<string, { wins: number; total: number; win_rate: number }>;
  by_timeframe: Record<string, { wins: number; total: number; win_rate: number }>;
}
```

**Step 2: Add stats API call**

In `web/src/shared/lib/api.ts`, add to the `api` object:

```typescript
  getSignalStats: (days = 7) =>
    request<SignalStats>(`/api/signals/stats?days=${days}`),
```

And add the import at the top:

```typescript
import type { Signal, SignalStats } from "../../features/signals/types";
```

Remove the existing `import type { Signal }` line if it exists elsewhere.

**Step 3: Commit**

```bash
git add web/src/features/signals/types.ts web/src/shared/lib/api.ts
git commit -m "feat: add outcome types and stats API to frontend"
```

---

## Task 5: Redesign Layout — Sticky top bar + new tab structure

**Files:**
- Modify: `web/src/shared/components/Layout.tsx`
- Modify: `web/src/index.css`
- Modify: `web/tailwind.config.ts`
- Modify: `web/src/App.tsx`

**Step 1: Update Tailwind config**

In `web/tailwind.config.ts`, add new colors and safelist entries:

```typescript
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#121212",
        card: "#1A1A1A",
        "card-hover": "#222222",
        long: "#22C55E",
        short: "#EF4444",
        accent: "#22C55E",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  safelist: [
    "text-long", "text-short",
    "bg-long/5", "bg-short/5",
    "bg-long/10", "bg-short/10",
    "bg-long/20", "bg-short/20",
    "border-long/30", "border-short/30",
  ],
  plugins: [],
} satisfies Config;
```

**Step 2: Update global CSS**

Replace `web/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --safe-top: env(safe-area-inset-top, 0px);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
}

body {
  background-color: #121212;
  color: #ffffff;
  font-family: system-ui, -apple-system, sans-serif;
  margin: 0;
  -webkit-font-smoothing: antialiased;
  -webkit-tap-highlight-color: transparent;
  overscroll-behavior: none;
}

dialog::backdrop {
  background: rgba(0, 0, 0, 0.6);
}

dialog {
  margin: 0;
  margin-top: auto;
  padding: 0;
  border: none;
  max-height: 85vh;
  width: 100%;
  max-width: 32rem;
  border-radius: 1rem 1rem 0 0;
  overflow-y: auto;
  background: #1a1a1a;
  color: #ffffff;
}

/* iOS PWA safe areas */
.safe-top {
  padding-top: var(--safe-top);
}

.safe-bottom {
  padding-bottom: max(var(--safe-bottom), 0.5rem);
}

/* Smooth scrolling for iOS */
.scroll-container {
  -webkit-overflow-scrolling: touch;
  overflow-y: auto;
}

/* Hide scrollbars but allow scrolling */
.no-scrollbar::-webkit-scrollbar {
  display: none;
}
.no-scrollbar {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
```

**Step 3: Create TickerBar component**

Create `web/src/shared/components/TickerBar.tsx`:

```typescript
import { useSettingsStore } from "../../features/settings/store";
import { formatPrice } from "../lib/format";

interface TickerBarProps {
  price: number | null;
  change24h: number | null;
  pair: string;
  onPairChange: (pair: string) => void;
  pairs: readonly string[];
}

export function TickerBar({ price, change24h, pair, onPairChange, pairs }: TickerBarProps) {
  const isPositive = (change24h ?? 0) >= 0;

  return (
    <div className="sticky top-0 z-30 bg-surface/90 backdrop-blur-md border-b border-gray-800/50 safe-top">
      <div className="flex items-center justify-between px-3 py-2">
        <select
          value={pair}
          onChange={(e) => onPairChange(e.target.value)}
          className="bg-transparent text-white font-bold text-sm border-none outline-none appearance-none pr-4"
          style={{ backgroundImage: "url(\"data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%239CA3AF' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e\")", backgroundPosition: "right 0 center", backgroundRepeat: "no-repeat", backgroundSize: "16px" }}
        >
          {pairs.map((p) => (
            <option key={p} value={p} className="bg-card">{p.replace("-SWAP", "")}</option>
          ))}
        </select>
        <div className="flex items-center gap-2">
          {price !== null && (
            <span className="font-mono font-bold text-sm">${formatPrice(price)}</span>
          )}
          {change24h !== null && (
            <span className={`text-xs font-mono ${isPositive ? "text-long" : "text-short"}`}>
              {isPositive ? "+" : ""}{change24h.toFixed(2)}%
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
```

**Step 4: Redesign Layout component**

Replace `web/src/shared/components/Layout.tsx`:

```typescript
import { useState, type ReactNode } from "react";
import { AVAILABLE_PAIRS } from "../lib/constants";
import { TickerBar } from "./TickerBar";

type Tab = "home" | "chart" | "signals" | "more";

interface LayoutProps {
  home: ReactNode;
  chart: ReactNode;
  signals: ReactNode;
  more: ReactNode;
  price: number | null;
  change24h: number | null;
  selectedPair: string;
  onPairChange: (pair: string) => void;
}

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: "home", label: "Home", icon: "◉" },
  { key: "chart", label: "Chart", icon: "◧" },
  { key: "signals", label: "Signals", icon: "⚡" },
  { key: "more", label: "More", icon: "≡" },
];

export function Layout({ home, chart, signals, more, price, change24h, selectedPair, onPairChange }: LayoutProps) {
  const [tab, setTab] = useState<Tab>("home");

  const content = { home, chart, signals, more }[tab];

  return (
    <div className="min-h-screen bg-surface text-white flex flex-col">
      <TickerBar
        price={price}
        change24h={change24h}
        pair={selectedPair}
        onPairChange={onPairChange}
        pairs={AVAILABLE_PAIRS}
      />
      <main className="flex-1 overflow-y-auto pb-16 scroll-container">{content}</main>
      <nav className="fixed bottom-0 left-0 right-0 bg-card/95 backdrop-blur-md border-t border-gray-800/50 flex safe-bottom z-30">
        {TABS.map(({ key, label, icon }) => (
          <TabButton key={key} active={tab === key} onClick={() => setTab(key)} label={label} icon={icon} />
        ))}
      </nav>
    </div>
  );
}

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  label: string;
  icon: string;
}

function TabButton({ active, onClick, label, icon }: TabButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 py-2 flex flex-col items-center gap-0.5 text-xs font-medium transition-colors ${
        active ? "text-long" : "text-gray-500"
      }`}
    >
      <span className="text-base">{icon}</span>
      {label}
    </button>
  );
}
```

**Step 5: Update App.tsx**

Replace `web/src/App.tsx`:

```typescript
import { useState } from "react";
import { Layout } from "./shared/components/Layout";
import { HomeView } from "./features/home/components/HomeView";
import { ChartView } from "./features/chart/components/ChartView";
import { SignalFeed } from "./features/signals/components/SignalFeed";
import { MorePage } from "./features/more/components/MorePage";
import { useSignalWebSocket } from "./features/signals/hooks/useSignalWebSocket";
import { useLivePrice } from "./shared/hooks/useLivePrice";
import { AVAILABLE_PAIRS } from "./shared/lib/constants";

export default function App() {
  const [selectedPair, setSelectedPair] = useState<string>(AVAILABLE_PAIRS[0]);
  useSignalWebSocket();
  const { price, change24h } = useLivePrice(selectedPair);

  return (
    <Layout
      home={<HomeView pair={selectedPair} />}
      chart={<ChartView pair={selectedPair} />}
      signals={<SignalFeed />}
      more={<MorePage />}
      price={price}
      change24h={change24h}
      selectedPair={selectedPair}
      onPairChange={setSelectedPair}
    />
  );
}
```

**Step 6: Create useLivePrice hook**

Create `web/src/shared/hooks/useLivePrice.ts`:

```typescript
import { useEffect, useState, useRef } from "react";

const OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public";

export function useLivePrice(pair: string) {
  const [price, setPrice] = useState<number | null>(null);
  const [change24h, setChange24h] = useState<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let ws: WebSocket;
    let shouldReconnect = true;
    let timer: ReturnType<typeof setTimeout>;

    function connect() {
      ws = new WebSocket(OKX_WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({
          op: "subscribe",
          args: [{ channel: "tickers", instId: pair }],
        }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.data?.[0]) {
            const d = msg.data[0];
            setPrice(Number(d.last));
            // 24h change % = (last - open24h) / open24h * 100
            if (d.open24h) {
              const open = Number(d.open24h);
              const last = Number(d.last);
              setChange24h(((last - open) / open) * 100);
            }
          }
        } catch { /* ignore */ }
      };

      ws.onclose = () => {
        if (shouldReconnect) timer = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      shouldReconnect = false;
      clearTimeout(timer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [pair]);

  return { price, change24h };
}
```

**Step 7: Create stub components (HomeView, MorePage)**

Create `web/src/features/home/components/HomeView.tsx`:

```typescript
interface Props {
  pair: string;
}

export function HomeView({ pair }: Props) {
  return (
    <div className="p-4">
      <p className="text-gray-500 text-center mt-12">Home — coming next</p>
    </div>
  );
}
```

Create `web/src/features/more/components/MorePage.tsx`:

```typescript
export function MorePage() {
  return (
    <div className="p-4">
      <p className="text-gray-500 text-center mt-12">More — coming next</p>
    </div>
  );
}
```

**Step 8: Verify it compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No errors

**Step 9: Commit**

```bash
git add web/src/shared/components/Layout.tsx web/src/shared/components/TickerBar.tsx web/src/shared/hooks/useLivePrice.ts web/src/App.tsx web/src/index.css web/tailwind.config.ts web/src/features/home/components/HomeView.tsx web/src/features/more/components/MorePage.tsx
git commit -m "feat: redesign layout with sticky ticker bar and new tab structure"
```

---

## Task 6: Build Home tab — mini chart + indicators + recent signals + stats

**Files:**
- Modify: `web/src/features/home/components/HomeView.tsx`
- Create: `web/src/features/home/components/IndicatorStrip.tsx`
- Create: `web/src/features/home/components/RecentSignals.tsx`
- Create: `web/src/features/home/components/PerformanceStrip.tsx`
- Create: `web/src/features/home/hooks/useSignalStats.ts`

**Step 1: Create useSignalStats hook**

Create `web/src/features/home/hooks/useSignalStats.ts`:

```typescript
import { useEffect, useState } from "react";
import { api } from "../../../shared/lib/api";
import type { SignalStats } from "../../signals/types";

export function useSignalStats(days = 7) {
  const [stats, setStats] = useState<SignalStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function fetch() {
      try {
        const data = await api.getSignalStats(days);
        if (!cancelled) setStats(data);
      } catch {
        // silently fail
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetch();
    const id = setInterval(fetch, 60000); // refresh every minute
    return () => { cancelled = true; clearInterval(id); };
  }, [days]);

  return { stats, loading };
}
```

**Step 2: Create PerformanceStrip**

Create `web/src/features/home/components/PerformanceStrip.tsx`:

```typescript
import type { SignalStats } from "../../signals/types";

interface Props {
  stats: SignalStats | null;
  loading: boolean;
}

export function PerformanceStrip({ stats, loading }: Props) {
  if (loading) return <div className="h-16 bg-card rounded-lg animate-pulse" />;
  if (!stats || stats.total_resolved === 0) return null;

  return (
    <div className="bg-card rounded-lg p-3">
      <div className="grid grid-cols-3 gap-2 text-center">
        <StatCell label="Win Rate" value={`${stats.win_rate}%`} color={stats.win_rate >= 50 ? "text-long" : "text-short"} />
        <StatCell label="Avg R:R" value={`${stats.avg_rr}`} color="text-white" />
        <StatCell label="Signals" value={`${stats.total_resolved}`} color="text-white" />
      </div>
      {Object.keys(stats.by_pair).length > 0 && (
        <div className="flex gap-3 mt-2 pt-2 border-t border-gray-800 text-xs text-gray-400 overflow-x-auto no-scrollbar">
          {Object.entries(stats.by_pair).map(([pair, data]) => (
            <span key={pair}>
              {pair.replace("-USDT-SWAP", "")}: <span className={data.win_rate >= 50 ? "text-long" : "text-short"}>{data.win_rate}%</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function StatCell({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div className={`text-lg font-mono font-bold ${color}`}>{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}
```

**Step 3: Create IndicatorStrip**

Create `web/src/features/home/components/IndicatorStrip.tsx`:

```typescript
interface Indicator {
  label: string;
  value: string;
  sentiment: "bullish" | "bearish" | "neutral";
}

interface Props {
  indicators: Indicator[];
}

export function IndicatorStrip({ indicators }: Props) {
  if (indicators.length === 0) return null;

  const colors = {
    bullish: "bg-long/15 text-long border-long/20",
    bearish: "bg-short/15 text-short border-short/20",
    neutral: "bg-gray-800/50 text-gray-400 border-gray-700/30",
  };

  return (
    <div className="flex gap-2 overflow-x-auto no-scrollbar py-1">
      {indicators.map((ind) => (
        <span
          key={ind.label}
          className={`shrink-0 px-2 py-1 rounded-md text-xs font-mono border ${colors[ind.sentiment]}`}
        >
          {ind.label} {ind.value}
        </span>
      ))}
    </div>
  );
}
```

**Step 4: Create RecentSignals**

Create `web/src/features/home/components/RecentSignals.tsx`:

```typescript
import { useSignalStore } from "../../signals/store";
import { formatScore, formatPrice, formatTime } from "../../../shared/lib/format";
import type { Signal } from "../../signals/types";

interface Props {
  onViewAll: () => void;
}

export function RecentSignals({ onViewAll }: Props) {
  const signals = useSignalStore((s) => s.signals.slice(0, 3));

  if (signals.length === 0) {
    return (
      <div className="bg-card rounded-lg p-4 text-center">
        <p className="text-gray-500 text-sm">No signals yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-xs text-gray-400 font-medium uppercase tracking-wider">Latest Signals</h2>
        <button onClick={onViewAll} className="text-xs text-long">View all</button>
      </div>
      {signals.map((signal) => (
        <CompactSignalCard key={signal.id} signal={signal} />
      ))}
    </div>
  );
}

function CompactSignalCard({ signal }: { signal: Signal }) {
  const isLong = signal.direction === "LONG";
  const dirColor = isLong ? "text-long" : "text-short";
  const borderColor = isLong ? "border-long/20" : "border-short/20";

  const outcomeBadge = signal.outcome && signal.outcome !== "PENDING" ? (
    <OutcomeBadge outcome={signal.outcome} />
  ) : null;

  return (
    <div className={`bg-card rounded-lg p-3 border ${borderColor}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`font-mono font-bold text-sm ${dirColor}`}>
            {signal.direction}
          </span>
          <span className="text-sm font-medium">{signal.pair.replace("-USDT-SWAP", "")}</span>
          <span className="text-xs text-gray-500">{signal.timeframe}</span>
        </div>
        <div className="flex items-center gap-2">
          {outcomeBadge}
          <span className={`font-mono text-sm font-bold ${dirColor}`}>
            {formatScore(signal.final_score)}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-3 mt-1.5 text-xs text-gray-400 font-mono">
        <span>E {formatPrice(signal.levels.entry)}</span>
        <span className="text-short">SL {formatPrice(signal.levels.stop_loss)}</span>
        <span className="text-long">TP {formatPrice(signal.levels.take_profit_1)}</span>
        <span className="ml-auto">{formatTime(signal.created_at)}</span>
      </div>
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    TP1_HIT: "bg-long/20 text-long",
    TP2_HIT: "bg-long/20 text-long",
    SL_HIT: "bg-short/20 text-short",
    EXPIRED: "bg-gray-700/50 text-gray-400",
  };
  const labels: Record<string, string> = {
    TP1_HIT: "TP1",
    TP2_HIT: "TP2",
    SL_HIT: "SL",
    EXPIRED: "EXP",
  };

  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${styles[outcome] ?? ""}`}>
      {labels[outcome] ?? outcome}
    </span>
  );
}
```

**Step 5: Build HomeView**

Replace `web/src/features/home/components/HomeView.tsx`:

```typescript
import { useState } from "react";
import { CandlestickChart } from "../../chart/components/CandlestickChart";
import { useChartData } from "../../chart/hooks/useChartData";
import { PerformanceStrip } from "./PerformanceStrip";
import { RecentSignals } from "./RecentSignals";
import { useSignalStats } from "../hooks/useSignalStats";
import type { Timeframe } from "../../signals/types";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

interface Props {
  pair: string;
}

export function HomeView({ pair }: Props) {
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const { candles, loading } = useChartData(pair, timeframe);
  const { stats, loading: statsLoading } = useSignalStats();

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* Mini Chart */}
      <div className="bg-card rounded-lg overflow-hidden">
        <div className="relative h-[200px]">
          {loading ? (
            <div className="w-full h-full animate-pulse bg-card" />
          ) : (
            <CandlestickChart candles={candles} />
          )}
        </div>
        <div className="flex gap-1 p-2 border-t border-gray-800/50">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`flex-1 py-1.5 rounded text-xs font-medium transition-colors ${
                timeframe === tf
                  ? "bg-long/15 text-long"
                  : "text-gray-500 active:bg-gray-800"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Performance Stats */}
      <PerformanceStrip stats={stats} loading={statsLoading} />

      {/* Recent Signals */}
      <RecentSignals onViewAll={() => {/* TODO: switch tab */}} />
    </div>
  );
}
```

**Step 6: Verify it compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No errors

**Step 7: Commit**

```bash
git add web/src/features/home/
git commit -m "feat: build Home tab with mini chart, performance stats, and recent signals"
```

---

## Task 7: Redesign Signals tab with outcome badges and performance header

**Files:**
- Modify: `web/src/features/signals/components/SignalFeed.tsx`
- Modify: `web/src/features/signals/components/SignalCard.tsx`
- Modify: `web/src/features/signals/components/SignalDetail.tsx`

**Step 1: Redesign SignalFeed with performance header**

Replace `web/src/features/signals/components/SignalFeed.tsx`:

```typescript
import { useState } from "react";
import { useSignalStore } from "../store";
import { SignalCard } from "./SignalCard";
import { SignalDetail } from "./SignalDetail";
import { ConnectionStatus } from "./ConnectionStatus";
import { OrderDialog } from "../../trading/components/OrderDialog";
import { PerformanceStrip } from "../../home/components/PerformanceStrip";
import { useSignalStats } from "../../home/hooks/useSignalStats";
import type { Signal } from "../types";

export function SignalFeed() {
  const { signals, selectedSignal, selectSignal, clearSelection } =
    useSignalStore();
  const [tradingSignal, setTradingSignal] = useState<Signal | null>(null);
  const { stats, loading: statsLoading } = useSignalStats();

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-bold uppercase tracking-wider text-gray-400">Signals</h1>
        <ConnectionStatus />
      </div>

      <PerformanceStrip stats={stats} loading={statsLoading} />

      {signals.length === 0 ? (
        <p className="text-gray-500 text-center text-sm mt-8">
          Waiting for signals...
        </p>
      ) : (
        <div className="space-y-2">
          {signals.map((signal) => (
            <SignalCard
              key={signal.id}
              signal={signal}
              onSelect={selectSignal}
              onExecute={setTradingSignal}
            />
          ))}
        </div>
      )}

      <SignalDetail signal={selectedSignal} onClose={clearSelection} />
      <OrderDialog signal={tradingSignal} onClose={() => setTradingSignal(null)} />
    </div>
  );
}
```

**Step 2: Redesign SignalCard with outcome badge**

Replace `web/src/features/signals/components/SignalCard.tsx`:

```typescript
import type { Signal } from "../types";
import { formatScore, formatPrice, formatTime } from "../../../shared/lib/format";

interface SignalCardProps {
  signal: Signal;
  onSelect: (signal: Signal) => void;
  onExecute?: (signal: Signal) => void;
}

export function SignalCard({ signal, onSelect, onExecute }: SignalCardProps) {
  const isLong = signal.direction === "LONG";
  const dirColor = isLong ? "text-long" : "text-short";
  const borderColor = isLong ? "border-long/20" : "border-short/20";
  const bgColor = isLong ? "bg-long/5" : "bg-short/5";

  const isPending = !signal.outcome || signal.outcome === "PENDING";

  return (
    <button
      onClick={() => onSelect(signal)}
      className={`w-full p-3 rounded-lg border text-left transition-colors active:opacity-80 ${borderColor} ${bgColor}`}
    >
      {/* Row 1: Direction, pair, score, outcome */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`font-mono font-bold text-sm ${dirColor}`}>
            {signal.direction}
          </span>
          <span className="font-medium text-sm">{signal.pair.replace("-USDT-SWAP", "")}</span>
          <span className="text-xs text-gray-500">{signal.timeframe}</span>
        </div>
        <div className="flex items-center gap-2">
          {!isPending && <OutcomeBadge outcome={signal.outcome} />}
          <span className={`font-mono font-bold text-sm ${dirColor}`}>
            {formatScore(signal.final_score)}
          </span>
        </div>
      </div>

      {/* Row 2: Levels */}
      <div className="flex items-center gap-3 mt-1.5 text-xs font-mono text-gray-400">
        <span>E {formatPrice(signal.levels.entry)}</span>
        <span className="text-short">SL {formatPrice(signal.levels.stop_loss)}</span>
        <span className="text-long">TP {formatPrice(signal.levels.take_profit_1)}</span>
      </div>

      {/* Row 3: Meta + outcome details */}
      <div className="flex items-center justify-between mt-1.5">
        <div className="flex items-center gap-2">
          <ConfidenceBadge confidence={signal.confidence} />
          {!isPending && signal.outcome_pnl_pct != null && (
            <span className={`text-xs font-mono ${signal.outcome_pnl_pct >= 0 ? "text-long" : "text-short"}`}>
              {signal.outcome_pnl_pct >= 0 ? "+" : ""}{signal.outcome_pnl_pct.toFixed(2)}%
            </span>
          )}
          {!isPending && signal.outcome_duration_minutes != null && (
            <span className="text-xs text-gray-500">
              {formatDuration(signal.outcome_duration_minutes)}
            </span>
          )}
        </div>
        <span className="text-xs text-gray-500">
          {formatTime(signal.created_at)}
        </span>
      </div>

      {/* Execute button (only for pending signals) */}
      {onExecute && isPending && (
        <button
          onClick={(e) => { e.stopPropagation(); onExecute(signal); }}
          className={`mt-2 w-full py-2 rounded text-xs font-medium transition-colors active:opacity-80 ${
            isLong ? "bg-long/15 text-long" : "bg-short/15 text-short"
          }`}
        >
          Execute {signal.direction}
        </button>
      )}
    </button>
  );
}

function ConfidenceBadge({ confidence }: { confidence: Signal["confidence"] }) {
  const styles = {
    HIGH: "bg-yellow-500/15 text-yellow-400",
    MEDIUM: "bg-blue-500/15 text-blue-400",
    LOW: "bg-gray-600/30 text-gray-400",
  };

  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${styles[confidence]}`}>
      {confidence}
    </span>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    TP1_HIT: "bg-long/20 text-long",
    TP2_HIT: "bg-long/20 text-long",
    SL_HIT: "bg-short/20 text-short",
    EXPIRED: "bg-gray-700/50 text-gray-400",
  };
  const labels: Record<string, string> = {
    TP1_HIT: "TP1 Hit",
    TP2_HIT: "TP2 Hit",
    SL_HIT: "SL Hit",
    EXPIRED: "Expired",
  };

  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${styles[outcome] ?? ""}`}>
      {labels[outcome] ?? outcome}
    </span>
  );
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}
```

**Step 3: Update SignalDetail to show outcome**

In `web/src/features/signals/components/SignalDetail.tsx`, add outcome section after price levels:

Add before the closing `</dialog>`:

```typescript
      {signal.outcome && signal.outcome !== "PENDING" && (
        <div className="p-4 border-t border-gray-800">
          <h3 className="text-sm text-gray-400 mb-2">Outcome</h3>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>Result: <span className={`font-mono font-bold ${signal.outcome.includes("TP") ? "text-long" : "text-short"}`}>{signal.outcome.replace("_", " ")}</span></div>
            {signal.outcome_pnl_pct != null && (
              <div>P&L: <span className={`font-mono ${signal.outcome_pnl_pct >= 0 ? "text-long" : "text-short"}`}>{signal.outcome_pnl_pct >= 0 ? "+" : ""}{signal.outcome_pnl_pct.toFixed(2)}%</span></div>
            )}
            {signal.outcome_duration_minutes != null && (
              <div>Duration: <span className="font-mono">{signal.outcome_duration_minutes < 60 ? `${signal.outcome_duration_minutes}m` : `${Math.floor(signal.outcome_duration_minutes / 60)}h ${signal.outcome_duration_minutes % 60}m`}</span></div>
            )}
          </div>
        </div>
      )}
```

**Step 4: Verify it compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No errors

**Step 5: Commit**

```bash
git add web/src/features/signals/components/
git commit -m "feat: redesign signal cards with outcome badges and performance header"
```

---

## Task 8: Redesign Chart tab with signal markers

**Files:**
- Modify: `web/src/features/chart/components/ChartView.tsx`
- Modify: `web/src/features/chart/components/CandlestickChart.tsx`

**Step 1: Update ChartView to accept pair prop and show signal markers**

Replace `web/src/features/chart/components/ChartView.tsx`:

```typescript
import { useState } from "react";
import { useChartData } from "../hooks/useChartData";
import { CandlestickChart } from "./CandlestickChart";
import { useSignalStore } from "../../signals/store";
import type { Timeframe } from "../../signals/types";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

interface Props {
  pair: string;
}

export function ChartView({ pair }: Props) {
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const { candles, loading } = useChartData(pair, timeframe);
  const signals = useSignalStore((s) =>
    s.signals.filter((sig) => sig.pair === pair && sig.timeframe === timeframe)
  );

  return (
    <div className="flex flex-col h-[calc(100vh-6.5rem)]">
      {/* Timeframe selector */}
      <div className="flex gap-1 px-3 py-2">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            onClick={() => setTimeframe(tf)}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              timeframe === tf
                ? "bg-long/15 text-long"
                : "text-gray-500 active:bg-gray-800"
            }`}
          >
            {tf}
          </button>
        ))}
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0 px-2 pb-2">
        {loading ? (
          <div className="w-full h-full bg-card rounded-lg animate-pulse" />
        ) : (
          <div className="relative w-full h-full rounded-lg overflow-hidden">
            <CandlestickChart candles={candles} signals={signals} />
          </div>
        )}
      </div>
    </div>
  );
}
```

**Step 2: Update CandlestickChart to render signal markers**

Replace `web/src/features/chart/components/CandlestickChart.tsx`:

```typescript
import { useEffect, useRef } from "react";
import { createChart, CandlestickSeries, type IChartApi, type ISeriesApi, ColorType } from "lightweight-charts";
import type { CandleData } from "../../../shared/lib/api";
import type { Signal } from "../../signals/types";

interface Props {
  candles: CandleData[];
  signals?: Signal[];
}

export function CandlestickChart({ candles, signals }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#1A1A1A" },
        textColor: "#6B7280",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "#1F293708" },
        horzLines: { color: "#1F2937" },
      },
      rightPriceScale: {
        borderVisible: false,
        textColor: "#6B7280",
      },
      crosshair: { mode: 1 },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderVisible: false,
        barSpacing: 6,
      },
      handleScroll: true,
      handleScale: true,
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22C55E",
      downColor: "#EF4444",
      borderVisible: false,
      wickUpColor: "#22C55E",
      wickDownColor: "#EF4444",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || candles.length === 0) return;
    const mapped = candles.map((c) => ({
      time: (typeof c.timestamp === "number" ? c.timestamp / 1000 : new Date(c.timestamp).getTime() / 1000) as any,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    seriesRef.current.setData(mapped);
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  useEffect(() => {
    if (!seriesRef.current || !signals?.length) return;
    const markers = signals.map((sig) => ({
      time: (new Date(sig.created_at).getTime() / 1000) as any,
      position: sig.direction === "LONG" ? "belowBar" as const : "aboveBar" as const,
      color: sig.direction === "LONG" ? "#22C55E" : "#EF4444",
      shape: sig.direction === "LONG" ? "arrowUp" as const : "arrowDown" as const,
      text: `${sig.direction} ${sig.final_score}`,
    }));
    seriesRef.current.setMarkers(markers);
  }, [signals]);

  return <div ref={containerRef} className="absolute inset-0" />;
}
```

**Step 3: Verify it compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add web/src/features/chart/
git commit -m "feat: redesign chart tab with signal markers and pair prop"
```

---

## Task 9: Build More tab (account + settings combined)

**Files:**
- Modify: `web/src/features/more/components/MorePage.tsx`

**Step 1: Build MorePage with collapsible sections**

Replace `web/src/features/more/components/MorePage.tsx`:

```typescript
import { useState } from "react";
import { AccountSummary } from "../../dashboard/components/AccountSummary";
import { PositionList } from "../../dashboard/components/PositionList";
import { useAccount } from "../../dashboard/hooks/useAccount";
import { useSettingsStore } from "../../settings/store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";
import type { Timeframe } from "../../signals/types";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

function toggleItem<T>(list: T[], item: T, minOne = true): T[] {
  if (list.includes(item)) {
    if (minOne && list.length <= 1) return list;
    return list.filter((i) => i !== item);
  }
  return [...list, item];
}

export function MorePage() {
  const { balance, positions, loading, error } = useAccount();
  const {
    pairs, timeframes, threshold, notificationsEnabled, apiBaseUrl,
    setPairs, setTimeframes, setThreshold, setNotificationsEnabled, setApiBaseUrl,
  } = useSettingsStore();
  const [pushStatus, setPushStatus] = useState<"idle" | "subscribing" | "error">("idle");

  async function handleNotificationToggle(enabled: boolean) {
    setNotificationsEnabled(enabled);
    if (enabled) {
      setPushStatus("subscribing");
      const ok = await subscribeToPush(pairs, timeframes, threshold);
      setPushStatus(ok ? "idle" : "error");
      if (!ok) setNotificationsEnabled(false);
    } else {
      await unsubscribeFromPush();
    }
  }

  return (
    <div className="p-3 space-y-3">
      {/* Account Section */}
      <Section title="Account">
        {error && (
          <div className="p-2 bg-short/10 border border-short/30 rounded-lg text-xs text-short mb-2">
            {error}
          </div>
        )}
        <AccountSummary balance={balance} loading={loading} />
        <div className="mt-2">
          <PositionList positions={positions} />
        </div>
      </Section>

      {/* Settings Section */}
      <Section title="Settings">
        {/* Pairs */}
        <div className="mb-3">
          <label className="text-xs text-gray-500 uppercase tracking-wider mb-1.5 block">Pairs</label>
          <div className="space-y-1.5">
            {AVAILABLE_PAIRS.map((pair) => (
              <label key={pair} className="flex items-center gap-3 p-2.5 bg-card rounded-lg cursor-pointer">
                <input
                  type="checkbox"
                  checked={pairs.includes(pair)}
                  onChange={() => setPairs(toggleItem(pairs, pair))}
                  className="accent-long w-4 h-4"
                />
                <span className="text-sm">{pair}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Timeframes */}
        <div className="mb-3">
          <label className="text-xs text-gray-500 uppercase tracking-wider mb-1.5 block">Timeframes</label>
          <div className="flex gap-1.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframes(toggleItem(timeframes, tf))}
                className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
                  timeframes.includes(tf)
                    ? "bg-long/15 text-long"
                    : "bg-card text-gray-500 active:bg-gray-800"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        {/* Threshold */}
        <div className="mb-3">
          <label className="text-xs text-gray-500 uppercase tracking-wider mb-1.5 block">
            Alert Threshold: <span className="text-white font-mono">{threshold}</span>
          </label>
          <input
            type="range"
            min={0}
            max={100}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-full accent-long"
          />
          <div className="flex justify-between text-xs text-gray-600 mt-0.5">
            <span>All</span>
            <span>Strong only</span>
          </div>
        </div>

        {/* Push Notifications */}
        <label className="flex items-center justify-between p-2.5 bg-card rounded-lg cursor-pointer mb-3">
          <div>
            <span className="text-sm">Push Notifications</span>
            {pushStatus === "error" && (
              <p className="text-xs text-short mt-0.5">Permission denied</p>
            )}
          </div>
          <input
            type="checkbox"
            checked={notificationsEnabled}
            disabled={pushStatus === "subscribing"}
            onChange={(e) => handleNotificationToggle(e.target.checked)}
            className="accent-long w-4 h-4"
          />
        </label>

        {/* API URL */}
        <div>
          <label className="text-xs text-gray-500 uppercase tracking-wider mb-1.5 block">API URL</label>
          <input
            type="url"
            value={apiBaseUrl}
            onChange={(e) => setApiBaseUrl(e.target.value)}
            className="w-full p-2.5 bg-card rounded-lg border border-gray-800 text-sm font-mono focus:border-long/50 focus:outline-none"
          />
        </div>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-xs text-gray-400 font-medium uppercase tracking-wider mb-2">{title}</h2>
      {children}
    </div>
  );
}
```

**Step 2: Verify it compiles**

Run: `cd web && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add web/src/features/more/
git commit -m "feat: build More tab with account info and settings"
```

---

## Task 10: Clean up old files and final integration

**Files:**
- Delete: `web/src/features/dashboard/components/Dashboard.tsx` (moved to More)
- Delete: `web/src/features/settings/components/SettingsPage.tsx` (moved to More)
- Verify all imports resolve

**Step 1: Remove old unused components**

The Dashboard and SettingsPage are now integrated into MorePage and HomeView. Keep the AccountSummary, PositionList, useAccount, and settings store since they're reused.

Check if any file still imports Dashboard or SettingsPage directly. If not, delete them:

```bash
rm web/src/features/dashboard/components/Dashboard.tsx
rm web/src/features/settings/components/SettingsPage.tsx
```

**Step 2: Run full TypeScript check**

Run: `cd web && npx tsc --noEmit`
Expected: No errors

**Step 3: Run frontend dev server to visually verify**

Run: `cd web && npm run dev`
Expected: App loads with new layout, 4 tabs, ticker bar

**Step 4: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: complete mobile UI redesign with signal accuracy tracking"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Signal outcome DB fields | models.py, migration SQL |
| 2 | Outcome resolver background task | outcome_resolver.py, main.py |
| 3 | Signal stats API endpoint | routes.py |
| 4 | Frontend types + API for outcomes | types.ts, api.ts |
| 5 | Layout redesign (ticker bar, tabs) | Layout.tsx, TickerBar.tsx, App.tsx, index.css |
| 6 | Home tab (mini chart, stats, signals) | HomeView.tsx + sub-components |
| 7 | Signals tab redesign (outcome badges) | SignalFeed.tsx, SignalCard.tsx, SignalDetail.tsx |
| 8 | Chart tab with signal markers | ChartView.tsx, CandlestickChart.tsx |
| 9 | More tab (account + settings) | MorePage.tsx |
| 10 | Cleanup + integration | Remove old files, verify |
