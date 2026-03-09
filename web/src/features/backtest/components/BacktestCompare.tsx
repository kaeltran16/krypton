import { useEffect, useRef } from "react";
import {
  createChart,
  LineSeries,
  ColorType,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useBacktestStore } from "../store";
import type { BacktestRun, BacktestStats } from "../types";

const CURVE_COLORS = ["#F0B90B", "#0ECB81", "#F6465D", "#3B82F6"];

function formatDuration(minutes: number | null | undefined): string {
  if (minutes == null) return "—";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

const METRIC_ROWS: { label: string; key: keyof BacktestStats; format: (v: any) => string; higherBetter: boolean }[] = [
  { label: "Total Trades", key: "total_trades", format: (v) => String(v), higherBetter: true },
  { label: "Win Rate", key: "win_rate", format: (v) => `${v.toFixed(1)}%`, higherBetter: true },
  { label: "Net P&L", key: "net_pnl", format: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`, higherBetter: true },
  { label: "Avg P&L", key: "avg_pnl", format: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`, higherBetter: true },
  { label: "Avg R:R", key: "avg_rr", format: (v) => v.toFixed(2), higherBetter: true },
  { label: "Max Drawdown", key: "max_drawdown", format: (v) => `${v.toFixed(2)}%`, higherBetter: false },
  { label: "Profit Factor", key: "profit_factor", format: (v) => v != null ? v.toFixed(2) : "—", higherBetter: true },
  { label: "Sharpe Ratio", key: "sharpe_ratio", format: (v) => v != null ? v.toFixed(2) : "—", higherBetter: true },
  { label: "Sortino Ratio", key: "sortino_ratio", format: (v) => v != null ? v.toFixed(2) : "—", higherBetter: true },
  { label: "Avg Duration", key: "avg_duration_minutes", format: (v) => formatDuration(v), higherBetter: false },
];

export function BacktestCompare() {
  const { runs, fetchRuns, compareIds, toggleCompareId, compareResult, compareLoading, runCompare, setTab, loadRunDetail } = useBacktestStore();

  useEffect(() => {
    fetchRuns();
  }, []);

  const completedRuns = runs.filter((r) => r.status === "completed");

  if (completedRuns.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted">
        <p className="text-sm">No saved runs yet.</p>
        <p className="text-xs text-dim mt-1">Run a backtest and save it to start comparing.</p>
        <button
          onClick={() => setTab("setup")}
          className="mt-3 px-4 py-2 rounded-lg text-sm bg-card-hover text-foreground border border-border"
        >
          Run a Backtest
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Run selection */}
      <div>
        <h3 className="text-[10px] text-dim font-medium uppercase tracking-wider mb-1.5 px-1">Select Runs to Compare</h3>
        <div className="bg-card rounded-lg border border-border divide-y divide-border">
          {completedRuns.map((run) => (
            <label
              key={run.id}
              className="flex items-center gap-3 px-3 py-2.5 hover:bg-card-hover transition-colors cursor-pointer"
            >
              <input
                type="checkbox"
                checked={compareIds.includes(run.id)}
                onChange={() => toggleCompareId(run.id)}
                className="accent-accent w-4 h-4"
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm truncate">
                  {run.pairs.map((p) => p.replace("-USDT-SWAP", "")).join(", ")} · {run.timeframe}
                </div>
                <div className="text-[10px] text-dim">
                  {new Date(run.created_at).toLocaleDateString()} · {run.total_trades} trades · {run.win_rate.toFixed(1)}% WR
                </div>
              </div>
              <span className={`text-sm font-mono ${run.net_pnl >= 0 ? "text-long" : "text-short"}`}>
                {run.net_pnl >= 0 ? "+" : ""}{run.net_pnl.toFixed(2)}%
              </span>
              <button
                onClick={(e) => { e.preventDefault(); loadRunDetail(run.id); }}
                className="px-2 py-1 rounded text-[10px] text-accent border border-accent/30 hover:bg-accent/10 transition-colors"
              >
                View
              </button>
            </label>
          ))}
        </div>
      </div>

      {/* Compare button */}
      <button
        onClick={runCompare}
        disabled={compareIds.length < 2 || compareLoading}
        className="w-full py-3 rounded-lg text-sm font-semibold bg-accent text-surface transition-colors hover:bg-accent/90 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {compareLoading
          ? "Comparing..."
          : compareIds.length < 2
            ? "Select at least 2 runs"
            : `Compare ${compareIds.length} Runs`}
      </button>

      {/* Comparison results */}
      {compareResult && compareResult.length >= 2 && (
        <>
          <CompareEquityCurves runs={compareResult} />
          <CompareTable runs={compareResult} />
        </>
      )}
    </div>
  );
}

