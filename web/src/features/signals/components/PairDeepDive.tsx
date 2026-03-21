import { useMemo } from "react";
import { useSignalStore } from "../store";
import { useLivePrice } from "../../../shared/hooks/useLivePrice";
import { useSignalStats } from "../../home/hooks/useSignalStats";
import { formatPair } from "../../../shared/lib/format";
import { computeRegime } from "../types";
import type { RawIndicators } from "../types";
import { TrendingUp, TrendingDown } from "lucide-react";

interface PairDeepDiveProps {
  pair: string;
  visible?: boolean;
}

export function PairDeepDive({ pair, visible = true }: PairDeepDiveProps) {
  const signals = useSignalStore((s) => s.signals);
  const { price, change24h } = useLivePrice(pair);
  const { stats } = useSignalStats(visible ? 30 : null);
  const pairStats = stats?.by_pair[pair];

  const pairSignals = useMemo(
    () => signals.filter((s) => s.pair === pair).slice(0, 5),
    [signals, pair]
  );

  const shortPair = formatPair(pair);
  const isPositive = (change24h ?? 0) >= 0;

  return (
    <div className="space-y-4">
      {/* Price Header */}
      <div className="flex items-end justify-between">
        <div>
          <h2 className="font-headline font-bold text-2xl">{shortPair}/USDT</h2>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-headline font-bold text-xl tabular-nums">
              {price ? price.toLocaleString(undefined, { minimumFractionDigits: 2 }) : "\u2014"}
            </span>
            {change24h != null && (
              <span className={`text-sm font-bold tabular-nums ${isPositive ? "text-tertiary-dim" : "text-error"}`}>
                {isPositive ? "+" : ""}{change24h.toFixed(2)}%
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Market Regime with Confidence */}
      <section className="bg-surface-container rounded-lg p-5 border border-outline-variant/10">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Market Regime</span>
        <div className="flex items-center gap-2 mb-3">
          <span className={`w-2 h-2 rounded-full animate-pulse motion-reduce:animate-none ${isPositive ? "bg-tertiary-dim" : "bg-error"}`} />
          <span className={`font-headline font-bold text-xl italic ${isPositive ? "text-tertiary-dim" : "text-error"}`}>
            {isPositive ? "Trending Bullish" : "Trending Bearish"}
          </span>
        </div>
        <ConfidenceBar indicators={pairSignals[0]?.raw_indicators} />
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
            {pairSignals[0]?.final_score?.toFixed(0) ?? "\u2014"}<span className="text-sm text-on-surface-variant">/100</span>
          </span>
        </div>
        <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant/5">
          <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Win Rate</span>
          <span className={`font-headline font-bold text-2xl tabular-nums ${(pairStats?.win_rate ?? 0) >= 50 ? "text-tertiary-dim" : "text-error"}`}>
            {pairStats ? `${pairStats.win_rate}%` : "\u2014"}
          </span>
        </div>
        <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant/5">
          <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Avg P&L</span>
          <span className={`font-headline font-bold text-2xl tabular-nums ${(pairStats?.avg_pnl ?? 0) >= 0 ? "text-tertiary-dim" : "text-error"}`}>
            {pairStats ? `${pairStats.avg_pnl >= 0 ? "+" : ""}${pairStats.avg_pnl.toFixed(1)}%` : "\u2014"}
          </span>
        </div>
      </section>

      {/* Momentum Profile */}
      <MomentumProfile indicators={pairSignals[0]?.raw_indicators} />

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
                    {signal.final_score?.toFixed(0) ?? "\u2014"}
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

function ConfidenceBar({ indicators }: { indicators?: RawIndicators | null }) {
  const regime = indicators ? computeRegime(indicators) : null;
  if (!regime) return null;
  const confidence = regime.dominantPct;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] text-on-surface-variant">
        <span>CONFIDENCE</span>
        <span className="font-mono tabular-nums">{confidence}%</span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={confidence}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Regime confidence: ${confidence}%`}
        className="h-1 bg-surface-container-highest rounded-full overflow-hidden"
      >
        <div className="h-full bg-primary rounded-full" style={{ width: `${confidence}%` }} />
      </div>
    </div>
  );
}

function MomentumProfile({ indicators }: { indicators?: RawIndicators | null }) {
  if (!indicators) return null;
  const metrics = [
    { label: "RSI (14)", value: indicators.rsi, format: (v: number) => v.toFixed(1) },
    { label: "ADX", value: indicators.adx, format: (v: number) => v.toFixed(1) },
    { label: "Vol Ratio", value: indicators.vol_ratio, format: (v: number) => `${v.toFixed(2)}x` },
  ].filter((m) => m.value != null);
  if (metrics.length === 0) return null;
  return (
    <section className="bg-surface-container rounded-lg p-5 border border-outline-variant/10">
      <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-3">Momentum Profile</h3>
      <div className="space-y-2">
        {metrics.map((m) => (
          <div key={m.label} className="flex items-center justify-between">
            <span className="text-xs text-on-surface-variant">{m.label}</span>
            <span className="font-mono font-bold text-sm tabular-nums text-on-surface">{m.format(m.value!)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
