import { useEffect, useRef, useState } from "react";

import { api, type CandleData } from "../../../shared/lib/api";

const OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/business";

const TF_MAP: Record<string, string> = {
  "15m": "candle15m",
  "1h": "candle1H",
  "4h": "candle4H",
  "1D": "candle1D",
};

const TF_BAR: Record<string, string> = {
  "15m": "15m",
  "1h": "1H",
  "4h": "4H",
  "1D": "1D",
};

export type TickCallback = (candle: CandleData) => void;

function parseOkxCandle(raw: string[]): CandleData {
  return {
    timestamp: Math.floor(Number(raw[0]) / 1000),
    open: Number(raw[1]),
    high: Number(raw[2]),
    low: Number(raw[3]),
    close: Number(raw[4]),
    volume: Number(raw[5]),
  };
}

export function useChartData(pair: string, timeframe: string) {
  const [candles, setCandles] = useState<CandleData[]>([]);
  const [loading, setLoading] = useState(true);
  const onTickRef = useRef<TickCallback | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    async function loadInitial() {
      setLoading(true);
      try {
        const bar = TF_BAR[timeframe] ?? timeframe;
        const response = await fetch(
          `https://www.okx.com/api/v5/market/candles?instId=${pair}&bar=${bar}&limit=200`,
        );
        const payload = await response.json();
        if (!cancelled && Array.isArray(payload.data)) {
          setCandles(payload.data.map(parseOkxCandle).reverse());
          return;
        }
      } catch {
        // fall through to backend cache
      }

      try {
        const data = await api.getCandles(pair, timeframe);
        if (!cancelled) {
          setCandles(data);
        }
      } catch {
        if (!cancelled) {
          setCandles([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    function connectWs() {
      const channel = TF_MAP[timeframe];
      if (!channel) return;

      const ws = new WebSocket(OKX_WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ op: "subscribe", args: [{ channel, instId: pair }] }));
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          const raw = message.data?.[0];
          if (!raw) return;

          const candle = parseOkxCandle(raw);
          onTickRef.current?.(candle);

          if (raw[8] === "1") {
            setCandles((prev) => {
              const last = prev[prev.length - 1];
              if (last && last.timestamp === candle.timestamp) {
                return [...prev.slice(0, -1), candle];
              }
              return [...prev, candle].slice(-200);
            });
          }
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (!cancelled) {
          reconnectTimer = setTimeout(connectWs, 3000);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    void loadInitial().then(connectWs);

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [pair, timeframe]);

  return { candles, loading, onTickRef };
}
