# Journal & Analytics Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge Analytics + Deep Dive into a single scrollable Analytics view, improve Calendar with signal-level day detail, and remove journal notes/status UI.

**Architecture:** Backend gets one new endpoint (`GET /api/signals/by-date`) and one new field (`by_direction`) on the existing stats response. Frontend rewrites `AnalyticsView.tsx` to absorb all DeepDive content, rewrites `CalendarView.tsx` with polish + signal cards, removes journal notes from `SignalDetail.tsx`, and collapses JournalView from 3 tabs to 2. `DeepDiveView.tsx` and `PairDeepDive.tsx` are deleted.

**Tech Stack:** Python/FastAPI (backend), React 19 + TypeScript + Tailwind CSS v3 + Zustand (frontend)

---

## File Structure

### Modified
| File | Responsibility |
|------|---------------|
| `backend/app/api/routes.py` | Add `GET /api/signals/by-date` endpoint + `by_direction` to stats |
| `web/src/features/signals/types.ts` | Add `by_direction` to `SignalStats` type |
| `web/src/shared/lib/api.ts` | Add `getSignalsByDate` method |
| `web/src/features/signals/components/JournalView.tsx` | Remove Deep Dive tab (3 tabs -> 2) |
| `web/src/features/signals/components/SignalDetail.tsx` | Remove `JournalSection` + related imports/state |
| `web/src/features/signals/components/AnalyticsView.tsx` | Full rewrite — merged Analytics + DeepDive |
| `web/src/features/signals/components/CalendarView.tsx` | Visual polish + signal cards on day tap |

### Created
| File | Responsibility |
|------|---------------|
| `web/src/features/signals/hooks/useSignalsByDate.ts` | Hook for fetching signals by date (calendar day detail) |

### Deleted
| File | Reason |
|------|--------|
| `web/src/features/signals/components/DeepDiveView.tsx` | Absorbed into AnalyticsView |
| `web/src/features/signals/components/PairDeepDive.tsx` | No remaining imports (only self-referencing) |

---

### Task 1: Backend — Add `by_direction` to stats + `by-date` endpoint

**Files:**
- Modify: `backend/app/api/routes.py:349-388` (stats handler, add `by_direction` computation)
- Modify: `backend/app/api/routes.py:326-335` (empty-stats fallback, add `by_direction: {}`)
- Modify: `backend/app/api/routes.py:275-588` (add new `by-date` endpoint before `create_router` return)

- [ ] **Step 1: Add `by_direction` computation to `get_signal_stats`**

In `backend/app/api/routes.py`, inside the `else` branch of the stats handler (after `by_timeframe` computation, around line 371), add:

```python
                by_direction: dict[str, dict] = {}
                for s in resolved:
                    d = by_direction.setdefault(s.direction, {"wins": 0, "losses": 0, "total": 0, "pnl_sum": 0.0})
                    d["total"] += 1
                    pnl = float(s.outcome_pnl_pct or 0)
                    d["pnl_sum"] += pnl
                    if s.outcome in ("TP1_HIT", "TP2_HIT"):
                        d["wins"] += 1
                    elif s.outcome == "SL_HIT":
                        d["losses"] += 1
                for d in by_direction.values():
                    if d["total"] > 0:
                        d["win_rate"] = round(d["wins"] / d["total"] * 100, 1)
                        d["avg_pnl"] = round(d["pnl_sum"] / d["total"], 4)
                    else:
                        d["win_rate"] = 0.0
                        d["avg_pnl"] = 0.0
                    del d["pnl_sum"]
```

Add `"by_direction": by_direction` to the stats dict (alongside `"by_timeframe": by_timeframe`).

- [ ] **Step 2: Update empty-stats fallback**

In the `if not resolved:` branch (around line 326), add `"by_direction": {}` to the stats dict.

- [ ] **Step 3: Add `GET /api/signals/by-date` endpoint**

Add this new endpoint inside `create_router()`, after the `get_signal_stats` handler and before the `get_signal_calendar` handler:

```python
    @router.get("/signals/by-date")
    async def get_signals_by_date(
        request: Request,
        _key: str = auth,
        date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ):
        year, mon, day = map(int, date.split("-"))
        start = datetime(year, mon, day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)

        db = request.app.state.db
        async with db.session_factory() as session:
            result = await session.execute(
                select(Signal)
                .where(Signal.created_at >= start)
                .where(Signal.created_at < end)
                .order_by(Signal.created_at.asc())
            )
            signals = result.scalars().all()
            return [_signal_to_dict(s) for s in signals]
```

- [ ] **Step 4: Run backend tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All existing tests pass (no schema changes needed).

---

### Task 2: Frontend types + API client

**Files:**
- Modify: `web/src/features/signals/types.ts:120-135` (add `by_direction` to `SignalStats`)
- Modify: `web/src/shared/lib/api.ts:245-256` (add `getSignalsByDate` method)

- [ ] **Step 1: Add `by_direction` to `SignalStats` interface**

In `web/src/features/signals/types.ts`, add after the `by_timeframe` line (line 128):

```typescript
  by_direction: Record<string, { wins: number; losses: number; total: number; win_rate: number; avg_pnl: number }>;
```

- [ ] **Step 2: Add `getSignalsByDate` to API client**

