import { useState, useRef, useEffect } from "react";
import { CollapsibleSection } from "../../../shared/components/CollapsibleSection";

interface NodeData {
  label: string;
  score?: number | null;
  details?: Record<string, number>;
  emitted?: boolean;
}

interface Props {
  nodes?: Record<string, NodeData>;
}

const VIEW_W = 800;
const EXPAND_H = 120;

const SOURCE_KEYS = ["technical", "order_flow", "onchain", "liquidation", "patterns", "confluence", "news"] as const;
const PROCESSING_KEYS = ["regime_blend", "agreement"] as const;
const GATE_KEYS = ["ml_gate", "llm_gate"] as const;
const OUTPUT_KEYS = ["threshold", "signal", "discard"] as const;

const ALL_KEYS = [...SOURCE_KEYS, ...PROCESSING_KEYS, ...GATE_KEYS, ...OUTPUT_KEYS] as const;
type NodeKey = (typeof ALL_KEYS)[number];

const DEFAULT_LABELS: Record<NodeKey, string> = {
  technical: "Technical",
  order_flow: "Order Flow",
  onchain: "On-Chain",
  liquidation: "Liquidation",
  patterns: "Patterns",
  confluence: "Confluence",
  news: "News",
  regime_blend: "Regime Blend",
  agreement: "Agreement",
  ml_gate: "ML Gate",
  llm_gate: "LLM Gate",
  threshold: "Threshold",
  signal: "Signal",
  discard: "Discard",
};

interface Pos { x: number; y: number; w: number; h: number }

function computePositions(narrow: boolean): Record<NodeKey, Pos> {
  const srcW = narrow ? 84 : 96;
  const srcH = 50;
  const procW = 130;
  const procH = 50;

  const pos: Partial<Record<NodeKey, Pos>> = {};

  if (narrow) {
    const row1 = SOURCE_KEYS.slice(0, 4);
    const row2 = SOURCE_KEYS.slice(4);
    const spacing1 = (VIEW_W - row1.length * srcW) / (row1.length + 1);
    const spacing2 = (VIEW_W - row2.length * srcW) / (row2.length + 1);
    row1.forEach((key, i) => {
      pos[key] = { x: spacing1 + i * (srcW + spacing1), y: 50, w: srcW, h: srcH };
    });
    row2.forEach((key, i) => {
      pos[key] = { x: spacing2 + i * (srcW + spacing2), y: 110, w: srcW, h: srcH };
    });
  } else {
    const srcSpacing = (VIEW_W - SOURCE_KEYS.length * srcW) / (SOURCE_KEYS.length + 1);
    SOURCE_KEYS.forEach((key, i) => {
      pos[key] = { x: srcSpacing + i * (srcW + srcSpacing), y: 50, w: srcW, h: srcH };
    });
  }

  const yShift = narrow ? 60 : 0;
  const cx = VIEW_W / 2 - procW / 2;
  pos.regime_blend = { x: cx, y: 160 + yShift, w: procW, h: procH };
  pos.agreement = { x: cx, y: 230 + yShift, w: procW, h: procH };
  pos.ml_gate = { x: cx, y: 310 + yShift, w: procW, h: procH };
  pos.llm_gate = { x: cx, y: 380 + yShift, w: procW, h: procH };
  pos.threshold = { x: cx, y: 450 + yShift, w: procW, h: procH };
  pos.signal = { x: cx - 80, y: 520 + yShift, w: 110, h: 44 };
  pos.discard = { x: cx + 80, y: 520 + yShift, w: 110, h: 44 };

  return pos as Record<NodeKey, Pos>;
}

type EdgeDef = { from: NodeKey; to: NodeKey };

const EDGES: EdgeDef[] = [
  ...SOURCE_KEYS.map((k) => ({ from: k as NodeKey, to: "regime_blend" as NodeKey })),
  { from: "regime_blend", to: "agreement" },
  { from: "agreement", to: "ml_gate" },
  { from: "ml_gate", to: "llm_gate" },
  { from: "llm_gate", to: "threshold" },
  { from: "threshold", to: "signal" },
  { from: "threshold", to: "discard" },
];

