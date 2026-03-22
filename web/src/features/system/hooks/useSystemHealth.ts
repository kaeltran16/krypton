import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "../../../shared/lib/api";
import type { SystemHealthResponse } from "../types";

export function useSystemHealth() {
  const [data, setData] = useState<SystemHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchedAtRef = useRef<number>(0);
  const [tick, setTick] = useState(0);

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
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Fetch on mount
  useEffect(() => {
    fetchHealth(false);
  }, [fetchHealth]);

  // Tick every 5s to keep relative times accurate
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 5000);
    return () => clearInterval(id);
  }, []);

  // Compute elapsed seconds since last fetch
  const elapsed = fetchedAtRef.current > 0
    ? Math.floor((Date.now() - fetchedAtRef.current) / 1000)
    : 0;

  // Force re-read of elapsed on each tick
  void tick;

  const refresh = useCallback(() => fetchHealth(true), [fetchHealth]);

  return { data, loading, refreshing, error, refresh, elapsed };
}
