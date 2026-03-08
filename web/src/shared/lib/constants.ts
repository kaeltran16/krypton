export const API_BASE_URL =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const WS_BASE_URL =
  import.meta.env.VITE_WS_URL ?? "ws://localhost:8000";

export const API_KEY = import.meta.env.VITE_API_KEY ?? "";

export const VAPID_PUBLIC_KEY = import.meta.env.VITE_VAPID_PUBLIC_KEY ?? "";

export const AVAILABLE_PAIRS = [
  "BTC-USDT-SWAP",
  "ETH-USDT-SWAP",
  "WIF-USDT-SWAP",
] as const;
