import { useEffect, useRef } from "react";
import { WebSocketManager } from "../../../shared/lib/websocket";
import { WS_BASE_URL } from "../../../shared/lib/constants";
import { useSignalStore } from "../store";
import { useSettingsStore } from "../../settings/store";
import { useNewsStore } from "../../news/store";
import { useAlertStore } from "../../alerts/store";
import { useEngineStore } from "../../engine/store";
import { useBacktestStore } from "../../backtest/store";
import { useDashboardStore } from "../../dashboard/store";
import { useHomeStore } from "../../home/store";
import { useMLStore } from "../../ml/store";
import { api } from "../../../shared/lib/api";
import { hapticPulse } from "../../../shared/lib/haptics";
import { useAgentStore } from "../../agent/store";

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

    api.getSignals({ limit: 50 }).then((signals) => {
      useSignalStore.getState().setSignals(signals);
    }).catch(() => {});

    const ws = new WebSocketManager(`${WS_BASE_URL}/ws/signals`);
    wsRef.current = ws;

    ws.onConnected = async () => {
      try {
        const { token } = await api.getWSToken();
        ws.send(JSON.stringify({ type: "auth", token }));
      } catch {
        // auth failed — WS will be closed by server after timeout
        return;
      }
      ws.send(JSON.stringify({ type: "subscribe", pairs: currentPairs, timeframes: currentTimeframes }));
      useSignalStore.getState().setConnected(true);
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
      } else if (data.type === "backtest_update") {
        const { type, ...run } = data;
        useBacktestStore.getState().onBacktestUpdate(run);
      } else if (data.type === "import_update") {
        const { type, ...status } = data;
        useBacktestStore.getState().onImportUpdate(status);
      } else if (data.type === "account_update") {
        const { type, ...portfolio } = data;
        useDashboardStore.getState().onAccountUpdate(portfolio);
      } else if (data.type === "stats_update") {
        const { type, ...stats } = data;
        useHomeStore.getState().onStatsUpdate(stats);
      } else if (data.type === "backfill_update") {
        const { type, ...status } = data;
        useMLStore.getState().onBackfillUpdate(status);
      } else if (data.type === "agent_analysis" && data.data) {
        useAgentStore.getState().addAnalysis(data.data);
      }
    };

    ws.connect();
    return () => ws.disconnect();
  }, [pairsKey, timeframesKey]);

  return wsRef;
}