function edgePath(from: Pos, to: Pos, fromOffset: number, toOffset: number): string {
  const x1 = from.x + from.w / 2;
  const y1 = from.y + from.h + fromOffset;
  const x2 = to.x + to.w / 2;
  const y2 = to.y + toOffset;
  const cy1 = y1 + (y2 - y1) * 0.4;
  const cy2 = y1 + (y2 - y1) * 0.6;
  return `M ${x1} ${y1} C ${x1} ${cy1}, ${x2} ${cy2}, ${x2} ${y2}`;
}

function edgeStroke(score: number | null | undefined, isDiscardPath: boolean): string {
  if (isDiscardPath) return "var(--color-outline-variant, #555)";
  if (score == null) return "var(--color-outline-variant, #555)";
  if (score > 0) return "var(--color-long, #2DD4A0)";
  if (score < 0) return "var(--color-short, #FB7185)";
  return "var(--color-outline-variant, #555)";
}

function scoreColor(score: number | null | undefined): string {
  if (score == null) return "text-on-surface-variant/50";
  if (score > 0) return "text-long";
  if (score < 0) return "text-short";
  return "text-on-surface-variant/50";
}

function borderColor(score: number | null | undefined, emitted?: boolean): string {
  if (emitted) return "border-long";
  if (score == null) return "border-outline-variant/30";
  if (score > 0) return "border-long/40";
  if (score < 0) return "border-short/40";
  return "border-outline-variant/30";
}

function bgColor(score: number | null | undefined, emitted?: boolean): string {
  if (emitted) return "bg-long/10";
  if (score == null) return "bg-surface-container";
  if (score > 0) return "bg-long/5";
  if (score < 0) return "bg-short/5";
  return "bg-surface-container";
}

function PipelineNode({
  nodeKey,
  data,
  pos,
  expanded,
  onToggle,
  yOffset,
}: {
  nodeKey: NodeKey;
  data: NodeData;
  pos: Pos;
  expanded: boolean;
  onToggle: () => void;
  yOffset: number;
}) {
  const h = expanded && data.details ? pos.h + EXPAND_H : pos.h;
  return (
    <>
      {nodeKey === "signal" && data.emitted && (
        <rect
          className="signal-glow"
          x={pos.x - 4}
          y={pos.y + yOffset - 4}
          width={pos.w + 8}
          height={h + 8}
          rx={10}
          fill="none"
          stroke="#2DD4A0"
          strokeWidth={2}
          filter="url(#glow-long)"
          opacity={0.8}
        >
          <animate attributeName="opacity" values="0.8;0.3;0.8" dur="2s" repeatCount="indefinite" />
        </rect>
      )}
      <foreignObject x={pos.x} y={pos.y + yOffset} width={pos.w} height={h}>
        <button
          onClick={onToggle}
          className={`w-full px-2 py-1.5 rounded-lg text-xs transition-colors border ${borderColor(data.score, data.emitted)} ${bgColor(data.score, data.emitted)} cursor-pointer`}
          style={{ minHeight: `${pos.h}px` }}
          aria-label={
            data.score != null
              ? `${data.label} score: ${data.score > 0 ? "+" : ""}${data.score.toFixed(1)}, ${data.score > 0 ? "long" : data.score < 0 ? "short" : "neutral"} bias`
              : `${data.label}: no data`
          }
        >
          <div className="text-on-surface-variant text-[10px]">{data.label}</div>
          {data.score != null && (
            <div className={`font-mono font-medium text-xs ${scoreColor(data.score)}`}>
              {data.score > 0 ? "+" : ""}{data.score.toFixed(1)}
            </div>
          )}
          {data.emitted && (
            <div className="text-[9px] text-long font-bold mt-0.5">EMITTED</div>
          )}
        </button>
        {expanded && data.details && (
          <div className="mt-1 space-y-0.5 px-1" aria-expanded="true">
            {Object.entries(data.details).map(([key, value]) => (
              <div key={key} className="flex justify-between text-[9px]">
                <span className="text-on-surface-variant">{key}</span>
                <span className={`font-mono ${value > 0 ? "text-long" : value < 0 ? "text-short" : "text-on-surface-variant"}`}>
                  {value > 0 ? "+" : ""}{value.toFixed(1)}
                </span>
              </div>
            ))}
          </div>
        )}
      </foreignObject>
    </>
  );
}

