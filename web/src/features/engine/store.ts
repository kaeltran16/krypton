import { create } from "zustand";
import { api } from "../../shared/lib/api";
import type { EngineParameters, PipelineScores } from "./types";

interface EngineStore {
  params: EngineParameters | null;
  loading: boolean;
  error: string | null;
  liveScores: Record<string, PipelineScores>;
  fetch: () => Promise<void>;
  refresh: () => Promise<void>;
  pushScores: (scores: PipelineScores) => void;
}

async function _load(set: (s: Partial<EngineStore>) => void) {
  set({ loading: true, error: null });
  try {
    const data = await api.getEngineParameters();
    set({ params: data, loading: false });
  } catch (e) {
    set({ error: (e as Error).message, loading: false });
  }
}

export const useEngineStore = create<EngineStore>((set, get) => ({
  params: null,
  loading: false,
  error: null,
  liveScores: {},

  fetch: async () => {
    if (get().params) return;
    await _load(set);
  },

  refresh: () => _load(set),

  pushScores: (scores) =>
    set((s) => ({
      liveScores: {
        ...s.liveScores,
        [`${scores.pair}:${scores.timeframe}`]: scores,
      },
    })),
}));
