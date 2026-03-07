import type { Signal } from "../types";
import { formatScore, formatPrice, formatTime } from "../../../shared/lib/format";

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
      {/* Row 1: Direction, pair, score, outcome */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`font-mono font-bold text-sm ${dirColor}`}>
            {signal.direction}
          </span>
          <span className="font-medium text-sm">{signal.pair.replace("-USDT-SWAP", "")}</span>
          <span className="text-xs text-gray-500">{signal.timeframe}</span>
        </div>
        <div className="flex items-center gap-1.5">
          {signal.user_status === "TRADED" && (
            <span className="text-xs px-1.5 py-0.5 rounded border border-long/40 text-long">Traded</span>
          )}
          {signal.user_status === "SKIPPED" && (
            <span className="text-xs px-1.5 py-0.5 rounded border border-gray-600 text-gray-400">Skipped</span>
          )}
          {signal.user_note && (
            <span className="text-xs text-gray-500" title="Has note">&#9998;</span>
          )}
          {!isPending && <OutcomeBadge outcome={signal.outcome} />}
          <span className={`font-mono font-bold text-sm ${dirColor}`}>
            {formatScore(signal.final_score)}
          </span>
        </div>
      </div>

      {/* Row 2: Levels */}
      <div className="flex items-center gap-3 mt-1.5 text-xs font-mono text-gray-400">
        <span>E {formatPrice(signal.levels.entry)}</span>
        <span className="text-short">SL {formatPrice(signal.levels.stop_loss)}</span>
        <span className="text-long">TP {formatPrice(signal.levels.take_profit_1)}</span>
      </div>

      {/* Row 3: Meta + outcome details */}
      <div className="flex items-center justify-between mt-1.5">
        <div className="flex items-center gap-2">
          <ConfidenceBadge confidence={signal.confidence} />
          {!isPending && signal.outcome_pnl_pct != null && (
            <span className={`text-xs font-mono ${signal.outcome_pnl_pct >= 0 ? "text-long" : "text-short"}`}>
              {signal.outcome_pnl_pct >= 0 ? "+" : ""}{signal.outcome_pnl_pct.toFixed(2)}%
            </span>
          )}
          {!isPending && signal.outcome_duration_minutes != null && (
            <span className="text-xs text-gray-500">
              {formatDuration(signal.outcome_duration_minutes)}
            </span>
          )}
        </div>
        <span className="text-xs text-gray-500">
          {formatTime(signal.created_at)}
        </span>
      </div>

      {/* Execute button (only for pending signals) */}
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

function ConfidenceBadge({ confidence }: { confidence: Signal["confidence"] }) {
  const styles = {
    HIGH: "bg-yellow-500/15 text-yellow-400",
    MEDIUM: "bg-blue-500/15 text-blue-400",
    LOW: "bg-gray-600/30 text-gray-400",
  };

  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${styles[confidence]}`}>
      {confidence}
    </span>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    TP1_HIT: "bg-long/20 text-long",
    TP2_HIT: "bg-long/20 text-long",
    SL_HIT: "bg-short/20 text-short",
    EXPIRED: "bg-gray-700/50 text-gray-400",
  };
  const labels: Record<string, string> = {
    TP1_HIT: "TP1 Hit",
    TP2_HIT: "TP2 Hit",
    SL_HIT: "SL Hit",
    EXPIRED: "Expired",
  };

  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${styles[outcome] ?? ""}`}>
      {labels[outcome] ?? outcome}
    </span>
  );
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}
