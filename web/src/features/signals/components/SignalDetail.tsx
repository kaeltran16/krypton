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
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-lg font-bold">{signal.pair}</span>
            <span className="ml-2 text-sm text-muted">{signal.timeframe}</span>
          </div>
          <button onClick={onClose} className="text-muted hover:text-foreground text-xl leading-none">&times;</button>
        </div>
        <div className={`text-2xl font-mono font-bold mt-1 ${color}`}>
          {signal.direction} {formatScore(signal.final_score)}
        </div>
      </div>

      <div className="p-4 border-b border-border">
        <h3 className="text-sm text-muted mb-2">Score Breakdown</h3>
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
        <div className="p-4 border-b border-border">
          <h3 className="text-sm text-muted mb-2">AI Analysis</h3>
          <p className="text-sm text-foreground leading-relaxed">{signal.explanation}</p>
        </div>
      )}

      <div className="p-4 border-b border-border">
        <h3 className="text-sm text-muted mb-2">Price Levels</h3>
        <div className="font-mono text-sm space-y-1">
          <LevelRow label="Entry" value={signal.levels.entry} />
          <LevelRow label="Stop Loss" value={signal.levels.stop_loss} className="text-short" />
          <LevelRow label="TP 1" value={signal.levels.take_profit_1} className="text-long" />
          <LevelRow label="TP 2" value={signal.levels.take_profit_2} className="text-long" />
        </div>
      </div>

      {signal.outcome && signal.outcome !== "PENDING" && (
        <div className="p-4 border-b border-border">
          <h3 className="text-sm text-muted mb-2">Outcome</h3>
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
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

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
        <h3 className="text-sm text-muted">Your Notes</h3>
        {saving && <span className="text-xs text-muted">Saving...</span>}
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
                    ? "bg-card-hover text-muted border border-border"
                    : "bg-card-hover text-foreground border border-border"
                : "text-muted border border-border"
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
        className="w-full bg-card-hover border border-border rounded-lg p-2.5 text-sm text-foreground placeholder-dim resize-none focus:outline-none focus:border-accent/50"
      />
      <div className="text-xs text-dim text-right mt-1">{note.length}/500</div>
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
      <span className={`text-muted ${className}`}>{label}</span>
      <span>{formatPrice(value)}</span>
    </div>
  );
}
