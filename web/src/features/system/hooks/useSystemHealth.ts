import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "../../../shared/lib/api";
import type { SystemHealthResponse } from "../types";

export function useSystemHealth() {
  const [data, setData] = useState<SystemHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const fetchedAtRef = useRef<number>(0);

  const fetchHealth = useCallback(async (isRefresh: boolean) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const result = await api.getSystemHealth();
      setData(result);
      fetchedAtRef.current = Date.now();
      setElapsed(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth(false);
  }, [fetchHealth]);

  useEffect(() => {
    const id = setInterval(() => {
      if (fetchedAtRef.current > 0) {
        setElapsed(Math.floor((Date.now() - fetchedAtRef.current) / 1000));
      }
    }, 5000);
    return () => clearInterval(id);
  }, []);

  const refresh = useCallback(() => fetchHealth(true), [fetchHealth]);

  return { data, loading, refreshing, error, refresh, elapsed };
}
