import { useEffect, useState, useRef } from "react";

const OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public";

interface TickerData {
  price: number | null;
  change24h: number | null;
  open24h: number | null;
  high24h: number | null;
  low24h: number | null;
  vol24h: number | null;
}

export function useLivePrice(pair: string): TickerData {
  const [data, setData] = useState<TickerData>({
    price: null, change24h: null, open24h: null,
    high24h: null, low24h: null, vol24h: null,
  });
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let ws: WebSocket;
    let shouldReconnect = true;
    let timer: ReturnType<typeof setTimeout>;

    function connect() {
      ws = new WebSocket(OKX_WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({
          op: "subscribe",
          args: [{ channel: "tickers", instId: pair }],
        }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.data?.[0]) {
            const d = msg.data[0];
            const last = Number(d.last);
            const open = d.open24h ? Number(d.open24h) : null;
            setData({
              price: last,
              change24h: open ? ((last - open) / open) * 100 : null,
              open24h: open,
              high24h: d.high24h ? Number(d.high24h) : null,
              low24h: d.low24h ? Number(d.low24h) : null,
              vol24h: d.vol24h ? Number(d.vol24h) : null,
            });
          }
        } catch { /* ignore */ }
      };

      ws.onclose = () => {
        if (shouldReconnect) timer = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      shouldReconnect = false;
      clearTimeout(timer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [pair]);

  return data;
}
