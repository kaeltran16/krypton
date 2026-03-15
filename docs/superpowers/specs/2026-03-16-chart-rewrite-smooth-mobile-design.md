# Chart Component Rewrite — Smooth Mobile Experience

**Date:** 2026-03-16
**Status:** Approved
**Scope:** `web/src/features/chart/components/CandlestickChart.tsx`, `web/src/features/chart/hooks/useChartData.ts`

## Problem

Two issues on mobile:

1. **Pinch-to-zoom lag**: No `touch-action` CSS on the chart container, so the browser's default touch handling (page zoom, pull-to-refresh) fights with lightweight-charts' built-in pinch/zoom handler, causing delayed/janky gestures.
2. **Flash on indicator toggle / timeframe switch**: A single monolithic `useEffect` handles both candle data and indicator series. Toggling one indicator re-runs `setData()` on candle + volume series and removes/recreates oscillator series, causing visible jumps and blank flashes.

## Solution

Keep lightweight-charts v5.1 (correct tool for the job). Rewrite the React integration layer in `CandlestickChart.tsx` with ref-stable architecture and separated effects.

### Architecture: Three isolated effects

**Effect 1 — Chart creation** (`[]` deps)
- Creates the chart instance, candle series, and volume series
- Sets up ResizeObserver for responsive sizing
- Cleanup on unmount only — chart is never destroyed/recreated during the component's lifetime

**Effect 2 — Candle data** (`[candles]` deps)
- Updates candle + volume series data
- Uses `update()` for single-candle streaming, `setData()` for full dataset loads
- Calls `fitContent()` only on full dataset loads, not during streaming
- Never touches indicator series

**Effect 3 — Indicators** (`[candles, enabledKey]` deps)
- Diffs previous vs. current enabled indicator set
- Three paths: `toAdd` (create series + set data), `toRemove` (remove series), `toUpdate` (call `setData()` on existing series)
- Never touches candle/volume series
- Preserves time scale visible range across indicator toggles

### Touch & zoom fix

CSS on chart container div:
- `touch-action: none` — delegates all touch gesture handling to lightweight-charts, removing browser conflicts
- `overscroll-behavior: none` — prevents pull-to-refresh and scroll chaining during horizontal pan

Chart options remain unchanged:
- `handleScale: { pinch: true, mouseWheel: true, axisPressedMouseMove: true }`
- `handleScroll: { horzTouchDrag: true, vertTouchDrag: false }` (vertical swipes still scroll the page)

### Eliminating flash on timeframe switch

In `useChartData.ts`: keep previous candles visible during fetch. Don't clear the candles array when a new timeframe fetch starts — only replace with `setCandles(newData)` on successful response. The chart continues showing stale data (old timeframe) until new data arrives, avoiding the blank flash.

### Indicator series diffing

Replace the current remove-all/recreate-all pattern with a stable `Map<string, { series: ISeriesApi[], type: 'overlay' | 'oscillator' }>` ref:

- **toRemove** (in map, not in enabled set): call `chart.removeSeries()` for each, delete from map
- **toAdd** (in enabled set, not in map): create series with `chart.addSeries()`, set data, store in map
- **toUpdate** (in both): call `setData()` on existing series objects — no remove/recreate

Compound indicators (BB, Ichimoku, SuperTrend) use sub-keys (e.g., `bb-upper`, `bb-middle`, `bb-lower`) stored as a group under the parent key.

## Files changed

| File | Change |
|------|--------|
| `web/src/features/chart/components/CandlestickChart.tsx` | Full rewrite — three separated effects, series diffing, stable refs |
| `web/src/features/chart/hooks/useChartData.ts` | Small tweak — don't clear candles array during timeframe fetch |

## What stays the same

- lightweight-charts v5.1 (no library change)
- `ChartView.tsx` (parent component, no changes)
- `IndicatorSheet.tsx` (indicator selection UI, no changes)
- `indicators.ts` (calculation functions, no changes)
- All chart options (colors, grid, crosshair, scale config)
- All indicator types and their visual configuration

## Testing

- Manual: pinch-to-zoom on mobile should feel immediate with no page zoom interference
- Manual: toggle indicators on/off — chart should not flash blank or jump
- Manual: switch timeframes — old candles stay visible until new data loads
- Manual: streaming candle updates should still animate smoothly
- Verify all 18 indicator types still render correctly after the rewrite
