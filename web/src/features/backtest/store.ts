import { create } from "zustand";
import { api } from "../../shared/lib/api";
import type {
  BacktestConfig,
  BacktestRun,
  BacktestRunSummary,
} from "./types";
import { AVAILABLE_PAIRS } from "../../shared/lib/constants";

type BacktestTab = "setup" | "results" | "compare" | "optimize";

interface BacktestState {
  tab: BacktestTab;
  setTab: (tab: BacktestTab) => void;

  // Config
  config: BacktestConfig;
  updateConfig: (patch: Partial<BacktestConfig>) => void;

  // Active run
  activeRun: BacktestRun | null;
  runLoading: boolean;
  runError: string | null;
  startRun: () => Promise<void>;
  cancelRun: () => Promise<void>;
  pollRun: (runId: string) => void;
  stopPolling: () => void;

  // Saved runs
  runs: BacktestRunSummary[];
  runsLoading: boolean;
  fetchRuns: () => Promise<void>;
  deleteRun: (id: string) => Promise<void>;
  loadRunDetail: (id: string) => Promise<void>;

  // Compare
  compareIds: string[];
  toggleCompareId: (id: string) => void;
  compareResult: BacktestRun[] | null;
  compareLoading: boolean;
  runCompare: () => Promise<void>;

  // Import
  importStatus: { job_id: string; status: string; total_imported: number } | null;
  importLoading: boolean;
  startImport: (lookbackDays: number) => Promise<void>;
  pollImport: (jobId: string) => void;
  onBacktestUpdate: (run: BacktestRun) => void;
  onImportUpdate: (status: { job_id: string; status: string; total_imported: number }) => void;
}

const defaultConfig: BacktestConfig = {
  pairs: [...AVAILABLE_PAIRS],
  timeframe: "15m",
  date_from: new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10),
  date_to: new Date().toISOString().slice(0, 10),
  signal_threshold: 40,
  tech_weight: 75,
  pattern_weight: 25,
  enable_patterns: true,
  sl_atr_multiplier: 1.5,
  tp1_atr_multiplier: 2.0,
  tp2_atr_multiplier: 3.0,
  max_concurrent_positions: 3,
  ml_enabled: false,
  ml_confidence_threshold: 65,
};

export const useBacktestStore = create<BacktestState>((set, get) => ({
  tab: "setup",
  setTab: (tab) => set({ tab }),

  config: { ...defaultConfig },
  updateConfig: (patch) =>
    set((s) => ({ config: { ...s.config, ...patch } })),

  activeRun: null,
  runLoading: false,
  runError: null,

  startRun: async () => {
    const { config } = get();
    set({ runLoading: true, runError: null, activeRun: null });
    try {
      const payload = {
        ...config,
        tech_weight: config.tech_weight / 100,
        pattern_weight: config.pattern_weight / 100,
        ml_confidence_threshold: config.ml_confidence_threshold / 100,
        parameter_overrides: config.parameter_overrides || undefined,
      };
      const { run_id } = await api.startBacktest(payload);
      get().pollRun(run_id);
    } catch (e: any) {
      set({ runLoading: false, runError: e.message || "Failed to start backtest" });
    }
  },

  cancelRun: async () => {
    const { activeRun } = get();
    if (!activeRun) return;
    try {
      await api.cancelBacktest(activeRun.id);
    } catch {
      // ignore
    }
  },

  pollRun: (runId) => {
    // initial fetch only — real-time updates come via WS
    api.getBacktestRun(runId).then((run) => {
      set({ activeRun: run });
      if (run.status !== "running") {
        set({ runLoading: false, tab: "results" });
        get().fetchRuns();
      }
    }).catch((e: any) => {
      set({ runLoading: false, runError: e.message });
    });
  },

  stopPolling: () => {
    // no-op — polling removed
  },

  onBacktestUpdate: (run) => {
    const { activeRun } = get();
    if (!activeRun || String(activeRun.id) !== String(run.id)) return;
    set({ activeRun: run as BacktestRun });
    if (run.status !== "running") {
      set({ runLoading: false, tab: "results" });
      get().fetchRuns();
    }
  },

  runs: [],
  runsLoading: false,
  fetchRuns: async () => {
    set({ runsLoading: true });
    try {
      const runs = await api.listBacktestRuns();
      set({ runs });
    } catch {
      // ignore
    } finally {
      set({ runsLoading: false });
    }
  },

  deleteRun: async (id) => {
    try {
      await api.deleteBacktestRun(id);
      set((s) => ({
        runs: s.runs.filter((r) => r.id !== id),
        compareIds: s.compareIds.filter((cid) => cid !== id),
      }));
    } catch {
      // ignore
    }
  },

  loadRunDetail: async (id) => {
    set({ runLoading: true, runError: null });
    try {
      const run = await api.getBacktestRunDetail(id);
      set({ activeRun: run, tab: "results" });
    } catch (e: any) {
      set({ runError: e.message });
    } finally {
      set({ runLoading: false });
    }
  },

  compareIds: [],
  toggleCompareId: (id) =>
    set((s) => ({
      compareIds: s.compareIds.includes(id)
        ? s.compareIds.filter((cid) => cid !== id)
        : s.compareIds.length < 4
          ? [...s.compareIds, id]
          : s.compareIds,
    })),

  compareResult: null,
  compareLoading: false,
  runCompare: async () => {
    const { compareIds } = get();
    if (compareIds.length < 2) return;
    set({ compareLoading: true });
    try {
      const { runs } = await api.compareBacktests(compareIds);
      set({ compareResult: runs });
    } catch {
      // ignore
    } finally {
      set({ compareLoading: false });
    }
  },

  importStatus: null,
  importLoading: false,
  startImport: async (lookbackDays) => {
    const { config } = get();
    set({ importLoading: true, importStatus: null });
    try {
      const result = await api.importCandles({
        pairs: config.pairs,
        timeframes: [config.timeframe],
        lookback_days: lookbackDays,
      });
      get().pollImport(result.job_id);
    } catch {
      set({ importLoading: false });
    }
  },

  pollImport: (jobId) => {
    // initial fetch only — real-time updates come via WS
    api.getImportStatus(jobId).then((status) => {
      set({ importStatus: status });
      if (status.status !== "running") {
        set({ importLoading: false });
      }
    }).catch(() => {
      set({ importLoading: false });
    });
  },

  onImportUpdate: (status) => {
    set({ importStatus: status });
    if (status.status !== "running") {
      set({ importLoading: false });
    }
  },
}));
