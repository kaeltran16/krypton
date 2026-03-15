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

### Architecture: Three separated effects

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
- Wrap indicator calculation loop in try/catch to protect chart stability if a calculation throws

**Ordering constraint:** Effects 2 and 3 both fire when `candles` changes. React fires effects in declaration order within the same commit, so Effect 2 (candle data) always runs before Effect 3 (indicators). This ordering is load-bearing — add a code comment to prevent reordering.

**Known limitation:** During streaming, Effect 3 recalculates all enabled indicators on every candle tick. This matches current behavior and is acceptable for MVP. Future optimization: use `update()` on the last indicator data point during streaming instead of full recalculation.

### Touch & zoom fix

CSS on chart container div:
- `touch-action: pan-y` — allows native vertical scrolling (so swiping up/down on the chart still scrolls the page) but delegates horizontal pan and pinch-zoom to JavaScript (lightweight-charts). This is the correct value — `touch-action: none` would break vertical page scrolling.
- `overscroll-behavior: none` — belt-and-suspenders addition to prevent scroll chaining (the body already sets this globally, but explicit on the chart container for clarity)

Chart options remain unchanged:
- `handleScale: { pinch: true, mouseWheel: true, axisPressedMouseMove: true }`
- `handleScroll: { horzTouchDrag: true, vertTouchDrag: false }` (vertical swipes still scroll the page)

### Eliminating flash on timeframe switch

In `useChartData.ts`: keep previous candles visible during fetch. Don't clear the candles array when a new timeframe fetch starts — only replace with `setCandles(newData)` on successful response. The chart continues showing stale data (old timeframe) until new data arrives, avoiding the blank flash.

**Loading indicator:** Pass the existing `loading` state (already returned by `useChartData`) into `CandlestickChart` as a prop. When `loading` is true, render a subtle pulsing dot or small spinner overlay in the top-right corner of the chart. This communicates to the user that new data is being fetched while stale data remains visible. The `ChartView.tsx` parent wires this through.

### Indicator series diffing

Replace the current remove-all/recreate-all pattern with a stable `Map<string, { series: ISeriesApi[], type: 'overlay' | 'oscillator' }>` ref:

- **toRemove** (in map, not in enabled set): call `chart.removeSeries()` for each, delete from map
- **toAdd** (in enabled set, not in map): create series with `chart.addSeries()`, set data, store in map
- **toUpdate** (in both): call `setData()` on existing series objects — no remove/recreate

For oscillator series (MACD, StochRSI, etc.) that have multiple sub-series, `toUpdate` calls `setData()` on each sub-series by index. This works because the sub-series count per oscillator ID is fixed (e.g., MACD always has 3: histogram, MACD line, signal line).

Compound indicators (BB, Ichimoku, SuperTrend) use a `COMPOUND_INDICATORS` constant map to define parent-to-sub-key relationships:
```ts
const COMPOUND_INDICATORS: Record<string, string[]> = {
  bb: ["bb-upper", "bb-middle", "bb-lower"],
  supertrend: ["supertrend-up", "supertrend-down"],
  ichimoku: ["ich-tenkan", "ich-kijun", "ich-senkouA", "ich-senkouB"],
};
```
This replaces the current hardcoded cleanup blocks and makes it maintainable when adding new compound indicators.

**Known limitation:** When all oscillators are disabled, the empty oscillator pane remains visible (lightweight-charts v5.1 has no `removePane()` API). It renders as a small empty area — acceptable for MVP.

## Files changed

| File | Change |
|------|--------|
| `web/src/features/chart/components/CandlestickChart.tsx` | Full rewrite — three separated effects, series diffing, stable refs |
| `web/src/features/chart/hooks/useChartData.ts` | No change — already keeps stale candles during fetch (verified) |
| `web/src/features/chart/components/ChartView.tsx` | Pass `loading` prop from `useChartData` to `CandlestickChart` |

## What stays the same

- lightweight-charts v5.1 (no library change)
- `ChartView.tsx` (parent component, minimal change — only wires `loading` prop through)
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
