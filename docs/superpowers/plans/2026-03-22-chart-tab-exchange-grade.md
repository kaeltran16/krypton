# Chart Tab: Exchange-Grade Compact Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the chart tab into a Binance/OKX-style full-bleed, compact trading view with better candle rendering, crosshair-driven OHLC overlay, and improved mobile touch handling.

**Architecture:** Three files change — `ChartView.tsx` gets a layout restructure (full-bleed, compact header, OHLC overlay replacing the strip), `CandlestickChart.tsx` gets chart config improvements (wider candles, auto-precision price formatting, touch fixes, crosshair event subscription), and `IndicatorSheet.tsx` has the unused `hasOscillator` export removed. A shared `getPairDecimals` helper in `shared/lib/format.ts` provides pair-aware decimal precision for both the chart price axis and the OHLC overlay.

**Tech Stack:** React 19, TypeScript, lightweight-charts v5, Tailwind CSS v3

**Spec:** `docs/superpowers/specs/2026-03-22-chart-tab-exchange-grade-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `web/src/features/chart/components/CandlestickChart.tsx` | Modify | Chart config (bar spacing, font size, touch), crosshair subscription, new `onCrosshairMove` + `pair` props, auto-precision `priceFormat.formatter`, loading indicator repositioned |
| `web/src/features/chart/components/ChartView.tsx` | Modify | Full-bleed layout, compact header row, OHLC overlay (live + crosshair mode), remove OHLC strip, remove `fullScreen` toggle, `formatVolume` stays local |
| `web/src/features/chart/components/IndicatorSheet.tsx` | Modify | Remove `hasOscillator` export (no longer consumed) |
| `web/src/shared/lib/format.ts` | Modify | Add `getPairDecimals` + `formatPricePrecision` helpers |

---

### Task 1: Chart Config Improvements (CandlestickChart.tsx)

Update the `CHART_OPTIONS` constant and container styling for wider candles, larger price scale font, and proper mobile touch handling.

**Files:**
- Modify: `web/src/features/chart/components/CandlestickChart.tsx:55-77` (CHART_OPTIONS)
- Modify: `web/src/features/chart/components/CandlestickChart.tsx:506-521` (container div)

- [ ] **Step 1: Update CHART_OPTIONS**

In `CandlestickChart.tsx`, change the `CHART_OPTIONS` constant:

```typescript
const CHART_OPTIONS: DeepPartial<ChartOptions> = {
  layout: {
    background: { type: ColorType.Solid, color: theme.chart.background },
    textColor: theme.chart.text,
    fontFamily: "Inter, system-ui, sans-serif",
    fontSize: 12, // was 11
  },
  grid: {
    vertLines: { color: theme.chart.grid },
    horzLines: { color: theme.chart.grid },
  },
  crosshair: { mode: CrosshairMode.Normal },
  rightPriceScale: {
    borderColor: theme.chart.scaleBorder,
  },
  timeScale: {
    borderColor: theme.chart.scaleBorder,
    timeVisible: true,
    secondsVisible: false,
    minBarSpacing: 7, // wider candles (was default ~4)
  },
  handleScale: { pinch: true, mouseWheel: true, axisPressedMouseMove: true },
  handleScroll: { pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true }, // vertTouchDrag was false
};
```

Changes: `fontSize: 12`, `minBarSpacing: 7`, `vertTouchDrag: true`.

- [ ] **Step 2: Update container touch-action**

In the return JSX at the bottom of `CandlestickChart.tsx`, change the container `style` from `touchAction: "pan-y"` to `touchAction: "none"`:

```tsx
<div
  ref={containerRef}
  className="w-full h-full"
  style={{ touchAction: "none", overscrollBehavior: "none" }}
