import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "../api";

// Mock fetch using vitest
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("ML API Client", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("startMLTraining", () => {
    it("should call training endpoint with correct parameters", async () => {
      const mockResponse = { job_id: "test-job-123", status: "running" };
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const params = {
        timeframe: "1h",
        lookback_days: 365,
        epochs: 100,
      };

      const result = await api.startMLTraining(params);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/ml/train"),
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            "Content-Type": "application/json",
          }),
          body: JSON.stringify(params),
        })
      );
      expect(result).toEqual(mockResponse);
    });

    it("should throw error on non-200 response", async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        statusText: "Bad Request",
      } as Response);

      await expect(api.startMLTraining({})).rejects.toThrow("API");
    });
  });

  describe("getMLTrainingStatus", () => {
    it("should return training job status", async () => {
      const mockStatus = {
        job_id: "test-job-123",
        status: "running",
        progress: { "BTC-USDT": { epoch: 10, total_epochs: 100, train_loss: 0.5, val_loss: 0.6 } },
      };
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => mockStatus,
      } as Response);

      const result = await api.getMLTrainingStatus("test-job-123");

      expect(result).toEqual(mockStatus);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/ml/train/test-job-123"),
        expect.any(Object)
      );
    });
  });

  describe("cancelMLTraining", () => {
    it("should call cancel endpoint with POST method", async () => {
      const mockResponse = { job_id: "test-job-123", status: "cancelled" };
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const result = await api.cancelMLTraining("test-job-123");

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/ml/train/test-job-123/cancel"),
        expect.objectContaining({
          method: "POST",
        })
      );
      expect(result).toEqual(mockResponse);
    });
  });

  describe("getMLStatus", () => {
    it("should return ML status", async () => {
      const mockStatus = {
        ml_enabled: true,
        loaded_pairs: ["btc_usdt", "eth_usdt"],
      };
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => mockStatus,
      } as Response);

      const result = await api.getMLStatus();

      expect(result).toEqual(mockStatus);
    });
  });

  describe("startMLBackfill", () => {
    it("should call backfill endpoint with correct parameters", async () => {
      const mockResponse = { job_id: "backfill-job-123", status: "running" };
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => mockResponse,
      } as Response);

      const params = {
        timeframe: "1h",
        lookback_days: 365,
      };

      const result = await api.startMLBackfill(params);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/ml/backfill"),
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({
            "Content-Type": "application/json",
          }),
          body: JSON.stringify(params),
        })
      );
      expect(result).toEqual(mockResponse);
    });
  });

  describe("getMLBackfillStatus", () => {
    it("should return backfill job status", async () => {
      const mockStatus = {
        job_id: "backfill-job-123",
        status: "completed",
        result: { "BTC-USDT": 1000, "ETH-USDT": 800 },
      };
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => mockStatus,
      } as Response);

      const result = await api.getMLBackfillStatus("backfill-job-123");

      expect(result).toEqual(mockStatus);
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/ml/backfill/backfill-job-123"),
        expect.any(Object)
      );
    });
  });
});
