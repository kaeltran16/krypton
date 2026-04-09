import { lazy, Suspense, useCallback, useEffect, useState } from "react";

import { useLivePrice } from "../../../shared/hooks/useLivePrice";
import { formatPricePrecision } from "../../../shared/lib/format";
import { api } from "../../../shared/lib/api";
import { useAgentAnalysis } from "../hooks/useAgentAnalysis";
import { useChartData } from "../hooks/useChartData";
import { useAgentStore } from "../store";
import { NarrativePanel } from "./NarrativePanel";

const AgentChart = lazy(() =>
  import("./AgentChart").then((module) => ({ default: module.AgentChart })),
);

const TIMEFRAMES = ["15m", "1h", "4h", "1D"] as const;

interface Props {
  pair: string;
}

function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(window.innerWidth >= 1024);

  useEffect(() => {
    const handleResize = () => setIsDesktop(window.innerWidth >= 1024);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return isDesktop;
}

export function AgentView({ pair }: Props) {
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]>("1h");
  const { candles, loading: candlesLoading, onTickRef } = useChartData(pair, timeframe);
  const { selected } = useAgentAnalysis();
  const { price, change24h } = useLivePrice(pair);
  const isDesktop = useIsDesktop();
  const setAnalyses = useAgentStore((state) => state.setAnalyses);
  const setLoading = useAgentStore((state) => state.setLoading);

  const handleRefresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getAgentAnalyses({ limit: 10 });
      setAnalyses(data);
    } catch {
      // ignore refresh failures
    } finally {
      setLoading(false);
    }
  }, [setAnalyses, setLoading]);

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col bg-surface">
      <div className="flex items-center gap-3 border-b border-white/5 px-4 py-2">
        <span className="text-sm font-medium text-white/90">{pair.replace("-SWAP", "")}</span>
        {price !== null ? (
          <span className="text-sm text-white/70">{formatPricePrecision(price, pair)}</span>
        ) : null}
        {change24h !== null ? (
          <span className={`text-xs ${change24h >= 0 ? "text-long" : "text-short"}`}>
            {change24h >= 0 ? "+" : ""}
            {change24h.toFixed(2)}%
          </span>
        ) : null}
        <div className="ml-auto flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              className={`rounded px-2 py-0.5 text-xs transition-colors ${
                timeframe === tf
                  ? "bg-accent/20 text-accent"
                  : "text-white/40 hover:text-white/60"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {isDesktop ? (
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div className="relative w-[70%] border-r border-white/5">
            {candlesLoading ? (
              <div className="absolute right-3 top-3 z-10 flex items-center gap-1.5 rounded bg-surface/90 px-2 py-1">
                <div className="h-3 w-3 animate-spin rounded-full border border-white/20 border-t-accent" />
                <span className="text-[10px] text-white/40">Loading</span>
              </div>
            ) : null}
            <Suspense
              fallback={
                <div className="flex h-full items-center justify-center">
                  <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-accent" />
                </div>
              }
            >
              <AgentChart candles={candles} pair={pair} analysis={selected} onTickRef={onTickRef} />
            </Suspense>
          </div>
          <div className="w-[30%]">
            <NarrativePanel onRefresh={handleRefresh} />
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-hidden">
          <NarrativePanel onRefresh={handleRefresh} />
        </div>
      )}
    </div>
  );
}
