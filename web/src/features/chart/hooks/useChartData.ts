import { useEffect, useState, useCallback, useRef } from "react";
import { api, type CandleData } from "../../../shared/lib/api";

type ChartTimeframe = "15m" | "1h" | "4h" | "1D";

const OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/business";
const OKX_REST_URL = "https://www.okx.com/api/v5/market/candles";

const TF_CHANNEL: Record<ChartTimeframe, string> = {
  "15m": "candle15m",
  "1h": "candle1H",
  "4h": "candle4H",
  "1D": "candle1D",
};

const TF_BAR: Record<ChartTimeframe, string> = {
  "15m": "15m",
  "1h": "1H",
  "4h": "4H",
  "1D": "1D",
};

async function fetchOkxCandles(pair: string, timeframe: ChartTimeframe): Promise<CandleData[]> {
  const bar = TF_BAR[timeframe];
  const res = await fetch(`${OKX_REST_URL}?instId=${pair}&bar=${bar}&limit=200`);
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

export type TickCallback = (candle: CandleData) => void;

export function useChartData(pair: string, timeframe: ChartTimeframe) {
  const [candles, setCandles] = useState<CandleData[]>([]);
  const [loading, setLoading] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);
  /** Called on every WS tick — chart component registers a handler to update series directly */
  const onTickRef = useRef<TickCallback | null>(null);

  const fetchCandles = useCallback(async () => {
    setLoading(true);
    try {
      // Fetch from OKX REST for freshest data (up to 200 candles)
      const okxData = await fetchOkxCandles(pair, timeframe);
      if (okxData.length > 0) {
        setCandles(okxData);
      } else {
        // Fall back to backend Redis cache
        const raw = await api.getCandles(pair, timeframe);
        setCandles(raw.map((c) => ({
          ...c,
          timestamp: typeof c.timestamp === "number" ? c.timestamp : new Date(c.timestamp as any).getTime(),
        })));
      }
    } catch {
      try {
        const raw = await api.getCandles(pair, timeframe);
        setCandles(raw.map((c) => ({
          ...c,
          timestamp: typeof c.timestamp === "number" ? c.timestamp : new Date(c.timestamp as any).getTime(),
        })));
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

            // Direct chart update on every tick — bypasses React render
            onTickRef.current?.(candle);

            // React state only updates on confirmed candles (triggers indicator recalc)
            if (confirmed) {
              setCandles((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                const lastTs = typeof last?.timestamp === "number"
                  ? last.timestamp
                  : new Date(last?.timestamp as any).getTime();

                if (last && lastTs === candle.timestamp) {
                  updated[updated.length - 1] = candle;
                } else if (candle.timestamp > lastTs) {
                  updated.push(candle);
                }
                return updated;
              });
            }
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

  return { candles, loading, onTickRef };
}
