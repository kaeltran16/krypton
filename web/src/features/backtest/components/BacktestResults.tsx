import { useEffect, useRef, useState, useMemo } from "react";
import { formatDuration, formatPair } from "../../../shared/lib/format";
import { Button } from "../../../shared/components/Button";
import { PillSelect } from "../../../shared/components/PillSelect";
import { SectionLabel } from "../../../shared/components/SectionLabel";
import { Card } from "../../../shared/components/Card";
import { Badge } from "../../../shared/components/Badge";
import { MetricCard } from "../../../shared/components/MetricCard";
import { ProgressBar } from "../../../shared/components/ProgressBar";
import { ParamRow } from "../../../shared/components/ParamRow";
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
        <ProgressBar value={60} className="w-48 mb-3 animate-pulse motion-reduce:animate-none" />
        <p className="text-sm">Running backtest...</p>
      </div>
    );
  }

  if (runError) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <p className="text-sm text-error mb-3">{runError}</p>
        <Button variant="secondary" onClick={() => setTab("setup")}>Back to Setup</Button>
      </div>
    );
  }

  if (!activeRun) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
        <p className="text-sm">No backtest results yet.</p>
        <Button variant="secondary" onClick={() => setTab("setup")} className="mt-3">Run a Backtest</Button>
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
          <Button variant="secondary" onClick={() => setTab("setup")}>Back to Setup</Button>
        )}
      </div>
    );
  }

  if (activeRun.status === "failed") {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <p className="text-sm text-error mb-3">Backtest failed.</p>
        <Button variant="secondary" onClick={() => setTab("setup")}>Retry</Button>
      </div>
    );
  }

  if (!activeRun.results || activeRun.results.trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-on-surface-variant">
        <p className="text-sm">No trades generated.</p>
        <p className="text-xs text-on-surface-variant mt-1">Try lowering the signal threshold or adjusting weights.</p>
        <Button variant="secondary" onClick={() => setTab("setup")} className="mt-3">Adjust Settings</Button>
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
      <PairBreakdown trades={trades} />
      <EquityCurve data={stats.equity_curve} />
      <MonthlyPnl data={stats.monthly_pnl} />
      <TradeList trades={trades} />
    </div>
  );
}

function StatsStrip({ stats }: { stats: BacktestStats }) {
  return (
    <div>
      <SectionLabel>Summary</SectionLabel>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Trades" value={String(stats.total_trades)} size="lg" accent="primary" />
        <MetricCard
          label="Win Rate"
          value={`${stats.win_rate.toFixed(1)}%`}
          size="lg"
          color={stats.win_rate >= 50 ? "text-long" : "text-error"}
          accent="long"
        />
        <MetricCard
          label="Net P&L"
          value={`${stats.net_pnl >= 0 ? "+" : ""}${stats.net_pnl.toFixed(2)}%`}
          size="lg"
          color={stats.net_pnl >= 0 ? "text-long" : "text-error"}
          accent="long"
        />
        <MetricCard label="Max DD" value={`${stats.max_drawdown.toFixed(2)}%`} size="lg" color="text-error" accent="error" />
        <MetricCard label="Sharpe" value={stats.sharpe_ratio != null ? stats.sharpe_ratio.toFixed(2) : "—"} size="lg" accent="primary" />
        <MetricCard label="PF" value={stats.profit_factor != null ? stats.profit_factor.toFixed(2) : "—"} size="lg" />
      </div>
    </div>
  );
}

