import { API_BASE_URL } from "./constants";
import type { Signal, SignalStats, CalendarResponse, UserStatus } from "../../features/signals/types";
import type { NewsEvent } from "../../features/news/types";
import type { BacktestRun, BacktestRunSummary, BacktestConfig } from "../../features/backtest/types";
import type { PipelineSettingsAPI } from "../../features/settings/types";
import type { Alert, AlertCreateRequest, AlertUpdateRequest, AlertHistoryEntry, AlertSettings } from "../../features/alerts/types";
import type { EngineParameters, ParameterDiff, AtrOptimizationResult } from "../../features/engine/types";

// ML Training Types
export interface MLTrainRequest {
  timeframe?: string;
  lookback_days?: number;
  epochs?: number;
  batch_size?: number;
  hidden_size?: number;
  num_layers?: number;
  lr?: number;
  seq_len?: number;
  dropout?: number;
  label_horizon?: number;
  label_threshold_pct?: number;
}

export interface MLTrainProgress {
  epoch: number;
  total_epochs: number;
  train_loss: number;
  val_loss: number;
  direction_acc?: number;
}

export interface MLTrainResult {
  best_epoch: number;
  best_val_loss: number;
  total_epochs: number;
  total_samples: number;
  flow_data_used: boolean;
  version?: string;
  direction_accuracy?: number;
  precision_per_class?: { long: number; short: number; neutral: number };
  recall_per_class?: { long: number; short: number; neutral: number };
  loss_history?: { epoch: number; train_loss: number; val_loss: number | null }[];
}

export interface MLTrainJob {
  job_id: string;
  status: "running" | "completed" | "failed" | "cancelled";
  progress?: Record<string, MLTrainProgress>;
  result?: Record<string, MLTrainResult>;
  error?: string;
  created_at?: string;
  params?: MLTrainRequest;
}

export interface MLStatus {
  ml_enabled: boolean;
  loaded_pairs: string[];
}

export interface MLBackfillRequest {
  timeframe?: string;
  lookback_days?: number;
}

export interface MLBackfillJob {
  job_id: string;
  status: "running" | "completed" | "failed" | "cancelled";
  progress?: Record<string, number>;
  result?: Record<string, number>;
  error?: string;
}

export const jsonHeaders: HeadersInit = {
  "Content-Type": "application/json",
};

