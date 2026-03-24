# Journal & Analytics Redesign

## Overview

Merge the Analytics and Deep Dive tabs into a single scrollable Analytics view, add missing breakdowns (timeframe, hourly heatmap, direction), improve the Calendar with better visual polish and signal-level day detail, and remove journal notes/status UI.

## Structural Changes

### Navigation: 3 tabs → 2

**Before:** Signals → Journal → [Analytics | Calendar | Deep Dive]
**After:** Signals → Journal → [Analytics | Calendar]

DeepDiveView is deleted. All its content (Sharpe, profit factor, drawdown chart, P&L distribution, notable trades, max DD, avg hold time) is absorbed into the merged Analytics view.

### Journal notes removal

Remove `JournalSection` from `SignalDetail.tsx` — the user_status buttons, note textarea, debounced save logic, and related state. The `patchSignalJournal` API method stays in `api.ts` (backend fields unchanged).

## Analytics View — Merged Layout

Single scrollable view, replaces both AnalyticsView and DeepDiveView. Component: `AnalyticsView.tsx` (rewritten).

Data source: `useSignalStats(days)` hook — same endpoint, no new API calls except `by_direction` (see Backend Changes).

### Section order (top to bottom):

**1. Period Selector** — scrolls with content (not sticky — the parent JournalView tab bar is already fixed at the top; two sticky rows would consume ~90px on small phones). 7D | 30D | All segmented control.

**2. Hero KPI Bento** — 2-column grid:
- Row 1: Net P&L (col-span-2, border-left accent, large text)
- Row 2: Win Rate | Expectancy
- Row 3: Sharpe | Avg R:R
- Row 4: Resolved | Wins | Losses | Expired — rendered as a `col-span-2` wrapper containing an inner `grid-cols-4 gap-2` grid. Expired is new — uses `stats.total_expired`.

Color rules: green for positive values, red for negative, neutral for informational (resolved count, avg R:R, avg hold).

**3. Equity & Risk** — section label "Equity & Risk", two stacked cards:
- Equity Curve: SVG polyline + gradient fill (same rendering as current). Line color: green if net positive, red if negative. Include `role="img"` + `aria-label` describing the current P&L value.
- Drawdown Chart: SVG area chart in red. Add max DD value label in top-right of card. Label text color: `text-on-surface` (not `theme.colors.outline`) to ensure >=4.5:1 contrast against both the red fill area and the card background. Include `role="img"` + `aria-label` describing max drawdown.

**4. Breakdowns** — section label "Breakdowns", four cards:

- **By Pair**: existing layout — pair icon, name, win rate, avg P&L, trade count. Carried over as-is.

- **By Timeframe** (NEW): 3-column grid (15m | 1h | 4h). Each cell shows win rate (colored) + trade count. Data source: `stats.by_timeframe`.

- **Best Hours to Trade** (NEW): 24-cell grid (6×4 rows, hours 0-23). Display-only (no tap interaction) — cells are too small for reliable touch targets. Each cell shows the hour number and a signed avg P&L value (e.g., `+0.3` / `-0.1`) to avoid relying on color alone (WCAG `color-not-only`). Cell background uses a **single-hue intensity scale**: green tint for profitable hours, red for losing, with opacity scaled to magnitude. Scaling is capped at the 90th percentile of magnitudes for the month to prevent outliers from washing out other cells. Legend bar at bottom: 12px tall gradient bar, text labels "Loss" (left) and "Profit" (right) at 12px minimum font size, with a center "0" marker. Data source: `stats.hourly_performance`. Include `role="img"` + `aria-label` summarizing the best/worst hours.

- **Long vs Short** (NEW): 2-column side-by-side cards. Each shows: direction label (prominent — primary differentiator, not the border color), win rate (large), trade count, avg P&L. Border-left 3px green-tinted for LONG, red-tinted for SHORT. Data source: `stats.by_direction` (new backend field). If `by_direction` is empty for the selected period, do not render this section (null-return guard).

**5. Distribution & Streaks** — section label "Distribution & Streaks", three cards:

- **P&L Distribution**: SVG bar chart histogram. Green bars for positive buckets, red for negative. Dashed vertical zero line. Moved from DeepDive. Include `role="img"` + `aria-label` describing the distribution shape.

- **Streaks**: 3-column grid — Current | Best Win | Worst Loss. Carried over as-is.

- **Notable Trades**: Best trade (green BEST badge, pair/tf/direction, P&L) and worst trade (red WORST badge). Moved from DeepDive.

**6. Risk Profile** — single card, 3-column grid:
- Profit Factor | Max Drawdown | Avg Hold Time. Moved from DeepDive.
- Guard: if `stats.total_resolved < 5`, show "—" for Sharpe/Profit Factor/Expectancy (statistically meaningless with fewer trades). Keep the section visible but with fallback values, matching the current DeepDive threshold behavior.

### Empty-state guards for new breakdown sections

All new breakdown components (`TimeframeBreakdown`, `HourlyHeatmap`, `DirectionBreakdown`) should return `null` when their data source is empty or has zero entries — same pattern as existing `PairBreakdown`.

### Loading skeleton update

