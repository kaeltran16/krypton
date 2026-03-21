import { useState, useCallback, useRef, useEffect } from "react";
import { SlidersHorizontal } from "lucide-react";
import { CandlestickChart, type CrosshairCandle } from "./CandlestickChart";
import { IndicatorSheet, getStoredIndicators } from "./IndicatorSheet";
import { useChartData } from "../hooks/useChartData";
import { useLivePrice } from "../../../shared/hooks/useLivePrice";
import { formatPricePrecision } from "../../../shared/lib/format";

type ChartTimeframe = "15m" | "1h" | "4h" | "1D";
const TIMEFRAMES: ChartTimeframe[] = ["15m", "1h", "4h", "1D"];

interface Props {
  pair: string;
}

export function ChartView({ pair }: Props) {
  const [timeframe, setTimeframe] = useState<ChartTimeframe>("1h");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [enabledIds, setEnabledIds] = useState<Set<string>>(getStoredIndicators);
  const { price, open24h, high24h, low24h, vol24h, change24h } = useLivePrice(pair);
  const { candles, loading, onTickRef } = useChartData(pair, timeframe);

  const [crosshairCandle, setCrosshairCandle] = useState<CrosshairCandle | null>(null);
  const rafRef = useRef(0);

  useEffect(() => () => cancelAnimationFrame(rafRef.current), []);

  const handleCrosshairMove = useCallback((candle: CrosshairCandle | null) => {
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => setCrosshairCandle(candle));
  }, []);

  const handleToggle = useCallback((id: string) => {
    setEnabledIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    <div className="flex flex-col h-[calc(100dvh-3.5rem)]">
      {/* Timeframe selector + indicator gear */}
      <div className="flex items-center justify-between px-2.5 py-1.5 bg-surface">
        <div className="flex gap-0.5">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-2 py-1 text-[10px] font-bold font-headline rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                timeframe === tf
                  ? "bg-primary/12 text-primary"
                  : "text-on-surface-variant hover:bg-surface-container-highest"
              }`}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>
        <button
          onClick={() => setSheetOpen(true)}
          aria-label={`Indicators${enabledIds.size > 0 ? ` (${enabledIds.size} active)` : ""}`}
          className={`relative p-2 rounded-lg transition-colors active:bg-surface-container-highest focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
            enabledIds.size > 0 ? "text-primary" : "text-on-surface-variant"
          }`}
        >
          <SlidersHorizontal size={18} />
          {enabledIds.size > 0 && (
            <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-primary-container text-on-primary-fixed text-[10px] font-bold rounded-full flex items-center justify-center">
              {enabledIds.size}
            </span>
          )}
        </button>
      </div>

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

      {/* Indicator Bottom Sheet */}
      <IndicatorSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        enabled={enabledIds}
        onToggle={handleToggle}
      />
    </div>
  );
}

function formatVolume(vol: number): string {
  if (vol >= 1_000_000) return `${(vol / 1_000_000).toFixed(1)}M`;
  if (vol >= 1_000) return `${(vol / 1_000).toFixed(1)}K`;
  return vol.toFixed(1);
}
