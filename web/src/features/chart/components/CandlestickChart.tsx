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
}

const CHART_OPTIONS: DeepPartial<ChartOptions> = {
  layout: {
    background: { type: ColorType.Solid, color: "#12161C" },
    textColor: "#848E9C",
    fontFamily: "Inter, system-ui, sans-serif",
    fontSize: 11,
  },
  grid: {
    vertLines: { color: "rgba(31, 41, 55, 0.5)" },
    horzLines: { color: "rgba(31, 41, 55, 0.5)" },
  },
  crosshair: { mode: CrosshairMode.Normal },
  rightPriceScale: {
    borderColor: "#1E2530",
  },
  timeScale: {
    borderColor: "#1E2530",
    timeVisible: true,
    secondsVisible: false,
  },
  handleScale: { pinch: true, mouseWheel: true, axisPressedMouseMove: true },
  handleScroll: { pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
};

function toTime(ts: number): UTCTimestamp {
  return (ts / 1000) as UTCTimestamp;
}

export function CandlestickChart({ candles, enabledIndicators }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const overlaySeriesRef = useRef<Map<string, ISeriesApi<"Line">[]>>(new Map());
  const oscSeriesRef = useRef<Map<string, ISeriesApi<"Line" | "Histogram">[]>>(new Map());
  const oscPaneCreated = useRef(false);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const prevCandleCountRef = useRef(0);
  const prevFirstTimeRef = useRef<UTCTimestamp | null>(null);

  // Stringify enabled indicators for stable effect dependency
  const enabledKey = useMemo(
    () => [...enabledIndicators].sort().join(","),
    [enabledIndicators]
  );

  // Create chart
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
      upColor: "#0ECB81",
      downColor: "#F6465D",
      wickUpColor: "#0ECB81",
      wickDownColor: "#F6465D",
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
      overlaySeriesRef.current.clear();
      oscSeriesRef.current.clear();
      oscPaneCreated.current = false;
      prevCandleCountRef.current = 0;
      prevFirstTimeRef.current = null;
    };
  }, []);

  // Update data + indicators
  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    const volSeries = volSeriesRef.current;
    if (!chart || !candleSeries || !volSeries || !candles.length) return;

    // Deduplicate by timestamp (keep last) and sort ascending
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
      color: c.close >= c.open ? "rgba(14,203,129,0.3)" : "rgba(246,70,93,0.3)",
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

    // --- Remove old indicator series ---
    for (const [key, seriesList] of overlaySeriesRef.current) {
      if (!enabledIndicators.has(key)) {
        for (const s of seriesList) chart.removeSeries(s);
        overlaySeriesRef.current.delete(key);
      }
    }
    for (const [key, seriesList] of oscSeriesRef.current) {
      if (!enabledIndicators.has(key)) {
        for (const s of seriesList) chart.removeSeries(s);
        oscSeriesRef.current.delete(key);
      }
    }

    // If we had a pane but no longer need it, we need to recreate the chart
    // For simplicity, we'll just leave the pane (it'll be empty and tiny)

    // --- Calculate and render indicators ---
    const closes = deduped.map((c) => c.close);
    const times = deduped.map((c) => toTime(c.timestamp));

    const ensureOscPane = (): number => {
      if (!oscPaneCreated.current) {
        const pane = chart.addPane();
        pane.setStretchFactor(300); // smaller relative to main (1000)
        oscPaneCreated.current = true;
      }
      return chart.panes().length - 1;
    };

    const addOverlaySeries = (
      id: string,
      data: (number | null)[],
      color: string,
      lineWidth: number = 1
    ) => {
      if (overlaySeriesRef.current.has(id)) {
        // Update existing
        const series = overlaySeriesRef.current.get(id)![0];
        const lineData = [];
        for (let i = 0; i < data.length; i++) {
          if (data[i] !== null) lineData.push({ time: times[i], value: data[i]! });
        }
        series.setData(lineData);
        return;
      }
      const series = chart.addSeries(LineSeries, {
        color,
        lineWidth: lineWidth as 1 | 2 | 3 | 4,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      const lineData = [];
      for (let i = 0; i < data.length; i++) {
        if (data[i] !== null) lineData.push({ time: times[i], value: data[i]! });
      }
      series.setData(lineData);
      overlaySeriesRef.current.set(id, [series]);
    };

    const addOscSeries = (
      id: string,
      datasets: { data: (number | null)[]; color: string; type?: "line" | "histogram" }[]
    ) => {
      const paneIdx = ensureOscPane();
      // Remove existing if any
      if (oscSeriesRef.current.has(id)) {
        for (const s of oscSeriesRef.current.get(id)!) chart.removeSeries(s);
        oscSeriesRef.current.delete(id);
      }
      const seriesList: ISeriesApi<"Line" | "Histogram">[] = [];
      for (const ds of datasets) {
        const lineData = [];
        for (let i = 0; i < ds.data.length; i++) {
          if (ds.data[i] !== null) {
            if (ds.type === "histogram") {
              lineData.push({
                time: times[i],
                value: ds.data[i]!,
                color: ds.data[i]! >= 0 ? "rgba(14,203,129,0.6)" : "rgba(246,70,93,0.6)",
              });
            } else {
              lineData.push({ time: times[i], value: ds.data[i]! });
            }
          }
        }
        if (ds.type === "histogram") {
          const s = chart.addSeries(HistogramSeries, {
            priceLineVisible: false,
            lastValueVisible: false,
            priceScaleId: `osc-${id}`,
          }, paneIdx);
          s.setData(lineData);
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
          s.setData(lineData);
          seriesList.push(s);
        }
      }
      oscSeriesRef.current.set(id, seriesList);
    };

    for (const id of enabledIndicators) {
      const def = INDICATOR_MAP.get(id);
      if (!def) continue;

      switch (id) {
        case "ema21":
          addOverlaySeries(id, calcEMA(closes, 21), def.color);
          break;
        case "ema50":
          addOverlaySeries(id, calcEMA(closes, 50), def.color);
          break;
        case "ema200":
          addOverlaySeries(id, calcEMA(closes, 200), def.color);
          break;
        case "sma21":
          addOverlaySeries(id, calcSMA(closes, 21), def.color);
          break;
        case "sma50":
          addOverlaySeries(id, calcSMA(closes, 50), def.color);
          break;
        case "sma200":
          addOverlaySeries(id, calcSMA(closes, 200), def.color);
          break;
        case "bb": {
          const bb = calcBB(closes);
          addOverlaySeries("bb-upper", bb.upper, "#6B7280");
          addOverlaySeries("bb-middle", bb.middle, "#6B7280");
          addOverlaySeries("bb-lower", bb.lower, "#6B7280");
          break;
        }
        case "vwap":
          addOverlaySeries(id, calcVWAP(deduped), def.color);
          break;
        case "supertrend": {
          const st = calcSuperTrend(deduped);
          // Color based on direction
          const stData = st.value.map((v, i) => ({
            val: v,
            color: st.direction[i] === 1 ? "#0ECB81" : "#F6465D",
          }));
          // We need two line series for up/down colors
          const upData: (number | null)[] = stData.map((d) =>
            d.color === "#0ECB81" ? d.val : null
          );
          const downData: (number | null)[] = stData.map((d) =>
            d.color === "#F6465D" ? d.val : null
          );
          addOverlaySeries("supertrend-up", upData, "#0ECB81", 2);
          addOverlaySeries("supertrend-down", downData, "#F6465D", 2);
          break;
        }
        case "psar": {
          const psar = calcParabolicSAR(deduped);
          addOverlaySeries(id, psar.value, def.color);
          break;
        }
        case "ichimoku": {
          const ich = calcIchimoku(deduped);
          addOverlaySeries("ich-tenkan", ich.tenkanSen, "#2196F3");
          addOverlaySeries("ich-kijun", ich.kijunSen, "#EF4444");
          addOverlaySeries("ich-senkouA", ich.senkouA, "#0ECB81");
          addOverlaySeries("ich-senkouB", ich.senkouB, "#F6465D");
          break;
        }
        case "pivots": {
          // Clear old price lines
          for (const pl of priceLinesRef.current) candleSeries.removePriceLine(pl);
          priceLinesRef.current = [];

          const srLevels = detectSupportResistance(deduped);
          for (const lv of srLevels) {
            const isSupport = lv.type === "support";
            const pl = candleSeries.createPriceLine({
              price: lv.price,
              color: isSupport ? "#0ECB81" : "#F6465D",
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
          addOscSeries(id, [{ data: calcRSI(closes), color: def.color }]);
          break;
        case "macd": {
          const macd = calcMACD(closes);
          addOscSeries(id, [
            { data: macd.histogram, color: "#6B7280", type: "histogram" },
            { data: macd.macd, color: "#3B82F6" },
            { data: macd.signal, color: "#F97316" },
          ]);
          break;
        }
        case "stochrsi": {
          const sr = calcStochRSI(closes);
          addOscSeries(id, [
            { data: sr.k, color: "#10B981" },
            { data: sr.d, color: "#EF4444" },
          ]);
          break;
        }
        case "cci":
          addOscSeries(id, [{ data: calcCCI(deduped), color: def.color }]);
          break;
        case "atr":
          addOscSeries(id, [{ data: calcATR(deduped), color: def.color }]);
          break;
        case "adx":
          addOscSeries(id, [{ data: calcADX(deduped), color: def.color }]);
          break;
        case "willr":
          addOscSeries(id, [{ data: calcWilliamsR(deduped), color: def.color }]);
          break;
        case "mfi":
          addOscSeries(id, [{ data: calcMFI(deduped), color: def.color }]);
          break;
        case "obv":
          addOscSeries(id, [{ data: calcOBV(deduped), color: def.color }]);
          break;
      }
    }

    // Clean up sub-indicator series for disabled compound indicators
    if (!enabledIndicators.has("bb")) {
      for (const k of ["bb-upper", "bb-middle", "bb-lower"]) {
        if (overlaySeriesRef.current.has(k)) {
          for (const s of overlaySeriesRef.current.get(k)!) chart.removeSeries(s);
          overlaySeriesRef.current.delete(k);
        }
      }
    }
    if (!enabledIndicators.has("supertrend")) {
      for (const k of ["supertrend-up", "supertrend-down"]) {
        if (overlaySeriesRef.current.has(k)) {
          for (const s of overlaySeriesRef.current.get(k)!) chart.removeSeries(s);
          overlaySeriesRef.current.delete(k);
        }
      }
    }
    if (!enabledIndicators.has("ichimoku")) {
      for (const k of ["ich-tenkan", "ich-kijun", "ich-senkouA", "ich-senkouB"]) {
        if (overlaySeriesRef.current.has(k)) {
          for (const s of overlaySeriesRef.current.get(k)!) chart.removeSeries(s);
          overlaySeriesRef.current.delete(k);
        }
      }
    }
    if (!enabledIndicators.has("pivots")) {
      for (const pl of priceLinesRef.current) candleSeries.removePriceLine(pl);
      priceLinesRef.current = [];
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, enabledKey]);

  return <div ref={containerRef} className="w-full h-full" />;
}
