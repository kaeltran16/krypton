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
};
