import { create } from "zustand";
import type { NewsEvent } from "./types";

interface NewsState {
  alerts: NewsEvent[];
  currentAlert: NewsEvent | null;
  addAlert: (news: NewsEvent) => void;
  dismissAlert: () => void;
}

export const useNewsStore = create<NewsState>((set) => ({
  alerts: [],
  currentAlert: null,
  addAlert: (news) =>
    set((s) => ({
      alerts: [news, ...s.alerts].slice(0, 50),
      currentAlert: news,
    })),
  dismissAlert: () => set({ currentAlert: null }),
}));
