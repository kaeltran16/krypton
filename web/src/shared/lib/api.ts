import { API_BASE_URL, API_KEY } from "./constants";
import type { Signal } from "../../features/signals/types";

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

export interface OrderRequest {
  pair: string;
  side: "buy" | "sell";
  size: string;
  order_type?: string;
  sl_price?: string;
  tp_price?: string;
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

  getCandles: (pair: string, timeframe: string, limit = 200) => {
    const query = new URLSearchParams({ pair, timeframe, limit: String(limit) });
    return request<CandleData[]>(`/api/candles?${query}`);
  },

  placeOrder: (order: OrderRequest) =>
    request<OrderResult>("/api/account/order", {
      method: "POST",
      body: JSON.stringify(order),
    }),
};
