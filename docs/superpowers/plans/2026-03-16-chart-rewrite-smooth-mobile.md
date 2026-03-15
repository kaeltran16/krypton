# Chart Rewrite — Smooth Mobile Experience Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the React integration layer for the candlestick chart to eliminate pinch-to-zoom lag and flash/jump on indicator toggle or timeframe switch.

**Architecture:** Three separated `useEffect` hooks (chart creation, candle data, indicators) with ref-stable series management. Indicator series are diffed (add/remove/update) instead of destroyed and recreated. Touch gesture conflicts resolved via `touch-action: pan-y` CSS.

**Tech Stack:** React 19, TypeScript, lightweight-charts v5.1, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-03-16-chart-rewrite-smooth-mobile-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `web/src/features/chart/components/CandlestickChart.tsx` | **Rewrite** | Chart lifecycle, series management, indicator rendering, loading overlay |
| `web/src/features/chart/components/ChartView.tsx` | **Modify** (2 lines) | Wire `loading` prop from `useChartData` to `CandlestickChart` |
| `web/src/features/chart/hooks/useChartData.ts` | **No change** | Already keeps stale candles during fetch (verified) |
| `web/src/features/chart/components/IndicatorSheet.tsx` | **No change** | Indicator selection UI |
| `web/src/features/chart/lib/indicators.ts` | **No change** | Calculation functions |

---

## Chunk 1: ChartView Wiring + CandlestickChart Scaffold

### Task 1: Wire loading prop through ChartView

**Files:**
- Modify: `web/src/features/chart/components/ChartView.tsx:20,80`

- [ ] **Step 1: Destructure `loading` from `useChartData` and pass to `CandlestickChart`**

In `ChartView.tsx`, change line 20 from:
```tsx
const { candles } = useChartData(pair, timeframe);
```
to:
```tsx
const { candles, loading } = useChartData(pair, timeframe);
```

And change line 80 from:
```tsx
<CandlestickChart candles={candles} enabledIndicators={enabledIds} />
```
to:
```tsx
<CandlestickChart candles={candles} enabledIndicators={enabledIds} loading={loading} />
```

---

### Task 2: Rewrite CandlestickChart — imports, types, constants, and component scaffold

**Files:**
- Rewrite: `web/src/features/chart/components/CandlestickChart.tsx`

This task writes the top half of the file: imports, types, constants, ref declarations, and the JSX return. Tasks 3-5 fill in the three effects.

- [ ] **Step 1: Write imports, Props, SeriesEntry type, constants, and COMPOUND_INDICATORS**

```tsx
import { useEffect, useRef, useMemo } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
} from "lightweight-charts";
import type {
  IChartApi,
  ISeriesApi,
  IPriceLine,
  UTCTimestamp,
  DeepPartial,
  ChartOptions,
} from "lightweight-charts";
import type { CandleData } from "../../../shared/lib/api";
import { theme } from "../../../shared/theme";
import { INDICATOR_MAP } from "./IndicatorSheet";
import {
  calcEMA,
  calcSMA,
  calcBB,
  calcRSI,
  calcMACD,
  calcATR,
  calcVWAP,
  calcStochRSI,
  calcCCI,
  calcADX,
  calcWilliamsR,
  calcMFI,
  calcOBV,
  calcSuperTrend,
  calcParabolicSAR,
  calcIchimoku,
  detectSupportResistance,
} from "../lib/indicators";

interface Props {
  candles: CandleData[];
  enabledIndicators: Set<string>;
  loading?: boolean;
}

interface SeriesEntry {
  series: ISeriesApi<"Line" | "Histogram">[];
  type: "overlay" | "oscillator";
}

const CHART_OPTIONS: DeepPartial<ChartOptions> = {
  layout: {
    background: { type: ColorType.Solid, color: theme.chart.background },
    textColor: theme.chart.text,
    fontFamily: "Inter, system-ui, sans-serif",
    fontSize: 11,
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
  },
  handleScale: { pinch: true, mouseWheel: true, axisPressedMouseMove: true },
  handleScroll: { pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
};

const COMPOUND_INDICATORS: Record<string, string[]> = {
  bb: ["bb-upper", "bb-middle", "bb-lower"],
  supertrend: ["supertrend-up", "supertrend-down"],
  ichimoku: ["ich-tenkan", "ich-kijun", "ich-senkouA", "ich-senkouB"],
};

function toTime(ts: number): UTCTimestamp {
  return (ts / 1000) as UTCTimestamp;
}
```

