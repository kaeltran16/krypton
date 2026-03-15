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
  const prevPivotHashRef = useRef("");

  const enabledKey = useMemo(
    () => [...enabledIndicators].sort().join(","),
    [enabledIndicators]
  );

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
      prevPivotHashRef.current = "";
    };
  }, []);

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

  // ── Effect 3: Indicators ([candles, enabledKey]) ──
  // Runs AFTER Effect 2 (candle data) — do not reorder
  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    if (!chart || !candleSeries || !candles.length) return;

    // TODO: dedup is also computed in Effect 2 — could lift to useMemo if profiling shows cost
    const deduped = [...new Map(candles.map((c) => [c.timestamp, c])).values()]
      .sort((a, b) => a.timestamp - b.timestamp);
    const closes = deduped.map((c) => c.close);
    const times = deduped.map((c) => toTime(c.timestamp));

    // oscPaneCreated is one-way (never reset to false) because lightweight-charts v5.1
    // has no removePane() API — the pane persists until chart unmount clears the ref.
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
            const srLevels = detectSupportResistance(deduped);
            // Hash levels to skip remove/recreate when unchanged (price lines have no setData)
            const hash = srLevels.map((l) => `${l.type}:${l.price}:${l.strength}`).join("|");
            if (hash !== prevPivotHashRef.current) {
              for (const pl of priceLinesRef.current) candleSeries.removePriceLine(pl);
              priceLinesRef.current = [];
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
              prevPivotHashRef.current = hash;
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
