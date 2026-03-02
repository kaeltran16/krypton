import { useEffect, useState, useCallback } from "react";
import { api, type AccountBalance, type Position } from "../../../shared/lib/api";

export function useAccount(pollInterval = 10000) {
  const [balance, setBalance] = useState<AccountBalance | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [bal, pos] = await Promise.all([api.getBalance(), api.getPositions()]);
      setBalance(bal);
      setPositions(pos);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch account");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, pollInterval);
    return () => clearInterval(id);
  }, [refresh, pollInterval]);

  return { balance, positions, loading, error, refresh };
}
