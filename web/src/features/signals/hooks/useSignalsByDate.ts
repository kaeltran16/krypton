import { useEffect, useState } from "react";
import { api } from "../../../shared/lib/api";
import type { Signal } from "../types";

export function useSignalsByDate(date: string | null) {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [prevKey, setPrevKey] = useState("");

  const key = `${date ?? ""}-${retryCount}`;
  if (key !== prevKey) {
    setPrevKey(key);
    if (date) {
      setSignals([]);
      setLoading(true);
      setError(false);
    } else {
      setSignals([]);
      setLoading(false);
      setError(false);
    }
  }

  useEffect(() => {
    if (!date) return;

    let cancelled = false;

    api.getSignalsByDate(date)
      .then((res) => {
        if (!cancelled) setSignals(res);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [date, retryCount]);

  const retry = () => setRetryCount((c) => c + 1);

  return { signals, loading, error, retry };
}
