# Chart Tab: Exchange-Grade Compact Redesign

## Problem

The chart tab doesn't feel like a real trading app. Specific issues:
- Candles are too small and hard to read at a glance
- Price scale is hard to read / insufficient precision
- Zoom/pan behavior is clunky on mobile
- Too much padding wastes chart real estate
- Sections (timeframe bar, chart, OHLC strip) feel disconnected

**Target feel**: Binance/OKX app — dark, integrated, compact controls.

## Design

### 1. Full-Bleed Chart Layout

Remove all spacing that steals from the chart canvas:

- Chart container: `px-0` (currently `px-2`), no `rounded-lg`, no `overflow-hidden`
- Chart height: `calc(100dvh - 56px - 32px - 72px)` — TickerBar (56px, rendered by Layout.tsx) + compact header (32px) + bottom nav (~72px including safe-area). This is approximately `calc(100dvh - 10rem)`
- Remove the separate OHLC strip entirely — its data moves into an overlay (Section 3)
- Remove the `fullScreen` / oscillator-based height toggle — since the OHLC strip no longer exists, the chart always gets the same height regardless of which indicators are active
- Remove the `hasOscillator` import from `IndicatorSheet` (becomes unused with `fullScreen` removal)

**Files**: `ChartView.tsx`

### 2. Compact Header Row

Replace the current timeframe bar + indicator gear with one tight row:

- **Left**: Timeframe pills (15m, 1H, 4H, 1D) — `px-2 py-1`, `text-[10px]`, `gap-0.5`. Active state: `bg-primary/12 text-primary` (subtle highlight, not solid bg)
- **Right**: Indicator gear icon with active-count badge (existing behavior, same position)
- **Row styling**: `px-2.5 py-1.5`, `bg-surface` (same as chart background), no bottom border
- Net height: ~32px (down from ~44px)

**Files**: `ChartView.tsx`

### 3. Two-Row OHLC Overlay

Render OHLC + market data as a translucent overlay inside the chart area (top-left), not a separate strip:

- **Row 1**: `O 67,100.20  H 67,450.80  L 66,890.50  C 67,234.50`
- **Row 2**: `+2.34%  Vol 1.2B  Amp 0.83%`
- **Style**: `text-[9px]` monospace, labels in `text-on-surface-variant/60`, values in `text-on-surface-variant`, change% colored `text-long`/`text-short`
- **Position**: `absolute top-1 left-1.5`, `pointer-events-none`, `z-10`
- **Data source (default mode)**: `useLivePrice` hook — this shows **24h ticker data** (open24h, high24h, low24h, price, vol24h, change24h). Volume is in contracts (OKX SWAP convention); formatted with existing `formatVolume` helper. Amplitude = `(high24h - low24h) / low24h * 100`
- **Data source (crosshair mode)**: Per-candle OHLCV from the crosshair callback (see Section 5). When crosshair is active, the overlay shows the specific candle's values, not 24h ticker data

This is a React div layered over the lightweight-charts canvas, not part of the chart library.

**Files**: `ChartView.tsx` (new overlay div inside chart container)

### 4. Chart Config Improvements

Config-level changes to lightweight-charts for better candle rendering and touch:

- **Wider candles**: Increase `timeScale.minBarSpacing` (e.g. 6-8px) so candle bodies have more visual weight
- **Price scale font**: `fontSize: 12` (currently 11). Auto-precision formatting based on price magnitude, applied in two places:
  - **Chart price axis**: via `priceFormat.formatter` on the candlestick series (requires passing `pair` as a new prop to `CandlestickChart`). Applied reactively: a dedicated effect watches `pair` and calls `candleSeriesRef.current.applyOptions({ priceFormat: { formatter: ... } })` when it changes — avoids a full chart remount on pair switch
  - **OHLC overlay**: via a shared `formatPricePrecision(price, pair)` helper in ChartView
  - Rules: BTC (>10,000): 1 decimal (`67,234.5`), ETH (100-10,000): 2 decimals (`3,456.78`), WIF (<100): 4 decimals (`1.2345`)
- **Touch handling**:
  - `handleScroll.vertTouchDrag: true` (currently `false`) — enables natural vertical pan on mobile
  - `touch-action: none` on chart container (currently `pan-y`) — chart captures all gestures without browser interference. This is safe because the chart tab is a single-screen layout with no scrollable content outside the chart
  - Pinch zoom already enabled (`handleScale.pinch: true`)

**Files**: `CandlestickChart.tsx` (CHART_OPTIONS constant, container style)

### 5. Crosshair ↔ OHLC Interaction

The OHLC overlay dynamically switches between live and historical data:

- **Default**: Shows live ticker data from `useLivePrice`
- **On crosshair move**: Shows the candle under the crosshair. A small visual indicator (e.g. dot or "Crosshair" label) signals historical mode
- **On crosshair leave** (finger lifts / mouse exits): Snaps back to live data

Implementation:
- `CandlestickChart` accepts a new prop: `onCrosshairMove?: (candle: { open: number; high: number; low: number; close: number; volume: number; time: number } | null) => void`
- On mount, subscribe to `chart.subscribeCrosshairMove(params)`. Extract OHLC from `params.seriesData.get(candleSeriesRef.current)` (returns `CandlestickData` — has `open/high/low/close` but no `volume`). Extract volume from `params.seriesData.get(volSeriesRef.current)?.value`. Call `onCrosshairMove({ ...ohlc, volume })` on move, `onCrosshairMove(null)` when crosshair leaves
- `ChartView` stores crosshair data in a `useState` guarded by `requestAnimationFrame` — the `onCrosshairMove` callback sets a rAF flag and only calls `setState` once per frame. This limits overlay re-renders to ~60fps (one small div, no reconciliation cost) while being far simpler than manual DOM writes across 7+ value spans

**Files**: `CandlestickChart.tsx` (subscribe to crosshair events, new `onCrosshairMove` prop), `ChartView.tsx` (overlay reads crosshair state)

### 6. Visual Cohesion

Eliminate the "disconnected sections" feel:

- **One surface**: Everything uses `bg-surface` (`#0a0f14`) — header row, chart area, no contrasting `bg-surface-container` bands
- **No borders**: Remove `border-b border-outline-variant/10` between header and chart
- **No rounded corners**: Chart container is raw edge-to-edge canvas
- **Loading indicator**: Reposition from `top-2 right-2` to `top-8 right-2` so it doesn't collide with the OHLC overlay

**Files**: `ChartView.tsx`

## Files Changed

| File | Changes |
|------|---------|
| `ChartView.tsx` | Layout restructure, compact header, OHLC overlay, remove OHLC strip, remove padding/borders, remove `fullScreen` toggle + `hasOscillator` import |
| `CandlestickChart.tsx` | Chart options (bar spacing, price scale font, touch config, auto-precision), crosshair subscription, new `onCrosshairMove` + `pair` props |

## Out of Scope

- Drawing tools
- Multi-chart / split-view
- Order entry from chart
- Signal markers on chart
- Replacing lightweight-charts library
- Indicator sheet UX changes (separate effort)
