import { useEffect } from "react";

import { api } from "../../../shared/lib/api";
import { useAgentStore } from "../store";

export function useAgentAnalysis() {
  const analyses = useAgentStore((state) => state.analyses);
  const loading = useAgentStore((state) => state.loading);
  const setAnalyses = useAgentStore((state) => state.setAnalyses);
  const setLoading = useAgentStore((state) => state.setLoading);
  const selected = useAgentStore((state) => state.getSelected());
  const latest = useAgentStore((state) => state.getLatest());

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const data = await api.getAgentAnalyses({ limit: 10 });
        if (!cancelled) {
          setAnalyses(data);
        }
      } catch {
        if (!cancelled) {
          setAnalyses([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [setAnalyses, setLoading]);

  return { analyses, loading, selected, latest };
}
