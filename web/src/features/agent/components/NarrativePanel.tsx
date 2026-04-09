import { useAgentStore } from "../store";
import type { AgentAnalysis } from "../types";
import { getStaleness, type StalenessLevel } from "../types";

const TYPE_LABELS: Record<string, string> = {
  brief: "Market Brief",
  pair_dive: "Pair Dive",
  signal_explain: "Signal Explain",
  position_check: "Position Check",
};

function relativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function stalenessColor(staleness: StalenessLevel): string {
  if (staleness === "fresh") return "text-white/50";
  if (staleness === "aging") return "text-yellow-400/80";
  return "text-red-400/70";
}

function ScoreBreakdown({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(([, value]) => typeof value === "number") as [
    string,
    number,
  ][];

  if (!entries.length) return null;

  return (
    <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
      {entries.slice(0, 8).map(([key, value]) => (
        <div key={key} className="flex justify-between gap-3">
          <span className="text-white/40">{key.replace(/_/g, " ")}</span>
          <span className="text-white/70">{value}</span>
        </div>
      ))}
    </div>
  );
}

function AnalysisCard({
  analysis,
  isSelected,
  onSelect,
}: {
  analysis: AgentAnalysis;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const staleness = getStaleness(analysis.created_at);

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-lg border p-3 text-left transition-colors ${
        isSelected
          ? "border-accent/30 bg-white/5"
          : "border-white/5 bg-white/[0.02] hover:bg-white/[0.04]"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] uppercase text-white/50">
            {TYPE_LABELS[analysis.type] ?? analysis.type}
          </span>
          {analysis.pair ? <span className="text-[10px] text-white/40">{analysis.pair}</span> : null}
        </div>
        <div className="flex items-center gap-1.5">
          {staleness === "stale" ? (
            <span className="text-[9px] text-red-400/60">(stale)</span>
          ) : null}
          <span className={`text-[10px] ${stalenessColor(staleness)}`}>
            {relativeTime(analysis.created_at)}
          </span>
        </div>
      </div>

      {isSelected ? (
        <div className="mt-2">
          <p className="text-xs leading-relaxed text-white/70">{analysis.narrative}</p>
          <ScoreBreakdown metadata={analysis.metadata} />
        </div>
      ) : null}
    </button>
  );
}

interface Props {
  onRefresh: () => void;
}

export function NarrativePanel({ onRefresh }: Props) {
  const analyses = useAgentStore((state) => state.analyses);
  const selectAnalysis = useAgentStore((state) => state.selectAnalysis);
  const loading = useAgentStore((state) => state.loading);
  const selected = useAgentStore((state) => state.getSelected());

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-accent" />
      </div>
    );
  }

  if (!analyses.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="text-sm text-white/50">No analyses yet</p>
        <p className="text-xs text-white/30">
          Run <code className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-white/50">/market-brief</code>{" "}
          from Claude Code CLI to generate your first analysis.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-white/5 px-4 py-2">
        <span className="text-xs text-white/40">Analyses</span>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded px-2 py-0.5 text-[10px] text-white/40 hover:bg-white/5 hover:text-white/60"
        >
          Refresh
        </button>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {analyses.map((analysis) => (
          <AnalysisCard
            key={analysis.id}
            analysis={analysis}
            isSelected={selected?.id === analysis.id}
            onSelect={() => selectAnalysis(analysis.id)}
          />
        ))}
      </div>

      {selected ? (
        <div className="border-t border-white/5 px-4 py-2">
          <span className="text-[10px] text-white/30">
            Updated {relativeTime(selected.created_at)}
          </span>
        </div>
      ) : null}
    </div>
  );
}
