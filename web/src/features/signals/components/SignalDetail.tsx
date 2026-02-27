import { useEffect, useRef } from "react";
import type { Signal } from "../types";
import { formatPrice, formatScore } from "../../../shared/lib/format";

interface SignalDetailProps {
  signal: Signal | null;
  onClose: () => void;
}

export function SignalDetail({ signal, onClose }: SignalDetailProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;

    if (signal) {
      dialog.showModal();
    } else {
      dialog.close();
    }
  }, [signal]);

  if (!signal) return null;

  const isLong = signal.direction === "LONG";
  const color = isLong ? "text-long" : "text-short";

  return (
    <dialog ref={ref} onClose={onClose} onClick={(e) => {
      if (e.target === ref.current) onClose();
    }}>
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-lg font-bold">{signal.pair}</span>
            <span className="ml-2 text-sm text-gray-400">{signal.timeframe}</span>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">&times;</button>
        </div>
        <div className={`text-2xl font-mono font-bold mt-1 ${color}`}>
          {signal.direction} {formatScore(signal.final_score)}
        </div>
      </div>

      <div className="p-4 border-b border-gray-800">
        <h3 className="text-sm text-gray-400 mb-2">Score Breakdown</h3>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            Traditional: <span className="font-mono">{formatScore(signal.traditional_score)}</span>
          </div>
          <div>
            LLM: <span className="font-mono">{signal.llm_opinion ?? "N/A"}</span>
          </div>
        </div>
      </div>

      {signal.explanation && (
        <div className="p-4 border-b border-gray-800">
          <h3 className="text-sm text-gray-400 mb-2">AI Analysis</h3>
          <p className="text-sm text-gray-300 leading-relaxed">{signal.explanation}</p>
        </div>
      )}

      <div className="p-4">
        <h3 className="text-sm text-gray-400 mb-2">Price Levels</h3>
        <div className="font-mono text-sm space-y-1">
          <LevelRow label="Entry" value={signal.levels.entry} />
          <LevelRow label="Stop Loss" value={signal.levels.stop_loss} className="text-short" />
          <LevelRow label="TP 1" value={signal.levels.take_profit_1} className="text-long" />
          <LevelRow label="TP 2" value={signal.levels.take_profit_2} className="text-long" />
        </div>
      </div>
    </dialog>
  );
}

interface LevelRowProps {
  label: string;
  value: number;
  className?: string;
}

function LevelRow({ label, value, className = "" }: LevelRowProps) {
  return (
    <div className="flex justify-between">
      <span className={`text-gray-400 ${className}`}>{label}</span>
      <span>{formatPrice(value)}</span>
    </div>
  );
}
