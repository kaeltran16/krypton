import { useEffect, useRef, useState } from "react";
import { formatDuration } from "../../../shared/lib/format";
import {
  createChart,
  LineSeries,
  ColorType,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useBacktestStore } from "../store";
import { theme } from "../../../shared/theme";
import type { BacktestRun, BacktestTrade, BacktestStats } from "../types";

export function BacktestResults() {
  const { activeRun, runLoading, runError, setTab } = useBacktestStore();

  if (runLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
        <div className="w-48 h-2 bg-surface-container-lowest rounded-full overflow-hidden mb-3">
          <div className="h-full bg-primary rounded-full animate-pulse motion-reduce:animate-none" style={{ width: "60%" }} />
        </div>
        <p className="text-sm">Running backtest...</p>
      </div>
    );
  }

  if (runError) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <p className="text-sm text-error mb-3">{runError}</p>
        <button
          onClick={() => setTab("setup")}
          className="px-4 py-2 rounded-lg text-sm bg-surface-container-lowest text-on-surface border border-outline-variant/20 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
        >
          Back to Setup
        </button>
      </div>
    );
  }

  if (!activeRun) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
        <p className="text-sm">No backtest results yet.</p>
        <button
          onClick={() => setTab("setup")}
          className="mt-3 px-4 py-2 rounded-lg text-sm bg-surface-container-lowest text-on-surface border border-outline-variant/20 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
        >
          Run a Backtest
        </button>
      </div>
    );
  }

  if (activeRun.status === "cancelled") {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
        <p className="text-sm mb-3">Run cancelled.</p>
        {activeRun.results && activeRun.results.trades.length > 0 ? (
          <ResultsContent run={activeRun} />
        ) : (
          <button
            onClick={() => setTab("setup")}
            className="px-4 py-2 rounded-lg text-sm bg-surface-container-lowest text-on-surface border border-outline-variant/20 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
          >
            Back to Setup
          </button>
        )}
      </div>
    );
  }

  if (activeRun.status === "failed") {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <p className="text-sm text-error mb-3">Backtest failed.</p>
        <button
          onClick={() => setTab("setup")}
          className="px-4 py-2 rounded-lg text-sm bg-surface-container-lowest text-on-surface border border-outline-variant/20 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!activeRun.results || activeRun.results.trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
        <p className="text-sm">No trades generated.</p>
        <p className="text-xs text-on-surface-variant mt-1">Try lowering the signal threshold or adjusting weights.</p>
        <button
          onClick={() => setTab("setup")}
          className="mt-3 px-4 py-2 rounded-lg text-sm bg-surface-container-lowest text-on-surface border border-outline-variant/20 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
        >
          Adjust Settings
        </button>
      </div>
    );
  }

  return <ResultsContent run={activeRun} />;
}

function ResultsContent({ run }: { run: BacktestRun }) {
  const stats = run.results!.stats;
  const trades = run.results!.trades;

  return (
    <div className="space-y-4">
      <StatsStrip stats={stats} />
      <EquityCurve data={stats.equity_curve} />
      <MonthlyPnl data={stats.monthly_pnl} />
      <TradeList trades={trades} />
    </div>
  );
}

