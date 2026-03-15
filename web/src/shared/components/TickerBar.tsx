import { formatPrice } from "../lib/format";
import { AVAILABLE_PAIRS } from "../lib/constants";

interface TickerBarProps {
  price: number | null;
  change24h: number | null;
  pair: string;
  onPairChange: (pair: string) => void;
}

export function TickerBar({ price, change24h, pair, onPairChange }: TickerBarProps) {
  const isPositive = (change24h ?? 0) >= 0;

  return (
    <div className="sticky top-0 z-40 bg-card/80 backdrop-blur-xl border-b border-white/[0.06] safe-top">
      <div className="flex items-center justify-between px-3 py-2">
        <select
          value={pair}
          onChange={(e) => onPairChange(e.target.value)}
          className="bg-transparent text-accent font-extrabold text-sm tracking-tight border-none outline-none appearance-none pr-4"
          style={{
            backgroundImage: "url(\"data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%23848E9C' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e\")",
            backgroundPosition: "right 0 center",
            backgroundRepeat: "no-repeat",
            backgroundSize: "16px",
          }}
        >
          {AVAILABLE_PAIRS.map((p) => (
            <option key={p} value={p} className="bg-card">{p.replace("-SWAP", "")}</option>
          ))}
        </select>
        <div className="flex items-center gap-2">
          {price !== null && (
            <span className="font-mono text-display text-sm">${formatPrice(price)}</span>
          )}
          {change24h !== null && (
            <span className={`text-xs font-mono ${isPositive ? "text-long" : "text-short"}`}>
              {isPositive ? "+"  : ""}{change24h.toFixed(2)}%
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
