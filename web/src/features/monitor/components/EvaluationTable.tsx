import { useState } from "react";
import { Badge, Button } from "../../../shared/components";
import { EvaluationDetail } from "./EvaluationDetail";
import { formatTime, formatPair } from "../../../shared/lib/format";
import type { PipelineEvaluation } from "../types";

function isNearThreshold(e: PipelineEvaluation) {
  return !e.emitted && Math.abs(e.final_score) >= e.effective_threshold * 0.85;
}

function ScoreCell({ value }: { value: number }) {
  const color =
    value > 0 ? "text-long" : value < 0 ? "text-short" : "text-on-surface-variant";
  return <span className={`font-mono text-xs ${color}`}>{value > 0 ? "+" : ""}{value}</span>;
}

export function EvaluationTable({
  items,
  hasMore,
  onLoadMore,
}: {
  items: PipelineEvaluation[];
  hasMore: boolean;
  onLoadMore: () => void;
}) {
  const [expandedId, setExpandedId] = useState<number | null>(null);

  if (!items.length) return null;

  return (
    <div>
      {/* Header */}
      <div className="grid grid-cols-[3rem_2.5rem_1fr_1fr_1fr_3.5rem] gap-1 px-2 py-1 text-[10px] text-on-surface-variant uppercase tracking-wider">
        <span>Time</span>
        <span>Pair</span>
        <span className="text-right">Final</span>
        <span className="text-right">Tech</span>
        <span className="text-right">Flow</span>
        <span className="text-right">Status</span>
      </div>

      {/* Rows */}
      {items.map((e) => (
        <div key={e.id}>
          <button
            className={`w-full grid grid-cols-[3rem_2.5rem_1fr_1fr_1fr_3.5rem] gap-1 px-2 py-2 text-xs items-center hover:bg-surface-container-high/50 transition-colors ${
              isNearThreshold(e) ? "bg-amber-500/5" : ""
            } ${expandedId === e.id ? "bg-surface-container-high/30" : ""}`}
            onClick={() => setExpandedId(expandedId === e.id ? null : e.id)}
          >
            <span className="text-on-surface-variant font-mono">{formatTime(e.evaluated_at)}</span>
            <span className="text-on-surface font-medium">{formatPair(e.pair)}</span>
            <span className="text-right"><ScoreCell value={e.final_score} /></span>
            <span className="text-right"><ScoreCell value={e.tech_score} /></span>
            <span className="text-right"><ScoreCell value={e.flow_score} /></span>
            <span className="text-right">
              <Badge color={e.emitted ? "long" : "muted"} pill>
                {e.emitted ? "emit" : "rej"}
              </Badge>
            </span>
          </button>
          {expandedId === e.id && <EvaluationDetail evaluation={e} />}
        </div>
      ))}

      {/* Load more */}
      {hasMore && (
        <div className="flex justify-center py-4">
          <Button variant="secondary" size="sm" onClick={onLoadMore}>
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}
