import { useEffect, useRef, useMemo } from "react";
import { formatDuration, formatPair } from "../../../shared/lib/format";
import { Button } from "../../../shared/components/Button";
import { Card } from "../../../shared/components/Card";
import { SectionLabel } from "../../../shared/components/SectionLabel";
import {
  createChart,
  LineSeries,
  ColorType,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useBacktestStore } from "../store";
import { theme } from "../../../shared/theme";
import type { BacktestRun, BacktestStats, BacktestConfig } from "../types";

const CURVE_COLORS = theme.indicators.curveColors;

function configLabel(config: BacktestConfig): string {
  const pairs = config.pairs.map(formatPair).join(", ");
  return `${pairs} \u00b7 ${config.timeframe} \u00b7 Thresh ${config.signal_threshold} \u00b7 SL ${config.sl_atr_multiplier}x`;
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
      <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
        <p className="text-sm">No saved runs yet.</p>
        <p className="text-xs text-on-surface-variant mt-1">Run a backtest and save it to start comparing.</p>
        <Button variant="secondary" size="sm" onClick={() => setTab("setup")} className="mt-3">
          Run a Backtest
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Run selection */}
      <div>
        <SectionLabel>Select Runs to Compare</SectionLabel>
        <Card padding="none" className="divide-y divide-outline-variant/10">
          {completedRuns.map((run) => (
            <label
              key={run.id}
              className="flex items-center gap-3 px-3 py-2.5 hover:bg-surface-container-high transition-colors cursor-pointer"
            >
              <input
                type="checkbox"
                checked={compareIds.includes(run.id)}
                onChange={() => toggleCompareId(run.id)}
                className="accent-primary w-4 h-4"
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-on-surface truncate">
                  {run.pairs.map(formatPair).join(", ")} · {run.timeframe}
                </div>
                <div className="text-[10px] text-on-surface-variant">
                  {new Date(run.created_at).toLocaleDateString()} · {run.total_trades} trades · {run.win_rate.toFixed(1)}% WR
                </div>
              </div>
              <span className={`text-sm font-mono tabular-nums ${run.net_pnl >= 0 ? "text-long" : "text-error"}`}>
                {run.net_pnl >= 0 ? "+" : ""}{run.net_pnl.toFixed(2)}%
              </span>
              <Button
                size="xs"
                onClick={(e) => { e.preventDefault(); loadRunDetail(run.id); }}
              >
                View
              </Button>
            </label>
          ))}
        </Card>
      </div>

      {/* Compare button */}
      <Button
        variant="solid"
        size="lg"
        onClick={runCompare}
        disabled={compareIds.length < 2}
        loading={compareLoading}
        className="font-headline font-bold text-xs tracking-widest uppercase"
      >
        {compareIds.length < 2
          ? "Select at least 2 runs"
          : `Compare ${compareIds.length} Runs`}
      </Button>

      {/* Comparison results */}
      {compareResult && compareResult.length >= 2 && (
        <>
          <CompareEquityCurves runs={compareResult} />
          <ConfigDiff runs={compareResult} />
          <CompareTable runs={compareResult} />
        </>
      )}
    </div>
  );
}

