import { useEffect, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { useSignalStore } from "../../signals/store";
import { formatScore, formatRelativeTime } from "../../../shared/lib/format";
import type { Signal } from "../../signals/types";

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
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      <div className="px-3 pt-3 pb-2 flex items-center justify-between">
        <span className="text-[11px] text-muted uppercase tracking-wider font-semibold">
          Recent Signals ({signals.length})
        </span>
        <span className="text-[11px] text-accent">&rarr;</span>
      </div>
      {signals.length === 0 ? (
        <p className="px-3 pb-3 text-sm text-dim">No signals in the last 24 hours</p>
      ) : (
        <div className="divide-y divide-border">
          {signals.map((signal) => (
            <SignalRow key={signal.id} signal={signal} />
          ))}
        </div>
      )}
    </div>
  );
}

function SignalRow({ signal }: { signal: Signal }) {
  const isLong = signal.direction === "LONG";

  return (
    <div className="px-3 py-2.5 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5 text-accent flex-shrink-0"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" /></svg>
        <span className="text-sm font-medium">{signal.pair.replace("-USDT-SWAP", "")}</span>
        <span className={`text-xs font-mono font-bold ${isLong ? "text-long" : "text-short"}`}>
          {signal.direction}
        </span>
        <span className={`text-xs font-mono ${isLong ? "text-long" : "text-short"}`}>
          {formatScore(signal.final_score)}
        </span>
        <span className="text-xs text-dim">{signal.timeframe}</span>
      </div>
      <span className="text-xs text-dim">{formatRelativeTime(signal.created_at)}</span>
    </div>
  );
}