function PairBreakdown({ trades }: { trades: BacktestTrade[] }) {
  const pairs = useMemo(() => {
    const map = new Map<string, { total: number; wins: number; net_pnl: number; rr_sum: number; rr_count: number }>();
    for (const t of trades) {
      let entry = map.get(t.pair);
      if (!entry) {
        entry = { total: 0, wins: 0, net_pnl: 0, rr_sum: 0, rr_count: 0 };
        map.set(t.pair, entry);
      }
      entry.total++;
      if (t.outcome.includes("TP") || t.outcome === "WIN") entry.wins++;
      entry.net_pnl += t.pnl_pct;
      if (t.exit_price != null) {
        const rr = Math.abs(t.exit_price - t.entry_price) / Math.abs(t.entry_price - t.sl);
        if (isFinite(rr)) {
          entry.rr_sum += rr;
          entry.rr_count++;
        }
      }
    }
    return Array.from(map, ([pair, d]) => ({
      pair,
      total: d.total,
      win_rate: d.total > 0 ? (d.wins / d.total) * 100 : 0,
      net_pnl: d.net_pnl,
      avg_rr: d.rr_count > 0 ? d.rr_sum / d.rr_count : 0,
    }));
  }, [trades]);

  if (pairs.length <= 1) return null;

  return (
    <div>
      <SectionLabel>Per-Pair Breakdown</SectionLabel>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {pairs.map((p) => (
          <Card key={p.pair} padding="none">
            <div className="text-sm font-medium text-on-surface px-3 pt-2 pb-1">{formatPair(p.pair)}/USDT</div>
            <ParamRow label="Trades" value={String(p.total)} />
            <ParamRow label="Win Rate" value={<span className={p.win_rate >= 50 ? "text-long" : "text-short"}>{p.win_rate.toFixed(1)}%</span>} />
            <ParamRow label="Net P&L" value={<span className={p.net_pnl >= 0 ? "text-long" : "text-short"}>{p.net_pnl >= 0 ? "+" : ""}{p.net_pnl.toFixed(2)}%</span>} />
            <ParamRow label="Avg R:R" value={p.avg_rr.toFixed(2)} last />
          </Card>
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
      color: theme.colors.primary,
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
      <SectionLabel>Equity Curve</SectionLabel>
      <Card padding="none" className="overflow-hidden">
        <div ref={containerRef} />
      </Card>
    </div>
  );
}

function MonthlyPnl({ data }: { data: Record<string, number> }) {
  const months = Object.entries(data).sort(([a], [b]) => a.localeCompare(b));
  if (months.length === 0) return null;

  return (
    <div>
      <SectionLabel>Monthly P&L</SectionLabel>
      <Card padding="sm">
        <div className="grid grid-cols-4 gap-1.5">
          {months.map(([month, pnl]) => (
            <div
              key={month}
              className={`rounded-lg p-2 text-center text-xs font-mono tabular-nums ${
                pnl >= 0 ? "bg-long/10 text-long" : "bg-error/10 text-error"
              }`}
            >
              <div className="text-[10px] text-on-surface-variant">{month}</div>
              <div className="font-medium">{pnl >= 0 ? "+" : ""}{pnl.toFixed(1)}%</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

type SortOption = "date-desc" | "date-asc" | "pnl-desc" | "pnl-asc" | "duration" | "score";

function TradeList({ trades }: { trades: BacktestTrade[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [pairFilter, setPairFilter] = useState("all");
  const [dirFilter, setDirFilter] = useState<"both" | "LONG" | "SHORT">("both");
  const [outcomeFilter, setOutcomeFilter] = useState<"all" | "wins" | "losses">("all");
  const [sort, setSort] = useState<SortOption>("date-desc");

  const allPairs = useMemo(() => [...new Set(trades.map((t) => t.pair))], [trades]);

  const filtered = useMemo(() => {
    let result = trades;
    if (pairFilter !== "all") result = result.filter((t) => t.pair === pairFilter);
    if (dirFilter !== "both") result = result.filter((t) => t.direction === dirFilter);
    if (outcomeFilter === "wins") result = result.filter((t) => t.outcome.includes("TP") || t.outcome === "WIN");
    if (outcomeFilter === "losses") result = result.filter((t) => !t.outcome.includes("TP") && t.outcome !== "WIN");

    const sorted = [...result];
    switch (sort) {
      case "date-desc": sorted.sort((a, b) => new Date(b.entry_time).getTime() - new Date(a.entry_time).getTime()); break;
      case "date-asc": sorted.sort((a, b) => new Date(a.entry_time).getTime() - new Date(b.entry_time).getTime()); break;
      case "pnl-desc": sorted.sort((a, b) => b.pnl_pct - a.pnl_pct); break;
      case "pnl-asc": sorted.sort((a, b) => a.pnl_pct - b.pnl_pct); break;
      case "duration": sorted.sort((a, b) => a.duration_minutes - b.duration_minutes); break;
      case "score": sorted.sort((a, b) => b.score - a.score); break;
    }
    return sorted;
  }, [trades, pairFilter, dirFilter, outcomeFilter, sort]);

  const clearFilters = () => {
    setPairFilter("all");
    setDirFilter("both");
    setOutcomeFilter("all");
    setExpanded(null);
  };

  return (
    <div>
      <SectionLabel>
        Trades ({filtered.length}{filtered.length !== trades.length ? ` of ${trades.length}` : ""})
      </SectionLabel>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-2 mb-2 items-center">
        {/* Pair filters */}
        <PillSelect
          options={["all", ...allPairs] as const}
          selected={pairFilter}
          onToggle={(v) => { setPairFilter(v); setExpanded(null); }}
          renderLabel={(v) => v === "all" ? "All Pairs" : formatPair(v)}
          size="sm"
          wrap
        />
        <div className="border-r border-outline-variant/20 h-6 self-center" />

        {/* Direction filters */}
        <PillSelect
          options={["both", "LONG", "SHORT"] as const}
          selected={dirFilter}
          onToggle={(v) => { setDirFilter(v); setExpanded(null); }}
          renderLabel={(v) => v === "both" ? "Both" : v === "LONG" ? "Long" : "Short"}
          size="sm"
          wrap
        />
        <div className="border-r border-outline-variant/20 h-6 self-center" />

        {/* Outcome filters */}
        <PillSelect
          options={["all", "wins", "losses"] as const}
          selected={outcomeFilter}
          onToggle={(v) => { setOutcomeFilter(v); setExpanded(null); }}
          renderLabel={(v) => v === "all" ? "All" : v === "wins" ? "Wins" : "Losses"}
          size="sm"
          wrap
        />
        <div className="border-r border-outline-variant/20 h-6 self-center" />

        {/* Sort dropdown */}
        <select
          value={sort}
          onChange={(e) => { setSort(e.target.value as SortOption); setExpanded(null); }}
          aria-label="Sort trades"
          className="min-h-[44px] px-3 py-2 rounded-lg text-xs font-bold bg-surface-container-lowest border border-outline-variant/30 text-on-surface-variant focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none"
        >
          <option value="date-desc">Date (newest)</option>
          <option value="date-asc">Date (oldest)</option>
          <option value="pnl-desc">P&L (high → low)</option>
          <option value="pnl-asc">P&L (low → high)</option>
          <option value="duration">Duration</option>
          <option value="score">Score</option>
        </select>
      </div>

      {/* Trade list */}
      <Card padding="none" className="overflow-hidden divide-y divide-outline-variant/10">
        {filtered.length === 0 ? (
          <div className="py-12 text-center text-on-surface-variant">
            <p className="text-sm">No trades match filters</p>
            <button onClick={clearFilters} className="mt-2 text-xs text-primary">Clear filters</button>
          </div>
        ) : (
          filtered.map((trade, i) => {
            const tradeId = `${trade.pair}-${trade.entry_time}-${i}`;
            return (
            <div key={tradeId}>
              <button
                onClick={() => setExpanded(expanded === tradeId ? null : tradeId)}
                className="w-full px-3 py-2.5 flex items-center justify-between text-left hover:bg-surface-container-high transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
              >
                <div className="flex items-center gap-2">
                  <Badge color={trade.direction === "LONG" ? "long" : "error"} className="uppercase text-[10px]">
                    {trade.direction}
                  </Badge>
                  <span className="text-sm text-on-surface">{formatPair(trade.pair)}</span>
                </div>
                <div className="flex items-center gap-3">
                  <OutcomeBadge outcome={trade.outcome} />
                  <span
                    className={`text-sm font-mono tabular-nums ${
                      trade.pnl_pct >= 0 ? "text-long" : "text-error"
                    }`}
                  >
                    {trade.pnl_pct >= 0 ? "+" : ""}{trade.pnl_pct.toFixed(2)}%
                  </span>
                </div>
              </button>
              {expanded === tradeId && <TradeDetail trade={trade} />}
            </div>
            );
          })
        )}
      </Card>
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
        <div>TP1: <span className="text-long font-mono tabular-nums">{trade.tp1.toLocaleString()}</span> / TP2: <span className="text-long font-mono tabular-nums">{trade.tp2.toLocaleString()}</span></div>
      </div>
      {trade.detected_patterns.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {trade.detected_patterns.map((p) => (
            <Badge key={p} color={trade.direction === "LONG" ? "long" : "error"} weight="medium" className="text-[10px]">
              {p}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const isWin = outcome.includes("TP") || outcome === "WIN";
  return (
    <Badge color={isWin ? "long" : "error"} className="text-[10px]">
      {outcome.replace("_", " ")}
    </Badge>
  );
}

