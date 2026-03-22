export interface ParameterValue {
  value: number | number[] | string | Record<string, number>;
  source: "hardcoded" | "configurable";
}

export interface ParameterDiff {
  path: string;
  current: number | null;
  proposed: number;
  source: string;
}

export interface AtrOptimizationResult {
  current: { sl_atr: number; tp1_atr: number; tp2_atr: number };
  proposed: { sl_atr: number; tp1_atr: number; tp2_atr: number };
  metrics: {
    signals_analyzed: number;
    current_sortino: number | null;
    proposed_sortino: number | null;
  };
}

export interface RegimeCapWeights {
  inner_caps: Record<string, number>;
  outer_weights: Record<string, number>;
}

export interface LearnedAtrEntry {
  sl_atr: ParameterValue;
  tp1_atr: ParameterValue;
  tp2_atr: ParameterValue;
  last_optimized_at: string | null;
  signal_count: number;
}

export interface EngineParameters {
  technical: {
    indicator_periods: Record<string, ParameterValue>;
    sigmoid_params: Record<string, ParameterValue>;
    mean_reversion: Record<string, ParameterValue>;
  };
  order_flow: {
    max_scores: Record<string, ParameterValue>;
    sigmoid_steepnesses: Record<string, ParameterValue>;
    regime_params: Record<string, ParameterValue>;
  };
  onchain: Record<string, Record<string, ParameterValue | Record<string, ParameterValue>>>;
  blending: {
    source_weights: Record<string, ParameterValue>;
    ml_blend_weight: ParameterValue;
    thresholds: Record<string, ParameterValue>;
    llm_factor_weights: Record<string, ParameterValue>;
    llm_factor_cap: ParameterValue;
    confluence_max_score: ParameterValue;
  };
  levels: Record<string, Record<string, ParameterValue>>;
  patterns: { strengths: Record<string, ParameterValue> };
  regime_weights: Record<string, Record<string, Record<string, RegimeCapWeights>>>;
  learned_atr: Record<string, Record<string, LearnedAtrEntry>>;
  performance_tracker: Record<string, Record<string, ParameterValue>>;
  descriptions?: Record<string, { description: string; pipeline_stage: string; range: string }>;
}
