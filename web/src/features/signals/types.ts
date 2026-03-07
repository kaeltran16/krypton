export type Direction = "LONG" | "SHORT";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";
export type LlmOpinion = "confirm" | "caution" | "contradict";
export type Timeframe = "15m" | "1h" | "4h";
export type SignalOutcome = "PENDING" | "TP1_HIT" | "TP2_HIT" | "SL_HIT" | "EXPIRED";
export type UserStatus = "OBSERVED" | "TRADED" | "SKIPPED";

export interface SignalLevels {
  entry: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
}

export interface Signal {
  id: number;
  pair: string;
  timeframe: Timeframe;
  direction: Direction;
  final_score: number;
  confidence: Confidence;
  traditional_score: number;
  llm_opinion: LlmOpinion | null;
  explanation: string | null;
  levels: SignalLevels;
  outcome: SignalOutcome;
  outcome_pnl_pct: number | null;
  outcome_duration_minutes: number | null;
  outcome_at: string | null;
  created_at: string;
  user_note: string | null;
  user_status: UserStatus;
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
