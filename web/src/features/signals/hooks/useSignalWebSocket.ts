import { useEffect, useRef } from "react";
import { WebSocketManager } from "../../../shared/lib/websocket";
import { WS_BASE_URL } from "../../../shared/lib/constants";
import { getWsToken } from "../../auth/hooks/useAuth";
import { useSignalStore } from "../store";
import { useSettingsStore } from "../../settings/store";
import { useNewsStore } from "../../news/store";
import { useAlertStore } from "../../alerts/store";
import { useEngineStore } from "../../engine/store";
import { api } from "../../../shared/lib/api";
import { hapticPulse } from "../../../shared/lib/haptics";

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

    const token = getWsToken();
    const params = new URLSearchParams();
    if (token) params.set("token", token);
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
        hapticPulse();
      } else if (data.type === "candle" && data.candle) {
        useSignalStore.getState().notifyCandleListeners(data.candle);
      } else if (data.type === "news_alert" && data.news) {
        useNewsStore.getState().addAlert(data.news);
      } else if (data.type === "alert_triggered") {
        useAlertStore.getState().addTriggeredAlert(data);
      } else if (data.type === "pipeline_scores" && data.scores) {
        useEngineStore.getState().pushScores(data.scores);
      }
    };

    ws.connect();
    return () => ws.disconnect();
  }, [pairsKey, timeframesKey]);

  return wsRef;
}
