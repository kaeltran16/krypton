import { useEffect, useState } from "react";
import { api } from "../../../shared/lib/api";
import type { SignalStats } from "../../signals/types";

export function useSignalStats(days: number | null = 7) {
  const [stats, setStats] = useState<SignalStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (days == null) {
      setLoading(false);
      return;
    }
    setLoading(true);
    let cancelled = false;
    async function fetch() {
      try {
        const data = await api.getSignalStats(days!);
        if (!cancelled) setStats(data);
      } catch {
        // silently fail
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetch();
    const id = setInterval(fetch, 60000); // refresh every minute
    return () => { cancelled = true; clearInterval(id); };
  }, [days]);

  return { stats, loading };
}