- [ ] **Step 2: Write the component function signature, refs, enabledKey memo, and JSX return**

```tsx
export function CandlestickChart({ candles, enabledIndicators, loading }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const seriesMapRef = useRef<Map<string, SeriesEntry>>(new Map());
  const oscPaneCreated = useRef(false);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const prevCandleCountRef = useRef(0);
  const prevFirstTimeRef = useRef<UTCTimestamp | null>(null);

  const enabledKey = useMemo(
    () => [...enabledIndicators].sort().join(","),
    [enabledIndicators]
  );

  // === Effects go here (Tasks 3-5) ===

  return (
    <div className="relative w-full h-full">
      <div
        ref={containerRef}
        className="w-full h-full"
        style={{ touchAction: "pan-y", overscrollBehavior: "none" }}
      />
      {loading && (
        <div className="absolute top-2 right-2 flex items-center gap-1.5 px-2 py-1 rounded bg-card/80 backdrop-blur-sm">
          <div className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
          <span className="text-[10px] text-muted font-medium">Loading</span>
        </div>
      )}
    </div>
  );
}
```

---

### Task 3: Effect 1 — Chart creation (mount-only)

**Files:**
- Modify: `web/src/features/chart/components/CandlestickChart.tsx` (insert after `enabledKey` memo)

- [ ] **Step 1: Write Effect 1 — creates chart, candle series, volume series, ResizeObserver**

Insert this effect after the `enabledKey` memo. This is identical to the current Effect 1 — it already works correctly.

```tsx
  // ── Effect 1: Chart creation (mount only) ──
  // DO NOT reorder effects — declaration order is load-bearing (see Effect 2/3 comments)
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      ...CHART_OPTIONS,
      width: container.clientWidth,
      height: container.clientHeight,
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: theme.chart.candleUp,
      downColor: theme.chart.candleDown,
      wickUpColor: theme.chart.candleUp,
      wickDownColor: theme.chart.candleDown,
      borderVisible: false,
    });
    candleSeriesRef.current = candleSeries;

    const volSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    volSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volSeriesRef.current = volSeries;

    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      chart.applyOptions({ width, height });
    });
    ro.observe(container);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volSeriesRef.current = null;
      seriesMapRef.current.clear();
      oscPaneCreated.current = false;
      prevCandleCountRef.current = 0;
      prevFirstTimeRef.current = null;
    };
  }, []);
```

- [ ] **Step 2: Run `pnpm build` to verify no type errors so far**

