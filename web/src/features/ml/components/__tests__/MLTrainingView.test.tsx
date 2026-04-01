import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { MLTrainingView } from "../MLTrainingView";
import { api } from "../../../../shared/lib/api";

vi.mock("../../../../shared/lib/api", () => ({
  api: {
    getMLDataReadiness: vi.fn(),
    startMLTraining: vi.fn(),
    getMLTrainingStatus: vi.fn(),
    cancelMLTraining: vi.fn(),
    startMLBackfill: vi.fn(),
    getMLBackfillStatus: vi.fn(),
    getMLTrainingHistory: vi.fn(),
    deleteMLTrainingRun: vi.fn(),
    getWSToken: vi.fn().mockResolvedValue({ token: "mock-ws-token" }),
  },
}));

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  constructor(_url: string) {
    MockWebSocket.instances.push(this);
    setTimeout(() => this.onopen?.(), 0);
  }
  send(data: string) { this.sent.push(data); }
  close() { this.onclose?.(); }
  simulateMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value; }),
    clear: vi.fn(() => { store = {}; }),
    removeItem: vi.fn((key: string) => { delete store[key]; }),
    get length() { return Object.keys(store).length; },
    key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
  };
})();
Object.defineProperty(window, "localStorage", { value: localStorageMock });

describe("MLTrainingView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.mocked(api.getMLTrainingHistory).mockResolvedValue([]);
    vi.mocked(api.getMLDataReadiness).mockResolvedValue({
      "BTC-USDT-SWAP": { count: 8760, oldest: "2025-03-22T00:00:00Z", sufficient: true },
      "ETH-USDT-SWAP": { count: 500, oldest: "2025-06-01T00:00:00Z", sufficient: true },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  async function renderAndSettle() {
    let result: ReturnType<typeof render>;
    await act(async () => {
      result = render(<MLTrainingView />);
    });
    return result!;
  }

  describe("Initial State", () => {
    it("should render new tab structure (Setup, Training, Results, History)", async () => {
      await renderAndSettle();

      expect(screen.getByText("Setup")).toBeInTheDocument();
      expect(screen.getByText("Training")).toBeInTheDocument();
      expect(screen.getByText("Results")).toBeInTheDocument();
      expect(screen.getByText("History")).toBeInTheDocument();
    });

    it("should fetch data readiness on mount", async () => {
      await renderAndSettle();
      expect(api.getMLDataReadiness).toHaveBeenCalledWith("1h");
    });
  });

  describe("Setup Tab", () => {
    it("should render preset bar", async () => {
      await renderAndSettle();

      expect(screen.getByText("Quick Test")).toBeInTheDocument();
      expect(screen.getByText("Balanced")).toBeInTheDocument();
      expect(screen.getByText("Production")).toBeInTheDocument();
    });

    it("should render timeframe and advanced settings toggle", async () => {
      await renderAndSettle();

      expect(screen.getAllByText("Timeframe").length).toBeGreaterThan(0);
      expect(screen.getByText("Advanced Settings")).toBeInTheDocument();
    });

    it("should show confirmation dialog when Start Training is clicked", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("Start Training"));
      });

      expect(screen.getByText("Confirm Training")).toBeInTheDocument();
    });
  });

  describe("Training Tab", () => {
    it("should show empty state when no job is active", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("Training"));
      });

      expect(screen.getByText("No active training job")).toBeInTheDocument();
    });
  });

  describe("Results Tab", () => {
    it("should show empty state when no completed runs exist", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("Results"));
      });

      expect(screen.getByText("No training results yet")).toBeInTheDocument();
    });
  });

  describe("History Tab", () => {
    it("should display empty state when no history", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("History"));
      });

      expect(screen.getByText("No training history yet")).toBeInTheDocument();
    });

    it("should display job entries when history exists", async () => {
      const mockHistory = [
        {
          job_id: "test-job-1",
          status: "completed" as const,
          result: {
            "BTC-USDT": {
              best_epoch: 10, best_val_loss: 0.5, total_epochs: 100,
              total_samples: 1000, flow_data_used: false,
              direction_accuracy: 0.65,
            },
          },
          created_at: new Date().toISOString(),
          params: { timeframe: "1h", lookback_days: 365, epochs: 100 },
        },
      ];
      vi.mocked(api.getMLTrainingHistory).mockResolvedValue(mockHistory);

      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("History"));
      });

      expect(screen.getByText("test-job-1")).toBeInTheDocument();
      expect(screen.getByText("completed")).toBeInTheDocument();
    });

    it("should navigate to Results when View Details is clicked", async () => {
      const mockHistory = [
        {
          job_id: "test-job-1",
          status: "completed" as const,
          result: {
            "BTC-USDT": {
              best_epoch: 10, best_val_loss: 0.5, total_epochs: 100,
              total_samples: 1000, flow_data_used: false,
            },
          },
          created_at: new Date().toISOString(),
          params: { timeframe: "1h", lookback_days: 365, epochs: 100 },
        },
      ];
      vi.mocked(api.getMLTrainingHistory).mockResolvedValue(mockHistory);

      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("History"));
      });

      await act(async () => {
        fireEvent.click(screen.getByText("View Details"));
      });

      // Should now be on Results tab showing that run
      expect(screen.getByText("Run test-job-1")).toBeInTheDocument();
    });
  });
});
