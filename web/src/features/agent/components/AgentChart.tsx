import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import type { CandleData } from "../../../shared/lib/api";
import { theme } from "../../../shared/theme";
import { getAnnotationOpacity, getStaleness, type AgentAnalysis, type Annotation } from "../types";
import type { TickCallback } from "../hooks/useChartData";
import { AnnotationPopover } from "./AnnotationPopover";
import { HorizontalPrimitive } from "../lib/primitives/HorizontalPrimitive";
import { ZonePrimitive } from "../lib/primitives/ZonePrimitive";
import { RegimeZonePrimitive } from "../lib/primitives/RegimeZonePrimitive";
import { TrendLinePrimitive } from "../lib/primitives/TrendLinePrimitive";
import { PositionPrimitive } from "../lib/primitives/PositionPrimitive";

interface Props {
  candles: CandleData[];
  pair: string;
  analysis?: AgentAnalysis;
  onTickRef?: MutableRefObject<TickCallback | null>;
}

type PrimitiveInstance =
  | HorizontalPrimitive
  | ZonePrimitive
  | RegimeZonePrimitive
  | TrendLinePrimitive
  | PositionPrimitive;

function toTime(timestamp: number): UTCTimestamp {
  return timestamp as UTCTimestamp;
}

export function AgentChart({ candles, pair, analysis, onTickRef }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const markerPluginRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const primitivesRef = useRef<Array<{ primitive: PrimitiveInstance; annotation: Annotation }>>([]);
  const annotationMapRef = useRef<Map<string, Annotation>>(new Map());
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const [popover, setPopover] = useState<{
    id: string;
    annotation: Annotation;
    x: number;
    y: number;
  } | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const annotationMap = annotationMapRef.current;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: theme.chart.background },
        textColor: theme.chart.text,
        fontFamily: "Inter, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: theme.chart.grid },
        horzLines: { color: theme.chart.grid },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: theme.chart.scaleBorder },
      timeScale: {
        borderColor: theme.chart.scaleBorder,
        timeVisible: true,
        secondsVisible: false,
      },
      handleScale: { pinch: true, mouseWheel: true, axisPressedMouseMove: true },
      handleScroll: { pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
    });
    chartRef.current = chart;

    const series = chart.addSeries(CandlestickSeries, {
      upColor: theme.chart.candleUp,
      downColor: theme.chart.candleDown,
      wickUpColor: theme.chart.candleUp,
      wickDownColor: theme.chart.candleDown,
      borderVisible: false,
    });
    seriesRef.current = series;

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    volumeRef.current = volume;

    markerPluginRef.current = createSeriesMarkers(series, []);

    const handleClick = (param: MouseEventParams<Time>) => {
      const hoveredId = param.hoveredObjectId;
      if (!hoveredId || !param.point) {
        setPopover(null);
        return;
      }
      const annotation = annotationMapRef.current.get(String(hoveredId));
      if (!annotation) {
        setPopover(null);
        return;
      }
      setPopover({
        id: String(hoveredId),
        annotation,
        x: Math.min(param.point.x + 12, container.clientWidth - 280),
        y: Math.max(param.point.y - 12, 8),
      });
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPopover(null);
      }
    };

    chart.subscribeClick(handleClick);
    window.addEventListener("keydown", handleEscape);

    resizeObserverRef.current = new ResizeObserver((entries) => {
      const entry = entries[0];
      chart.applyOptions({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    resizeObserverRef.current.observe(container);

    return () => {
      chart.unsubscribeClick(handleClick);
      window.removeEventListener("keydown", handleEscape);
      markerPluginRef.current?.detach();
      markerPluginRef.current = null;
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      volumeRef.current = null;
      annotationMap.clear();
      primitivesRef.current = [];
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    const volume = volumeRef.current;
    if (!series || !volume || candles.length === 0) return;

    const data = candles.map((candle) => ({
      time: toTime(candle.timestamp),
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    }));

    const volumeData = candles.map((candle) => ({
      time: toTime(candle.timestamp),
      value: candle.volume,
      color: candle.close >= candle.open ? theme.chart.volumeUp : theme.chart.volumeDown,
    }));

    series.setData(data);
    volume.setData(volumeData);
    chartRef.current?.timeScale().fitContent();
  }, [candles]);

  useEffect(() => {
    if (!onTickRef || !seriesRef.current || !volumeRef.current) return;
    onTickRef.current = (candle) => {
      seriesRef.current?.update({
        time: toTime(candle.timestamp),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      });
      volumeRef.current?.update({
        time: toTime(candle.timestamp),
        value: candle.volume,
        color: candle.close >= candle.open ? theme.chart.volumeUp : theme.chart.volumeDown,
      });
    };
    return () => {
      if (onTickRef) {
        onTickRef.current = null;
      }
    };
  }, [onTickRef]);

  const recomputeCoordinates = useCallback(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;

    for (const { primitive, annotation } of primitivesRef.current) {
      try {
        if (primitive instanceof HorizontalPrimitive && annotation.type === "level") {
          primitive.setCoordinate(series.priceToCoordinate(annotation.price));
        } else if (primitive instanceof ZonePrimitive && annotation.type === "zone") {
          primitive.setCoordinates({
            y1: series.priceToCoordinate(annotation.from_price) ?? 0,
            y2: series.priceToCoordinate(annotation.to_price) ?? 0,
            x1: annotation.from_time
              ? chart.timeScale().timeToCoordinate(annotation.from_time as Time) ?? undefined
              : undefined,
            x2: annotation.to_time
              ? chart.timeScale().timeToCoordinate(annotation.to_time as Time) ?? undefined
              : undefined,
          });
        } else if (primitive instanceof RegimeZonePrimitive && annotation.type === "regime") {
          const x1 = chart.timeScale().timeToCoordinate(annotation.from_time as Time);
          const x2 = chart.timeScale().timeToCoordinate(annotation.to_time as Time);
          if (x1 !== null && x2 !== null) {
            primitive.setCoordinates(x1, x2);
          }
        } else if (primitive instanceof TrendLinePrimitive && annotation.type === "trendline") {
          const x1 = chart.timeScale().timeToCoordinate(annotation.from.time as Time);
          const y1 = series.priceToCoordinate(annotation.from.price);
          const x2 = chart.timeScale().timeToCoordinate(annotation.to.time as Time);
          const y2 = series.priceToCoordinate(annotation.to.price);
          if (x1 !== null && y1 !== null && x2 !== null && y2 !== null) {
            primitive.setCoordinates({ x1, y1, x2, y2 });
          }
        } else if (primitive instanceof PositionPrimitive && annotation.type === "position") {
          primitive.setCoordinates({
            entry: series.priceToCoordinate(annotation.entry_price),
            sl: annotation.sl_price ? series.priceToCoordinate(annotation.sl_price) : null,
            tp: annotation.tp_price ? series.priceToCoordinate(annotation.tp_price) : null,
          });
        }
      } catch {
        // ignore malformed annotation payloads
      }
    }
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;

    for (const { primitive } of primitivesRef.current) {
      series.detachPrimitive(primitive);
    }
    primitivesRef.current = [];
    annotationMapRef.current.clear();
    markerPluginRef.current?.setMarkers([]);

    if (!analysis) return;

    const opacity = getAnnotationOpacity(getStaleness(analysis.created_at));
    const filteredAnnotations = analysis.annotations.filter((annotation) => annotation.pair === pair);
    const markers: SeriesMarker<Time>[] = [];

    filteredAnnotations.forEach((annotation, index) => {
      const externalId = `ann-${analysis.id}-${index}`;
      annotationMapRef.current.set(externalId, annotation);

      try {
        if (annotation.type === "level") {
          const primitive = new HorizontalPrimitive(annotation, externalId, opacity);
          series.attachPrimitive(primitive);
          primitivesRef.current.push({ primitive, annotation });
        } else if (annotation.type === "zone") {
          const primitive = new ZonePrimitive(annotation, externalId, opacity);
          series.attachPrimitive(primitive);
          primitivesRef.current.push({ primitive, annotation });
        } else if (annotation.type === "regime") {
          const primitive = new RegimeZonePrimitive(annotation, externalId, opacity);
          series.attachPrimitive(primitive);
          primitivesRef.current.push({ primitive, annotation });
        } else if (annotation.type === "trendline") {
          const primitive = new TrendLinePrimitive(annotation, externalId, opacity);
          series.attachPrimitive(primitive);
          primitivesRef.current.push({ primitive, annotation });
        } else if (annotation.type === "position") {
          const primitive = new PositionPrimitive(annotation, externalId, opacity);
          series.attachPrimitive(primitive);
          primitivesRef.current.push({ primitive, annotation });
        } else if (annotation.type === "signal") {
          markers.push({
            id: externalId,
            time: annotation.time as Time,
            position: annotation.direction === "long" ? "belowBar" : "aboveBar",
            color:
              annotation.direction === "long"
                ? theme.annotations.signal_long
                : theme.annotations.signal_short,
            shape: annotation.direction === "long" ? "arrowUp" : "arrowDown",
            text: annotation.label,
          });
        }
      } catch {
        // ignore malformed annotation payloads
      }
    });

    markerPluginRef.current?.setMarkers(markers);
    recomputeCoordinates();
    if (popover && !annotationMapRef.current.has(popover.id)) {
      queueMicrotask(() => {
        setPopover((current) =>
          current && !annotationMapRef.current.has(current.id) ? null : current,
        );
      });
    }

    const handleRangeChange = () => recomputeCoordinates();
    chart.timeScale().subscribeVisibleLogicalRangeChange(handleRangeChange);
    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleRangeChange);
    };
  }, [analysis, pair, popover, recomputeCoordinates]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      {analysis && getStaleness(analysis.created_at) === "stale" ? (
        <div className="absolute left-3 top-3 rounded bg-red-500/10 px-2 py-1 text-[10px] text-red-300">
          This analysis is outdated. Re-run to refresh.
        </div>
      ) : null}
      {popover ? (
        <AnnotationPopover
          annotation={popover.annotation}
          x={popover.x}
          y={popover.y}
          onClose={() => setPopover(null)}
        />
      ) : null}
    </div>
  );
}
