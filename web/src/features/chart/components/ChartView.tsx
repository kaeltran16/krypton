import { useState, useCallback } from "react";
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
  const { candles, loading } = useChartData(pair, timeframe);

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
      <div className="flex items-center justify-between px-3 py-1.5">
        <div className="flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                timeframe === tf
                  ? "bg-accent/15 text-accent"
                  : "text-muted active:bg-card-hover"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
        <button
          onClick={() => setSheetOpen(true)}
          className={`relative p-1.5 rounded transition-colors active:bg-card-hover ${
            enabledIds.size > 0 ? "text-accent" : "text-muted"
          }`}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="4" y1="21" x2="4" y2="14" />
            <line x1="4" y1="10" x2="4" y2="3" />
            <line x1="12" y1="21" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12" y2="3" />
            <line x1="20" y1="21" x2="20" y2="16" />
            <line x1="20" y1="12" x2="20" y2="3" />
            <line x1="1" y1="14" x2="7" y2="14" />
            <line x1="9" y1="8" x2="15" y2="8" />
            <line x1="17" y1="16" x2="23" y2="16" />
          </svg>
          {enabledIds.size > 0 && (
            <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-accent text-surface text-[10px] font-bold rounded-full flex items-center justify-center">
              {enabledIds.size}
            </span>
          )}
        </button>
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0 px-2">
        <div className="w-full h-full rounded-lg overflow-hidden">
          <CandlestickChart candles={candles} enabledIndicators={enabledIds} loading={loading} />
        </div>
      </div>

      {/* OHLC Strip — hidden when oscillators are active */}
      {!fullScreen && (
        <div className="px-3 py-2 border-t border-border">
          <div className="flex items-center justify-between text-xs font-mono text-muted">
            <div className="flex gap-3">
              <span>O <span className="text-foreground">{open24h ? formatPrice(open24h) : "—"}</span></span>
              <span>H <span className="text-foreground">{high24h ? formatPrice(high24h) : "—"}</span></span>
              <span>L <span className="text-foreground">{low24h ? formatPrice(low24h) : "—"}</span></span>
              <span>C <span className="text-foreground">{price ? formatPrice(price) : "—"}</span></span>
            </div>
          </div>
          <div className="flex items-center justify-between text-xs font-mono mt-0.5">
            <span className="text-muted">
              Vol <span className="text-foreground">{vol24h ? formatVolume(vol24h) : "—"}</span>
            </span>
            {change24h !== null && (
              <span className={change24h >= 0 ? "text-long" : "text-short"}>
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
