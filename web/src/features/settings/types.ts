import type { Timeframe } from "../signals/types";

export interface Settings {
  pairs: string[];
  threshold: number;
  timeframes: Timeframe[];
  notificationsEnabled: boolean;
  apiBaseUrl: string;
  onchainEnabled: boolean;
  newsAlertsEnabled: boolean;
  newsContextWindow: number;
}

/** Shape returned by GET /api/pipeline/settings and sent via PUT */
export interface PipelineSettingsAPI {
  pairs: string[];
  timeframes: Timeframe[];
  signal_threshold: number;
  onchain_enabled: boolean;
  news_alerts_enabled: boolean;
  news_context_window: number;
  updated_at: string | null;
}

export const DEFAULT_SETTINGS: Settings = {
  pairs: ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
  threshold: 50,
  timeframes: ["15m", "1h", "4h"],
  notificationsEnabled: true,
  apiBaseUrl: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
  onchainEnabled: true,
  newsAlertsEnabled: true,
  newsContextWindow: 30,
};

/** Convert API response (snake_case) → Zustand store (camelCase) */
export function apiToStore(api: PipelineSettingsAPI): Partial<Settings> {
  return {
    pairs: api.pairs,
    timeframes: api.timeframes,
    threshold: api.signal_threshold,
    onchainEnabled: api.onchain_enabled,
    newsAlertsEnabled: api.news_alerts_enabled,
    newsContextWindow: api.news_context_window,
  };
}

/** Convert Zustand store fields → API body (snake_case, partial) */
export function storeToApi(
  patch: Partial<Pick<Settings, "pairs" | "timeframes" | "threshold" | "onchainEnabled" | "newsAlertsEnabled" | "newsContextWindow">>
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (patch.pairs !== undefined) out.pairs = patch.pairs;
  if (patch.timeframes !== undefined) out.timeframes = patch.timeframes;
  if (patch.threshold !== undefined) out.signal_threshold = patch.threshold;
  if (patch.onchainEnabled !== undefined) out.onchain_enabled = patch.onchainEnabled;
  if (patch.newsAlertsEnabled !== undefined) out.news_alerts_enabled = patch.newsAlertsEnabled;
  if (patch.newsContextWindow !== undefined) out.news_context_window = patch.newsContextWindow;
  return out;
}
