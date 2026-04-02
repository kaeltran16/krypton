import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import type { Signal } from "../types";
import { formatPrice, formatScore } from "../../../shared/lib/format";
import { PatternDetailRow } from "./PatternBadges";
import { IndicatorAudit } from "./IndicatorAudit";
import { ReasoningChain } from "./ReasoningChain";
import { Badge } from "../../../shared/components/Badge";
import { Button } from "../../../shared/components/Button";
import { ProgressBar } from "../../../shared/components/ProgressBar";

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
        <Button variant="ghost" size="md" icon={<X size={20} />} onClick={handleClose} aria-label="Close signal detail" />
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
            {signal.confidence_tier && (
              <Badge
                color={signal.confidence_tier === "high" ? "long" : signal.confidence_tier === "medium" ? "accent" : "muted"}
                pill
                weight="medium"
              >
                {signal.confidence_tier}
              </Badge>
            )}
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
        <ScoreBarRow label="Technical Analysis" value={Math.abs(signal.traditional_score)} />
        {signal.raw_indicators?.confluence_score != null && signal.raw_indicators.confluence_score !== 0 && (
          <ScoreBarRow label="HTF Confluence" value={Math.min(Math.abs(signal.raw_indicators.confluence_score as number), 100)} />
        )}
        {signal.llm_contribution != null && (
          <ScoreBarRow label="LLM Consensus" value={Math.min(Math.abs(signal.llm_contribution), 100)} />
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

function ScoreBarRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs font-medium uppercase tracking-wide">
        <span className="text-on-surface">{label}</span>
        <span className="text-primary tabular">{Math.round(value)}%</span>
      </div>
      <ProgressBar value={value} height="sm" track="bg-surface-container-highest" />
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
        className="w-full flex items-center justify-between px-5 py-3 text-xs uppercase tracking-widest text-on-surface-variant hover:text-on-surface transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
      >
        Engine Parameters
        <span className="text-sm">{open ? "\u2212" : "+"}</span>
      </button>
      {open && <SnapshotContent snapshot={snapshot} />}
    </div>
  );
}

