import { useEffect, useState, useCallback } from "react";
import { api, type Portfolio } from "../../../shared/lib/api";
import { useDashboardStore } from "../store";

export function useAccount() {
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
  }, [refresh]);

  const wsPortfolio = useDashboardStore((s) => s.wsPortfolio);
  useEffect(() => {
    if (wsPortfolio) {
      setPortfolio(wsPortfolio);
      setError(null);
      setLoading(false);
    }
  }, [wsPortfolio]);

  // backward-compatible fields
  const balance = portfolio
    ? {
        total_equity: portfolio.total_equity,
        unrealized_pnl: portfolio.unrealized_pnl,
        currencies: [{ currency: "USDT", available: portfolio.available_balance, frozen: 0, equity: portfolio.total_equity }],
      }
    : null;

  return { portfolio, balance, positions: portfolio?.positions ?? [], loading, error, refresh };
}
