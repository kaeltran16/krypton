import { useEffect, useRef, useState, useCallback } from "react";
import type { Signal, UserStatus } from "../types";
import { formatPrice, formatScore } from "../../../shared/lib/format";
import { api } from "../../../shared/lib/api";
import { useSignalStore } from "../store";

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

      <div className="p-4 border-b border-gray-800">
        <h3 className="text-sm text-gray-400 mb-2">Price Levels</h3>
        <div className="font-mono text-sm space-y-1">
          <LevelRow label="Entry" value={signal.levels.entry} />
          <LevelRow label="Stop Loss" value={signal.levels.stop_loss} className="text-short" />
          <LevelRow label="TP 1" value={signal.levels.take_profit_1} className="text-long" />
          <LevelRow label="TP 2" value={signal.levels.take_profit_2} className="text-long" />
        </div>
      </div>

      {signal.outcome && signal.outcome !== "PENDING" && (
        <div className="p-4 border-b border-gray-800">
          <h3 className="text-sm text-gray-400 mb-2">Outcome</h3>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>Result: <span className={`font-mono font-bold ${signal.outcome.includes("TP") ? "text-long" : "text-short"}`}>{signal.outcome.replace("_", " ")}</span></div>
            {signal.outcome_pnl_pct != null && (
              <div>P&L: <span className={`font-mono ${signal.outcome_pnl_pct >= 0 ? "text-long" : "text-short"}`}>{signal.outcome_pnl_pct >= 0 ? "+" : ""}{signal.outcome_pnl_pct.toFixed(2)}%</span></div>
            )}
            {signal.outcome_duration_minutes != null && (
              <div>Duration: <span className="font-mono">{signal.outcome_duration_minutes < 60 ? `${signal.outcome_duration_minutes}m` : `${Math.floor(signal.outcome_duration_minutes / 60)}h ${signal.outcome_duration_minutes % 60}m`}</span></div>
            )}
          </div>
        </div>
      )}

      <JournalSection signal={signal} />
    </dialog>
  );
}

function JournalSection({ signal }: { signal: Signal }) {
  const updateSignal = useSignalStore((s) => s.updateSignal);
  const [note, setNote] = useState(signal.user_note ?? "");
  const [saving, setSaving] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Reset note when signal changes
  useEffect(() => {
    setNote(signal.user_note ?? "");
  }, [signal.id, signal.user_note]);

  const saveNote = useCallback(
    (value: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(async () => {
        setSaving(true);
        try {
          await api.patchSignalJournal(signal.id, { note: value });
          updateSignal(signal.id, { user_note: value || null });
        } catch { /* ignore */ }
        setSaving(false);
      }, 800);
    },
    [signal.id, updateSignal],
  );

  const handleStatusChange = async (status: UserStatus) => {
    setSaving(true);
    try {
      await api.patchSignalJournal(signal.id, { status });
      updateSignal(signal.id, { user_status: status });
    } catch { /* ignore */ }
    setSaving(false);
  };

  const statuses: { value: UserStatus; label: string }[] = [
    { value: "OBSERVED", label: "Observed" },
    { value: "TRADED", label: "Traded" },
    { value: "SKIPPED", label: "Skipped" },
  ];

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm text-gray-400">Your Notes</h3>
        {saving && <span className="text-xs text-gray-500">Saving...</span>}
      </div>

      <div className="flex gap-1.5 mb-3">
        {statuses.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => handleStatusChange(value)}
            className={`flex-1 py-1.5 text-xs font-medium rounded-full transition-colors ${
              signal.user_status === value
                ? value === "TRADED"
                  ? "bg-long/20 text-long border border-long/40"
                  : value === "SKIPPED"
                    ? "bg-gray-700 text-gray-300 border border-gray-600"
                    : "bg-gray-700 text-white border border-gray-600"
                : "text-gray-500 border border-gray-800"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <textarea
        value={note}
        onChange={(e) => {
          const v = e.target.value;
          setNote(v);
          saveNote(v);
        }}
        maxLength={500}
        rows={3}
        placeholder="Add a note about this signal..."
        className="w-full bg-surface border border-gray-800 rounded-lg p-2.5 text-sm text-gray-300 placeholder-gray-600 resize-none focus:outline-none focus:border-gray-600"
      />
      <div className="text-xs text-gray-600 text-right mt-1">{note.length}/500</div>
    </div>
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
