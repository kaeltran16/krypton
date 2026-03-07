import { useEffect, useState, useCallback, useRef } from "react";
import { api, type CandleData } from "../../../shared/lib/api";
import type { Timeframe } from "../../signals/types";

const OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/business";
const OKX_REST_URL = "https://www.okx.com/api/v5/market/candles";

const TF_CHANNEL: Record<Timeframe, string> = {
  "15m": "candle15m",
  "1h": "candle1H",
  "4h": "candle4H",
};

const TF_BAR: Record<Timeframe, string> = {
  "15m": "15m",
  "1h": "1H",
  "4h": "4H",
};

const MIN_CANDLES = 60;

async function fetchOkxCandles(pair: string, timeframe: Timeframe): Promise<CandleData[]> {
  const bar = TF_BAR[timeframe];
  const res = await fetch(`${OKX_REST_URL}?instId=${pair}&bar=${bar}&limit=100`);
  if (!res.ok) return [];
  const json = await res.json();
  if (!json.data || !Array.isArray(json.data)) return [];
  return json.data
    .map((raw: string[]) => parseOkxCandle(raw))
    .sort((a: CandleData, b: CandleData) => a.timestamp - b.timestamp);
}

function parseOkxCandle(raw: string[]): CandleData {
  return {
    timestamp: Number(raw[0]),
    open: Number(raw[1]),
    high: Number(raw[2]),
    low: Number(raw[3]),
    close: Number(raw[4]),
    volume: Number(raw[5]),
  };
}

export function useChartData(pair: string, timeframe: Timeframe) {
  const [candles, setCandles] = useState<CandleData[]>([]);
  const [loading, setLoading] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);

  const fetchCandles = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getCandles(pair, timeframe);
      if (data.length >= MIN_CANDLES) {
        setCandles(data);
      } else {
        const okxData = await fetchOkxCandles(pair, timeframe as Timeframe);
        setCandles(okxData.length > data.length ? okxData : data);
      }
    } catch {
      try {
        const okxData = await fetchOkxCandles(pair, timeframe as Timeframe);
        setCandles(okxData);
      } catch {
        setCandles([]);
      }
    } finally {
      setLoading(false);
    }
  }, [pair, timeframe]);

  useEffect(() => {
    fetchCandles();
  }, [fetchCandles]);

  useEffect(() => {
    const channel = TF_CHANNEL[timeframe];
    if (!channel) return;

    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let shouldReconnect = true;

    function connect() {
      ws = new WebSocket(OKX_WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({
          op: "subscribe",
          args: [{ channel, instId: pair }],
        }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (!msg.data || !Array.isArray(msg.data)) return;

          for (const raw of msg.data) {
            const candle = parseOkxCandle(raw);
            const confirmed = raw[8] === "1";

            setCandles((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              const lastTs = typeof last?.timestamp === "number"
                ? last.timestamp
                : new Date(last?.timestamp as any).getTime();

              if (last && lastTs === candle.timestamp) {
                updated[updated.length - 1] = candle;
              } else if (confirmed || (last && candle.timestamp > lastTs)) {
                updated.push(candle);
              }
              return updated;
            });
          }
        } catch { /* ignore malformed */ }
      };

      ws.onclose = () => {
        if (shouldReconnect) {
          reconnectTimer = setTimeout(connect, 2000);
        }
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      shouldReconnect = false;
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [pair, timeframe]);

  return { candles, loading };
}
