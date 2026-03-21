import { useEffect, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { Zap } from "lucide-react";
import { useSignalStore } from "../../signals/store";
import { formatScore, formatRelativeTime, formatPair } from "../../../shared/lib/format";
import type { Signal } from "../../signals/types";

const OUTCOME_BADGE: Record<string, { label: string; cls: string }> = {
  PENDING: { label: "PENDING", cls: "bg-accent/15 text-primary" },
  TP1_HIT: { label: "TP1", cls: "bg-long/15 text-long" },
  TP2_HIT: { label: "TP2", cls: "bg-long/15 text-long" },
  SL_HIT: { label: "SL", cls: "bg-short/15 text-short" },
  EXPIRED: { label: "EXP", cls: "bg-outline-variant/20 text-on-surface-variant" },
};

export function RecentSignals() {
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  const signals = useSignalStore(useShallow((s) =>
    s.signals.filter((sig) => new Date(sig.created_at).getTime() > cutoff).slice(0, 3)
  ));

  return (
    <div className="space-y-3">
      <div className="px-1">
        <h2 className="text-xs font-bold tracking-widest uppercase text-on-surface-variant">
          Recent Signals ({signals.length})
        </h2>
      </div>
      {signals.length === 0 ? (
        <p className="px-1 text-sm text-outline">No signals in the last 24h &mdash; markets are being monitored</p>
      ) : (
        <div className="bg-surface-container rounded-lg overflow-hidden divide-y divide-outline-variant/10">
          {signals.map((signal) => (
            <SignalRow key={signal.id} signal={signal} />
          ))}
        </div>
      )}
    </div>
  );
}

function SignalRow({ signal }: { signal: Signal }) {
  const selectSignal = useSignalStore((s) => s.selectSignal);
  const isLong = signal.direction === "LONG";
  const badge = OUTCOME_BADGE[signal.outcome] ?? OUTCOME_BADGE.PENDING;

  return (
    <button
      onClick={() => selectSignal(signal)}
      className="w-full px-3 py-2.5 flex items-center justify-between text-left active:bg-surface-container-high/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      <div className="flex items-center gap-2 min-w-0">
        <Zap size={14} className="text-primary flex-shrink-0" />
        <span className="font-headline font-bold text-sm">{formatPair(signal.pair)}</span>
        <span className={`text-xs font-mono font-bold ${isLong ? "text-long" : "text-short"}`}>
          {signal.direction}
        </span>
        <span className={`text-xs font-mono tabular ${isLong ? "text-long" : "text-short"}`}>
          {formatScore(signal.final_score)}
        </span>
        <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${badge.cls}`}>
          {badge.label}
        </span>
      </div>
      <span className="text-xs text-outline tabular flex-shrink-0 ml-2">{formatRelativeTime(signal.created_at)}</span>
    </button>
  );
}
