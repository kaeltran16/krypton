import { useShallow } from "zustand/react/shallow";
import { useSignalStore } from "../../signals/store";
import { formatScore, formatRelativeTime } from "../../../shared/lib/format";
import type { Signal } from "../../signals/types";

export function RecentSignals() {
  const signals = useSignalStore(useShallow((s) => s.signals.slice(0, 3)));

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      <div className="px-3 pt-3 pb-2 flex items-center justify-between">
        <span className="text-[10px] text-muted uppercase tracking-wider">
          Recent Signals ({signals.length})
        </span>
        <span className="text-[10px] text-accent">&rarr;</span>
      </div>
      {signals.length === 0 ? (
        <p className="px-3 pb-3 text-sm text-dim">Waiting for signals...</p>
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
        <span className="text-accent text-xs">&#9889;</span>
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