In `web/src/shared/lib/api.ts`, add after the `getSignalCalendar` method (line 255):

```typescript
  getSignalsByDate: (date: string) =>
    request<Signal[]>(`/api/signals/by-date?date=${date}`),
```

- [ ] **Step 3: Verify frontend compiles**

Run: `cd web && pnpm build`
Expected: Build succeeds with no type errors.

---

### Task 3: JournalView — Remove Deep Dive tab

**Files:**
- Modify: `web/src/features/signals/components/JournalView.tsx` (full file — remove DeepDive import, tab, and rendering)

- [ ] **Step 1: Rewrite JournalView.tsx**

Replace the full contents of `web/src/features/signals/components/JournalView.tsx` with:

```tsx
import { useState } from "react";
import { AnalyticsView } from "./AnalyticsView";
import { CalendarView } from "./CalendarView";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";

type JournalTab = "analytics" | "calendar";

const TABS: { value: JournalTab; label: string }[] = [
  { value: "analytics", label: "Analytics" },
  { value: "calendar", label: "Calendar" },
];

export function JournalView() {
  const [tab, setTab] = useState<JournalTab>("analytics");

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 pt-3">
        <SegmentedControl
          options={TABS}
          value={tab}
          onChange={setTab}
          fullWidth
        />
      </div>

      {tab === "analytics" && <AnalyticsView />}
      {tab === "calendar" && <CalendarView />}
    </div>
  );
}
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd web && pnpm build`
Expected: Build succeeds (DeepDiveView still exists but is unused — deletion comes in Task 8).

---

### Task 4: SignalDetail — Remove JournalSection

**Files:**
- Modify: `web/src/features/signals/components/SignalDetail.tsx` (remove JournalSection function + its usage + related imports)

- [ ] **Step 1: Remove JournalSection and related code**

In `web/src/features/signals/components/SignalDetail.tsx`:

1. Remove the `USER_STATUSES` const (lines 12-16)
2. Remove the import of `UserStatus` from the type import on line 3 (keep `Signal`)
3. Remove the import of `api` (line 5) — only used by JournalSection
4. Remove the import of `useSignalStore` (line 6) — only used by JournalSection
5. Remove `<JournalSection signal={signal} />` call (line 165)
6. Delete the entire `JournalSection` function (lines 219-318)

After edits, the type import on line 3 should be:
```typescript
import type { Signal } from "../types";
```

And remove these imports entirely:
```typescript
import { api } from "../../../shared/lib/api";
import { useSignalStore } from "../store";
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd web && pnpm build`
Expected: Build succeeds with no type errors.

---

### Task 5: Create `useSignalsByDate` hook

**Files:**
- Create: `web/src/features/signals/hooks/useSignalsByDate.ts`

- [ ] **Step 1: Write the hook**

Create `web/src/features/signals/hooks/useSignalsByDate.ts`:

```typescript
import { useEffect, useState } from "react";
import { api } from "../../../shared/lib/api";
import type { Signal } from "../types";

export function useSignalsByDate(date: string | null) {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    if (!date) {
      setSignals([]);
      setLoading(false);
      setError(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(false);

    api.getSignalsByDate(date)
      .then((res) => {
        if (!cancelled) setSignals(res);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [date, retryCount]);

  const retry = () => setRetryCount((c) => c + 1);

  return { signals, loading, error, retry };
}
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd web && pnpm build`
Expected: Build succeeds (hook is unused but type-correct).

---

### Task 6: AnalyticsView — Full rewrite (merged layout)

**Files:**
- Modify: `web/src/features/signals/components/AnalyticsView.tsx` (complete rewrite)

This is the largest task. The new `AnalyticsView` merges all content from the current `AnalyticsView` + `DeepDiveView` into a single scrollable view with new breakdown sections.

- [ ] **Step 1: Rewrite AnalyticsView.tsx**

Replace the full contents of `web/src/features/signals/components/AnalyticsView.tsx`:

