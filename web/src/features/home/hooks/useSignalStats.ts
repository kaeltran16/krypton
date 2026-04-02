import { useEffect, useState } from "react";
import { api } from "../../../shared/lib/api";
import type { SignalStats } from "../../signals/types";
import { useHomeStore } from "../store";

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
    api.getSignalStats(days).then((data) => {
      if (!cancelled) {
        setStats(data);
        setLoading(false);
      }
    }).catch(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [days]);

  const wsStats = useHomeStore((s) => s.wsStats);
  useEffect(() => {
    if (wsStats) {
      setStats(wsStats);
      setLoading(false);
    }
  }, [wsStats]);

  return { stats, loading };
}
