export interface GroupHealth {
  group: string;
  priority: number;
  profit_factor: number | null;
  signals_since_last_opt: number;
  needs_eval: boolean;
  status: "green" | "yellow" | "red";
}

export interface ProposalChange {
  current: number;
  proposed: number;
}

export interface BacktestMetrics {
  profit_factor: number;
  win_rate: number;
  avg_rr: number;
  drawdown: number;
  signals_tested: number;
  optimization_mode?: "backtest" | "live_signals";
}

export interface ShadowProgress {
  total: number;
  resolved: number;
  target: number;
  complete: boolean;
}

export interface Proposal {
  id: number;
  status: "pending" | "shadow" | "approved" | "rejected" | "promoted" | "rolled_back";
  parameter_group: string;
  changes: Record<string, ProposalChange>;
  backtest_metrics: BacktestMetrics;
  shadow_metrics: ShadowProgress | null;
  created_at: string | null;
  shadow_started_at: string | null;
  promoted_at: string | null;
  rejected_reason: string | null;
}

export interface OptimizerStatus {
  global_profit_factor: number | null;
  resolved_count: number;
  groups: GroupHealth[];
  active_shadow: {
    proposal_id: number;
    group: string;
    progress: ShadowProgress;
    changes: Record<string, ProposalChange>;
  } | null;
}