/>
```

- [ ] **Step 3: Reposition loading indicator**

Change the loading overlay position from `top-2 right-2` to `top-8 right-2` so it doesn't collide with the OHLC overlay:

```tsx
{loading && (
  <div className="absolute top-8 right-2 flex items-center gap-1.5 px-2 py-1 rounded bg-card/80 backdrop-blur-sm">
    <div className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
    <span className="text-[10px] text-muted font-medium">Loading</span>
  </div>
)}
```

- [ ] **Step 4: Verify in browser**

Run: `cd web && pnpm dev`

Open the chart tab. Verify:
- Candles appear wider/chunkier
- Price scale text is slightly larger
- Touch drag works vertically on mobile (or Chrome DevTools mobile emulation)
- No browser scroll interference on the chart

---

### Task 2: Auto-Precision Price Formatting (CandlestickChart.tsx + shared/lib/format.ts)

Add a `pair` prop and apply pair-aware price formatting to the chart's price axis. BTC (>10,000) gets 1 decimal, ETH (100-10,000) gets 2, WIF (<100) gets 4. Price precision logic lives in `shared/lib/format.ts` so ChartView can reuse it.

**Files:**
- Modify: `web/src/shared/lib/format.ts` (add `getPairDecimals` + `formatPricePrecision`)
- Modify: `web/src/features/chart/components/CandlestickChart.tsx:43-48` (Props interface)
- Modify: `web/src/features/chart/components/CandlestickChart.tsx:89` (destructure props)
- Modify: `web/src/features/chart/components/ChartView.tsx:72` (pass `pair` prop)
- Add new effect after Effect 1.5 (~line 184)

- [ ] **Step 1: Add shared price precision helpers to format.ts**

In `web/src/shared/lib/format.ts`, add:

```typescript
export function getPairDecimals(pair: string): number {
  return pair.startsWith("BTC") ? 1 : pair.startsWith("ETH") ? 2 : 4;
}

export function formatPricePrecision(price: number, pair: string): string {
  const decimals = getPairDecimals(pair);
  return price.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}
