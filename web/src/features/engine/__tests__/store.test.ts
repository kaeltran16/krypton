import { describe, it, expect, vi, beforeEach } from "vitest";
import { useEngineStore } from "../store";

vi.mock("../../../shared/lib/api", () => ({
  api: {
    getEngineParameters: vi.fn(),
  },
}));

import { api } from "../../../shared/lib/api";
const mockApi = api as unknown as { getEngineParameters: ReturnType<typeof vi.fn> };

describe("useEngineStore", () => {
  beforeEach(() => {
    useEngineStore.setState({ params: null, loading: false, error: null });
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
});
