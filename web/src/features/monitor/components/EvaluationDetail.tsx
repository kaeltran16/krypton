import { useState } from "react";
import { Badge, Card, CollapsibleSection } from "../../../shared/components";
import type { PipelineEvaluation } from "../types";

function ScoreRow({ label, value }: { label: string; value: number | null }) {
  if (value === null || value === undefined) return null;
  const color =
    value > 0 ? "text-long" : value < 0 ? "text-short" : "text-on-surface-variant";
  return (
    <div className="flex justify-between text-xs py-0.5">
      <span className="text-on-surface-variant">{label}</span>
      <span className={color}>{value > 0 ? "+" : ""}{Math.round(value)}</span>
    </div>
  );
}

const INDICATOR_LABELS: Record<string, string> = {
  adx: "ADX",
  rsi: "RSI",
  bb_upper: "BB Upper",
  bb_lower: "BB Lower",
  bb_width: "BB Width",
  bb_width_pct: "BB Width %",
  atr: "ATR",
  obv_slope: "OBV Slope",
  vol_ratio: "Vol Ratio",
};

const FLOW_LABELS: Record<string, string> = {
  funding_rate: "Funding Rate",
  long_short_ratio: "L/S Ratio",
  open_interest_change_pct: "OI Change %",
  cvd_delta: "CVD Delta",
};

export function EvaluationDetail({ evaluation: e }: { evaluation: PipelineEvaluation }) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({});
  const toggle = (key: string) =>
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));

  const techIndicators = Object.entries(e.indicators).filter(
    ([k]) => k in INDICATOR_LABELS
  );
  const flowIndicators = Object.entries(e.indicators).filter(
    ([k]) => k in FLOW_LABELS
  );

  return (
    <Card padding="sm" className="mt-1 mb-2 border border-outline-variant/10">
      <p className="text-[10px] text-on-surface-variant uppercase tracking-wider mb-2">
        Scoring Pipeline
      </p>

      {/* Sub-scores */}
      <div className="grid grid-cols-2 gap-x-4">
        <ScoreRow label="Technical" value={e.tech_score} />
        <ScoreRow label="Order Flow" value={e.flow_score} />
        <ScoreRow label="On-chain" value={e.onchain_score} />
        <ScoreRow label="Pattern" value={e.pattern_score} />
        <ScoreRow label="Liquidation" value={e.liquidation_score} />
        <ScoreRow label="Confluence" value={e.confluence_score} />
      </div>

      <div className="border-t border-outline-variant/10 my-2" />

      {/* Transformation chain */}
      <div className="grid grid-cols-2 gap-x-4">
        <ScoreRow label="Preliminary" value={e.indicator_preliminary} />
        <ScoreRow label="Blended (post-ML)" value={e.blended_score} />
        <ScoreRow label="LLM Contribution" value={e.llm_contribution} />
        <ScoreRow label="Final" value={e.final_score} />
      </div>

      <div className="flex items-center gap-2 mt-2 mb-1">
        <Badge color={e.ml_agreement === "agree" ? "long" : e.ml_agreement === "disagree" ? "short" : "muted"}>
          ML: {e.ml_agreement}
        </Badge>
        {e.ml_score !== null && (
          <span className="text-[10px] text-on-surface-variant">
            score {e.ml_score.toFixed(2)} · conf {e.ml_confidence?.toFixed(2)}
          </span>
        )}
      </div>

      {/* Regime */}
      <div className="flex gap-3 mt-2 text-[10px] text-on-surface-variant">
        <span>Trend {(e.regime.trending * 100).toFixed(0)}%</span>
        <span>Range {(e.regime.ranging * 100).toFixed(0)}%</span>
        <span>Vol {(e.regime.volatile * 100).toFixed(0)}%</span>
      </div>

      {/* Collapsible indicator sections */}
      {techIndicators.length > 0 && (
        <CollapsibleSection
          title="Technical Indicators"
          open={!!openSections.tech}
          onToggle={() => toggle("tech")}
        >
          <div className="grid grid-cols-2 gap-x-4">
            {techIndicators.map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs py-0.5">
                <span className="text-on-surface-variant">{INDICATOR_LABELS[k] ?? k}</span>
                <span className="text-on-surface">{typeof v === "number" ? v.toFixed(2) : v}</span>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {flowIndicators.length > 0 && (
        <CollapsibleSection
          title="Order Flow"
          open={!!openSections.flow}
          onToggle={() => toggle("flow")}
        >
          <div className="grid grid-cols-2 gap-x-4">
            {flowIndicators.map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs py-0.5">
                <span className="text-on-surface-variant">{FLOW_LABELS[k] ?? k}</span>
                <span className="text-on-surface">{typeof v === "number" ? v.toFixed(4) : v}</span>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}
    </Card>
  );
}
