import { useState, useCallback, useEffect, useRef } from "react";
import { api } from "../../../shared/lib/api";
import type { PipelineEvaluation, MonitorSummary, MonitorFilters, MonitorPeriod } from "../types";

const PERIOD_HOURS: Record<MonitorPeriod, number> = {
  "1h": 1, "6h": 6, "24h": 24, "7d": 168,
};

export function useMonitorData() {
  const [filters, setFilters] = useState<MonitorFilters>({
    pair: null,
    emitted: null,
    period: "24h",
  });
  const [items, setItems] = useState<PipelineEvaluation[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<MonitorSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const offsetRef = useRef(0);

  const fetchData = useCallback(async (reset: boolean) => {
    const fromOffset = reset ? 0 : offsetRef.current;
    if (reset) setLoading(true);
    setError(null);

    const hours = PERIOD_HOURS[filters.period];
    const after = new Date(Date.now() - hours * 3600_000).toISOString();

    try {
      const [evalResult, summaryResult] = await Promise.all([
        api.getMonitorEvaluations({
          pair: filters.pair ?? undefined,
          emitted: filters.emitted ?? undefined,
          after,
          limit: 50,
          offset: fromOffset,
        }),
        reset ? api.getMonitorSummary(filters.period) : Promise.resolve(null),
      ]);

      if (reset) {
        setItems(evalResult.items);
        if (summaryResult) setSummary(summaryResult);
      } else {
        setItems((prev) => [...prev, ...evalResult.items]);
      }
      setTotal(evalResult.total);
      offsetRef.current = fromOffset + evalResult.items.length;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchData(true);
  }, [fetchData]);

  const refresh = useCallback(() => fetchData(true), [fetchData]);
  const loadMore = useCallback(() => fetchData(false), [fetchData]);

  const updateFilter = useCallback(<K extends keyof MonitorFilters>(key: K, value: MonitorFilters[K]) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }, []);

  const hasMore = items.length < total;

  return {
    filters, updateFilter,
    items, total, summary,
    loading, error,
    refresh, loadMore, hasMore,
  };
}