The top-level loading skeleton in `AnalyticsView` currently renders 3 placeholder blocks. Update to **6 blocks** (`h-24`) to better approximate the merged view's scroll height and prevent layout shift (CLS) when data loads.

### Component structure

```
AnalyticsView (main, owns period state + useSignalStats)
├── SummaryBento (hero KPIs)
├── EquityCurve (SVG chart)
├── DrawdownChart (SVG chart)
├── PairBreakdown (list)
├── TimeframeBreakdown (3-col grid) — NEW
├── HourlyHeatmap (6×4 grid, display-only) — NEW
├── DirectionBreakdown (2-col cards) — NEW
├── PnlDistribution (SVG histogram)
├── StreakTracker (3-col grid)
├── NotableTrades (best/worst)
└── RiskProfile (3-col grid)
```

Each is a small private component within `AnalyticsView.tsx` (same pattern as the current file).

## Calendar Improvements

### Visual polish

| Element | Before | After |
|---------|--------|-------|
| Cell gap | `gap-0.5` | `gap-1` |
| Cell shape | minimal | `rounded-lg`, `bg-surface-container-highest` for empty days |
| Cell padding | `p-0.5` | `p-1` (ensures touch area meets 44px minimum on 375px phones) |
| Cell content | day number + `{count}s` + P&L | day number + P&L only (remove signal count) |
| Today indicator | `border border-outline-variant/10` | `border border-primary/40` + small "TODAY" label |
| Selected indicator | `ring-1 ring-primary` | `ring-2 ring-primary` |
| P&L tinting | `bg-tertiary-dim/10` / `bg-error/10` | same but with intensity scaled to magnitude — capped at the 90th percentile of daily P&L magnitudes for the month to prevent outlier days from washing out all other tinting |

### Day detail with signal cards

When a day is tapped, render below the calendar grid inside a `max-h-[400px] overflow-y-auto` container to prevent many signals from pushing the calendar off-screen:

1. **Summary bar** (existing): net P&L, wins, losses — now using flex with dividers instead of grid
2. **Signal cards** (NEW): lazy-loaded via `GET /api/signals/by-date?date=YYYY-MM-DD`

Each signal card shows:
- Left: direction icon (arrow up-right for LONG, down-right for SHORT) in tinted circle
- Middle: pair/USDT + direction badge, timeframe + score + created_at time
- Right: outcome P&L %, outcome badge (TP1 HIT / TP2 HIT / SL HIT / EXPIRED)
- Border-left: 3px, green for long, red for short

States:
- Loading: skeleton card placeholders (2-3 rows)
- Empty: "No signals on {date}" text
- Error: "Failed to load" with retry button

### New hook: `useSignalsByDate`

```typescript
function useSignalsByDate(date: string | null) {
  // Fetches signals for selected date via api.getSignalsByDate(date)
  // Returns { signals, loading, error }
  // Cancels on date change via AbortController (match CalendarView's `let cancelled` pattern)
  // AbortController signal passed to fetch; abort() called in useEffect cleanup
}
```

## Backend Changes

### 1. New endpoint: `GET /api/signals/by-date`

Location: `backend/app/api/routes.py`

```
GET /api/signals/by-date?date=2026-03-14
Auth: X-API-Key
Response: Signal[] (full signal dicts, ordered by created_at ASC)
Filter: WHERE DATE(created_at) = :date
```

No caching needed — small payload, infrequent access pattern.

### 2. Add `by_direction` to stats response

In the existing `get_signal_stats` handler, add computation alongside `by_pair`:

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

Add `"by_direction": by_direction` to the stats response dict. Update the empty-stats fallback to include `"by_direction": {}`.

### Frontend type update

Add to `SignalStats` in `signals/types.ts`:

```typescript
by_direction: Record<string, { wins: number; losses: number; total: number; win_rate: number; avg_pnl: number }>;
```

Add `getSignalsByDate` to `api.ts`:

```typescript
getSignalsByDate: (date: string) =>
  request<Signal[]>(`/api/signals/by-date?date=${date}`)
```

## Files Changed

### Modified
- `web/src/features/signals/components/AnalyticsView.tsx` — full rewrite with merged layout
- `web/src/features/signals/components/JournalView.tsx` — remove Deep Dive tab
- `web/src/features/signals/components/CalendarView.tsx` — visual polish + signal cards
- `web/src/features/signals/components/SignalDetail.tsx` — remove JournalSection
- `web/src/features/signals/types.ts` — add `by_direction` to SignalStats
- `web/src/shared/lib/api.ts` — add `getSignalsByDate` method
- `backend/app/api/routes.py` — add `by-date` endpoint + `by_direction` computation

### Deleted
- `web/src/features/signals/components/DeepDiveView.tsx`
- `web/src/features/signals/components/PairDeepDive.tsx` (verify no other imports first)

### New
- `web/src/features/signals/hooks/useSignalsByDate.ts` — hook for calendar day detail

## Out of Scope

- Export/share functionality
- Journal notes and user_status UI (removed, not replaced)
- Backend schema changes (no migrations)
- Changes to the Signal Feed tab
- Changes to PairDeepDive beyond deletion (if unused)
