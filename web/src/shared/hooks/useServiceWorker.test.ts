import { vi, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useServiceWorker } from "./useServiceWorker";

let onNeedRefreshCb: (() => void) | undefined;
const mockUpdateSW = vi.fn(() => Promise.resolve());

vi.mock("virtual:pwa-register", () => ({
  registerSW: (opts: { onNeedRefresh?: () => void }) => {
    onNeedRefreshCb = opts.onNeedRefresh;
    return mockUpdateSW;
  },
}));

beforeEach(() => {
  onNeedRefreshCb = undefined;
  mockUpdateSW.mockClear();
});

it("starts with modal hidden", () => {
  const { result } = renderHook(() => useServiceWorker());
  expect(result.current.showUpdateModal).toBe(false);
});

it("shows modal when onNeedRefresh fires", () => {
  const { result } = renderHook(() => useServiceWorker());
  act(() => onNeedRefreshCb?.());
  expect(result.current.showUpdateModal).toBe(true);
});

it("hides modal after dismiss", () => {
  const { result } = renderHook(() => useServiceWorker());
  act(() => onNeedRefreshCb?.());
  act(() => result.current.dismiss());
  expect(result.current.showUpdateModal).toBe(false);
});

it("calls updateSW(true) on applyUpdate", () => {
  const { result } = renderHook(() => useServiceWorker());
  act(() => onNeedRefreshCb?.());
  act(() => result.current.applyUpdate());
  expect(mockUpdateSW).toHaveBeenCalledWith(true);
});
