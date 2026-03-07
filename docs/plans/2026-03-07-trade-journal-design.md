# Trade Journal Design

**Date:** 2026-03-07
**Status:** Approved

## Overview

Transform the Signals tab into a full Trade Journal — an auto-logged, annotatable record of every signal with deep analytics and a calendar view. The journal builds on existing signal + outcome tracking infrastructure with minimal data model changes.

## Navigation

The **Signals tab (⚡)** becomes the **Journal tab**. Three sub-views via segmented control:

**Feed | Analytics | Calendar**

## Data Model Changes

Add two fields to the existing `Signal` model:

```python
user_note: Optional[str]  # Free-form annotation, max 500 chars
user_status: str  # OBSERVED (default) | TRADED | SKIPPED
```

No new tables. The journal is a richer view of existing signal data.

### Frontend Type Updates

Extend `Signal` interface in `types.ts`:
```typescript
user_note: string | null;
user_status: "OBSERVED" | "TRADED" | "SKIPPED";
```

Extend `SignalStats` interface with new analytics fields:
```typescript
equity_curve: { date: string; cumulative_pnl: number }[];
hourly_performance: { hour: number; avg_pnl: number; count: number }[];
streaks: { current: number; best_win: number; worst_loss: number };
```

Add `updateSignal(id, patch)` action to Zustand signal store so PATCH results merge into the existing signal list without a full refetch.

## API Changes

### New Endpoint

```
PATCH /api/signals/{id}/journal
Body: { status?: "OBSERVED"|"TRADED"|"SKIPPED", note?: string }

Validation:
- 404 if signal ID doesn't exist
- status must be one of the three enum values (reject otherwise)
- note max length: 500 characters (truncate or reject)
- Invalidate Redis stats cache keys on success
```

### Extended: GET /api/signals/stats

Add to response:
- `equity_curve`: `[{date, cumulative_pnl}]` — downsample to daily buckets when range > 90 days
- `hourly_performance`: `[{hour, avg_pnl, count}]`
- `streaks`: `{current, best_win, worst_loss}`

"All" period is capped at 365 days to bound query cost.

### New Endpoint

```
GET /api/signals/calendar?month=2026-03
Response: {
  days: [{date, signal_count, net_pnl, wins, losses}],
  monthly_summary: {total_signals, net_pnl, best_day, worst_day}
}
```

## Section 1: Enhanced Feed View

The feed keeps its current card layout with additions:

**Signal Card updates:**
- Status chip: `TRADED` (green outline), `SKIPPED` (gray), or none (observed)
- Note icon if signal has a user note

**Signal Detail (bottom sheet) updates:**
- New section at bottom: "Your Notes"
  - Status toggle: Observed / Traded / Skipped (3 pill buttons)
  - Text input for notes (free-form, auto-saves via PATCH)

**Feed filters (new):**
- Status filter: All | Traded | Skipped

## Section 2: Analytics View

Scrollable dashboard with period selector (7D | 30D | All):

1. **Performance Summary Strip** — Win rate %, Avg R:R, Total signals, Net P&L %
2. **Equity Curve** — Line chart of cumulative P&L % over time (canvas/SVG)
3. **Time-of-Day Heatmap** — 24-column grid colored by avg outcome per hour
4. **Pair Breakdown Table** — Per-pair: win rate, avg P&L, count, best/worst
5. **Streak Tracker** — Current streak, best win streak, worst loss streak

Equity curve always uses all resolved signals by default. A "Traded only" toggle filters to `user_status = TRADED` when enabled.

## Section 3: Calendar View

Month-grid calendar (CSS grid, 7 columns, no library):

**Day cell:**
- Signal count, net P&L % (green/red), background tint by profitability

**Interactions:**
- Tap day → shows that day's signals in mini-list below calendar
- Left/right arrow buttons to navigate months
- Current day highlighted

**Monthly summary** at top:
- Month name, total signals, net P&L %, best day, worst day

## UI States

All three views (Feed, Analytics, Calendar) must handle:
- **Loading:** Skeleton placeholders while data fetches
- **Empty:** Contextual message when no resolved signals exist (e.g., "No resolved signals yet — analytics will appear as signals resolve")
- **Error:** Brief error message with retry button if API call fails

## Tech Notes

- Reuse `useSignalStats` hook, extended for new analytics data
- Calendar: pure CSS grid, no external library
- Equity curve: raw SVG `<polyline>` — simple, no library needed, sufficient for a single line chart
- Heatmap: pure CSS grid with background-color opacity mapping
- All analytics computed server-side via SQL aggregation queries
- Auto-save journal annotations (debounced PATCH, no optimistic update — just show a brief saving indicator)
- Dark theme consistent with OKX style (greens for profit, reds for loss)

## Tests

### Backend (pytest)
- **PATCH /api/signals/{id}/journal:** valid update, invalid status enum rejected, note over 500 chars rejected, 404 for missing signal, stats cache invalidated after PATCH
- **GET /api/signals/stats (extended):** equity curve with 0 signals returns empty array, streaks computation with mixed win/loss sequences, hourly_performance bucketing, "All" period capped at 365 days
- **GET /api/signals/calendar:** correct day aggregation, empty month returns empty days array, month boundary handling (signals on last/first day)

### Frontend (vitest)
- Analytics calculations: streak logic, equity curve cumulative math
- Calendar grid: correct number of day cells for different months, selected day state
