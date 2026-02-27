import type { Timeframe } from "../signals/types";

export interface Settings {
  pairs: string[];
  threshold: number;
  timeframes: Timeframe[];
  notificationsEnabled: boolean;
  apiBaseUrl: string;
}

export const DEFAULT_SETTINGS: Settings = {
  pairs: ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
  threshold: 50,
  timeframes: ["15m", "1h", "4h"],
  notificationsEnabled: true,
  apiBaseUrl: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
};