function CompareTable({ runs }: { runs: BacktestRun[] }) {
  return (
    <div>
      <SectionLabel>Side-by-Side</SectionLabel>
      <Card padding="none" className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-outline-variant/10">
              <th className="text-left px-3 py-2 text-[10px] font-headline font-bold text-on-surface-variant uppercase tracking-wider">Metric</th>
              {runs.map((run, i) => (
                <th key={run.id} className="text-right px-3 py-2">
                  <div className="flex items-center justify-end gap-1.5">
                    <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: CURVE_COLORS[i] }} />
                    <div className="text-right">
                      <span className="text-[10px] font-headline font-bold text-on-surface-variant uppercase tracking-wider block">
                        Run {i + 1}
                      </span>
                      <span className="text-[10px] text-on-surface-variant/70 font-mono block truncate max-w-[200px]">
                        {configLabel(run.config)}
                      </span>
                    </div>
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
                <tr key={row.key} className="border-b border-outline-variant/10 last:border-0">
                  <td className="px-3 py-2 text-on-surface-variant">{row.label}</td>
                  {runs.map((run, i) => {
                    const val = run.results?.stats[row.key];
                    const isBest = i === bestIdx;
                    return (
                      <td
                        key={run.id}
                        className={`px-3 py-2 text-right font-mono tabular-nums ${isBest ? "text-primary font-bold" : "text-on-surface"}`}
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
      </Card>
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
        background: { type: ColorType.Solid, color: theme.chart.background },
        textColor: theme.chart.text,
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: theme.chart.grid },
        horzLines: { color: theme.chart.grid },
      },
      rightPriceScale: { borderColor: theme.chart.scaleBorder },
      timeScale: { borderColor: theme.chart.scaleBorder },
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
      <SectionLabel>Equity Curves</SectionLabel>
      <Card padding="none" className="overflow-hidden">
        <div ref={containerRef} />
        <div className="flex items-center gap-4 px-3 py-2 border-t border-outline-variant/10">
          {runs.map((run, i) => (
            <div key={run.id} className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: CURVE_COLORS[i] }} />
              <span className="text-[10px] text-on-surface-variant">
                Run {i + 1}: {configLabel(run.config)}
              </span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

const CONFIG_DIFF_KEYS: { key: keyof BacktestConfig; label: string }[] = [
  { key: "signal_threshold", label: "Signal Threshold" },
  { key: "tech_weight", label: "Tech Weight" },
  { key: "pattern_weight", label: "Pattern Weight" },
  { key: "enable_patterns", label: "Patterns Enabled" },
  { key: "sl_atr_multiplier", label: "SL (ATR x)" },
  { key: "tp1_atr_multiplier", label: "TP1 (ATR x)" },
  { key: "tp2_atr_multiplier", label: "TP2 (ATR x)" },
  { key: "max_concurrent_positions", label: "Max Positions" },
  { key: "ml_enabled", label: "ML Enabled" },
  { key: "ml_confidence_threshold", label: "ML Confidence" },
];

function ConfigDiff({ runs }: { runs: BacktestRun[] }) {
  const diffs = useMemo(() => {
    return CONFIG_DIFF_KEYS.filter(({ key }) => {
      const values = runs.map((r) => String(r.config[key]));
      return new Set(values).size > 1;
    });
  }, [runs]);

  return (
    <div>
      <SectionLabel>Config Differences</SectionLabel>
      <Card padding="none" className="overflow-x-auto">
        {diffs.length === 0 ? (
          <p className="px-3 py-4 text-sm text-on-surface-variant text-center">All parameters identical across runs</p>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-outline-variant/10">
                  <th className="text-left px-3 py-2 text-[10px] font-headline font-bold text-on-surface-variant uppercase tracking-wider">Parameter</th>
                  {runs.map((run, i) => (
                    <th key={run.id} className="text-right px-3 py-2">
                      <div className="flex items-center justify-end gap-1.5">
                        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: CURVE_COLORS[i] }} />
                        <span className="text-[10px] font-headline font-bold text-on-surface-variant uppercase tracking-wider">Run {i + 1}</span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {diffs.map(({ key, label }) => (
                  <tr key={key} className="border-b border-outline-variant/10 last:border-0">
                    <td className="px-3 py-2 text-on-surface-variant">{label}</td>
                    {runs.map((run, i) => (
                      <td
                        key={run.id}
                        className="px-3 py-2 text-right font-mono tabular-nums font-bold"
                        style={{ color: CURVE_COLORS[i] }}
                      >
                        {String(run.config[key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="px-3 py-2 text-[10px] text-on-surface-variant border-t border-outline-variant/10">
              {diffs.length} of {CONFIG_DIFF_KEYS.length} parameters differ — identical parameters hidden
            </p>
          </>
        )}
      </Card>
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