function CompareTable({ runs }: { runs: BacktestRun[] }) {
  return (
    <div>
      <h3 className="text-[10px] text-dim font-medium uppercase tracking-wider mb-1.5 px-1">Side-by-Side</h3>
      <div className="bg-card rounded-lg border border-border overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-3 py-2 text-[10px] text-dim font-medium uppercase tracking-wider">Metric</th>
              {runs.map((run, i) => (
                <th key={run.id} className="text-right px-3 py-2">
                  <div className="flex items-center justify-end gap-1.5">
                    <div className="w-2 h-2 rounded-full" style={{ backgroundColor: CURVE_COLORS[i] }} />
                    <span className="text-[10px] text-dim font-medium uppercase tracking-wider">
                      Run {i + 1}
                    </span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {METRIC_ROWS.map((row) => {
              const values = runs.map((r) => {
                const v = r.results?.stats[row.key];
                return typeof v === "number" ? v : null;
              });
              const bestIdx = findBestIdx(values, row.higherBetter);

              return (
                <tr key={row.key} className="border-b border-border last:border-0">
                  <td className="px-3 py-2 text-muted">{row.label}</td>
                  {runs.map((run, i) => {
                    const val = run.results?.stats[row.key];
                    const isBest = i === bestIdx;
                    return (
                      <td
                        key={run.id}
                        className={`px-3 py-2 text-right font-mono ${isBest ? "text-accent font-semibold" : "text-foreground"}`}
                      >
                        {val != null ? row.format(val) : "—"}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CompareEquityCurves({ runs }: { runs: BacktestRun[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 220,
      layout: {
        background: { type: ColorType.Solid, color: "#12161C" },
        textColor: "#848E9C",
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "rgba(31, 41, 55, 0.5)" },
        horzLines: { color: "rgba(31, 41, 55, 0.5)" },
      },
      rightPriceScale: { borderColor: "#1E2530" },
      timeScale: { borderColor: "#1E2530" },
    });

    runs.forEach((run, i) => {
      const curve = run.results?.stats.equity_curve;
      if (!curve || curve.length === 0) return;

      const series = chart.addSeries(LineSeries, {
        color: CURVE_COLORS[i % CURVE_COLORS.length],
        lineWidth: 2,
        priceFormat: { type: "custom", formatter: (v: number) => `${v.toFixed(2)}%` },
      });

      const deduped = new Map<number, number>();
      for (const d of curve) {
        const t = new Date(d.time).getTime() / 1000;
        deduped.set(t, d.cumulative_pnl);
      }
      const seriesData = Array.from(deduped, ([time, value]) => ({
        time: time as UTCTimestamp,
        value,
      })).sort((a, b) => (a.time as number) - (b.time as number));
      series.setData(seriesData);
    });

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const onResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [runs]);

  return (
    <div>
      <h3 className="text-[10px] text-dim font-medium uppercase tracking-wider mb-1.5 px-1">Equity Curves</h3>
      <div className="bg-card rounded-lg border border-border overflow-hidden">
        <div ref={containerRef} />
        <div className="flex items-center gap-4 px-3 py-2 border-t border-border">
          {runs.map((run, i) => (
            <div key={run.id} className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: CURVE_COLORS[i] }} />
              <span className="text-[10px] text-dim">
                {run.pairs.map((p) => p.replace("-USDT-SWAP", "")).join(",")} · {run.timeframe}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function findBestIdx(values: (number | null)[], higherBetter: boolean): number {
  let bestIdx = -1;
  let bestVal: number | null = null;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null) continue;
    if (bestVal == null || (higherBetter ? v > bestVal : v < bestVal)) {
      bestVal = v;
      bestIdx = i;
    }
  }
  return bestIdx;
}
