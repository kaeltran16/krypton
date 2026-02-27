import { describe, it, expect, beforeEach } from "vitest";
import { useSettingsStore } from "./store";

describe("useSettingsStore", () => {
  beforeEach(() => {
    useSettingsStore.getState().reset();
    localStorage.clear();
  });

  it("starts with defaults", () => {
    const state = useSettingsStore.getState();
    expect(state.pairs).toEqual(["BTC-USDT-SWAP", "ETH-USDT-SWAP"]);
    expect(state.threshold).toBe(50);
    expect(state.timeframes).toEqual(["15m", "1h", "4h"]);
    expect(state.notificationsEnabled).toBe(true);
  });

  it("updates pairs", () => {
    useSettingsStore.getState().setPairs(["BTC-USDT-SWAP"]);
    expect(useSettingsStore.getState().pairs).toEqual(["BTC-USDT-SWAP"]);
  });

  it("updates threshold", () => {
    useSettingsStore.getState().setThreshold(75);
    expect(useSettingsStore.getState().threshold).toBe(75);
  });

  it("updates timeframes", () => {
    useSettingsStore.getState().setTimeframes(["4h"]);
    expect(useSettingsStore.getState().timeframes).toEqual(["4h"]);
  });

  it("resets to defaults", () => {
    useSettingsStore.getState().setThreshold(90);
    useSettingsStore.getState().reset();
    expect(useSettingsStore.getState().threshold).toBe(50);
  });
});