function SnapshotContent({ snapshot }: { snapshot: Record<string, unknown> }) {
  const weights = snapshot.source_weights as Record<string, number> | undefined;
  const thresholds = snapshot.thresholds as Record<string, number> | undefined;
  const atr = snapshot.atr_multipliers as Record<string, unknown> | undefined;
  const regime = snapshot.regime_mix as Record<string, number> | undefined;
  const regimeCaps = snapshot.regime_caps as Record<string, number> | undefined;
  const regimeOuter = snapshot.regime_outer as Record<string, number> | undefined;
  const meanRev = snapshot.mean_reversion as Record<string, unknown> | undefined;
  const llmWeights = snapshot.llm_factor_weights as Record<string, number> | undefined;
  const confluence = snapshot.confluence as Record<string, number> | undefined;
  const mlRamp = snapshot.ml_weight_ramp as Record<string, number> | undefined;

  return (
        <div className="px-5 pb-5 space-y-4">
          {/* Source Weights */}
          {weights && Object.keys(weights).length > 0 && (
            <SnapGroup title="Source Weights">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(weights).map(([k, v]) => (
                  <SnapPill key={k} label={k} value={fmtPct(v)} />
                ))}
                {mlRamp != null && (
                  <>
                    <SnapPill label="ml_min" value={fmtPct(mlRamp.min)} />
                    <SnapPill label="ml_max" value={fmtPct(mlRamp.max)} />
                  </>
                )}
              </div>
            </SnapGroup>
          )}

          {/* Thresholds */}
          {thresholds && Object.keys(thresholds).length > 0 && (
            <SnapGroup title="Thresholds">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(thresholds).map(([k, v]) => (
                  <SnapPill key={k} label={k.replace(/_/g, " ")} value={String(v)} />
                ))}
              </div>
            </SnapGroup>
          )}

          {/* ATR Multipliers */}
          {atr && (
            <SnapGroup title="ATR Multipliers">
              <div className="flex flex-wrap gap-1.5">
                {atr.sl != null && <SnapPill label="SL" value={String(atr.sl)} />}
                {atr.tp1 != null && <SnapPill label="TP1" value={String(atr.tp1)} />}
                {atr.tp2 != null && <SnapPill label="TP2" value={String(atr.tp2)} />}
                {atr.source != null ? (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary self-center">
                    {String(atr.source).replace(/_/g, " ")}
                  </span>
                ) : null}
              </div>
            </SnapGroup>
          )}

          {/* Regime Mix */}
          {regime && Object.keys(regime).length > 0 && (
            <SnapGroup title="Regime Mix">
              <RegimeBar regime={regime} />
            </SnapGroup>
          )}

          {/* Regime Caps */}
          {regimeCaps && Object.keys(regimeCaps).length > 0 && (
            <SnapGroup title="Regime Caps">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(regimeCaps).map(([k, v]) => (
                  <SnapPill key={k} label={k} value={String(Math.round(v))} />
                ))}
              </div>
            </SnapGroup>
          )}

          {/* Regime Outer */}
          {regimeOuter && Object.keys(regimeOuter).length > 0 && (
            <SnapGroup title="Regime Outer Weights">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(regimeOuter).map(([k, v]) => (
                  <SnapPill key={k} label={k} value={v.toFixed(3)} />
                ))}
              </div>
            </SnapGroup>
          )}

          {/* LLM Factor Weights */}
          {llmWeights && Object.keys(llmWeights).length > 0 && (
            <SnapGroup title="LLM Factor Weights">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(llmWeights).map(([k, v]) => (
                  <SnapPill key={k} label={k.replace(/_/g, " ")} value={String(v)} />
                ))}
              </div>
              {snapshot.llm_factor_cap != null && (
                <div className="mt-1.5">
                  <SnapPill label="cap" value={String(snapshot.llm_factor_cap)} />
                </div>
              )}
            </SnapGroup>
          )}

          {/* Mean Reversion */}
          {meanRev && Object.keys(meanRev).length > 0 && (
            <SnapGroup title="Mean Reversion">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(meanRev).map(([k, v]) => (
                  <SnapPill key={k} label={k.replace(/_/g, " ")} value={typeof v === "number" ? v.toFixed(2) : String(v)} />
                ))}
              </div>
            </SnapGroup>
          )}

          {/* Confluence */}
          {confluence && Object.keys(confluence).length > 0 && (
            <SnapGroup title="Confluence">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(confluence).map(([k, v]) => (
                  <SnapPill key={k} label={k.replace(/_/g, " ")} value={typeof v === "number" ? v.toFixed(2) : String(v)} />
                ))}
              </div>
            </SnapGroup>
          )}
        </div>
  );
}

function SnapGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-on-surface-variant/60 mb-1.5">{title}</p>
      {children}
    </div>
  );
}

function SnapPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded bg-surface-container-highest/60">
      <span className="text-on-surface-variant">{label}</span>
      <span className="font-mono text-on-surface">{value}</span>
    </span>
  );
}

function RegimeBar({ regime }: { regime: Record<string, number> }) {
  const total = Object.values(regime).reduce((a, b) => a + b, 0) || 1;
  const colors: Record<string, string> = {
    trending: "bg-primary",
    ranging: "bg-accent",
    volatile: "bg-short",
  };
  return (
    <div>
      <div className="flex h-2 rounded-full overflow-hidden">
        {Object.entries(regime).map(([k, v]) => (
          <div
            key={k}
            className={`${colors[k] ?? "bg-muted"} transition-all`}
            style={{ width: `${(v / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="flex gap-3 mt-1.5">
        {Object.entries(regime).map(([k, v]) => (
          <span key={k} className="text-[10px] text-on-surface-variant">
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${colors[k] ?? "bg-muted"} mr-1`} />
            {k} {Math.round((v / total) * 100)}%
          </span>
        ))}
      </div>
    </div>
  );
}

function fmtPct(v: number): string {
  return v <= 1 ? `${Math.round(v * 100)}%` : `${v}%`;
}

