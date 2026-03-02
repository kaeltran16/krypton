import { useEffect, useState, useCallback } from "react";
import { api, type CandleData } from "../../../shared/lib/api";
import { useSignalStore } from "../../signals/store";
import type { Timeframe } from "../../signals/types";

export function useChartData(pair: string, timeframe: Timeframe) {
  const [candles, setCandles] = useState<CandleData[]>([]);
  const [loading, setLoading] = useState(true);
  const addCandleListener = useSignalStore((s) => s.addCandleListener);
  const removeCandleListener = useSignalStore((s) => s.removeCandleListener);

  const fetchCandles = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getCandles(pair, timeframe);
      setCandles(data);
    } catch {
      setCandles([]);
    } finally {
      setLoading(false);
    }
  }, [pair, timeframe]);

  useEffect(() => {
    fetchCandles();
  }, [fetchCandles]);

  useEffect(() => {
    const handler = (candle: any) => {
      if (candle.pair !== pair || candle.timeframe !== timeframe) return;
      setCandles((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last && last.timestamp === candle.timestamp) {
          updated[updated.length - 1] = candle;
        } else if (candle.confirmed) {
          updated.push(candle);
        } else if (last && candle.timestamp > last.timestamp) {
          updated.push(candle);
        }
        return updated;
      });
    };
    addCandleListener(handler);
    return () => removeCandleListener(handler);
  }, [pair, timeframe, addCandleListener, removeCandleListener]);

  return { candles, loading };
}
