import { create } from "zustand";
import type { Signal } from "./types";

const MAX_SIGNALS = 100;

interface SignalState {
  signals: Signal[];
  selectedSignal: Signal | null;
  connected: boolean;
  candleListeners: Set<(candle: any) => void>;
  addSignal: (signal: Signal) => void;
  setSignals: (signals: Signal[]) => void;
  updateSignal: (id: number, patch: Partial<Signal>) => void;
  selectSignal: (signal: Signal) => void;
  clearSelection: () => void;
  setConnected: (connected: boolean) => void;
  clear: () => void;
  addCandleListener: (fn: (candle: any) => void) => void;
  removeCandleListener: (fn: (candle: any) => void) => void;
  notifyCandleListeners: (candle: any) => void;
}

export const useSignalStore = create<SignalState>((set, get) => ({
  signals: [],
  selectedSignal: null,
  connected: false,
  candleListeners: new Set(),
  addSignal: (signal) =>
    set((state) => ({
      signals: [signal, ...state.signals].slice(0, MAX_SIGNALS),
    })),
  setSignals: (signals) => set({ signals: signals.slice(0, MAX_SIGNALS) }),
  updateSignal: (id, patch) =>
    set((state) => ({
      signals: state.signals.map((s) => (s.id === id ? { ...s, ...patch } : s)),
      selectedSignal:
        state.selectedSignal?.id === id
          ? { ...state.selectedSignal, ...patch }
          : state.selectedSignal,
    })),
  selectSignal: (signal) => set({ selectedSignal: signal }),
  clearSelection: () => set({ selectedSignal: null }),
  setConnected: (connected) => set({ connected }),
  clear: () => set({ signals: [], selectedSignal: null, connected: false }),
  addCandleListener: (fn) => { get().candleListeners.add(fn); },
  removeCandleListener: (fn) => { get().candleListeners.delete(fn); },
  notifyCandleListeners: (candle) => { get().candleListeners.forEach((fn) => fn(candle)); },
}));
