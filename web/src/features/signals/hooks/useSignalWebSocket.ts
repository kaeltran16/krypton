import { useEffect, useRef } from "react";
import { WebSocketManager } from "../../../shared/lib/websocket";
import { WS_BASE_URL, API_KEY } from "../../../shared/lib/constants";
import { useSignalStore } from "../store";
import { useSettingsStore } from "../../settings/store";

export function useSignalWebSocket() {
  const { addSignal, setConnected } = useSignalStore();
  const { pairs, timeframes, threshold } = useSettingsStore();
  const wsRef = useRef<WebSocketManager | null>(null);
  const thresholdRef = useRef(threshold);
  thresholdRef.current = threshold;

  useEffect(() => {
    const params = new URLSearchParams();
    if (API_KEY) params.set("api_key", API_KEY);
    const qs = params.toString();

    const ws = new WebSocketManager(
      `${WS_BASE_URL}/ws/signals${qs ? `?${qs}` : ""}`,
    );
    wsRef.current = ws;

    ws.onConnected = () => {
      setConnected(true);
      ws.send(JSON.stringify({ type: "subscribe", pairs, timeframes }));
    };

    ws.onDisconnected = () => setConnected(false);

    ws.onMessage = (data: any) => {
      if (
        data.type === "signal" &&
        Math.abs(data.signal.final_score) >= thresholdRef.current
      ) {
        addSignal(data.signal);
      }
    };

    ws.connect();
    return () => ws.disconnect();
  }, [pairs, timeframes, addSignal, setConnected]);

  return wsRef;
}