export default function PipelineFlow({ nodes }: Props) {
  const [expanded, setExpanded] = useState<NodeKey | null>(null);
  const [optOpen, setOptOpen] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver(([entry]) => {
      const isNarrow = entry.contentRect.width < 500;
      setNarrow((prev) => (prev === isNarrow ? prev : isNarrow));
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  const positions = computePositions(narrow);
  const viewHBase = narrow ? 640 : 580;

  const getData = (key: NodeKey): NodeData => {
    const override = nodes?.[key];
    return { label: DEFAULT_LABELS[key], ...override };
  };

  const expandedPos = expanded ? positions[expanded] : null;
  const yOffset = (key: NodeKey): number => {
    if (!expandedPos) return 0;
    const p = positions[key];
    return p.y > expandedPos.y ? EXPAND_H : 0;
  };

  const viewH = expanded ? viewHBase + EXPAND_H : viewHBase;

  return (
    <div ref={containerRef} className="bg-surface-container-low rounded-xl p-3 space-y-2">
      <div className="text-[10px] font-bold uppercase tracking-widest text-primary">
        Signal Pipeline
      </div>
      <svg
        role="img"
        aria-label="Signal pipeline DAG visualization"
        viewBox={`0 0 ${VIEW_W} ${viewH}`}
        width="100%"
        height="auto"
        preserveAspectRatio="xMidYMin meet"
        className="overflow-visible"
      >
        <title>Signal Pipeline</title>

        <defs>
          <filter id="glow-long" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feFlood floodColor="#2DD4A0" floodOpacity="0.4" result="color" />
            <feComposite in="color" in2="blur" operator="in" result="glow" />
            <feMerge>
              <feMergeNode in="glow" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <style>{`
          .edge-animated {
            animation: pulse-down 2s linear infinite;
          }
          @keyframes pulse-down {
            to { stroke-dashoffset: -24; }
          }
          @media (prefers-reduced-motion: reduce) {
            .edge-animated { animation: none; }
          }
          .signal-glow {
            pointer-events: none;
          }
        `}</style>

        {/* Edges */}
        <g>
          {EDGES.map((e) => {
            const fromPos = positions[e.from];
            const toPos = positions[e.to];
            const fromData = getData(e.from);
            const isDiscard = e.to === "discard";
            const hasScore = fromData.score != null;
            return (
              <path
                key={`${e.from}-${e.to}`}
                className={`pipeline-edge ${hasScore && !isDiscard ? "edge-animated" : ""}`}
                d={edgePath(fromPos, toPos, yOffset(e.from), yOffset(e.to))}
                fill="none"
                stroke={edgeStroke(fromData.score, isDiscard)}
                strokeWidth={hasScore && !isDiscard ? 2 : 1}
                strokeDasharray={!hasScore || isDiscard ? "4 4" : "8 16"}
                strokeOpacity={isDiscard ? 0.4 : 0.7}
              />
            );
          })}
        </g>

        {/* Nodes */}
        <g>
          {ALL_KEYS.map((key) => (
            <PipelineNode
              key={key}
              nodeKey={key}
              data={getData(key)}
              pos={positions[key]}
              expanded={expanded === key}
              onToggle={() => setExpanded(expanded === key ? null : key)}
              yOffset={yOffset(key)}
            />
          ))}
        </g>
      </svg>

      <CollapsibleSection
        title="Self-Optimization"
        summary="ATR Learning, Param Optimizer, Regime Online"
        open={optOpen}
        onToggle={() => setOptOpen(!optOpen)}
      >
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            { label: "Outcome Resolver", desc: "Resolves TP/SL/expiry" },
            { label: "ATR Learning", desc: "Learns SL/TP multipliers" },
            { label: "Param Optimizer", desc: "Shadow-tests parameters" },
            { label: "Regime Online", desc: "Adapts source weights" },
          ].map((item) => (
            <div
              key={item.label}
              className="px-3 py-2 rounded-lg bg-surface-container border border-outline-variant/20 text-xs"
            >
              <div className="text-on-surface-variant font-medium">{item.label}</div>
              <div className="text-on-surface-variant/50 text-[10px] mt-0.5">{item.desc}</div>
            </div>
          ))}
        </div>
      </CollapsibleSection>
    </div>
  );
}