let _unauthorizedFired = false;
export function resetUnauthorizedFlag() { _unauthorizedFired = false; }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: jsonHeaders,
    credentials: "include",
    ...init,
  });
  if (res.status === 401) {
    if (!_unauthorizedFired) {
      _unauthorizedFired = true;
      window.dispatchEvent(new Event("auth:unauthorized"));
    }
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

export interface AccountBalance {
  total_equity: number;
  unrealized_pnl: number;
  currencies: {
    currency: string;
    available: number;
    frozen: number;
    equity: number;
  }[];
}

export interface Position {
  pair: string;
  side: "long" | "short";
  size: number;
  avg_price: number;
  mark_price: number;
  unrealized_pnl: number;
  liquidation_price: number | null;
  margin: number;
  leverage: string;
}

export interface CandleData {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Portfolio {
  total_equity: number;
  unrealized_pnl: number;
  available_balance: number;
  used_margin: number;
  total_exposure: number;
  margin_utilization: number;
  positions: Position[];
}

export interface RiskMetrics {
  position_size_usd: number;
  position_size_base: number;
  risk_amount_usd: number;
  risk_pct: number;
  tp1_rr: number | null;
  tp2_rr: number | null;
}

export interface RiskSettings {
  risk_per_trade: number;
  max_position_size_usd: number | null;
  daily_loss_limit_pct: number;
  max_concurrent_positions: number;
  max_exposure_pct: number;
  cooldown_after_loss_minutes: number | null;
  max_risk_per_trade_pct: number;
  updated_at: string | null;
}

export interface RiskRule {
  rule: string;
  status: "OK" | "WARNING" | "BLOCKED";
  reason: string;
}

export interface RiskCheckResult {
  status: "OK" | "WARNING" | "BLOCKED";
  rules: RiskRule[];
}

export interface RiskState {
  equity: number;
  daily_pnl_pct: number;
  open_positions_count: number;
  total_exposure_usd: number;
  exposure_pct: number;
  last_sl_hit_at: string | null;
}

export interface RiskStatus {
  settings: RiskSettings;
  state: RiskState;
  rules: RiskRule[];
  overall_status: "OK" | "WARNING" | "BLOCKED";
}

export interface OrderRequest {
  pair: string;
  side: "buy" | "sell";
  size: string;
  order_type?: string;
  sl_price?: string;
  tp_price?: string;
  override?: boolean;
  override_rules?: string[];
}

export interface OrderResult {
  success: boolean;
  order_id?: string;
  error?: string;
  warning?: string;
}

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  picture: string | null;
}

interface AuthResponse {
  token: string;
  user: AuthUser;
}

export const api = {
  authMe: () => request<AuthResponse>("/api/auth/me"),
  authGoogle: (idToken: string) => request<AuthResponse>("/api/auth/google", {
    method: "POST",
    body: JSON.stringify({ id_token: idToken }),
  }),
  authLogout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),

  getSignals: (params?: {
    pair?: string;
    timeframe?: string;
    limit?: number;
    since?: string;
  }) => {
    const query = new URLSearchParams();
    if (params?.pair) query.set("pair", params.pair);
    if (params?.timeframe) query.set("timeframe", params.timeframe);
    if (params?.limit) query.set("limit", String(params.limit));
    if (params?.since) query.set("since", params.since);
    const qs = query.toString();
    return request<Signal[]>(`/api/signals${qs ? `?${qs}` : ""}`);
  },

  getBalance: () => request<AccountBalance>("/api/account/balance"),

  getPositions: () => request<Position[]>("/api/account/positions"),

  getPortfolio: () => request<Portfolio>("/api/account/portfolio"),

  getRiskSettings: () => request<RiskSettings>("/api/risk/settings"),

  updateRiskSettings: (settings: Partial<RiskSettings>) =>
    request<RiskSettings>("/api/risk/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  checkRisk: (params: { pair: string; direction: string; size_usd: number }) =>
    request<RiskCheckResult>("/api/risk/check", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  getRiskStatus: () => request<RiskStatus>("/api/risk/status"),

  getCandles: (pair: string, timeframe: string, limit = 200) => {
    const query = new URLSearchParams({ pair, timeframe, limit: String(limit) });
    return request<CandleData[]>(`/api/candles?${query}`);
  },

  getSignalStats: (days = 7) =>
    request<SignalStats>(`/api/signals/stats?days=${days}`),

  patchSignalJournal: (id: number, patch: { status?: UserStatus; note?: string }) =>
    request<Signal>(`/api/signals/${id}/journal`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  getSignalCalendar: (month: string) =>
    request<CalendarResponse>(`/api/signals/calendar?month=${month}`),

  getSignalsByDate: (date: string) =>
    request<Signal[]>(`/api/signals/by-date?date=${date}`),

  placeOrder: (order: OrderRequest) =>
    request<OrderResult>("/api/account/order", {
      method: "POST",
      body: JSON.stringify(order),
    }),

  closePosition: (pair: string, posSide: "long" | "short") =>
    request<{ success: boolean }>("/api/account/close-position", {
      method: "POST",
      body: JSON.stringify({ pair, pos_side: posSide }),
    }),

  getNews: (params?: {
    category?: string;
    impact?: string;
    sentiment?: string;
    pair?: string;
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.category) query.set("category", params.category);
    if (params?.impact) query.set("impact", params.impact);
    if (params?.sentiment) query.set("sentiment", params.sentiment);
    if (params?.pair) query.set("pair", params.pair);
    if (params?.limit) query.set("limit", String(params.limit));
    if (params?.offset) query.set("offset", String(params.offset));
    const qs = query.toString();
    return request<NewsEvent[]>(`/api/news${qs ? `?${qs}` : ""}`);
  },

  getRecentNews: (limit = 20) =>
    request<NewsEvent[]>(`/api/news/recent?limit=${limit}`),

  // Backtest
  importCandles: (params: { pairs: string[]; timeframes: string[]; lookback_days: number }) =>
    request<{ job_id: string; status: string }>("/api/backtest/import", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  getImportStatus: (jobId: string) =>
    request<{ job_id: string; status: string; total_imported: number; errors: string[] }>(
      `/api/backtest/import/${jobId}`,
    ),

  startBacktest: (config: BacktestConfig) =>
    request<{ run_id: string; status: string }>("/api/backtest/run", {
      method: "POST",
      body: JSON.stringify(config),
    }),

  getBacktestRun: (runId: string) =>
    request<BacktestRun>(`/api/backtest/run/${runId}`),

  cancelBacktest: (runId: string) =>
    request<{ run_id: string; status: string }>(`/api/backtest/run/${runId}/cancel`, {
      method: "POST",
    }),

  listBacktestRuns: () =>
    request<BacktestRunSummary[]>("/api/backtest/runs"),

  getBacktestRunDetail: (runId: string) =>
    request<BacktestRun>(`/api/backtest/runs/${runId}`),

  compareBacktests: (runIds: string[]) =>
    request<{ runs: BacktestRun[] }>("/api/backtest/compare", {
      method: "POST",
      body: JSON.stringify({ run_ids: runIds }),
    }),

  deleteBacktestRun: (runId: string) =>
    request<{ deleted: string }>(`/api/backtest/runs/${runId}`, {
      method: "DELETE",
    }),

  // ML
  getMLStatus: () =>
    request<{ ml_enabled: boolean; loaded_pairs: string[] }>("/api/ml/status"),

  getMLDataReadiness: (timeframe: string) =>
    request<Record<string, { count: number; oldest: string | null; sufficient: boolean }>>(
      `/api/ml/data-readiness?timeframe=${encodeURIComponent(timeframe)}`,
    ),

  startMLTraining: (params: MLTrainRequest) =>
    request<{ job_id: string; status: string }>("/api/ml/train", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  getMLTrainingStatus: (jobId: string) =>
    request<{ job_id: string; status: string; progress: Record<string, unknown>; result?: Record<string, unknown> }>(
      `/api/ml/train/${jobId}`,
    ),

  cancelMLTraining: (jobId: string) =>
    request<{ job_id: string; status: string }>(`/api/ml/train/${jobId}/cancel`, {
      method: "POST",
    }),

  startMLBackfill: (params: { timeframe?: string; lookback_days?: number }) =>
    request<{ job_id: string; status: string }>("/api/ml/backfill", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  getMLBackfillStatus: (jobId: string) =>
    request<{ job_id: string; status: string; progress: Record<string, unknown>; result?: Record<string, unknown> }>(
      `/api/ml/backfill/${jobId}`,
    ),

  // Pipeline settings
  getPipelineSettings: () =>
    request<PipelineSettingsAPI>("/api/pipeline/settings"),

  updatePipelineSettings: (patch: Partial<Omit<PipelineSettingsAPI, "updated_at">>) =>
    request<PipelineSettingsAPI>("/api/pipeline/settings", {
      method: "PUT",
      body: JSON.stringify(patch),
    }),

  // Alerts
  getAlerts: () => request<Alert[]>("/api/alerts"),

  createAlert: (body: AlertCreateRequest) =>
    request<Alert>("/api/alerts", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  updateAlert: (id: string, body: AlertUpdateRequest) =>
    request<Alert>(`/api/alerts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deleteAlert: (id: string) =>
    request<{ deleted: string }>(`/api/alerts/${id}`, {
      method: "DELETE",
    }),

  getAlertHistory: (params?: { since?: string; until?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.since) query.set("since", params.since);
    if (params?.until) query.set("until", params.until);
    if (params?.limit) query.set("limit", String(params.limit));
    const qs = query.toString();
    return request<AlertHistoryEntry[]>(`/api/alerts/history${qs ? `?${qs}` : ""}`);
  },

  getAlertSettings: () => request<AlertSettings>("/api/alerts/settings"),

  updateAlertSettings: (body: Partial<AlertSettings>) =>
    request<AlertSettings>("/api/alerts/settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  // Engine parameters
  getEngineParameters: () =>
    request<EngineParameters>("/api/engine/parameters"),

  previewEngineApply: (changes: Record<string, number | Record<string, number>>) =>
    request<{ preview: true; diff: ParameterDiff[] }>("/api/engine/apply", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ changes, confirm: false }),
    }),

  confirmEngineApply: (changes: Record<string, number | Record<string, number>>) =>
    request<{ applied: true; diff: ParameterDiff[] }>("/api/engine/apply", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ changes, confirm: true }),
    }),

  optimizeAtr: (pair: string, timeframe: string) =>
    request<AtrOptimizationResult>("/api/backtest/optimize-atr", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ pair, timeframe }),
    }),
};
