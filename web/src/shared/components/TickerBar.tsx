import { ChevronDown } from "lucide-react";
import { formatPrice } from "../lib/format";
import { AVAILABLE_PAIRS } from "../lib/constants";

interface TickerBarProps {
  price: number | null;
  change24h: number | null;
  pair: string;
  onPairChange: (pair: string) => void;
  totalPnl?: number | null;
}

export function TickerBar({ price, change24h, pair, onPairChange, totalPnl }: TickerBarProps) {
  const showPnl = totalPnl != null;
  const isPositive = showPnl ? totalPnl >= 0 : (change24h ?? 0) >= 0;

  return (
    <header className="bg-surface flex justify-between items-center w-full px-4 min-h-14 z-40 sticky top-0 safe-top">
      <div className="flex items-center gap-3">
        <span className="text-on-surface font-headline font-bold text-lg tracking-tight">KRYPTON</span>
        <div className="h-4 w-px bg-outline-variant/30" />
        <div className="relative flex items-center">
          <select
            value={pair}
            onChange={(e) => onPairChange(e.target.value)}
            aria-label="Select trading pair"
            className="bg-transparent font-headline font-bold tracking-tight text-base text-primary-container border-none outline-none appearance-none cursor-pointer pr-5"
          >
            {AVAILABLE_PAIRS.map((p) => (
              <option key={p} value={p} className="bg-surface-container text-on-surface">
                {p.replace("-SWAP", "")}
              </option>
            ))}
          </select>
          <ChevronDown size={14} className="absolute right-0 pointer-events-none text-primary-container/60" />
        </div>
      </div>
      <div className="flex items-center gap-4">
        {showPnl ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-on-surface-variant">P&L</span>
            <span className={`font-mono text-sm font-bold tabular ${isPositive ? "text-long" : "text-short"}`}>
              {isPositive ? "+" : ""}${formatPrice(Math.abs(totalPnl))}
            </span>
          </div>
        ) : (
          <>
            {price !== null && (
              <span className="font-mono text-sm tabular text-on-surface">
                ${formatPrice(price)}
              </span>
            )}
            {change24h !== null && (
              <div className="flex items-center gap-1.5 px-2 py-1 bg-surface-container rounded-lg">
                <span className={`text-xs font-headline font-bold tracking-widest uppercase ${
                  isPositive ? "text-tertiary-dim" : "text-error"
                }`}>
                  {isPositive ? "+" : ""}{change24h.toFixed(2)}%
                </span>
              </div>
            )}
          </>
        )}
      </div>
    </header>
  );
}
