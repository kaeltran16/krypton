export type Direction = "LONG" | "SHORT";
export type Timeframe = "15m" | "1h" | "4h";
export type SignalOutcome = "PENDING" | "TP1_HIT" | "TP2_HIT" | "SL_HIT" | "EXPIRED";
export type UserStatus = "OBSERVED" | "TRADED" | "SKIPPED";

export interface SignalLevels {
  entry: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
}

export interface RiskMetrics {
  position_size_usd: number;
  position_size_base: number;
  risk_amount_usd: number;
  risk_pct: number;
  tp1_rr: number | null;
  tp2_rr: number | null;
}

export interface DetectedPattern {
  name: string;
  type: "candlestick" | "chart";
  bias: "bullish" | "bearish" | "neutral";
  strength: number;
}

export type FactorDirection = "bullish" | "bearish";

export interface LLMFactor {
  type: string;
  direction: FactorDirection;
  strength: 1 | 2 | 3;
  reason: string;
}

export interface Signal {
  id: number;
  pair: string;
  timeframe: Timeframe;
  direction: Direction;
  final_score: number;
  traditional_score: number;
  llm_factors: LLMFactor[] | null;
  llm_contribution: number | null;
  explanation: string | null;
  levels: SignalLevels;
  outcome: SignalOutcome;
  outcome_pnl_pct: number | null;
  outcome_duration_minutes: number | null;
  outcome_at: string | null;
  created_at: string;
  user_note: string | null;
  user_status: UserStatus;
  risk_metrics: RiskMetrics | null;
  detected_patterns: DetectedPattern[] | null;
  correlated_news_ids: number[] | null;
}

export interface PerformanceMetrics {
  sharpe_ratio: number | null;
  max_drawdown_pct: number;
  profit_factor: number | null;
  expectancy: number | null;
  avg_hold_time_minutes: number | null;
  best_trade: { pnl_pct: number; pair: string; timeframe: string; direction: string } | null;
  worst_trade: { pnl_pct: number; pair: string; timeframe: string; direction: string } | null;
}

export interface SignalStats {
  win_rate: number;
  avg_rr: number;
  total_resolved: number;
  total_wins: number;
  total_losses: number;
  total_expired?: number;
  by_pair: Record<string, { wins: number; losses: number; total: number; win_rate: number; avg_pnl: number }>;
  by_timeframe: Record<string, { wins: number; total: number; win_rate: number }>;
  equity_curve: { date: string; cumulative_pnl: number }[];
  hourly_performance: { hour: number; avg_pnl: number; count: number }[];
  streaks: { current: number; best_win: number; worst_loss: number };
  performance: PerformanceMetrics;
  drawdown_series: { date: string; drawdown: number }[];
  pnl_distribution: { bucket: number; count: number }[];
}

export interface CalendarDay {
  date: string;
  signal_count: number;
  net_pnl: number;
  wins: number;
  losses: number;
}

export interface CalendarResponse {
  days: CalendarDay[];
  monthly_summary: {
    total_signals: number;
    net_pnl: number;
    best_day: string | null;
    worst_day: string | null;
  };
}
