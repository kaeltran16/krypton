import { create } from "zustand";
import type { Portfolio } from "../../shared/lib/api";

interface DashboardState {
  wsPortfolio: Portfolio | null;
  onAccountUpdate: (data: Portfolio) => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  wsPortfolio: null,
  onAccountUpdate: (data) => set({ wsPortfolio: data }),
}));