function StatsStrip({ stats }: { stats: BacktestStats }) {
  const items = [
    { label: "Trades", value: String(stats.total_trades), border: "border-primary" },
    { label: "Win Rate", value: `${stats.win_rate.toFixed(1)}%`, color: stats.win_rate >= 50 ? "text-tertiary-dim" : "text-error", border: "border-tertiary-dim" },
    { label: "Net P&L", value: `${stats.net_pnl >= 0 ? "+" : ""}${stats.net_pnl.toFixed(2)}%`, color: stats.net_pnl >= 0 ? "text-tertiary-dim" : "text-error", border: "border-tertiary-dim" },
    { label: "Max DD", value: `${stats.max_drawdown.toFixed(2)}%`, color: "text-error", border: "border-error" },
    { label: "Sharpe", value: stats.sharpe_ratio != null ? stats.sharpe_ratio.toFixed(2) : "—", border: "border-primary" },
    { label: "PF", value: stats.profit_factor != null ? stats.profit_factor.toFixed(2) : "—", border: "border-outline-variant/30" },
  ];

  return (
    <div>
      <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-1.5 px-1 text-on-surface-variant">Summary</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {items.map((item) => (
          <div key={item.label} className={`bg-surface-container p-4 rounded border-l-2 ${item.border}`}>
            <div className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">{item.label}</div>
            <div className={`text-2xl font-headline font-bold tabular-nums mt-0.5 ${item.color || "text-on-surface"}`}>
              {item.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EquityCurve({ data }: { data: { time: string; cumulative_pnl: number }[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 200,
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

    const series = chart.addSeries(LineSeries, {
      color: theme.colors.accent,
      lineWidth: 2,
      priceFormat: { type: "custom", formatter: (v: number) => `${v.toFixed(2)}%` },
    });

    const deduped = new Map<number, number>();
    for (const d of data) {
      const t = new Date(d.time).getTime() / 1000;
      deduped.set(t, d.cumulative_pnl);
    }
    const seriesData = Array.from(deduped, ([time, value]) => ({
      time: time as UTCTimestamp,
      value,
    })).sort((a, b) => (a.time as number) - (b.time as number));

    series.setData(seriesData);
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
  }, [data]);

  return (
    <div>
      <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-1.5 px-1 text-on-surface-variant">Equity Curve</h3>
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 overflow-hidden">
        <div ref={containerRef} />
      </div>
    </div>
  );
}

function MonthlyPnl({ data }: { data: Record<string, number> }) {
  const months = Object.entries(data).sort(([a], [b]) => a.localeCompare(b));
  if (months.length === 0) return null;

  return (
    <div>
      <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-1.5 px-1 text-on-surface-variant">Monthly P&L</h3>
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 p-3">
        <div className="grid grid-cols-4 gap-1.5">
          {months.map(([month, pnl]) => (
            <div
              key={month}
              className={`rounded-lg p-2 text-center text-xs font-mono tabular-nums ${
                pnl >= 0 ? "bg-tertiary-dim/10 text-tertiary-dim" : "bg-error/10 text-error"
              }`}
            >
              <div className="text-[10px] text-on-surface-variant">{month}</div>
              <div className="font-medium">{pnl >= 0 ? "+" : ""}{pnl.toFixed(1)}%</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TradeList({ trades }: { trades: BacktestTrade[] }) {
  const [expanded, setExpanded] = useState<number | null>(null);

  return (
    <div>
      <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-1.5 px-1 text-on-surface-variant">
        Trades ({trades.length})
      </h3>
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 overflow-hidden divide-y divide-outline-variant/10">
        {trades.map((trade, i) => (
          <div key={i}>
            <button
              onClick={() => setExpanded(expanded === i ? null : i)}
              className="w-full px-3 py-2.5 flex items-center justify-between text-left hover:bg-surface-container-high transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
            >
              <div className="flex items-center gap-2">
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                    trade.direction === "LONG" ? "bg-tertiary-dim/15 text-tertiary-dim" : "bg-error/15 text-error"
                  }`}
                >
                  {trade.direction}
                </span>
                <span className="text-sm text-on-surface">{trade.pair.replace("-USDT-SWAP", "")}</span>
              </div>
              <div className="flex items-center gap-3">
                <OutcomeBadge outcome={trade.outcome} />
                <span
                  className={`text-sm font-mono tabular-nums ${
                    trade.pnl_pct >= 0 ? "text-tertiary-dim" : "text-error"
                  }`}
                >
                  {trade.pnl_pct >= 0 ? "+" : ""}{trade.pnl_pct.toFixed(2)}%
                </span>
              </div>
            </button>
            {expanded === i && <TradeDetail trade={trade} />}
          </div>
        ))}
      </div>
    </div>
  );
}

function TradeDetail({ trade }: { trade: BacktestTrade }) {
  return (
    <div className="px-3 pb-3 space-y-1.5 text-xs">
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-on-surface-variant">
        <div>Entry: <span className="text-on-surface font-mono tabular-nums">{new Date(trade.entry_time).toLocaleString()}</span></div>
        <div>Exit: <span className="text-on-surface font-mono tabular-nums">{trade.exit_time ? new Date(trade.exit_time).toLocaleString() : "—"}</span></div>
        <div>Entry Price: <span className="text-on-surface font-mono tabular-nums">{trade.entry_price.toLocaleString()}</span></div>
        <div>Exit Price: <span className="text-on-surface font-mono tabular-nums">{trade.exit_price?.toLocaleString() ?? "—"}</span></div>
        <div>Score: <span className="text-primary font-mono tabular-nums">{trade.score}</span></div>
        <div>Duration: <span className="text-on-surface font-mono tabular-nums">{formatDuration(trade.duration_minutes)}</span></div>
        <div>SL: <span className="text-error font-mono tabular-nums">{trade.sl.toLocaleString()}</span></div>
        <div>TP1: <span className="text-tertiary-dim font-mono tabular-nums">{trade.tp1.toLocaleString()}</span> / TP2: <span className="text-tertiary-dim font-mono tabular-nums">{trade.tp2.toLocaleString()}</span></div>
      </div>
      {trade.detected_patterns.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {trade.detected_patterns.map((p) => (
            <span
              key={p}
              className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                trade.direction === "LONG" ? "bg-tertiary-dim/10 text-tertiary-dim" : "bg-error/10 text-error"
              }`}
            >
              {p}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const isWin = outcome.includes("TP") || outcome === "WIN";
  return (
    <span
      className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
        isWin ? "bg-tertiary-dim/10 text-tertiary-dim" : "bg-error/10 text-error"
      }`}
    >
      {outcome.replace("_", " ")}
    </span>
  );
}

