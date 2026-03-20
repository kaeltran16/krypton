import { useState, useCallback } from "react";
import { SlidersHorizontal } from "lucide-react";
import { CandlestickChart } from "./CandlestickChart";
import { IndicatorSheet, getStoredIndicators, hasOscillator } from "./IndicatorSheet";
import { useChartData } from "../hooks/useChartData";
import { useLivePrice } from "../../../shared/hooks/useLivePrice";
import { formatPrice } from "../../../shared/lib/format";

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

  const fullScreen = hasOscillator(enabledIds);

  const handleToggle = useCallback((id: string) => {
    setEnabledIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    <div className={`flex flex-col ${fullScreen ? "h-[calc(100dvh-4rem)]" : "h-[calc(100dvh-6.5rem)]"}`}>
      {/* Timeframe selector + indicator gear */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-surface-container border-b border-outline-variant/10">
        <div className="flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-3 py-1 text-xs font-bold font-headline rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                timeframe === tf
                  ? "bg-surface-container-highest text-primary"
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

      {/* Chart */}
      <div className="flex-1 min-h-0 px-2">
        <div className="w-full h-full rounded-lg overflow-hidden">
          <CandlestickChart candles={candles} enabledIndicators={enabledIds} loading={loading} onTickRef={onTickRef} />
        </div>
      </div>

      {/* OHLC Strip — hidden when oscillators are active */}
      {!fullScreen && (
        <div className="px-3 py-2 border-t border-outline-variant/10">
          <div className="flex items-center justify-between text-[10px] uppercase tracking-widest text-on-surface-variant font-medium">
            <div className="flex gap-3">
              <span>O <span className="text-on-surface tabular">{open24h ? formatPrice(open24h) : "—"}</span></span>
              <span>H <span className="text-on-surface tabular">{high24h ? formatPrice(high24h) : "—"}</span></span>
              <span>L <span className="text-on-surface tabular">{low24h ? formatPrice(low24h) : "—"}</span></span>
              <span>C <span className="text-on-surface tabular">{price ? formatPrice(price) : "—"}</span></span>
            </div>
          </div>
          <div className="flex items-center justify-between text-xs font-mono mt-0.5">
            <span className="text-on-surface-variant">
              Vol <span className="text-on-surface tabular">{vol24h ? formatVolume(vol24h) : "—"}</span>
            </span>
            {change24h !== null && (
              <span className={`tabular ${change24h >= 0 ? "text-long" : "text-short"}`}>
                24h {change24h >= 0 ? "+" : ""}{change24h.toFixed(2)}%
              </span>
            )}
          </div>
        </div>
      )}

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
