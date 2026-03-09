import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { Timeframe } from "../signals/types";
import { DEFAULT_SETTINGS, apiToStore, storeToApi } from "./types";
import { api } from "../../shared/lib/api";

interface SettingsState {
  pairs: string[];
  threshold: number;
  timeframes: Timeframe[];
  notificationsEnabled: boolean;
  apiBaseUrl: string;
  onchainEnabled: boolean;
  newsAlertsEnabled: boolean;
  newsContextWindow: number;
  /** True while initial fetch from server is in-flight */
  loading: boolean;
  /** Last sync error message, cleared on next successful sync */
  syncError: string | null;
  setPairs: (pairs: string[]) => void;
  setThreshold: (threshold: number) => void;
  setTimeframes: (timeframes: Timeframe[]) => void;
  setNotificationsEnabled: (enabled: boolean) => void;
  setApiBaseUrl: (url: string) => void;
  setOnchainEnabled: (enabled: boolean) => void;
  setNewsAlertsEnabled: (enabled: boolean) => void;
  setNewsContextWindow: (minutes: number) => void;
  /** Hydrate store from server on app init */
  fetchFromServer: () => Promise<void>;
  reset: () => void;
}

// --- Debounced sync --------------------------------------------------------

let _syncTimer: ReturnType<typeof setTimeout> | undefined;
let _lastServerState: Record<string, unknown> = {};

function debouncedSync(patch: Record<string, unknown>, delayMs = 500) {
  clearTimeout(_syncTimer);
  _syncTimer = setTimeout(async () => {
    const apiPatch = storeToApi(patch as never);
    try {
      await api.updatePipelineSettings(apiPatch);
      _lastServerState = { ..._lastServerState, ...patch };
      useSettingsStore.setState({ syncError: null });
    } catch (e) {
      // Revert to last known server state
      useSettingsStore.setState({
        ..._lastServerState,
        syncError: e instanceof Error ? e.message : "Sync failed",
      } as Partial<SettingsState>);
    }
  }, delayMs);
}

// Helper: set store + queue sync for a pipeline field
function setAndSync(patch: Partial<SettingsState>) {
  useSettingsStore.setState(patch);
  debouncedSync(patch as Record<string, unknown>);
}

// ---------------------------------------------------------------------------

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      ...DEFAULT_SETTINGS,
      loading: true,
      syncError: null,

      setPairs: (pairs) => setAndSync({ pairs }),
      setThreshold: (threshold) => setAndSync({ threshold }),
      setTimeframes: (timeframes) => setAndSync({ timeframes }),
      setOnchainEnabled: (onchainEnabled) => setAndSync({ onchainEnabled }),
      setNewsAlertsEnabled: (newsAlertsEnabled) => setAndSync({ newsAlertsEnabled }),
      setNewsContextWindow: (newsContextWindow) => setAndSync({ newsContextWindow }),

      // Client-only — no server sync
      setNotificationsEnabled: (enabled) => set({ notificationsEnabled: enabled }),
      setApiBaseUrl: (url) => set({ apiBaseUrl: url }),

      fetchFromServer: async () => {
        try {
          const data = await api.getPipelineSettings();
          const mapped = apiToStore(data);
          _lastServerState = { ...mapped };
          set({ ...mapped, loading: false, syncError: null });
        } catch {
          // Use defaults on failure — don't block the app
          set({ loading: false });
        }
      },

      reset: () => set(DEFAULT_SETTINGS),
    }),
    {
      name: "krypton-settings",
      storage: createJSONStorage(() => localStorage),
      // Only persist client-only fields to localStorage
      partialize: (state) => ({
        notificationsEnabled: state.notificationsEnabled,
        apiBaseUrl: state.apiBaseUrl,
      }),
    },
  ),
);
