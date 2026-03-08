import { API_BASE_URL, API_KEY } from "./constants";
import type { Signal, SignalStats, CalendarResponse, UserStatus } from "../../features/signals/types";
import type { NewsEvent } from "../../features/news/types";

export const jsonHeaders: HeadersInit = {
  "Content-Type": "application/json",
  ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { headers: jsonHeaders, ...init });
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
}

export const api = {
  getSignals: (params?: {
    pair?: string;
    timeframe?: string;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.pair) query.set("pair", params.pair);
    if (params?.timeframe) query.set("timeframe", params.timeframe);
    if (params?.limit) query.set("limit", String(params.limit));
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

  placeOrder: (order: OrderRequest) =>
    request<OrderResult>("/api/account/order", {
      method: "POST",
      body: JSON.stringify(order),
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
};