```

- [ ] **Step 2: Add `pair` prop to CandlestickChart**

Update the `Props` interface and destructure:

```typescript
interface Props {
  candles: CandleData[];
  enabledIndicators: Set<string>;
  loading?: boolean;
  onTickRef?: MutableRefObject<TickCallback | null>;
  pair: string;                    // NEW
  onCrosshairMove?: (candle: {     // NEW (used in Task 5)
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    time: number;
  } | null) => void;
}
```

Update the destructure:

```typescript
export function CandlestickChart({ candles, enabledIndicators, loading, onTickRef, pair, onCrosshairMove }: Props) {
```

- [ ] **Step 3: Update CandlestickChart call in ChartView to pass `pair`**

In `ChartView.tsx`, update the `<CandlestickChart>` call to pass the new required `pair` prop immediately (prevents build breakage):

```tsx
<CandlestickChart candles={candles} enabledIndicators={enabledIds} loading={loading} onTickRef={onTickRef} pair={pair} />
```

- [ ] **Step 4: Add price formatter helper (module-level in CandlestickChart)**

Add this helper function above the component (after `toTime`), importing from shared:

```typescript
import { getPairDecimals } from "../../../shared/lib/format";

function makePriceFormatter(pair: string) {
  const decimals = getPairDecimals(pair);
  return (price: number) => price.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}
```

- [ ] **Step 5: Add Effect 1.6 — reactive price format update**

Add a new effect after Effect 1.5 (the tick handler). This effect reactively updates the candle series price format when `pair` changes, without remounting the chart:

```typescript
// ── Effect 1.6: Auto-precision price format ([pair]) ──
useEffect(() => {
  const candleSeries = candleSeriesRef.current;
  if (!candleSeries) return;
  candleSeries.applyOptions({
    priceFormat: {
      type: "custom",
      formatter: makePriceFormatter(pair),
    },
  });
}, [pair]);
```

- [ ] **Step 6: Verify in browser**

Open the chart tab. Switch between BTC, ETH, and WIF pairs:
- BTC price axis should show 1 decimal (e.g. `67,234.5`)
- ETH price axis should show 2 decimals (e.g. `3,456.78`)
- WIF price axis should show 4 decimals (e.g. `1.2345`)

---

### Task 3: Crosshair Event Subscription (CandlestickChart.tsx)

Subscribe to crosshair move events and forward OHLCV data to the parent via the new `onCrosshairMove` callback.

**Files:**
- Modify: `web/src/features/chart/components/CandlestickChart.tsx` (new effect after Effect 1.6)

- [ ] **Step 1: Add crosshair effect**

Add a new effect after Effect 1.6. This subscribes to chart crosshair events and extracts OHLC from the candle series + volume from the volume series. Import `MouseEventParams` from lightweight-charts for type safety:

```typescript
import type { MouseEventParams } from "lightweight-charts";
// (add to existing lightweight-charts type imports)
```

```typescript
// ── Effect 1.7: Crosshair ↔ OHLC callback ([onCrosshairMove]) ──
useEffect(() => {
  const chart = chartRef.current;
  const candleSeries = candleSeriesRef.current;
  const volSeries = volSeriesRef.current;
  if (!chart || !candleSeries || !volSeries || !onCrosshairMove) return;

  const handler = (params: MouseEventParams) => {
    if (!params.point || params.point.x < 0 || params.point.y < 0) {
      onCrosshairMove(null);
      return;
    }
    const ohlc = params.seriesData.get(candleSeries) as
      | { open: number; high: number; low: number; close: number; time: number }
      | undefined;
    const vol = params.seriesData.get(volSeries) as
      | { value: number }
      | undefined;
    if (ohlc) {
      onCrosshairMove({
        open: ohlc.open,
        high: ohlc.high,
        low: ohlc.low,
        close: ohlc.close,
        volume: vol?.value ?? 0,
        time: typeof ohlc.time === "number" ? ohlc.time : 0,
      });
    } else {
      onCrosshairMove(null);
    }
  };

  chart.subscribeCrosshairMove(handler);
  return () => chart.unsubscribeCrosshairMove(handler);
}, [onCrosshairMove]);
```

- [ ] **Step 2: Verify no regressions**

Run: `cd web && pnpm build`

Expected: TypeScript compilation passes with no errors (`pair` was already wired in Task 2 Step 3, `onCrosshairMove` is optional).

---

### Task 4: Remove `fullScreen` / `hasOscillator` (ChartView.tsx + IndicatorSheet.tsx)

Remove the oscillator-based height toggle that is no longer needed (the OHLC strip is being removed, so the chart always gets the same height).

**Files:**
- Modify: `web/src/features/chart/components/ChartView.tsx:4,23,35` (remove imports and usage)
- Modify: `web/src/features/chart/components/IndicatorSheet.tsx:66-75` (remove `hasOscillator` export)

- [ ] **Step 1: Remove `hasOscillator` from IndicatorSheet.tsx**

Delete the `OSCILLATOR_IDS` set and `hasOscillator` function (lines 66-75 of `IndicatorSheet.tsx`):

```typescript
// DELETE these lines:
const OSCILLATOR_IDS = new Set(
  INDICATOR_GROUPS.find((g) => g.label === "Oscillators")!.items.map((i) => i.id)
);

export function hasOscillator(enabledIds: Set<string>): boolean {
  for (const id of enabledIds) {
    if (OSCILLATOR_IDS.has(id)) return true;
  }
  return false;
}
```

- [ ] **Step 2: Remove `hasOscillator` usage from ChartView.tsx**

In `ChartView.tsx`:

1. Change the import on line 4 from:
   ```typescript
   import { IndicatorSheet, getStoredIndicators, hasOscillator } from "./IndicatorSheet";
   ```
   to:
   ```typescript
   import { IndicatorSheet, getStoredIndicators } from "./IndicatorSheet";
   ```

2. Delete the `fullScreen` variable (line 23):
   ```typescript
   // DELETE:
   const fullScreen = hasOscillator(enabledIds);
   ```

3. Replace the dynamic height class on the outer div (line 35). Change:
   ```tsx
   <div className={`flex flex-col ${fullScreen ? "h-[calc(100dvh-4rem)]" : "h-[calc(100dvh-6.5rem)]"}`}>
   ```
   to a static height. The deduction accounts only for elements outside ChartView (TickerBar `h-14` = 56px ≈ 3.5rem). The header row inside is handled by flex layout, and the glass bottom nav intentionally overlays the chart:
   ```tsx
   <div className="flex flex-col h-[calc(100dvh-3.5rem)]">
   ```

- [ ] **Step 3: Verify build**

Run: `cd web && pnpm build`

Expected: No TypeScript errors. No references to `hasOscillator` remain.

---

### Task 5: OHLC Overlay with Crosshair Interaction (ChartView.tsx)

Replace the bottom OHLC strip with a translucent overlay inside the chart area. The overlay shows live 24h ticker data by default and switches to per-candle data on crosshair hover.

**Files:**
- Modify: `web/src/features/chart/components/ChartView.tsx` (full restructure of JSX)

- [ ] **Step 1: Add crosshair state and rAF-throttled callback**

At the top of `ChartView`, after the existing state declarations, add:

```typescript
import { useState, useCallback, useRef } from "react";
// (update the existing import to include useRef)
```

Then inside the component:

```typescript
const [crosshairCandle, setCrosshairCandle] = useState<{
  open: number; high: number; low: number; close: number; volume: number; time: number;
} | null>(null);
const rafRef = useRef(0);

const handleCrosshairMove = useCallback((candle: {
  open: number; high: number; low: number; close: number; volume: number; time: number;
} | null) => {
  cancelAnimationFrame(rafRef.current);
  rafRef.current = requestAnimationFrame(() => setCrosshairCandle(candle));
}, []);
```

- [ ] **Step 2: Import `formatPricePrecision` from shared**

In `ChartView.tsx`, update the format import (replacing `formatPrice` which is no longer used):

```typescript
import { formatPricePrecision } from "../../../shared/lib/format";
```

- [ ] **Step 3: Remove the OHLC strip JSX**

Delete the entire `{!fullScreen && ( ... )}` block (lines 77-98 in the original file) — the bottom OHLC strip with O/H/L/C values, volume, and 24h change.

- [ ] **Step 4: Add the OHLC overlay inside the chart container**

Replace the chart section with a `relative` wrapper containing the chart + overlay. The overlay is a `pointer-events-none` div positioned `absolute top-1 left-1.5`:

```tsx
{/* Chart with OHLC overlay */}
<div className="flex-1 min-h-0 relative">
  <CandlestickChart
    candles={candles}
    enabledIndicators={enabledIds}
    loading={loading}
    onTickRef={onTickRef}
    pair={pair}
    onCrosshairMove={handleCrosshairMove}
  />
  {/* OHLC Overlay */}
  <div className="absolute top-1 left-1.5 z-10 pointer-events-none font-mono">
    {(() => {
      // Use direct destructuring instead of an intermediate boolean —
      // TypeScript cannot narrow through `const isLive = !crosshairCandle`.
      const cc = crosshairCandle;
      const o = cc ? cc.open : open24h;
      const h = cc ? cc.high : high24h;
      const l = cc ? cc.low : low24h;
      const c = cc ? cc.close : price;
      const vol = cc ? cc.volume : vol24h;
      const pctChange = cc
        ? (o ? ((c! - o) / o) * 100 : null)
        : change24h;
      const amp = h && l && l > 0 ? ((h - l) / l) * 100 : null;

      return (
        <>
          <div className="text-[9px] leading-tight flex gap-2">
            <span className="text-on-surface-variant/60">O <span className="text-on-surface-variant tabular">{o != null ? formatPricePrecision(o, pair) : "—"}</span></span>
            <span className="text-on-surface-variant/60">H <span className="text-on-surface-variant tabular">{h != null ? formatPricePrecision(h, pair) : "—"}</span></span>
            <span className="text-on-surface-variant/60">L <span className="text-on-surface-variant tabular">{l != null ? formatPricePrecision(l, pair) : "—"}</span></span>
            <span className="text-on-surface-variant/60">C <span className="text-on-surface-variant tabular">{c != null ? formatPricePrecision(c, pair) : "—"}</span></span>
            {cc && <span className="text-on-surface-variant/40 text-[8px]">Crosshair</span>}
          </div>
          <div className="text-[9px] leading-tight flex gap-2 mt-px">
            {pctChange != null && (
              <span className={`tabular ${pctChange >= 0 ? "text-long" : "text-short"}`}>
                {pctChange >= 0 ? "+" : ""}{pctChange.toFixed(2)}%
              </span>
            )}
            <span className="text-on-surface-variant/60">Vol <span className="text-on-surface-variant tabular">{vol != null ? formatVolume(vol) : "—"}</span></span>
            {amp != null && (
              <span className="text-on-surface-variant/60">Amp <span className="text-on-surface-variant tabular">{amp.toFixed(2)}%</span></span>
            )}
          </div>
        </>
      );
    })()}
  </div>
</div>
```

- [ ] **Step 5: Verify in browser**

Run: `cd web && pnpm dev`

Open the chart tab. Verify:
- OHLC overlay appears top-left inside the chart area with 9px monospace text
- Default mode shows 24h ticker data (O/H/L/C + change% + Vol + Amp)
- Hovering crosshair over candles switches to per-candle OHLCV + "Crosshair" label
- Lifting finger / mouse leaving chart snaps back to live data
- No bottom OHLC strip exists anymore

---

### Task 6: Full-Bleed Layout + Compact Header + Visual Cohesion (ChartView.tsx)

Final layout pass — remove all padding/borders, compact the header row, set the correct chart height, and unify surface colors.

**Files:**
- Modify: `web/src/features/chart/components/ChartView.tsx` (layout classes)

- [ ] **Step 1: Verify outer container height**

The outer div should already be `h-[calc(100dvh-3.5rem)]` from Task 4. This accounts for the TickerBar (`h-14` = 56px ≈ 3.5rem) only — the glass bottom nav intentionally overlays the chart for a full-bleed feel, and the header row inside is handled by flex layout. Verify this is correct.

- [ ] **Step 2: Compact the header row**

Update the header row (timeframe pills + indicator gear). Change the row div classes from:

```tsx
<div className="flex items-center justify-between px-3 py-1.5 bg-surface-container border-b border-outline-variant/10">
```

to:

```tsx
<div className="flex items-center justify-between px-2.5 py-1.5 bg-surface">
```

Changes: `px-3` → `px-2.5`, `bg-surface-container` → `bg-surface`, removed `border-b border-outline-variant/10`.

- [ ] **Step 3: Compact timeframe pills**

Update each timeframe button's classes from:

```tsx
className={`px-3 py-1 text-xs font-bold font-headline rounded-lg transition-colors ...`}
```

to:

```tsx
className={`px-2 py-1 text-[10px] font-bold font-headline rounded-lg transition-colors ...`}
```

And change the gap on the pills container from `gap-1` to `gap-0.5`.

Also update the active state. Change from:

```tsx
timeframe === tf
  ? "bg-surface-container-highest text-primary"
  : "text-on-surface-variant hover:bg-surface-container-highest"
```

to:

```tsx
timeframe === tf
  ? "bg-primary/12 text-primary"
  : "text-on-surface-variant hover:bg-surface-container-highest"
```

- [ ] **Step 4: Remove chart container padding and rounding**

Change the chart wrapper from:

```tsx
<div className="flex-1 min-h-0 px-2">
  <div className="w-full h-full rounded-lg overflow-hidden">
```

to just the `relative` wrapper from Task 5 (no `px-2`, no `rounded-lg`, no inner wrapper):

```tsx
<div className="flex-1 min-h-0 relative">
```

The chart and overlay live directly inside this div.

- [ ] **Step 5: Verify in browser**

Run: `cd web && pnpm dev`

Open the chart tab. Verify:
- Chart is edge-to-edge (no side padding)
- Header row is compact (~32px), no bottom border
- Header background matches chart background (single `bg-surface` surface)
- Timeframe pills are smaller with subtle active highlight
- Everything feels like one integrated surface, no disconnected sections
- Loading indicator doesn't overlap the OHLC overlay

- [ ] **Step 6: Verify build**

Run: `cd web && pnpm build`

Expected: Clean build, no TypeScript errors.

---

## Commit

After all tasks pass the final verification checklist, make a single commit:

```bash
git add web/src/shared/lib/format.ts web/src/features/chart/components/CandlestickChart.tsx web/src/features/chart/components/ChartView.tsx web/src/features/chart/components/IndicatorSheet.tsx
git commit -m "feat(chart): exchange-grade compact redesign — full-bleed layout, OHLC overlay, crosshair, wider candles"
```

---

## Final Verification Checklist

After all tasks are complete:

- [ ] `pnpm build` passes with no errors
- [ ] `pnpm lint` passes
- [ ] Chart fills viewport edge-to-edge with no padding or rounded corners
- [ ] Candles are visually wider/chunkier than before
- [ ] Price axis shows pair-appropriate decimal precision (BTC: 1, ETH: 2, WIF: 4)
- [ ] OHLC overlay (top-left, 9px monospace) shows live ticker data by default
- [ ] Crosshair interaction switches overlay to per-candle OHLCV with "Crosshair" label
- [ ] Lifting finger / exiting chart returns overlay to live mode
- [ ] Mobile touch: vertical drag pans chart, pinch zooms, no browser scroll interference
- [ ] Header row is compact (~32px), single surface color, no borders
- [ ] No bottom OHLC strip exists
- [ ] Loading indicator visible at `top-8` (doesn't collide with overlay)
- [ ] IndicatorSheet still works (gear icon, toggle indicators, badge count)
