export interface BacktestConfig {
  pairs: string[];
  timeframe: string;
  date_from: string;
  date_to: string;
  signal_threshold: number;
  tech_weight: number;
  pattern_weight: number;
  enable_patterns: boolean;
  sl_atr_multiplier: number;
  tp1_atr_multiplier: number;
  tp2_atr_multiplier: number;
  max_concurrent_positions: number;
  ml_enabled: boolean;
  ml_confidence_threshold: number;
}

export interface BacktestTrade {
  pair: string;
  direction: "LONG" | "SHORT";
  entry_time: string;
  exit_time: string | null;
  entry_price: number;
  exit_price: number | null;
  sl: number;
  tp1: number;
  tp2: number;
  outcome: string;
  pnl_pct: number;
  score: number;
  detected_patterns: string[];
  duration_minutes: number;
}

export interface BacktestStats {
  total_trades: number;
  win_rate: number;
  net_pnl: number;
  avg_pnl: number;
  avg_rr: number;
  max_drawdown: number;
  profit_factor: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  best_trade: { pnl_pct: number; pair: string; direction: string } | null;
  worst_trade: { pnl_pct: number; pair: string; direction: string } | null;
  avg_duration_minutes: number;
  by_direction: Record<string, { total: number; wins: number; win_rate: number }>;
  monthly_pnl: Record<string, number>;
  equity_curve: { time: string; cumulative_pnl: number }[];
}

export interface BacktestRun {
  id: string;
  created_at: string;
  status: "running" | "completed" | "failed" | "cancelled";
  config: BacktestConfig;
  pairs: string[];
  timeframe: string;
  date_from: string;
  date_to: string;
  results: {
    stats: BacktestStats;
    trades: BacktestTrade[];
  } | null;
}

export interface BacktestRunSummary {
  id: string;
  created_at: string;
  status: string;
  pairs: string[];
  timeframe: string;
  total_trades: number;
  win_rate: number;
  net_pnl: number;
  max_drawdown: number;
}
