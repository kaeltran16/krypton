import { describe, it, expect, beforeEach } from "vitest";
import { useSignalStore } from "./store";
import type { Signal } from "./types";

function createSignal(overrides: Partial<Signal> = {}): Signal {
  return {
    id: 1,
    pair: "BTC-USDT-SWAP",
    timeframe: "1h",
    direction: "LONG",
    final_score: 75,
    traditional_score: 70,
    llm_factors: [{ type: "rsi_divergence", direction: "bullish", strength: 2, reason: "RSI higher lows" }],
    llm_contribution: 14,
    explanation: "Strong trend",
    levels: { entry: 85000, stop_loss: 84000, take_profit_1: 87000, take_profit_2: 89000 },
    outcome: "PENDING",
    outcome_pnl_pct: null,
    outcome_duration_minutes: null,
    outcome_at: null,
    user_note: null,
    user_status: "OBSERVED",
    risk_metrics: null,
    detected_patterns: null,
    correlated_news_ids: null,
    created_at: "2026-02-27T12:00:00Z",
    ...overrides,
  };
}

describe("useSignalStore", () => {
  beforeEach(() => {
    useSignalStore.getState().clear();
  });

  it("starts empty", () => {
    const state = useSignalStore.getState();
    expect(state.signals).toEqual([]);
    expect(state.selectedSignal).toBeNull();
    expect(state.connected).toBe(false);
  });

  it("adds signal to front of list", () => {
    const s1 = createSignal({ id: 1 });
    const s2 = createSignal({ id: 2 });
    useSignalStore.getState().addSignal(s1);
    useSignalStore.getState().addSignal(s2);
    expect(useSignalStore.getState().signals[0].id).toBe(2);
    expect(useSignalStore.getState().signals[1].id).toBe(1);
  });

  it("caps signals at 100", () => {
    for (let i = 0; i < 110; i++) {
      useSignalStore.getState().addSignal(createSignal({ id: i }));
    }
    expect(useSignalStore.getState().signals).toHaveLength(100);
  });

  it("selects and clears signal", () => {
    const s = createSignal();
    useSignalStore.getState().selectSignal(s);
    expect(useSignalStore.getState().selectedSignal).toEqual(s);

    useSignalStore.getState().clearSelection();
    expect(useSignalStore.getState().selectedSignal).toBeNull();
  });

  it("tracks connection status", () => {
    useSignalStore.getState().setConnected(true);
    expect(useSignalStore.getState().connected).toBe(true);
  });
});
