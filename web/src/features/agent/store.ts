import { create } from "zustand";

import type { AgentAnalysis } from "./types";

interface AgentStore {
  analyses: AgentAnalysis[];
  selectedId: number | null;
  loading: boolean;
  setAnalyses: (analyses: AgentAnalysis[]) => void;
  addAnalysis: (analysis: AgentAnalysis) => void;
  selectAnalysis: (id: number | null) => void;
  setLoading: (loading: boolean) => void;
  getSelected: () => AgentAnalysis | undefined;
  getLatest: () => AgentAnalysis | undefined;
}

export const useAgentStore = create<AgentStore>((set, get) => ({
  analyses: [],
  selectedId: null,
  loading: false,
  setAnalyses: (analyses) =>
    set((state) => ({
      analyses,
      selectedId:
        state.selectedId && analyses.some((item) => item.id === state.selectedId)
          ? state.selectedId
          : analyses[0]?.id ?? null,
    })),
  addAnalysis: (analysis) =>
    set((state) => ({
      analyses: [analysis, ...state.analyses.filter((item) => item.id !== analysis.id)].slice(
        0,
        50,
      ),
      selectedId: analysis.id,
    })),
  selectAnalysis: (id) => set({ selectedId: id }),
  setLoading: (loading) => set({ loading }),
  getSelected: () => {
    const { analyses, selectedId } = get();
    if (selectedId === null) return analyses[0];
    return analyses.find((analysis) => analysis.id === selectedId) ?? analyses[0];
  },
  getLatest: () => get().analyses[0],
}));
