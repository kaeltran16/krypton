import { create } from "zustand";

export type Tab = "home" | "agent" | "signals" | "positions" | "more";

interface PositionTarget {
  pair: string;
  side: string;
}

interface NavigationStore {
  tab: Tab;
  setTab: (tab: Tab) => void;
  positionTarget: PositionTarget | null;
  navigateToPosition: (pair: string, side: string) => void;
  clearPositionTarget: () => void;
}

export const useNavigationStore = create<NavigationStore>((set) => ({
  tab: "home",
  setTab: (tab) => set({ tab }),
  positionTarget: null,
  navigateToPosition: (pair, side) =>
    set({ tab: "positions", positionTarget: { pair, side } }),
  clearPositionTarget: () => set({ positionTarget: null }),
}));
