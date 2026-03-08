import { useEffect, useState, useCallback } from "react";
import { api, type Portfolio, type Position } from "../../../shared/lib/api";

export function useAccount(pollInterval = 10000) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.getPortfolio();
      setPortfolio(data);
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

  // Backward-compatible fields
  const balance = portfolio
    ? {
        total_equity: portfolio.total_equity,
        unrealized_pnl: portfolio.unrealized_pnl,
        currencies: [{ currency: "USDT", available: portfolio.available_balance, frozen: 0, equity: portfolio.total_equity }],
      }
    : null;

  return { portfolio, balance, positions: portfolio?.positions ?? [], loading, error, refresh };
}
