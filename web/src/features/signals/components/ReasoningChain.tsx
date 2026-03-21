import { computeRegime } from "../types";
import type { Signal, DetectedPattern } from "../types";

interface ReasoningChainProps {
  signal: Signal;
}

interface Step {
  phase: string;
  detail: string;
  value?: string;
  sentiment?: "bullish" | "bearish" | "neutral";
}

function buildChain(signal: Signal): Step[] {
  const steps: Step[] = [];
  const ind = signal.raw_indicators;

  // Step 1: Market regime
  const regime = ind ? computeRegime(ind) : null;
  if (regime) {
    steps.push({
      phase: "Regime Detection",
      detail: `Market classified as ${regime.dominant}`,
      value: `${regime.dominantPct}% confidence`,
      sentiment: regime.dominant === "trending" ? "bullish" : "neutral",
    });
  }

  // Step 2: Technical scan
  if (ind?.rsi != null) {
    const rsiLabel =
      ind.rsi > 70 ? "overbought" : ind.rsi < 30 ? "oversold" : "neutral";
    steps.push({
      phase: "Technical Scan",
      detail: `RSI ${ind.rsi.toFixed(1)} (${rsiLabel}), ADX ${ind.adx?.toFixed(1) ?? "N/A"}`,
      value: `Score: ${Math.abs(signal.traditional_score).toFixed(0)}`,
      sentiment: signal.direction === "LONG" ? "bullish" : "bearish",
    });
  }

  // Step 3: Pattern recognition
  if (signal.detected_patterns && signal.detected_patterns.length > 0) {
    const names = signal.detected_patterns
      .slice(0, 3)
      .map((p: DetectedPattern) => p.name)
      .join(", ");
    const bias = signal.detected_patterns[0]?.bias ?? "neutral";
    steps.push({
      phase: "Pattern Recognition",
      detail: names,
      value: `${signal.detected_patterns.length} pattern${signal.detected_patterns.length > 1 ? "s" : ""}`,
      sentiment: bias === "bullish" ? "bullish" : bias === "bearish" ? "bearish" : "neutral",
    });
  }

  // Step 4: Order flow
  if (ind?.funding_rate != null) {
    steps.push({
      phase: "Order Flow",
      detail: `Funding ${(ind.funding_rate * 100).toFixed(4)}%, OI ${ind.open_interest_change_pct != null ? `${ind.open_interest_change_pct > 0 ? "+" : ""}${ind.open_interest_change_pct.toFixed(1)}%` : "N/A"}`,
      value: ind.long_short_ratio != null ? `L/S ${ind.long_short_ratio.toFixed(2)}` : undefined,
      sentiment: "neutral",
    });
  }

  // Step 5: LLM consensus
  if (signal.llm_factors && signal.llm_factors.length > 0) {
    const bullCount = signal.llm_factors.filter((f) => f.direction === "bullish").length;
    const bearCount = signal.llm_factors.filter((f) => f.direction === "bearish").length;
    steps.push({
      phase: "LLM Consensus",
      detail: `${bullCount} bullish, ${bearCount} bearish factor${bullCount + bearCount > 1 ? "s" : ""}`,
      value: signal.llm_contribution != null ? `${signal.llm_contribution > 0 ? "+" : ""}${signal.llm_contribution.toFixed(1)}` : undefined,
      sentiment: bullCount > bearCount ? "bullish" : bearCount > bullCount ? "bearish" : "neutral",
    });
  }

  // Step 6: Final score
  steps.push({
    phase: "Signal Emission",
    detail: `${signal.direction} ${signal.pair} ${signal.timeframe}`,
    value: `Score: ${Math.abs(signal.final_score).toFixed(0)}/100`,
    sentiment: signal.direction === "LONG" ? "bullish" : "bearish",
  });

  return steps;
}

const SENTIMENT_DOT: Record<string, string> = {
  bullish: "bg-long",
  bearish: "bg-short",
  neutral: "bg-outline",
};

export function ReasoningChain({ signal }: ReasoningChainProps) {
  const steps = buildChain(signal);
  if (steps.length <= 1) return null;

  return (
    <div className="p-5 border-b border-outline-variant/10">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-4">
        Engine Reasoning Chain
      </h3>
      {steps.map((step, i) => (
        <div key={step.phase} className="flex gap-3">
          {/* Timeline */}
          <div className="flex flex-col items-center w-3 flex-shrink-0" aria-hidden="true">
            <div className={`w-2 h-2 rounded-full mt-1.5 ${SENTIMENT_DOT[step.sentiment ?? "neutral"]}`} />
            {i < steps.length - 1 && (
              <div className="w-px flex-1 bg-outline-variant/20 my-1" />
            )}
          </div>
          {/* Content */}
          <div className="pb-4 min-w-0">
            <div className="flex items-baseline gap-2">
              <span className="text-xs font-bold text-on-surface uppercase tracking-wider">
                {step.phase}
              </span>
              {step.value && (
                <span className="text-[10px] font-mono tabular-nums text-primary">
                  {step.value}
                </span>
              )}
            </div>
            <p className="text-xs text-on-surface-variant mt-0.5 leading-relaxed">
              {step.detail}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
