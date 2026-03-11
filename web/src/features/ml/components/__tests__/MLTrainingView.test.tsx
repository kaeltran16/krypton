import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { MLTrainingView } from "../MLTrainingView";
import { api } from "../../../../shared/lib/api";

vi.mock("../../../../shared/lib/api", () => ({
  api: {
    getMLStatus: vi.fn(),
    startMLTraining: vi.fn(),
    getMLTrainingStatus: vi.fn(),
    cancelMLTraining: vi.fn(),
    startMLBackfill: vi.fn(),
    getMLBackfillStatus: vi.fn(),
  },
}));

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
    vi.mocked(api.getMLStatus).mockResolvedValue({ ml_enabled: true, loaded_pairs: [] });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  async function renderAndSettle(props = {}) {
    let result: ReturnType<typeof render>;
    await act(async () => {
      result = render(<MLTrainingView onBack={() => {}} {...props} />);
    });
    return result!;
  }

  describe("Initial State", () => {
    it("should render all tabs", async () => {
      await renderAndSettle();

      expect(screen.getByText("Configure")).toBeInTheDocument();
      expect(screen.getByText("Training")).toBeInTheDocument();
      expect(screen.getByText("History")).toBeInTheDocument();
      expect(screen.getByText("Backfill")).toBeInTheDocument();
    });

    it("should load ML status on mount", async () => {
      await renderAndSettle();

      expect(api.getMLStatus).toHaveBeenCalledOnce();
    });

    it("should call onBack when back button is clicked", async () => {
      const onBack = vi.fn();
      await act(async () => {
        render(<MLTrainingView onBack={onBack} />);
      });

      fireEvent.click(screen.getByText("Back"));

      expect(onBack).toHaveBeenCalledOnce();
    });
  });

  describe("Configure Tab", () => {
    it("should render configuration form with default values", async () => {
      await renderAndSettle();

      expect(screen.getByText("Timeframe")).toBeInTheDocument();
      expect(screen.getByText("Lookback Days")).toBeInTheDocument();
      expect(screen.getByText("Epochs")).toBeInTheDocument();
    });

    it("should show confirmation dialog when start training is clicked", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("Start Training"));
      });

      expect(screen.getByText("Confirm Training")).toBeInTheDocument();
    });

    it("should reset to defaults when reset button is clicked", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("Reset to Defaults"));
      });

      expect(screen.getByText("1h")).toBeInTheDocument();
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

  describe("History Tab", () => {
    it("should display empty state when no history", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("History"));
      });

      expect(screen.getByText("No training history yet")).toBeInTheDocument();
    });

    it("should display job cards when history exists", async () => {
      const mockHistory = [
        {
          job_id: "test-job-1",
          status: "completed",
          result: { "BTC-USDT": { best_epoch: 10, best_val_loss: 0.5, total_epochs: 100, total_samples: 1000, flow_data_used: false } },
          created_at: new Date().toISOString(),
          params: { timeframe: "1h", lookback_days: 365 },
        },
      ];
      localStorageMock.getItem.mockReturnValue(JSON.stringify(mockHistory));

      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("History"));
      });

      expect(screen.getByText("test-job-1")).toBeInTheDocument();
      expect(screen.getByText("completed")).toBeInTheDocument();
    });
  });

  describe("Backfill Tab", () => {
    it("should render backfill form", async () => {
      await renderAndSettle();

      await act(async () => {
        fireEvent.click(screen.getByText("Backfill"));
      });

      expect(screen.getByText("Backfill Settings")).toBeInTheDocument();
      expect(screen.getByText("Start Backfill")).toBeInTheDocument();
    });
  });
});
