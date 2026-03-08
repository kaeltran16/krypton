import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { Timeframe } from "../signals/types";
import { DEFAULT_SETTINGS } from "./types";

interface SettingsState {
  pairs: string[];
  threshold: number;
  timeframes: Timeframe[];
  notificationsEnabled: boolean;
  apiBaseUrl: string;
  onchainEnabled: boolean;
  newsAlertsEnabled: boolean;
  newsContextWindow: number;
  setPairs: (pairs: string[]) => void;
  setThreshold: (threshold: number) => void;
  setTimeframes: (timeframes: Timeframe[]) => void;
  setNotificationsEnabled: (enabled: boolean) => void;
  setApiBaseUrl: (url: string) => void;
  setOnchainEnabled: (enabled: boolean) => void;
  setNewsAlertsEnabled: (enabled: boolean) => void;
  setNewsContextWindow: (minutes: number) => void;
  reset: () => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      ...DEFAULT_SETTINGS,
      setPairs: (pairs) => set({ pairs }),
      setThreshold: (threshold) => set({ threshold }),
      setTimeframes: (timeframes) => set({ timeframes }),
      setNotificationsEnabled: (enabled) =>
        set({ notificationsEnabled: enabled }),
      setApiBaseUrl: (url) => set({ apiBaseUrl: url }),
      setOnchainEnabled: (enabled) => set({ onchainEnabled: enabled }),
      setNewsAlertsEnabled: (enabled) => set({ newsAlertsEnabled: enabled }),
      setNewsContextWindow: (minutes) => set({ newsContextWindow: minutes }),
      reset: () => set(DEFAULT_SETTINGS),
    }),
    {
      name: "krypton-settings",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        pairs: state.pairs,
        threshold: state.threshold,
        timeframes: state.timeframes,
        notificationsEnabled: state.notificationsEnabled,
        apiBaseUrl: state.apiBaseUrl,
        onchainEnabled: state.onchainEnabled,
        newsAlertsEnabled: state.newsAlertsEnabled,
        newsContextWindow: state.newsContextWindow,
      }),
    },
  ),
);
