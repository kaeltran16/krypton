import { useEffect, useRef } from "react";
import { WebSocketManager } from "../../../shared/lib/websocket";
import { WS_BASE_URL, API_KEY } from "../../../shared/lib/constants";
import { useSignalStore } from "../store";
import { useSettingsStore } from "../../settings/store";
import { useNewsStore } from "../../news/store";
import { api } from "../../../shared/lib/api";

export function useSignalWebSocket() {
  const pairs = useSettingsStore((s) => s.pairs);
  const timeframes = useSettingsStore((s) => s.timeframes);
  const threshold = useSettingsStore((s) => s.threshold);
  const wsRef = useRef<WebSocketManager | null>(null);
  const thresholdRef = useRef(threshold);
  thresholdRef.current = threshold;

  const pairsKey = JSON.stringify(pairs);
  const timeframesKey = JSON.stringify(timeframes);

  useEffect(() => {
    const currentPairs = JSON.parse(pairsKey);
    const currentTimeframes = JSON.parse(timeframesKey);

    // load existing signals from the database
    api.getSignals({ limit: 50 }).then((signals) => {
      useSignalStore.getState().setSignals(signals);
    }).catch(() => {});

    const params = new URLSearchParams();
    if (API_KEY) params.set("api_key", API_KEY);
    const qs = params.toString();

    const ws = new WebSocketManager(
      `${WS_BASE_URL}/ws/signals${qs ? `?${qs}` : ""}`,
    );
    wsRef.current = ws;

    ws.onConnected = () => {
      useSignalStore.getState().setConnected(true);
      ws.send(JSON.stringify({ type: "subscribe", pairs: currentPairs, timeframes: currentTimeframes }));
    };

    ws.onDisconnected = () => useSignalStore.getState().setConnected(false);

    ws.onMessage = (data: any) => {
      if (
        data.type === "signal" &&
        Math.abs(data.signal.final_score) >= thresholdRef.current
      ) {
        useSignalStore.getState().addSignal(data.signal);
      } else if (data.type === "candle" && data.candle) {
        useSignalStore.getState().notifyCandleListeners(data.candle);
      } else if (data.type === "news_alert" && data.news) {
        useNewsStore.getState().addAlert(data.news);
      }
    };

    ws.connect();
    return () => ws.disconnect();
  }, [pairsKey, timeframesKey]);

  return wsRef;
}
