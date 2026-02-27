import { create } from "zustand";
import type { Signal } from "./types";

const MAX_SIGNALS = 100;

interface SignalState {
  signals: Signal[];
  selectedSignal: Signal | null;
  connected: boolean;
  addSignal: (signal: Signal) => void;
  setSignals: (signals: Signal[]) => void;
  selectSignal: (signal: Signal) => void;
  clearSelection: () => void;
  setConnected: (connected: boolean) => void;
  clear: () => void;
}

export const useSignalStore = create<SignalState>((set) => ({
  signals: [],
  selectedSignal: null,
  connected: false,
  addSignal: (signal) =>
    set((state) => ({
      signals: [signal, ...state.signals].slice(0, MAX_SIGNALS),
    })),
  setSignals: (signals) => set({ signals: signals.slice(0, MAX_SIGNALS) }),
  selectSignal: (signal) => set({ selectedSignal: signal }),
  clearSelection: () => set({ selectedSignal: null }),
  setConnected: (connected) => set({ connected }),
  clear: () => set({ signals: [], selectedSignal: null, connected: false }),
}));
