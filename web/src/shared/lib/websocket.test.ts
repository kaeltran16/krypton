import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { WebSocketManager } from "./websocket";

let mockInstances: any[];

beforeEach(() => {
  mockInstances = [];
  vi.useFakeTimers();

  vi.stubGlobal(
    "WebSocket",
    class MockWebSocket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;

      readyState = 0;
      onopen: (() => void) | null = null;
      onclose: (() => void) | null = null;
      onmessage: ((e: any) => void) | null = null;
      onerror: (() => void) | null = null;
      url: string;
      send = vi.fn();
      close = vi.fn();

      constructor(url: string) {
        this.url = url;
        mockInstances.push(this);
      }
    },
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("WebSocketManager", () => {
  it("connects and fires onConnected", () => {
    const ws = new WebSocketManager("ws://test");
    const onConnected = vi.fn();
    ws.onConnected = onConnected;
    ws.connect();

    mockInstances[0].readyState = 1;
    mockInstances[0].onopen!();

    expect(onConnected).toHaveBeenCalledOnce();
  });

  it("parses JSON messages and fires onMessage", () => {
    const ws = new WebSocketManager("ws://test");
    const onMessage = vi.fn();
    ws.onMessage = onMessage;
    ws.connect();

    const data = { type: "signal", pair: "BTC" };
    mockInstances[0].onmessage!({ data: JSON.stringify(data) });

    expect(onMessage).toHaveBeenCalledWith(data);
  });

  it("ignores malformed messages", () => {
    const ws = new WebSocketManager("ws://test");
    const onMessage = vi.fn();
    ws.onMessage = onMessage;
    ws.connect();

    mockInstances[0].onmessage!({ data: "not-json{" });

    expect(onMessage).not.toHaveBeenCalled();
  });

  it("reconnects with exponential backoff after close", () => {
    const ws = new WebSocketManager("ws://test");
    ws.connect();
    expect(mockInstances).toHaveLength(1);

    mockInstances[0].onclose!();
    vi.advanceTimersByTime(1000);
    expect(mockInstances).toHaveLength(2);

    mockInstances[1].onclose!();
    vi.advanceTimersByTime(2000);
    expect(mockInstances).toHaveLength(3);
  });

  it("does not reconnect after disconnect()", () => {
    const ws = new WebSocketManager("ws://test");
    ws.connect();

    ws.disconnect();
    mockInstances[0].onclose?.();
    vi.advanceTimersByTime(5000);

    expect(mockInstances).toHaveLength(1);
  });

  it("resets backoff delay after successful connection", () => {
    const ws = new WebSocketManager("ws://test");
    ws.connect();

    mockInstances[0].onclose!();
    vi.advanceTimersByTime(1000);
    mockInstances[1].readyState = 1;
    mockInstances[1].onopen!();

    mockInstances[1].onclose!();
    vi.advanceTimersByTime(1000);
    expect(mockInstances).toHaveLength(3);
  });

  it("sends data when connected", () => {
    const ws = new WebSocketManager("ws://test");
    ws.connect();
    mockInstances[0].readyState = 1;

    ws.send('{"type":"subscribe"}');

    expect(mockInstances[0].send).toHaveBeenCalledWith('{"type":"subscribe"}');
  });

  it("silently drops send when not connected", () => {
    const ws = new WebSocketManager("ws://test");
    ws.connect();

    ws.send('{"type":"subscribe"}');

    expect(mockInstances[0].send).not.toHaveBeenCalled();
  });
});
