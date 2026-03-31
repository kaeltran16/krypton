export interface PipelineEvaluation {
  id: number;
  pair: string;
  timeframe: string;
  evaluated_at: string;
  emitted: boolean;
  signal_id: number | null;
  final_score: number;
  effective_threshold: number;
  tech_score: number;
  flow_score: number;
  onchain_score: number | null;
  pattern_score: number | null;
  liquidation_score: number | null;
  confluence_score: number | null;
  news_score: number | null;
  indicator_preliminary: number;
  blended_score: number;
  ml_score: number | null;
  ml_confidence: number | null;
  llm_contribution: number;
  ml_agreement: "agree" | "disagree" | "neutral";
  indicators: Record<string, number>;
  regime: { trending: number; ranging: number; volatile: number };
  availabilities: Record<string, { availability: number; conviction: number }>;
  suppressed_reason: string | null;
}

export interface MonitorSummary {
  period: string;
  total_evaluations: number;
  emitted_count: number;
  emission_rate: number;
  avg_abs_score: number;
  per_pair: PairSummary[];
}

export interface PairSummary {
  pair: string;
  total: number;
  emitted: number;
  emission_rate: number;
  avg_abs_score: number;
}

export type MonitorPeriod = "1h" | "6h" | "24h" | "7d";

export interface MonitorFilters {
  pair: string | null;
  emitted: boolean | null;
  suppressed: boolean | null;
  period: MonitorPeriod;
}
