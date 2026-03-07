import type { Signal } from "../types";
import { formatScore, formatPrice, formatRelativeTime } from "../../../shared/lib/format";

interface SignalCardProps {
  signal: Signal;
  onSelect: (signal: Signal) => void;
  onExecute?: (signal: Signal) => void;
}

export function SignalCard({ signal, onSelect, onExecute }: SignalCardProps) {
  const isLong = signal.direction === "LONG";
  const dirColor = isLong ? "text-long" : "text-short";
  const borderColor = isLong ? "border-long/20" : "border-short/20";
  const bgColor = isLong ? "bg-long/5" : "bg-short/5";
  const isPending = !signal.outcome || signal.outcome === "PENDING";

  return (
    <button
      onClick={() => onSelect(signal)}
      className={`w-full p-3 rounded-lg border text-left transition-colors active:opacity-80 ${borderColor} ${bgColor}`}
    >
      {/* Header: pair, direction badge, timeframe */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-accent text-xs">&#9889;</span>
          <span className="font-medium text-sm">{signal.pair.replace("-USDT-SWAP", "")}</span>
          <span className={`text-xs font-mono font-bold px-1.5 py-0.5 rounded ${
            isLong ? "bg-long/15 text-long" : "bg-short/15 text-short"
          }`}>
            {signal.direction}
          </span>
          <span className="text-xs text-dim px-1.5 py-0.5 rounded bg-card-hover">
            {signal.timeframe}
          </span>
        </div>
        {!isPending && <OutcomeBadge outcome={signal.outcome} />}
      </div>

      {/* Score with visual bar */}
      <div className="flex items-center gap-2 mt-2">
        <span className="text-xs text-muted">Score</span>
        <span className={`font-mono font-bold text-sm ${dirColor}`}>
          {formatScore(signal.final_score)}
        </span>
        <div className="flex-1 h-1.5 bg-card-hover rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${isLong ? "bg-long" : "bg-short"}`}
            style={{ width: `${Math.min(Math.max(signal.final_score, 0), 100)}%` }}
          />
        </div>
      </div>

      {/* Price levels */}
      <div className="flex items-center gap-3 mt-2 text-xs font-mono text-muted">
        <span>Entry <span className="text-foreground">{formatPrice(signal.levels.entry)}</span></span>
        <span>SL <span className="text-short">{formatPrice(signal.levels.stop_loss)}</span></span>
        <span>TP <span className="text-long">{formatPrice(signal.levels.take_profit_1)}</span></span>
      </div>

      {/* Footer: timestamp + badges */}
      <div className="flex items-center justify-between mt-2">
        <span className="text-xs text-dim">{formatRelativeTime(signal.created_at)}</span>
        <div className="flex items-center gap-1.5">
          {signal.user_status === "TRADED" && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border border-long/40 text-long">Traded</span>
          )}
          {signal.user_status === "SKIPPED" && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border border-border text-muted">Skipped</span>
          )}
          {!isPending && signal.outcome_pnl_pct != null && (
            <span className={`text-xs font-mono ${signal.outcome_pnl_pct >= 0 ? "text-long" : "text-short"}`}>
              {signal.outcome_pnl_pct >= 0 ? "+" : ""}{signal.outcome_pnl_pct.toFixed(2)}%
            </span>
          )}
        </div>
      </div>

      {/* Execute button */}
      {onExecute && isPending && (
        <button
          onClick={(e) => { e.stopPropagation(); onExecute(signal); }}
          className={`mt-2 w-full py-2 rounded text-xs font-medium transition-colors active:opacity-80 ${
            isLong ? "bg-long/15 text-long" : "bg-short/15 text-short"
          }`}
        >
          Execute {signal.direction}
        </button>
      )}
    </button>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    TP1_HIT: "bg-long/20 text-long",
    TP2_HIT: "bg-long/20 text-long",
    SL_HIT: "bg-short/20 text-short",
    EXPIRED: "bg-card-hover text-dim",
  };
  const labels: Record<string, string> = {
    TP1_HIT: "TP1 Hit",
    TP2_HIT: "TP2 Hit",
    SL_HIT: "SL Hit",
    EXPIRED: "Expired",
  };

  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${styles[outcome] ?? ""}`}>
      {labels[outcome] ?? outcome}
    </span>
  );
}
