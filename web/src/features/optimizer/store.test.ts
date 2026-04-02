import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/lib/api", () => ({
  api: {
    getOptimizerStatus: vi.fn(),
    getOptimizerProposals: vi.fn(),
    approveProposal: vi.fn(),
    rejectProposal: vi.fn(),
    promoteProposal: vi.fn(),
    rollbackProposal: vi.fn(),
    optimizeFromSignals: vi.fn(),
  },
}));

import { api } from "../../shared/lib/api";
import { useOptimizerStore } from "./store";

const mockApi = vi.mocked(api);

describe("useOptimizerStore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useOptimizerStore.setState({
      status: null,
      proposals: [],
      loading: false,
      actionLoading: false,
      signalOptLoading: false,
      error: null,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps refreshing after live-signal optimization starts until a proposal appears", async () => {
    const status = {
      global_profit_factor: null,
      resolved_count: 0,
      groups: [],
      active_shadow: null,
    };
    const proposal = {
      id: 7,
      status: "pending" as const,
      parameter_group: "regime_outer_weights",
      changes: {
        trending: { current: 0, proposed: 1 },
      },
      backtest_metrics: {
        profit_factor: 0,
        win_rate: 0,
        avg_rr: 0,
        drawdown: 0,
        signals_tested: 58,
        optimization_mode: "live_signals" as const,
      },
      shadow_metrics: null,
      created_at: null,
      shadow_started_at: null,
      promoted_at: null,
      rejected_reason: null,
    };

    mockApi.optimizeFromSignals.mockResolvedValue({
      status: "started",
      pair: "BTC-USDT-SWAP",
      signals_queued: 58,
    });
    mockApi.getOptimizerStatus.mockResolvedValue(status);
    mockApi.getOptimizerProposals
      .mockResolvedValueOnce({ proposals: [] })
      .mockResolvedValueOnce({ proposals: [proposal] });

    const run = useOptimizerStore.getState().optimizeFromSignals("BTC-USDT-SWAP");

    await Promise.resolve();
    await vi.runAllTimersAsync();
    await run;

    expect(mockApi.getOptimizerProposals).toHaveBeenCalledTimes(2);
    expect(useOptimizerStore.getState().proposals).toEqual([proposal]);
  });
});
