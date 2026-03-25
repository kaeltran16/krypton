import { describe, it, expect, vi, beforeEach } from "vitest";
import { useEngineStore } from "../store";
import type { PipelineScores } from "../types";

vi.mock("../../../shared/lib/api", () => ({
  api: {
    getEngineParameters: vi.fn(),
  },
}));

import { api } from "../../../shared/lib/api";
const mockApi = api as unknown as { getEngineParameters: ReturnType<typeof vi.fn> };

describe("useEngineStore", () => {
  beforeEach(() => {
    useEngineStore.setState({ params: null, loading: false, error: null, liveScores: {} });
    vi.clearAllMocks();
  });

  it("fetch loads params and sets loading states", async () => {
    const mockParams = { technical: {}, blending: {} };
    mockApi.getEngineParameters.mockResolvedValue(mockParams);

    await useEngineStore.getState().fetch();

    expect(useEngineStore.getState().params).toEqual(mockParams);
    expect(useEngineStore.getState().loading).toBe(false);
    expect(useEngineStore.getState().error).toBeNull();
  });

  it("fetch skips if params already loaded", async () => {
    useEngineStore.setState({ params: { technical: {} } as any });

    await useEngineStore.getState().fetch();

    expect(mockApi.getEngineParameters).not.toHaveBeenCalled();
  });

  it("fetch sets error on failure", async () => {
    mockApi.getEngineParameters.mockRejectedValue(new Error("Network error"));

    await useEngineStore.getState().fetch();

    expect(useEngineStore.getState().error).toBe("Network error");
    expect(useEngineStore.getState().params).toBeNull();
  });

  it("refresh always re-fetches", async () => {
    useEngineStore.setState({ params: { technical: {} } as any });
    const newParams = { technical: {}, blending: {} };
    mockApi.getEngineParameters.mockResolvedValue(newParams);

    await useEngineStore.getState().refresh();

    expect(mockApi.getEngineParameters).toHaveBeenCalled();
    expect(useEngineStore.getState().params).toEqual(newParams);
  });

  it("pushScores stores scores keyed by pair:timeframe", () => {
    const scores: PipelineScores = {
      pair: "BTC-USDT-SWAP",
      timeframe: "1H",
      technical: 42.5,
      order_flow: -10.3,
      onchain: null,
      patterns: 5.0,
      regime_blend: 30.1,
      ml_gate: 15.0,
      llm_gate: 0.8,
      signal: 35.2,
      emitted: false,
    };

    useEngineStore.getState().pushScores(scores);

    const stored = useEngineStore.getState().liveScores["BTC-USDT-SWAP:1H"];
    expect(stored).toEqual(scores);
  });

  it("pushScores overwrites previous scores for same key", () => {
    const first: PipelineScores = {
      pair: "BTC-USDT-SWAP",
      timeframe: "1H",
      technical: 42.5,
      order_flow: -10.3,
      onchain: null,
      patterns: 5.0,
      regime_blend: 30.1,
      ml_gate: 15.0,
      llm_gate: 0.8,
      signal: 35.2,
      emitted: false,
    };
    const second: PipelineScores = {
      ...first,
      technical: 50.0,
      signal: 45.0,
      emitted: true,
    };

    useEngineStore.getState().pushScores(first);
    useEngineStore.getState().pushScores(second);

    const stored = useEngineStore.getState().liveScores["BTC-USDT-SWAP:1H"];
    expect(stored.technical).toBe(50.0);
    expect(stored.signal).toBe(45.0);
    expect(stored.emitted).toBe(true);
  });
});
