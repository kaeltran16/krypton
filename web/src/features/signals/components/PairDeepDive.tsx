import { useMemo } from "react";
import { useSignalStore } from "../store";
import { useLivePrice } from "../../../shared/hooks/useLivePrice";
import { TrendingUp, TrendingDown } from "lucide-react";

interface PairDeepDiveProps {
  pair: string;
}

export function PairDeepDive({ pair }: PairDeepDiveProps) {
  const signals = useSignalStore((s) => s.signals);
  const { price, change24h } = useLivePrice(pair);

  const pairSignals = useMemo(
    () => signals.filter((s) => s.pair === pair).slice(0, 5),
    [signals, pair]
  );

  const shortPair = pair.replace("-USDT-SWAP", "");
  const isPositive = (change24h ?? 0) >= 0;

  return (
    <div className="space-y-4">
      {/* Price Header */}
      <div className="flex items-end justify-between">
        <div>
          <h2 className="font-headline font-bold text-2xl">{shortPair}/USDT</h2>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-headline font-bold text-xl tabular-nums">
              {price ? price.toLocaleString(undefined, { minimumFractionDigits: 2 }) : "—"}
            </span>
            {change24h != null && (
              <span className={`text-sm font-bold tabular-nums ${isPositive ? "text-tertiary-dim" : "text-error"}`}>
                {isPositive ? "+" : ""}{change24h.toFixed(2)}%
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Market Regime */}
      <section className="bg-surface-container rounded-lg p-5 border border-outline-variant/10">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Market Regime</span>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full animate-pulse motion-reduce:animate-none ${isPositive ? "bg-tertiary-dim" : "bg-error"}`} />
          <span className={`font-headline font-bold text-xl italic ${isPositive ? "text-tertiary-dim" : "text-error"}`}>
            {isPositive ? "Trending Bullish" : "Trending Bearish"}
          </span>
        </div>
      </section>

      {/* Engine Stats Bento */}
      <section className="grid grid-cols-2 gap-3">
        <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant/5">
          <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Signals (24h)</span>
          <span className="font-headline font-bold text-2xl tabular-nums">{pairSignals.length}</span>
        </div>
        <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant/5">
          <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Latest Score</span>
          <span className="font-headline font-bold text-2xl tabular-nums">
            {pairSignals[0]?.final_score?.toFixed(0) ?? "—"}
          </span>
        </div>
      </section>

      {/* Signal Audit Log */}
      <section className="space-y-3">
        <h3 className="font-headline font-bold text-sm tracking-widest uppercase px-1">Signal Audit Log</h3>
        {pairSignals.length === 0 ? (
          <p className="text-on-surface-variant text-sm text-center py-8">No recent signals for {shortPair}</p>
        ) : (
          pairSignals.map((signal) => {
            const isLong = signal.direction === "LONG";
            return (
              <div
                key={signal.id}
                className={`bg-surface-container hover:bg-surface-container-high transition-colors p-4 rounded-lg flex items-center justify-between border-l-2 ${
                  isLong ? "border-tertiary-dim" : "border-error"
                }`}
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 bg-surface-container-highest flex items-center justify-center rounded">
                    {isLong ? (
                      <TrendingUp size={20} className="text-tertiary-dim" />
                    ) : (
                      <TrendingDown size={20} className="text-error" />
                    )}
                  </div>
                  <div>
                    <div className="font-headline font-bold text-sm">
                      {signal.direction} {signal.timeframe?.toUpperCase()}
                    </div>
                    <div className="text-[10px] text-on-surface-variant tabular-nums">
                      {new Date(signal.created_at).toLocaleTimeString()} UTC
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className={`font-mono font-bold text-sm tabular-nums ${isLong ? "text-tertiary-dim" : "text-error"}`}>
                    {signal.final_score?.toFixed(0) ?? "—"}
                  </div>
                  <div className="text-[10px] text-on-surface-variant uppercase font-bold">
                    {signal.outcome}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </section>
    </div>
  );
}