```tsx
import { useState, useId } from "react";
import { BarChart3 } from "lucide-react";
import { useSignalStats } from "../../home/hooks/useSignalStats";
import { theme } from "../../../shared/theme";
import { formatPair } from "../../../shared/lib/format";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { EmptyState } from "../../../shared/components/EmptyState";
import type { SignalStats, PerformanceMetrics } from "../types";

type Period = "7" | "30" | "365";

const PERIODS: { value: Period; label: string }[] = [
  { value: "7", label: "7D" },
  { value: "30", label: "30D" },
  { value: "365", label: "All" },
];

export function AnalyticsView() {
  const [period, setPeriod] = useState<Period>("7");
  const { stats, loading } = useSignalStats(Number(period));

  if (loading) {
    return (
      <div className="p-3 space-y-3">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="h-24 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none" />
        ))}
      </div>
    );
  }

  if (!stats || stats.total_resolved === 0) {
    return (
      <div className="p-3">
        <EmptyState
          icon={<BarChart3 size={32} />}
          title="No resolved signals yet"
          subtitle="Analytics will appear as signals resolve"
        />
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3 overflow-y-auto">
      {/* 1. Period selector */}
      <SegmentedControl options={PERIODS} value={period} onChange={setPeriod} />

      {/* 2. Hero KPI Bento */}
      <SummaryBento stats={stats} />

      {/* 3. Equity & Risk */}
      <h3 className="text-xs font-bold text-on-surface-variant uppercase tracking-widest px-1">Equity & Risk</h3>
      <EquityCurve data={stats.equity_curve} />
      <DrawdownChart data={stats.drawdown_series} maxDd={stats.performance.max_drawdown_pct} />

      {/* 4. Breakdowns */}
      <h3 className="text-xs font-bold text-on-surface-variant uppercase tracking-widest px-1">Breakdowns</h3>
      <PairBreakdown data={stats.by_pair} />
      <TimeframeBreakdown data={stats.by_timeframe} />
      <HourlyHeatmap data={stats.hourly_performance} />
      <DirectionBreakdown data={stats.by_direction} />

      {/* 5. Distribution & Streaks */}
      <h3 className="text-xs font-bold text-on-surface-variant uppercase tracking-widest px-1">Distribution & Streaks</h3>
      <PnlDistribution data={stats.pnl_distribution} />
      <StreakTracker streaks={stats.streaks} />
      <NotableTrades perf={stats.performance} />

      {/* 6. Risk Profile */}
      <RiskProfile perf={stats.performance} totalResolved={stats.total_resolved} />
    </div>
  );
}

// ─── SummaryBento ────────────────────────────────────────────────

function SummaryBento({ stats }: { stats: SignalStats }) {
  const netPnl = stats.equity_curve.length > 0
    ? stats.equity_curve[stats.equity_curve.length - 1].cumulative_pnl
    : 0;

  const expectancy = stats.performance.expectancy;
  const sharpe = stats.performance.sharpe_ratio;
  const showDash = stats.total_resolved < 5;

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* Net P&L — col-span-2 */}
      <div className="col-span-2 bg-surface-container rounded-lg p-4 border-l-4 border-tertiary-dim">
        <div className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-1">Net P&L</div>
        <div className={`font-headline text-3xl font-bold tabular-nums ${netPnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
          {netPnl >= 0 ? "+" : ""}{netPnl.toFixed(1)}%
        </div>
      </div>

      {/* Win Rate */}
      <div className="bg-surface-container rounded-lg p-4">
        <div className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-1">Win Rate</div>
        <div className={`font-headline text-2xl font-bold tabular-nums ${stats.win_rate >= 50 ? "text-tertiary-dim" : "text-error"}`}>
          {stats.win_rate}%
        </div>
      </div>

      {/* Expectancy */}
      <div className="bg-surface-container rounded-lg p-4">
        <div className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-1">Expectancy</div>
        <div className={`font-headline text-2xl font-bold tabular-nums ${
          showDash || expectancy == null ? "text-on-surface" : expectancy >= 0 ? "text-tertiary-dim" : "text-error"
        }`}>
          {showDash || expectancy == null ? "—" : `${expectancy >= 0 ? "+" : ""}${expectancy}%`}
        </div>
      </div>

      {/* Sharpe */}
      <div className="bg-surface-container rounded-lg p-4">
        <div className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-1">Sharpe</div>
        <div className={`font-headline text-2xl font-bold tabular-nums ${
          showDash || sharpe == null ? "text-on-surface" : sharpe > 0 ? "text-tertiary-dim" : "text-error"
        }`}>
          {showDash || sharpe == null ? "—" : sharpe}
        </div>
      </div>

      {/* Avg R:R */}
      <div className="bg-surface-container rounded-lg p-4">
        <div className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-1">Avg R:R</div>
        <div className="font-headline text-2xl font-bold tabular-nums text-on-surface">{stats.avg_rr}</div>
      </div>

      {/* Row 4: Resolved | Wins | Losses | Expired */}
      <div className="col-span-2 bg-surface-container rounded-lg p-4">
        <div className="grid grid-cols-4 gap-2 text-center">
          <div>
            <div className="font-headline text-lg font-bold tabular-nums text-on-surface">{stats.total_resolved}</div>
            <div className="text-xs text-on-surface-variant">Resolved</div>
          </div>
          <div>
            <div className="font-headline text-lg font-bold tabular-nums text-tertiary-dim">{stats.total_wins}</div>
            <div className="text-xs text-on-surface-variant">Wins</div>
          </div>
          <div>
            <div className="font-headline text-lg font-bold tabular-nums text-error">{stats.total_losses}</div>
            <div className="text-xs text-on-surface-variant">Losses</div>
          </div>
          <div>
            <div className="font-headline text-lg font-bold tabular-nums text-on-surface">{stats.total_expired ?? 0}</div>
            <div className="text-xs text-on-surface-variant">Expired</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── EquityCurve ─────────────────────────────────────────────────

function EquityCurve({ data }: { data: SignalStats["equity_curve"] }) {
  const gradientId = useId();
  if (data.length < 2) return null;

  const width = 320;
  const height = 120;
  const pad = { top: 10, right: 10, bottom: 20, left: 10 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;

  const values = data.map((d) => d.cumulative_pnl);
  const minVal = Math.min(0, ...values);
  const maxVal = Math.max(0, ...values);
  const range = maxVal - minVal || 1;

  const points = data
    .map((d, i) => {
      const x = pad.left + (i / (data.length - 1)) * w;
      const y = pad.top + h - ((d.cumulative_pnl - minVal) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  const lastVal = values[values.length - 1];
  const lineColor = lastVal >= 0 ? theme.colors.long : theme.colors.short;

  const areaPoints = data.map((d, i) => {
    const x = pad.left + (i / (data.length - 1)) * w;
    const y = pad.top + h - ((d.cumulative_pnl - minVal) / range) * h;
    return `${x},${y}`;
  });
  const fillPath = `${pad.left},${pad.top + h} ${areaPoints.join(" ")} ${pad.left + w},${pad.top + h}`;

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-2">Equity Curve</h3>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none" role="img" aria-label={`Equity curve, current P&L ${lastVal >= 0 ? "+" : ""}${lastVal.toFixed(1)}%`}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.3" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
          </linearGradient>
        </defs>
        <polygon fill={`url(#${gradientId})`} points={fillPath} />
        <polyline fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" points={points} />
      </svg>
    </div>
  );
}

// ─── DrawdownChart ───────────────────────────────────────────────

function DrawdownChart({ data, maxDd }: { data: SignalStats["drawdown_series"]; maxDd: number }) {
  if (data.length < 2) return null;

  const width = 320;
  const height = 100;
  const pad = { top: 5, right: 10, bottom: 15, left: 10 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;

  const values = data.map((d) => d.drawdown);
  const minVal = Math.min(...values, 0);
  const range = Math.abs(minVal) || 1;

  const points = data
    .map((d, i) => {
      const x = pad.left + (i / (data.length - 1)) * w;
      const y = pad.top + (Math.abs(d.drawdown) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  const firstX = pad.left;
  const lastX = pad.left + w;
  const fillPoints = `${firstX},${pad.top} ${points} ${lastX},${pad.top}`;

  return (
    <div className="bg-surface-container rounded-lg p-4 relative">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-bold text-on-surface-variant uppercase tracking-widest">Drawdown</h3>
        <span className="text-xs font-mono font-bold tabular-nums text-on-surface">
          {maxDd > 0 ? `-${maxDd}%` : "0%"}
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none" role="img" aria-label={`Drawdown chart, max drawdown ${minVal.toFixed(1)}%`}>
        <polygon fill={theme.colors.short + "15"} points={fillPoints} />
        <polyline fill="none" stroke={theme.colors.short} strokeWidth="1.5" strokeLinejoin="round" points={points} />
      </svg>
    </div>
  );
}

// ─── PairBreakdown ───────────────────────────────────────────────

function PairBreakdown({ data }: { data: SignalStats["by_pair"] }) {
  const pairs = Object.entries(data);
  if (pairs.length === 0) return null;

  return (
    <div className="space-y-3">
      {pairs.map(([pair, stats]) => (
        <div key={pair} className="bg-surface-container rounded-lg p-4 hover:bg-surface-container-high transition-colors">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-surface-container-highest flex items-center justify-center">
              <span className="font-headline font-bold text-xs text-primary">{pair.replace("-USDT-SWAP", "").slice(0, 3)}</span>
            </div>
            <div className="flex-1">
              <span className="font-headline font-bold text-sm">{pair.replace("-USDT-SWAP", "")}/USDT</span>
              <div className="flex items-center gap-3 text-xs font-mono mt-0.5">
                <span className={stats.win_rate >= 50 ? "text-tertiary-dim" : "text-error"}>
                  {stats.win_rate}% WR
                </span>
                <span className={stats.avg_pnl >= 0 ? "text-tertiary-dim" : "text-error"}>
                  {stats.avg_pnl >= 0 ? "+" : ""}{stats.avg_pnl.toFixed(2)}%
                </span>
                <span className="text-on-surface-variant">{stats.total} trades</span>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── TimeframeBreakdown (NEW) ────────────────────────────────────

function TimeframeBreakdown({ data }: { data: SignalStats["by_timeframe"] }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;

  const order = ["15m", "1h", "4h"];
  const sorted = order
    .filter((tf) => data[tf])
    .map((tf) => ({ tf, ...data[tf] }));
  if (sorted.length === 0) return null;

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-3">By Timeframe</h3>
      <div className="grid grid-cols-3 gap-2 text-center">
        {sorted.map(({ tf, win_rate, total }) => (
          <div key={tf}>
            <div className="text-sm font-headline font-bold text-on-surface mb-1">{tf}</div>
            <div className={`text-lg font-headline font-bold tabular-nums ${win_rate >= 50 ? "text-tertiary-dim" : "text-error"}`}>
              {win_rate}%
            </div>
            <div className="text-xs text-on-surface-variant">{total} trades</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── HourlyHeatmap (NEW) ─────────────────────────────────────────

function HourlyHeatmap({ data }: { data: SignalStats["hourly_performance"] }) {
  if (!data || data.length === 0 || data.every((d) => d.count === 0)) return null;

  const magnitudes = data.filter((d) => d.count > 0).map((d) => Math.abs(d.avg_pnl));
  const sorted = [...magnitudes].sort((a, b) => a - b);
  const p90Idx = Math.floor(sorted.length * 0.9);
  const maxMag = sorted[p90Idx] || sorted[sorted.length - 1] || 1;

  const bestHour = data.reduce((best, d) => d.avg_pnl > best.avg_pnl ? d : best, data[0]);
  const worstHour = data.reduce((worst, d) => d.avg_pnl < worst.avg_pnl ? d : worst, data[0]);

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-3">Best Hours to Trade</h3>
      <div
        className="grid grid-cols-6 gap-1"
        role="img"
        aria-label={`Hourly heatmap. Best hour: ${bestHour.hour}:00 (${bestHour.avg_pnl >= 0 ? "+" : ""}${bestHour.avg_pnl.toFixed(2)}%). Worst hour: ${worstHour.hour}:00 (${worstHour.avg_pnl >= 0 ? "+" : ""}${worstHour.avg_pnl.toFixed(2)}%)`}
      >
        {data.map((d) => {
          const intensity = d.count > 0 ? Math.min(Math.abs(d.avg_pnl) / maxMag, 1) : 0;
          const opacity = 0.1 + intensity * 0.5;
          const bgColor = d.count === 0
            ? "transparent"
            : d.avg_pnl >= 0
              ? `rgba(45, 212, 160, ${opacity})`
              : `rgba(251, 113, 133, ${opacity})`;

          return (
            <div
              key={d.hour}
              className="aspect-square rounded flex flex-col items-center justify-center"
              style={{ backgroundColor: bgColor }}
            >
              <span className="text-[10px] text-on-surface-variant leading-none">{d.hour}</span>
              {d.count > 0 && (
                <span className={`text-[9px] font-mono tabular-nums leading-none mt-0.5 ${d.avg_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
                  {d.avg_pnl >= 0 ? "+" : ""}{d.avg_pnl.toFixed(1)}
                </span>
              )}
            </div>
          );
        })}
      </div>
      {/* Legend */}
      <div className="mt-2 flex items-center gap-1">
        <span className="text-xs text-on-surface-variant">Loss</span>
        <div className="flex-1 h-3 rounded-sm relative" style={{
          background: `linear-gradient(to right, rgba(251,113,133,0.6), rgba(251,113,133,0.1), transparent, rgba(45,212,160,0.1), rgba(45,212,160,0.6))`,
        }}>
          <span className="absolute left-1/2 -translate-x-1/2 top-0 text-xs text-on-surface-variant leading-3">0</span>
        </div>
        <span className="text-xs text-on-surface-variant">Profit</span>
      </div>
    </div>
  );
}

// ─── DirectionBreakdown (NEW) ────────────────────────────────────

function DirectionBreakdown({ data }: { data: SignalStats["by_direction"] }) {
  if (!data || Object.keys(data).length === 0) return null;

  const directions = ["LONG", "SHORT"] as const;
  const available = directions.filter((d) => data[d]);
  if (available.length === 0) return null;

  return (
    <div className="grid grid-cols-2 gap-3">
      {available.map((dir) => {
        const d = data[dir];
        const isLong = dir === "LONG";
        return (
          <div
            key={dir}
            className={`bg-surface-container rounded-lg p-4 border-l-[3px] ${isLong ? "border-tertiary-dim" : "border-error"}`}
          >
            <div className={`text-sm font-headline font-bold mb-2 ${isLong ? "text-tertiary-dim" : "text-error"}`}>
              {dir}
            </div>
            <div className={`text-2xl font-headline font-bold tabular-nums ${d.win_rate >= 50 ? "text-tertiary-dim" : "text-error"}`}>
              {d.win_rate}%
            </div>
            <div className="text-xs text-on-surface-variant mt-1">{d.total} trades</div>
            <div className={`text-xs font-mono tabular-nums mt-0.5 ${d.avg_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
              {d.avg_pnl >= 0 ? "+" : ""}{d.avg_pnl.toFixed(2)}% avg
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── PnlDistribution (from DeepDive) ────────────────────────────

function PnlDistribution({ data }: { data: SignalStats["pnl_distribution"] }) {
  if (data.length === 0) return null;

  const maxCount = Math.max(...data.map((d) => d.count));
  const width = 320;
  const height = 80;
  const pad = { top: 5, right: 10, bottom: 15, left: 10 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;
  const barWidth = Math.max(w / data.length - 2, 4);

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-2">P&L Distribution</h3>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none" role="img" aria-label={`P&L distribution across ${data.length} buckets`}>
        {data.map((d, i) => {
          const barH = (d.count / maxCount) * h;
          const x = pad.left + (i / data.length) * w;
          const y = pad.top + h - barH;
          const fill = d.bucket >= 0 ? theme.colors.long : theme.colors.short;
          return (
            <rect key={i} x={x} y={y} width={barWidth} height={barH} fill={fill} opacity={0.7} rx={1} />
          );
        })}
        {(() => {
          const zeroIdx = data.findIndex((d) => d.bucket >= 0);
          if (zeroIdx < 0 || !data.some((d) => d.bucket < 0)) return null;
          const x = pad.left + (zeroIdx / data.length) * w;
          return (
            <line x1={x} y1={pad.top} x2={x} y2={pad.top + h} stroke={theme.colors["outline-variant"]} strokeWidth="0.5" strokeDasharray="3" />
          );
        })()}
      </svg>
    </div>
  );
}

// ─── StreakTracker ────────────────────────────────────────────────

function StreakTracker({ streaks }: { streaks: SignalStats["streaks"] }) {
  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-3">Streaks</h3>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className={`text-lg font-headline font-bold tabular-nums ${streaks.current >= 0 ? "text-tertiary-dim" : "text-error"}`}>
            {streaks.current >= 0 ? `+${streaks.current}` : streaks.current}
          </div>
          <div className="text-xs text-on-surface-variant">Current</div>
        </div>
        <div>
          <div className="text-lg font-headline font-bold tabular-nums text-tertiary-dim">+{streaks.best_win}</div>
          <div className="text-xs text-on-surface-variant">Best Win</div>
        </div>
        <div>
          <div className="text-lg font-headline font-bold tabular-nums text-error">{streaks.worst_loss}</div>
          <div className="text-xs text-on-surface-variant">Worst Loss</div>
        </div>
      </div>
    </div>
  );
}

// ─── NotableTrades (from DeepDive) ───────────────────────────────

function NotableTrades({ perf }: { perf: PerformanceMetrics }) {
  if (!perf.best_trade && !perf.worst_trade) return null;

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-3">Notable Trades</h3>
      <div className="space-y-1.5">
        {perf.best_trade && (
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span className="text-xs text-long bg-long/10 px-1.5 py-0.5 rounded font-bold">BEST</span>
              <span className="text-on-surface-variant">
                {formatPair(perf.best_trade.pair)} {perf.best_trade.timeframe} {perf.best_trade.direction}
              </span>
            </div>
            <span className="font-mono text-long tabular-nums">+{perf.best_trade.pnl_pct}%</span>
          </div>
        )}
        {perf.worst_trade && (
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span className="text-xs text-short bg-short/10 px-1.5 py-0.5 rounded font-bold">WORST</span>
              <span className="text-on-surface-variant">
                {formatPair(perf.worst_trade.pair)} {perf.worst_trade.timeframe} {perf.worst_trade.direction}
              </span>
            </div>
            <span className="font-mono text-short tabular-nums">{perf.worst_trade.pnl_pct}%</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── RiskProfile (from DeepDive) ─────────────────────────────────

function RiskProfile({ perf, totalResolved }: { perf: PerformanceMetrics; totalResolved: number }) {
  const showDash = totalResolved < 5;

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-3">Risk Profile</h3>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className={`text-base font-headline font-bold tabular-nums ${
            showDash || perf.profit_factor == null ? "text-on-surface" : perf.profit_factor > 1 ? "text-tertiary-dim" : "text-error"
          }`}>
            {showDash || perf.profit_factor == null ? "—" : perf.profit_factor}
          </div>
          <div className="text-xs text-on-surface-variant">Profit Factor</div>
        </div>
        <div>
          <div className={`text-base font-headline font-bold tabular-nums ${perf.max_drawdown_pct > 3 ? "text-error" : "text-on-surface"}`}>
            {perf.max_drawdown_pct > 0 ? `-${perf.max_drawdown_pct}%` : "0%"}
          </div>
          <div className="text-xs text-on-surface-variant">Max Drawdown</div>
        </div>
        <div>
          <div className="text-base font-headline font-bold tabular-nums text-on-surface">
            {perf.avg_hold_time_minutes != null ? formatHoldTime(perf.avg_hold_time_minutes) : "—"}
          </div>
          <div className="text-xs text-on-surface-variant">Avg Hold Time</div>
        </div>
      </div>
    </div>
  );
}

function formatHoldTime(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd web && pnpm build`
Expected: Build succeeds with no type errors.

---

### Task 7: CalendarView — Visual polish + signal cards

**Files:**
- Modify: `web/src/features/signals/components/CalendarView.tsx` (full rewrite)

- [ ] **Step 1: Rewrite CalendarView.tsx**

Replace the full contents of `web/src/features/signals/components/CalendarView.tsx`:

```tsx
import { useState, useEffect } from "react";
import { TrendingUp, TrendingDown } from "lucide-react";
import { api } from "../../../shared/lib/api";
import { formatPair, formatTime } from "../../../shared/lib/format";
import { useSignalsByDate } from "../hooks/useSignalsByDate";
import type { CalendarDay, CalendarResponse, Signal } from "../types";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function formatMonth(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

function getMonthName(year: number, month: number): string {
  return new Date(year, month - 1).toLocaleString("en", { month: "long", year: "numeric" });
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

function getStartDay(year: number, month: number): number {
  const day = new Date(year, month - 1, 1).getDay();
  return day === 0 ? 6 : day - 1;
}

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function CalendarView() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    api
      .getSignalCalendar(formatMonth(year, month))
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setSelectedDay(null);
        }
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [year, month]);

  const prevMonth = () => {
    if (month === 1) { setYear(year - 1); setMonth(12); }
    else setMonth(month - 1);
  };
  const nextMonth = () => {
    if (month === 12) { setYear(year + 1); setMonth(1); }
    else setMonth(month + 1);
  };

  const dayMap = new Map<string, CalendarDay>();
  data?.days.forEach((d) => dayMap.set(d.date, d));

  const daysInMonth = getDaysInMonth(year, month);
  const startDay = getStartDay(year, month);
  const today = todayStr();
  const summary = data?.monthly_summary;

  // Compute 90th percentile of daily P&L magnitudes for tinting
  const pnlMagnitudes = data?.days
    .map((d) => Math.abs(d.net_pnl))
    .filter((v) => v > 0)
    .sort((a, b) => a - b) ?? [];
  const p90 = pnlMagnitudes.length > 0
    ? pnlMagnitudes[Math.floor(pnlMagnitudes.length * 0.9)] || pnlMagnitudes[pnlMagnitudes.length - 1]
    : 1;

  return (
    <div className="p-3 space-y-3">
      {/* Monthly summary */}
      {summary && summary.total_signals > 0 && (
        <div className="bg-surface-container rounded-lg p-3">
          <div className="grid grid-cols-4 gap-2 text-center text-xs">
            <div>
              <div className="font-mono font-bold text-on-surface tabular-nums">{summary.total_signals}</div>
              <div className="text-on-surface-variant">Signals</div>
            </div>
            <div>
              <div className={`font-mono font-bold tabular-nums ${summary.net_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
                {summary.net_pnl >= 0 ? "+" : ""}{summary.net_pnl.toFixed(1)}%
              </div>
              <div className="text-on-surface-variant">Net P&L</div>
            </div>
            <div>
              <div className="font-mono font-bold tabular-nums text-tertiary-dim">{summary.best_day?.slice(8) ?? "—"}</div>
              <div className="text-on-surface-variant">Best Day</div>
            </div>
            <div>
              <div className="font-mono font-bold tabular-nums text-error">{summary.worst_day?.slice(8) ?? "—"}</div>
              <div className="text-on-surface-variant">Worst Day</div>
            </div>
          </div>
        </div>
      )}

      {/* Month navigation */}
      <div className="flex items-center justify-between">
        <button onClick={prevMonth} aria-label="Previous month" className="text-on-surface-variant hover:text-on-surface px-2 py-1 text-lg focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">&larr;</button>
        <span className="text-sm font-headline font-bold">{getMonthName(year, month)}</span>
        <button onClick={nextMonth} aria-label="Next month" className="text-on-surface-variant hover:text-on-surface px-2 py-1 text-lg focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">&rarr;</button>
      </div>

      {loading ? (
        <div className="h-64 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none" />
      ) : error ? (
        <div className="text-center py-8">
          <p className="text-on-surface-variant text-sm mb-2">Failed to load calendar</p>
          <button onClick={() => { setLoading(true); setError(false); api.getSignalCalendar(formatMonth(year, month)).then(setData).catch(() => setError(true)).finally(() => setLoading(false)); }} className="text-xs text-primary focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">Retry</button>
        </div>
      ) : (
        <>
          {/* Calendar grid */}
          <div className="bg-surface-container rounded-lg p-2">
            {/* Weekday headers */}
            <div className="grid grid-cols-7 gap-1 mb-1">
              {WEEKDAYS.map((d) => (
                <div key={d} className="text-center text-xs text-on-surface-variant font-bold uppercase py-1">{d}</div>
              ))}
            </div>

            {/* Day cells */}
            <div className="grid grid-cols-7 gap-1">
              {Array.from({ length: startDay }).map((_, i) => (
                <div key={`empty-${i}`} className="aspect-square rounded-lg bg-surface-container-highest/30" />
              ))}

              {Array.from({ length: daysInMonth }).map((_, i) => {
                const dayNum = i + 1;
                const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(dayNum).padStart(2, "0")}`;
                const dayData = dayMap.get(dateStr);
                const isToday = dateStr === today;
                const isSelected = dateStr === selectedDay;

                // P&L tinting with intensity scaled to magnitude, capped at p90
                let bgStyle: React.CSSProperties | undefined;
                if (dayData && dayData.net_pnl !== 0) {
                  const intensity = Math.min(Math.abs(dayData.net_pnl) / p90, 1);
                  const opacity = 0.05 + intensity * 0.15;
                  bgStyle = {
                    backgroundColor: dayData.net_pnl > 0
                      ? `rgba(45, 212, 160, ${opacity})`
                      : `rgba(251, 113, 133, ${opacity})`,
                  };
                }

                return (
                  <button
                    key={dayNum}
                    onClick={() => setSelectedDay(isSelected ? null : dateStr)}
                    className={`aspect-square rounded-lg flex flex-col items-center justify-center p-1 transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                      !dayData && !isToday ? "bg-surface-container-highest/30" : ""
                    } ${
                      isSelected ? "ring-2 ring-primary" : ""
                    } ${isToday ? "border border-primary/40" : ""}`}
                    style={bgStyle}
                  >
                    <span className={`text-xs ${isToday ? "text-primary font-bold" : "text-on-surface-variant"}`}>
                      {dayNum}
                    </span>
                    {isToday && (
                      <span className="text-[8px] text-primary font-bold leading-none">TODAY</span>
                    )}
                    {dayData && (
                      <span className={`text-[10px] font-mono tabular-nums leading-none ${dayData.net_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
                        {dayData.net_pnl >= 0 ? "+" : ""}{dayData.net_pnl.toFixed(1)}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Selected day detail with signal cards */}
          {selectedDay && <DayDetail date={selectedDay} dayData={dayMap.get(selectedDay)} />}
        </>
      )}
    </div>
  );
}

// ─── DayDetail ───────────────────────────────────────────────────

function DayDetail({ date, dayData }: { date: string; dayData?: CalendarDay }) {
  const { signals, loading: signalsLoading, error: signalsError, retry } = useSignalsByDate(date);

  return (
    <div className="max-h-[400px] overflow-y-auto space-y-3">
      {/* Summary bar */}
      {dayData && dayData.signal_count > 0 && (
        <div className="bg-surface-container rounded-lg p-3">
          <div className="flex items-center justify-center gap-4 text-sm">
            <span className={`font-mono font-bold tabular-nums ${dayData.net_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
              {dayData.net_pnl >= 0 ? "+" : ""}{dayData.net_pnl.toFixed(2)}% P&L
            </span>
            <span className="text-outline-variant">|</span>
            <span className="font-mono font-bold text-tertiary-dim tabular-nums">{dayData.wins}W</span>
            <span className="text-outline-variant">|</span>
            <span className="font-mono font-bold text-error tabular-nums">{dayData.losses}L</span>
          </div>
        </div>
      )}

      {/* Signal cards */}
      {signalsLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none" />
          ))}
        </div>
      ) : signalsError ? (
        <div className="bg-surface-container rounded-lg p-3 text-center">
          <p className="text-on-surface-variant text-sm mb-2">Failed to load signals</p>
          <button onClick={retry} className="text-xs text-primary focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">Retry</button>
        </div>
      ) : signals.length === 0 ? (
        <div className="bg-surface-container rounded-lg p-3 text-center">
          <p className="text-on-surface-variant text-sm">No signals on {date}</p>
        </div>
      ) : (
        signals.map((signal) => <SignalDayCard key={signal.id} signal={signal} />)
      )}
    </div>
  );
}

// ─── SignalDayCard ────────────────────────────────────────────────

function SignalDayCard({ signal }: { signal: Signal }) {
  const isLong = signal.direction === "LONG";

  const outcomeBadge = signal.outcome !== "PENDING" ? (
    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
      signal.outcome.includes("TP") ? "bg-long/10 text-long" :
      signal.outcome === "EXPIRED" ? "bg-outline-variant/20 text-on-surface-variant" :
      "bg-short/10 text-short"
    }`}>
      {signal.outcome.replace("_", " ")}
    </span>
  ) : null;

  return (
    <div className={`bg-surface-container rounded-lg p-3 flex items-center gap-3 border-l-[3px] ${isLong ? "border-tertiary-dim" : "border-error"}`}>
      {/* Direction icon */}
      <div className={`w-8 h-8 rounded-full flex items-center justify-center ${isLong ? "bg-long/10" : "bg-short/10"}`}>
        {isLong ? <TrendingUp size={16} className="text-long" /> : <TrendingDown size={16} className="text-short" />}
      </div>

      {/* Middle: pair, direction, timeframe, score, time */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-headline font-bold text-sm">{formatPair(signal.pair)}/USDT</span>
          <span className={`text-[10px] font-bold uppercase ${isLong ? "text-long" : "text-short"}`}>{signal.direction}</span>
        </div>
        <div className="text-xs text-on-surface-variant mt-0.5">
          {signal.timeframe} &middot; Score {Math.abs(signal.final_score).toFixed(0)} &middot; {formatTime(signal.created_at)}
        </div>
      </div>

      {/* Right: P&L, outcome */}
      <div className="text-right shrink-0">
        {signal.outcome_pnl_pct != null && (
          <div className={`font-mono font-bold text-sm tabular-nums ${signal.outcome_pnl_pct >= 0 ? "text-long" : "text-short"}`}>
            {signal.outcome_pnl_pct >= 0 ? "+" : ""}{signal.outcome_pnl_pct.toFixed(2)}%
          </div>
        )}
        {outcomeBadge}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify frontend compiles**

Run: `cd web && pnpm build`
Expected: Build succeeds with no type errors.

---

### Task 8: Delete DeepDiveView.tsx and PairDeepDive.tsx

**Files:**
- Delete: `web/src/features/signals/components/DeepDiveView.tsx`
- Delete: `web/src/features/signals/components/PairDeepDive.tsx`

Precondition: `DeepDiveView` is only imported by `JournalView` (already removed in Task 3). `PairDeepDive` has no imports outside its own file.

- [ ] **Step 1: Delete files**

```bash
rm web/src/features/signals/components/DeepDiveView.tsx
rm web/src/features/signals/components/PairDeepDive.tsx
```

- [ ] **Step 2: Verify no broken imports**

Run: `cd web && pnpm build`
Expected: Build succeeds — no remaining imports of either file.

---

### Task 9: Final verification

- [ ] **Step 1: Run full frontend build**

Run: `cd web && pnpm build`
Expected: Build succeeds with no errors or warnings.

- [ ] **Step 2: Run frontend tests**

Run: `cd web && pnpm test -- --run`
Expected: All tests pass.

- [ ] **Step 3: Run backend tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 4: Run frontend lint**

Run: `cd web && pnpm lint`
Expected: No lint errors.

- [ ] **Step 5: Commit all changes**

```bash
git add -A
git commit -m "feat: journal & analytics redesign — merge DeepDive, calendar signal cards, remove journal notes"
```
