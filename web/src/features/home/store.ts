import { create } from "zustand";
import type { SignalStats } from "../signals/types";

interface HomeState {
  wsStats: SignalStats | null;
  onStatsUpdate: (data: SignalStats) => void;
}

export const useHomeStore = create<HomeState>((set) => ({
  wsStats: null,
  onStatsUpdate: (data) => set({ wsStats: data }),
}));
