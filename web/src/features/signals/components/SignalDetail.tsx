import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import type { Signal } from "../types";
import { formatPrice, formatScore } from "../../../shared/lib/format";
import { PatternDetailRow } from "./PatternBadges";
import { IndicatorAudit } from "./IndicatorAudit";
import { ReasoningChain } from "./ReasoningChain";
import ParameterRow from "../../engine/components/ParameterRow";

interface SignalDetailProps {
  signal: Signal | null;
  onClose: () => void;
}

export function SignalDetail({ signal, onClose }: SignalDetailProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;

    if (signal && !dialog.open) {
      dialog.showModal();
    } else if (!signal && dialog.open) {
      dialog.close();
    }
  }, [signal]);

  if (!signal) return null;

  const isLong = signal.direction === "LONG";
  const scoreNum = Math.abs(signal.final_score);
  const sentimentLabel = isLong ? "Long Sentiment" : "Short Sentiment";

  const handleClose = () => {
    ref.current?.close();
  };

  return (
    <dialog ref={ref} onClose={onClose} onClick={(e) => {
      if (e.target === ref.current) handleClose();
    }}>
      <div className="sticky top-0 z-10 flex justify-end p-2">
        <button
          onClick={handleClose}
          aria-label="Close signal detail"
          className="p-3 rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <X size={20} />
        </button>
      </div>
      {/* Hero Score Section */}
      <div className="px-5 pb-5 border-b border-outline-variant/10 flex justify-between items-center relative overflow-hidden">
        <div className="relative z-10">
          <p className="text-xs uppercase tracking-widest text-on-surface-variant mb-1">Overall Signal Score</p>
          <div className="flex items-baseline gap-2">
            <span className="font-headline font-bold text-5xl text-primary tabular">{formatScore(signal.final_score)}</span>
            <span className="text-on-surface-variant font-headline font-medium text-lg">/100</span>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${isLong ? "bg-long" : "bg-short"}`} />
            <span className={`text-xs font-medium uppercase tracking-wider ${isLong ? "text-long" : "text-short"}`}>
              {sentimentLabel}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-headline font-bold text-on-surface">{signal.pair}</span>
            <span className="text-on-surface-variant text-sm">{signal.timeframe}</span>
          </div>
        </div>
        <div className="relative z-10 h-24 w-24">
          <svg className="h-full w-full" viewBox="0 0 36 36">
            <path className="stroke-surface-container-highest" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" strokeWidth="3" />
            <path className="stroke-primary" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" strokeDasharray={`${scoreNum}, 100`} strokeLinecap="butt" strokeWidth="3" />
          </svg>
        </div>
        <div className="absolute -right-10 -top-10 h-40 w-40 bg-primary/5 blur-3xl rounded-full" />
      </div>

      {/* Score Breakdown */}
      <div className="p-5 border-b border-outline-variant/10 space-y-4">
        <h2 className="text-xs uppercase tracking-widest text-on-surface-variant">Intelligence Components</h2>
        <ScoreBar label="Technical Analysis" value={Math.abs(signal.traditional_score)} />
        {signal.llm_contribution != null && (
          <ScoreBar label="LLM Consensus" value={Math.min(Math.abs(signal.llm_contribution), 100)} />
        )}
        {signal.llm_factors && signal.llm_factors.length > 0 && (
          <div className="mt-2 space-y-1">
            {signal.llm_factors.map((f, i) => (
              <div key={i} className="flex items-center gap-2 text-xs" title={f.reason}>
                <span className={f.direction === "bullish" ? "text-long" : "text-short"}>
                  {f.direction === "bullish" ? "+" : "-"}
                </span>
                <span className="text-on-surface-variant">{(f.type ?? "unknown").replace(/_/g, " ")}</span>
                <span className="font-mono">{"*".repeat(f.strength)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {signal.raw_indicators && (
        <IndicatorAudit indicators={signal.raw_indicators} />
      )}

      <ReasoningChain signal={signal} />

      {signal.detected_patterns && signal.detected_patterns.length > 0 && (
        <PatternDetailRow patterns={signal.detected_patterns} />
      )}

      {signal.explanation && (
        <div className="p-5 border-b border-outline-variant/10">
          <h3 className="text-xs uppercase tracking-widest text-on-surface-variant mb-3">AI Analysis</h3>
          <p className="text-sm text-on-surface leading-relaxed">{signal.explanation}</p>
        </div>
      )}

      {/* Execution Matrix */}
      <div className="p-5 border-b border-outline-variant/10">
        <h3 className="text-xs uppercase tracking-widest text-on-surface-variant mb-4">Execution Matrix</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="p-3 rounded bg-surface-container-lowest border-l-2 border-primary">
            <p className="text-xs font-medium text-primary uppercase mb-1">Entry Range</p>
            <p className="font-headline font-bold text-lg tabular">{formatPrice(signal.levels.entry)}</p>
          </div>
          <div className="p-3 rounded bg-surface-container-lowest border-l-2 border-short">
            <p className="text-xs font-medium text-short uppercase mb-1">Stop Loss</p>
            <p className="font-headline font-bold text-lg tabular">{formatPrice(signal.levels.stop_loss)}</p>
          </div>
          <div className="p-3 rounded bg-surface-container-lowest border-l-2 border-long">
            <p className="text-xs font-medium text-long uppercase mb-1">Take Profit 1</p>
            <p className="font-headline font-bold text-lg tabular">{formatPrice(signal.levels.take_profit_1)}</p>
          </div>
          <div className="p-3 rounded bg-surface-container-lowest border-l-2 border-long/60">
            <p className="text-xs font-medium text-long uppercase mb-1">Take Profit 2</p>
            <p className="font-headline font-bold text-lg tabular">{formatPrice(signal.levels.take_profit_2)}</p>
          </div>
        </div>
      </div>

      {signal.outcome && signal.outcome !== "PENDING" && (
        <div className="p-5 border-b border-outline-variant/10">
          <h3 className="text-xs uppercase tracking-widest text-on-surface-variant mb-2">Outcome</h3>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>Result: <span className={`font-mono font-bold ${signal.outcome.includes("TP") ? "text-long" : "text-short"}`}>{signal.outcome.replace("_", " ")}</span></div>
            {signal.outcome_pnl_pct != null && (
              <div>P&L: <span className={`font-mono tabular ${signal.outcome_pnl_pct >= 0 ? "text-long" : "text-short"}`}>{signal.outcome_pnl_pct >= 0 ? "+" : ""}{signal.outcome_pnl_pct.toFixed(2)}%</span></div>
            )}
            {signal.outcome_duration_minutes != null && (
              <div>Duration: <span className="font-mono tabular">{signal.outcome_duration_minutes < 60 ? `${signal.outcome_duration_minutes}m` : `${Math.floor(signal.outcome_duration_minutes / 60)}h ${signal.outcome_duration_minutes % 60}m`}</span></div>
            )}
          </div>
        </div>
      )}

      {signal.engine_snapshot ? (
        <SnapshotSection snapshot={signal.engine_snapshot} />
      ) : (
        <p className="text-xs text-on-surface-variant px-4 py-2">Parameter snapshot not available</p>
      )}
    </dialog>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs font-medium uppercase tracking-wide">
        <span className="text-on-surface">{label}</span>
        <span className="text-primary tabular">{Math.round(value)}%</span>
      </div>
      <div className="h-1 w-full bg-surface-container-highest rounded-full overflow-hidden">
        <div className="h-full bg-primary rounded-full" style={{ width: `${Math.min(value, 100)}%` }} />
      </div>
    </div>
  );
}

function SnapshotSection({ snapshot }: { snapshot: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-t border-outline-variant/10">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full flex items-center justify-between px-4 py-2 text-xs text-on-surface-variant hover:text-on-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
      >
        Engine Parameters
        <span>{open ? "\u2212" : "+"}</span>
      </button>
      {open && (
        <div>
          {Object.entries(snapshot).map(([key, value]) => (
            <ParameterRow
              key={key}
              name={key}
              value={value as unknown}
              source="configurable"
            />
          ))}
        </div>
      )}
    </div>
  );
}

