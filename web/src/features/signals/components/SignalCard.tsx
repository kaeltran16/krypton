import type { Signal } from "../types";
import { formatScore, formatTime } from "../../../shared/lib/format";

interface SignalCardProps {
  signal: Signal;
  onSelect: (signal: Signal) => void;
  onExecute?: (signal: Signal) => void;
}

export function SignalCard({ signal, onSelect, onExecute }: SignalCardProps) {
  const isLong = signal.direction === "LONG";

  return (
    <button
      onClick={() => onSelect(signal)}
      className={`w-full p-4 rounded-lg border text-left transition-colors
        ${isLong ? "border-long/30 bg-long/5 hover:bg-long/10" : "border-short/30 bg-short/5 hover:bg-short/10"}`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium">{signal.pair}</span>
          <span className="text-xs text-gray-400">{signal.timeframe}</span>
        </div>
        <span className={`font-mono font-bold ${isLong ? "text-long" : "text-short"}`}>
          {signal.direction} {formatScore(signal.final_score)}
        </span>
      </div>
      <div className="flex items-center justify-between mt-2">
        <ConfidenceBadge confidence={signal.confidence} />
        <span className="text-xs text-gray-500">
          {formatTime(signal.created_at)}
        </span>
      </div>
      {onExecute && (
        <button
          onClick={(e) => { e.stopPropagation(); onExecute(signal); }}
          className={`mt-2 w-full py-2 rounded text-sm font-medium ${
            isLong ? "bg-long/20 text-long" : "bg-short/20 text-short"
          }`}
        >
          Execute {signal.direction}
        </button>
      )}
    </button>
  );
}

interface ConfidenceBadgeProps {
  confidence: Signal["confidence"];
}

function ConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  const styles = {
    HIGH: "bg-yellow-500/20 text-yellow-400",
    MEDIUM: "bg-blue-500/20 text-blue-400",
    LOW: "bg-gray-500/20 text-gray-400",
  };

  return (
    <span className={`text-xs px-2 py-0.5 rounded ${styles[confidence]}`}>
      {confidence}
    </span>
  );
}