Run: `cd web && pnpm build`
Expected: Build succeeds (the file compiles even though Effects 2/3 are not yet written — the chart just won't show data yet)

---

## Chunk 2: Effects 2 and 3

### Task 4: Effect 2 — Candle data updates

**Files:**
- Modify: `web/src/features/chart/components/CandlestickChart.tsx` (insert after Effect 1)

- [ ] **Step 1: Write Effect 2 — candle + volume data with streaming detection**

Insert after Effect 1. This is the candle-data-only part of the old monolithic effect.

```tsx
  // ── Effect 2: Candle data ([candles] only) ──
  // Runs BEFORE Effect 3 (indicators) — do not reorder
  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    const volSeries = volSeriesRef.current;
    if (!chart || !candleSeries || !volSeries || !candles.length) return;

    const deduped = [...new Map(candles.map((c) => [c.timestamp, c])).values()]
      .sort((a, b) => a.timestamp - b.timestamp);

    const mapped = deduped.map((c) => ({
      time: toTime(c.timestamp),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    const volData = deduped.map((c) => ({
      time: toTime(c.timestamp),
      value: c.volume,
      color: c.close >= c.open ? theme.chart.volumeUp : theme.chart.volumeDown,
    }));

    const prevCount = prevCandleCountRef.current;
    const firstTime = mapped[0]?.time ?? null;
    const datasetChanged = prevFirstTimeRef.current !== firstTime;
    const isStreaming =
      prevCount > 0 && !datasetChanged && Math.abs(deduped.length - prevCount) <= 1;

    if (isStreaming) {
      candleSeries.update(mapped[mapped.length - 1]);
      volSeries.update(volData[volData.length - 1]);
    } else {
      candleSeries.setData(mapped);
      volSeries.setData(volData);
      chart.timeScale().fitContent();
    }
    prevCandleCountRef.current = deduped.length;
    prevFirstTimeRef.current = firstTime;
  }, [candles]);
```

---

### Task 5: Effect 3 — Indicator rendering with series diffing

**Files:**
- Modify: `web/src/features/chart/components/CandlestickChart.tsx` (insert after Effect 2)

This is the largest task. It replaces the old monolithic indicator section with a diffing approach.

- [ ] **Step 1: Write the helper functions inside Effect 3 — dedup, ensureOscPane, buildLineData, addOverlay, addOsc**

Insert after Effect 2:

```tsx
  // ── Effect 3: Indicators ([candles, enabledKey]) ──
  // Runs AFTER Effect 2 (candle data) — do not reorder
  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    if (!chart || !candleSeries || !candles.length) return;

    const deduped = [...new Map(candles.map((c) => [c.timestamp, c])).values()]
      .sort((a, b) => a.timestamp - b.timestamp);
    const closes = deduped.map((c) => c.close);
    const times = deduped.map((c) => toTime(c.timestamp));

    const ensureOscPane = (): number => {
      if (!oscPaneCreated.current) {
        const pane = chart.addPane();
        pane.setStretchFactor(300);
        oscPaneCreated.current = true;
      }
      return chart.panes().length - 1;
    };

    const buildLineData = (data: (number | null)[]) => {
      const out: { time: UTCTimestamp; value: number }[] = [];
      for (let i = 0; i < data.length; i++) {
        if (data[i] !== null) out.push({ time: times[i], value: data[i]! });
      }
      return out;
    };

    const buildHistData = (data: (number | null)[]) => {
      const out: { time: UTCTimestamp; value: number; color: string }[] = [];
      for (let i = 0; i < data.length; i++) {
        if (data[i] !== null) {
          out.push({
            time: times[i],
            value: data[i]!,
            color: data[i]! >= 0 ? theme.chart.macdHistUp : theme.chart.macdHistDown,
          });
        }
      }
      return out;
    };

    // Add or update a single overlay line series
    const upsertOverlay = (
      id: string,
      data: (number | null)[],
      color: string,
      lineWidth: number = 1
    ) => {
      const existing = seriesMapRef.current.get(id);
      const lineData = buildLineData(data);
      if (existing) {
        existing.series[0].setData(lineData);
        return;
      }
      const s = chart.addSeries(LineSeries, {
        color,
        lineWidth: lineWidth as 1 | 2 | 3 | 4,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      s.setData(lineData);
      seriesMapRef.current.set(id, { series: [s], type: "overlay" });
    };

    // Add or update oscillator series (multiple sub-series per ID)
    const upsertOsc = (
      id: string,
      datasets: { data: (number | null)[]; color: string; type?: "line" | "histogram" }[]
    ) => {
      const paneIdx = ensureOscPane();
      const existing = seriesMapRef.current.get(id);

      if (existing && existing.series.length === datasets.length) {
        // Update existing sub-series by index
        for (let i = 0; i < datasets.length; i++) {
          const ds = datasets[i];
          if (ds.type === "histogram") {
            existing.series[i].setData(buildHistData(ds.data));
          } else {
            existing.series[i].setData(buildLineData(ds.data));
          }
        }
        return;
      }

      // Remove old if sub-series count changed (shouldn't happen, but defensive)
      if (existing) {
        for (const s of existing.series) chart.removeSeries(s);
        seriesMapRef.current.delete(id);
      }

      const seriesList: ISeriesApi<"Line" | "Histogram">[] = [];
      for (const ds of datasets) {
        if (ds.type === "histogram") {
          const s = chart.addSeries(HistogramSeries, {
            priceLineVisible: false,
            lastValueVisible: false,
            priceScaleId: `osc-${id}`,
          }, paneIdx);
          s.setData(buildHistData(ds.data));
          seriesList.push(s);
        } else {
          const s = chart.addSeries(LineSeries, {
            color: ds.color,
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
            priceScaleId: `osc-${id}`,
          }, paneIdx);
          s.setData(buildLineData(ds.data));
          seriesList.push(s);
        }
      }
      seriesMapRef.current.set(id, { series: seriesList, type: "oscillator" });
    };
```

- [ ] **Step 2: Write the diff logic — compute toRemove, then render all enabled indicators**

Continue inside the same effect, after the helper functions:

```tsx
    // --- Diff: remove series for disabled indicators ---
    const currentEnabled = new Set(enabledIndicators);

    // Expand compound indicators to their sub-keys for removal
    const allEnabledKeys = new Set(currentEnabled);
    for (const [parent, subKeys] of Object.entries(COMPOUND_INDICATORS)) {
      if (currentEnabled.has(parent)) {
        for (const sk of subKeys) allEnabledKeys.add(sk);
      }
    }

    for (const [key, entry] of seriesMapRef.current) {
      if (!allEnabledKeys.has(key)) {
        for (const s of entry.series) chart.removeSeries(s);
        seriesMapRef.current.delete(key);
      }
    }

    // Remove price lines if pivots disabled
    if (!currentEnabled.has("pivots")) {
      for (const pl of priceLinesRef.current) candleSeries.removePriceLine(pl);
      priceLinesRef.current = [];
    }

    // --- Render all enabled indicators (upsert handles add vs update) ---
    try {
      for (const id of enabledIndicators) {
        const def = INDICATOR_MAP.get(id);
        if (!def) continue;

        switch (id) {
          case "ema21":
            upsertOverlay(id, calcEMA(closes, 21), def.color);
            break;
          case "ema50":
            upsertOverlay(id, calcEMA(closes, 50), def.color);
            break;
          case "ema200":
            upsertOverlay(id, calcEMA(closes, 200), def.color);
            break;
          case "sma21":
            upsertOverlay(id, calcSMA(closes, 21), def.color);
            break;
          case "sma50":
            upsertOverlay(id, calcSMA(closes, 50), def.color);
            break;
          case "sma200":
            upsertOverlay(id, calcSMA(closes, 200), def.color);
            break;
          case "bb": {
            const bb = calcBB(closes);
            upsertOverlay("bb-upper", bb.upper, theme.indicators.bb);
            upsertOverlay("bb-middle", bb.middle, theme.indicators.bb);
            upsertOverlay("bb-lower", bb.lower, theme.indicators.bb);
            break;
          }
          case "vwap":
            upsertOverlay(id, calcVWAP(deduped), def.color);
            break;
          case "supertrend": {
            const st = calcSuperTrend(deduped);
            const stData = st.value.map((v, i) => ({
              val: v,
              up: st.direction[i] === 1,
            }));
            const upData: (number | null)[] = stData.map((d) => d.up ? d.val : null);
            const downData: (number | null)[] = stData.map((d) => d.up ? null : d.val);
            upsertOverlay("supertrend-up", upData, theme.chart.candleUp, 2);
            upsertOverlay("supertrend-down", downData, theme.chart.candleDown, 2);
            break;
          }
          case "psar": {
            const psar = calcParabolicSAR(deduped);
            upsertOverlay(id, psar.value, def.color);
            break;
          }
          case "ichimoku": {
            const ich = calcIchimoku(deduped);
            upsertOverlay("ich-tenkan", ich.tenkanSen, theme.indicators.ichTenkan);
            upsertOverlay("ich-kijun", ich.kijunSen, theme.indicators.ichKijun);
            upsertOverlay("ich-senkouA", ich.senkouA, theme.indicators.ichSenkouA);
            upsertOverlay("ich-senkouB", ich.senkouB, theme.indicators.ichSenkouB);
            break;
          }
          case "pivots": {
            for (const pl of priceLinesRef.current) candleSeries.removePriceLine(pl);
            priceLinesRef.current = [];
            const srLevels = detectSupportResistance(deduped);
            for (const lv of srLevels) {
              const isSupport = lv.type === "support";
              const pl = candleSeries.createPriceLine({
                price: lv.price,
                color: isSupport ? theme.chart.candleUp : theme.chart.candleDown,
                lineWidth: lv.strength >= 4 ? 2 : 1,
                lineStyle: LineStyle.Dashed,
                axisLabelVisible: true,
                title: `${isSupport ? "S" : "R"} (${lv.strength})`,
              });
              priceLinesRef.current.push(pl);
            }
            break;
          }
          case "rsi":
            upsertOsc(id, [{ data: calcRSI(closes), color: def.color }]);
            break;
          case "macd": {
            const macd = calcMACD(closes);
            upsertOsc(id, [
              { data: macd.histogram, color: theme.indicators.bb, type: "histogram" },
              { data: macd.macd, color: theme.indicators.macd },
              { data: macd.signal, color: theme.indicators.macdSignal },
            ]);
            break;
          }
          case "stochrsi": {
            const sr = calcStochRSI(closes);
            upsertOsc(id, [
              { data: sr.k, color: theme.indicators.stochK },
              { data: sr.d, color: theme.indicators.stochD },
            ]);
            break;
          }
          case "cci":
            upsertOsc(id, [{ data: calcCCI(deduped), color: def.color }]);
            break;
          case "atr":
            upsertOsc(id, [{ data: calcATR(deduped), color: def.color }]);
            break;
          case "adx":
            upsertOsc(id, [{ data: calcADX(deduped), color: def.color }]);
            break;
          case "willr":
            upsertOsc(id, [{ data: calcWilliamsR(deduped), color: def.color }]);
            break;
          case "mfi":
            upsertOsc(id, [{ data: calcMFI(deduped), color: def.color }]);
            break;
          case "obv":
            upsertOsc(id, [{ data: calcOBV(deduped), color: def.color }]);
            break;
        }
      }
    } catch (e) {
      console.error("[CandlestickChart] indicator calculation error:", e);
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, enabledKey]);
```

---

## Chunk 3: Verification

### Task 6: Build and verify

**Files:** None (verification only)

- [ ] **Step 1: Run TypeScript build**

Run: `cd web && pnpm build`
Expected: Build succeeds with no type errors

- [ ] **Step 2: Run linter**

Run: `cd web && pnpm lint`
Expected: No new lint errors (the existing `eslint-disable-next-line` comment covers the exhaustive deps)

- [ ] **Step 3: Commit**

```bash
git add web/src/features/chart/components/CandlestickChart.tsx web/src/features/chart/components/ChartView.tsx
git commit -m "feat: rewrite chart component for smooth mobile zoom and indicator toggling"
```

### Manual Test Checklist (post-deploy)

- [ ] Pinch-to-zoom on mobile feels immediate, no page zoom interference
- [ ] Vertical swipe on the chart still scrolls the page
- [ ] Toggle indicators on/off — no flash or visible jump
- [ ] Switch timeframes — old candles stay visible, loading dot appears in top-right
- [ ] Streaming candle updates animate smoothly (no full chart rebuild)
- [ ] All 18 indicator types render correctly: EMA(21/50/200), SMA(21/50/200), BB, VWAP, SuperTrend, Parabolic SAR, Ichimoku, Support/Resistance, RSI, MACD, StochRSI, CCI, ATR, ADX, Williams %R, MFI, OBV
- [ ] Compound indicators (BB, Ichimoku, SuperTrend) clean up all sub-series when disabled
- [ ] Empty oscillator pane renders as a small empty area when all oscillators disabled (known limitation)
