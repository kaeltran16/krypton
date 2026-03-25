import { useState } from "react";

interface NodeData {
  label: string;
  score?: number | null;
  details?: Record<string, number>;
  emitted?: boolean;
}

interface Props {
  nodes?: Record<string, NodeData>;
}

const DEFAULT_NODES: Record<string, NodeData> = {
  technical: { label: "Technical" },
  order_flow: { label: "Order Flow" },
  onchain: { label: "On-Chain" },
  patterns: { label: "Patterns" },
  regime_blend: { label: "Regime Blend" },
  ml_gate: { label: "ML Gate" },
  llm_gate: { label: "LLM Gate" },
  signal: { label: "Signal" },
};

function ScoreNode({
  data,
  onClick,
  active,
}: {
  data: NodeData;
  onClick: () => void;
  active: boolean;
}) {
  const score = data.score;
  const color =
    score == null ? "text-muted" :
    score > 0 ? "text-long" :
    score < 0 ? "text-short" :
    "text-muted";

  return (
    <button
      onClick={onClick}
      className={`min-h-[44px] px-3 py-2 rounded text-xs transition-colors ${
        active
          ? "bg-primary/20 border border-primary/40"
          : "bg-surface-container border border-outline-variant/30 hover:border-primary/30"
      }`}
    >
      <div className="text-muted">{data.label}</div>
      {score != null && (
        <div className={`font-mono font-medium ${color}`}>
          {score > 0 ? "+" : ""}{score.toFixed(1)}
        </div>
      )}
      {data.emitted && (
        <div className="text-[10px] text-long font-medium mt-0.5">EMITTED</div>
      )}
    </button>
  );
}

export default function PipelineFlow({ nodes }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const merged = { ...DEFAULT_NODES, ...nodes };

  const expandedNode = expanded ? merged[expanded] : null;

  return (
    <div className="bg-surface-container-low rounded-xl p-3 space-y-2">
      <div className="text-[10px] font-bold uppercase tracking-widest text-primary">
        Signal Pipeline
      </div>

      {/* Flow: 2-row layout */}
      <div className="space-y-2">
        {/* Source scores row */}
        <div className="grid grid-cols-4 gap-1">
          {["technical", "order_flow", "onchain", "patterns"].map((key) => (
            <ScoreNode
              key={key}
              data={merged[key]}
              onClick={() => setExpanded(expanded === key ? null : key)}
              active={expanded === key}
            />
          ))}
        </div>
        <div className="text-muted text-[10px] text-center">{"\u2193"}</div>
        {/* Pipeline stages row */}
        <div className="grid grid-cols-4 gap-1">
          {["regime_blend", "ml_gate", "llm_gate", "signal"].map((key) => (
            <ScoreNode
              key={key}
              data={merged[key]}
              onClick={() => setExpanded(expanded === key ? null : key)}
              active={expanded === key}
            />
          ))}
        </div>
      </div>

      {/* Expanded details */}
      {expandedNode?.details && (
        <div className="border-t border-border/30 pt-2 space-y-0.5">
          {Object.entries(expandedNode.details).map(([key, value]) => (
            <div key={key} className="flex justify-between text-[10px] px-1">
              <span className="text-muted">{key}</span>
              <span className={`font-mono ${value > 0 ? "text-long" : value < 0 ? "text-short" : "text-muted"}`}>
                {value > 0 ? "+" : ""}{value.toFixed(1)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
