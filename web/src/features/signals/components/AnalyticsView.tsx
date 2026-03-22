import { useState, useId } from "react";
import { BarChart3 } from "lucide-react";
import { useSignalStats } from "../../home/hooks/useSignalStats";
import { theme, hexToRgba } from "../../../shared/theme";
import { formatPair, formatDuration } from "../../../shared/lib/format";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { EmptyState } from "../../../shared/components/EmptyState";
import type { SignalStats, PerformanceMetrics } from "../types";
import { Card } from "../../../shared/components/Card";
import { Badge } from "../../../shared/components/Badge";
import { MetricCard } from "../../../shared/components/MetricCard";
import { Skeleton } from "../../../shared/components/Skeleton";
import { SectionLabel } from "../../../shared/components/SectionLabel";

type Period = "7" | "30" | "365";

const PERIODS: { value: Period; label: string }[] = [
  { value: "7", label: "7D" },
  { value: "30", label: "30D" },
  { value: "365", label: "All" },
];

export function AnalyticsView() {
  const [period, setPeriod] = useState<Period>("7");
  const { stats, loading } = useSignalStats(Number(period));

  if (loading) {
    return (
      <div className="p-3 space-y-3">
        <Skeleton count={6} height="h-24" border={false} />
      </div>
    );
  }

  if (!stats || stats.total_resolved === 0) {
    return (
      <div className="p-3">
        <EmptyState
          icon={<BarChart3 size={32} />}
          title="No resolved signals yet"
          subtitle="Analytics will appear as signals resolve"
        />
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3 overflow-y-auto">
      <SegmentedControl options={PERIODS} value={period} onChange={setPeriod} />

      <SummaryBento stats={stats} />

      <SectionLabel>Equity & Risk</SectionLabel>
      <EquityCurve data={stats.equity_curve} />
      <DrawdownChart data={stats.drawdown_series} maxDd={stats.performance.max_drawdown_pct} />

      <SectionLabel>Breakdowns</SectionLabel>
      <PairBreakdown data={stats.by_pair} />
      <TimeframeBreakdown data={stats.by_timeframe} />
      <HourlyHeatmap data={stats.hourly_performance} />
      <DirectionBreakdown data={stats.by_direction} />

      <SectionLabel>Distribution & Streaks</SectionLabel>
      <PnlDistribution data={stats.pnl_distribution} />
      <StreakTracker streaks={stats.streaks} />
      <NotableTrades perf={stats.performance} />

      <RiskProfile perf={stats.performance} totalResolved={stats.total_resolved} />
    </div>
  );
}

// ─── SummaryBento ────────────────────────────────────────────────

function SummaryBento({ stats }: { stats: SignalStats }) {
  const netPnl = stats.equity_curve.length > 0
    ? stats.equity_curve[stats.equity_curve.length - 1].cumulative_pnl
    : 0;

  const expectancy = stats.performance.expectancy;
  const sharpe = stats.performance.sharpe_ratio;
  const showDash = stats.total_resolved < 5;

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* Net P&L — col-span-2 */}
      <Card border={false} className="col-span-2 border-l-4 border-tertiary-dim">
        <div className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-1">Net P&L</div>
        <div className={`font-headline text-3xl font-bold tabular-nums ${netPnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
          {netPnl >= 0 ? "+" : ""}{netPnl.toFixed(1)}%
        </div>
      </Card>

      {/* Win Rate */}
      <Card border={false}>
        <div className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-1">Win Rate</div>
        <div className={`font-headline text-2xl font-bold tabular-nums ${stats.win_rate >= 50 ? "text-tertiary-dim" : "text-error"}`}>
          {stats.win_rate}%
        </div>
      </Card>

      {/* Expectancy */}
      <Card border={false}>
        <div className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-1">Expectancy</div>
        <div className={`font-headline text-2xl font-bold tabular-nums ${
          showDash || expectancy == null ? "text-on-surface" : expectancy >= 0 ? "text-tertiary-dim" : "text-error"
        }`}>
          {showDash || expectancy == null ? "—" : `${expectancy >= 0 ? "+" : ""}${expectancy}%`}
        </div>
      </Card>

      {/* Sharpe */}
      <Card border={false}>
        <div className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-1">Sharpe</div>
        <div className={`font-headline text-2xl font-bold tabular-nums ${
          showDash || sharpe == null ? "text-on-surface" : sharpe > 0 ? "text-tertiary-dim" : "text-error"
        }`}>
          {showDash || sharpe == null ? "—" : sharpe}
        </div>
      </Card>

      {/* Avg R:R */}
      <Card border={false}>
        <div className="text-xs font-bold text-on-surface-variant uppercase tracking-widest mb-1">Avg R:R</div>
        <div className="font-headline text-2xl font-bold tabular-nums text-on-surface">{stats.avg_rr}</div>
      </Card>

      {/* Row 4: Resolved | Wins | Losses | Expired */}
      <div className="col-span-2 grid grid-cols-4 gap-2">
        <MetricCard label="Resolved" value={stats.total_resolved} />
        <MetricCard label="Wins" value={stats.total_wins} color="text-tertiary-dim" />
        <MetricCard label="Losses" value={stats.total_losses} color="text-error" />
        <MetricCard label="Expired" value={stats.total_expired ?? 0} />
      </div>
    </div>
  );
}

// ─── EquityCurve ─────────────────────────────────────────────────

function EquityCurve({ data }: { data: SignalStats["equity_curve"] }) {
  const gradientId = useId();
  if (data.length < 2) return null;

  const width = 320;
  const height = 120;
  const pad = { top: 10, right: 10, bottom: 20, left: 10 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;

  const values = data.map((d) => d.cumulative_pnl);
  const minVal = Math.min(0, ...values);
  const maxVal = Math.max(0, ...values);
  const range = maxVal - minVal || 1;

  const points = data
    .map((d, i) => {
      const x = pad.left + (i / (data.length - 1)) * w;
      const y = pad.top + h - ((d.cumulative_pnl - minVal) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  const lastVal = values[values.length - 1];
  const lineColor = lastVal >= 0 ? theme.colors.long : theme.colors.short;

  const areaPoints = data.map((d, i) => {
    const x = pad.left + (i / (data.length - 1)) * w;
    const y = pad.top + h - ((d.cumulative_pnl - minVal) / range) * h;
    return `${x},${y}`;
  });
  const fillPath = `${pad.left},${pad.top + h} ${areaPoints.join(" ")} ${pad.left + w},${pad.top + h}`;

  return (
    <Card border={false}>
      <SectionLabel>Equity Curve</SectionLabel>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none" role="img" aria-label={`Equity curve, current P&L ${lastVal >= 0 ? "+" : ""}${lastVal.toFixed(1)}%`}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.3" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
          </linearGradient>
        </defs>
        <polygon fill={`url(#${gradientId})`} points={fillPath} />
        <polyline fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" points={points} />
      </svg>
    </Card>
  );
}

// ─── DrawdownChart ───────────────────────────────────────────────

function DrawdownChart({ data, maxDd }: { data: SignalStats["drawdown_series"]; maxDd: number }) {
  if (data.length < 2) return null;

  const width = 320;
  const height = 100;
  const pad = { top: 5, right: 10, bottom: 15, left: 10 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;

  const values = data.map((d) => d.drawdown);
  const minVal = Math.min(...values, 0);
  const range = Math.abs(minVal) || 1;

  const points = data
    .map((d, i) => {
      const x = pad.left + (i / (data.length - 1)) * w;
      const y = pad.top + (Math.abs(d.drawdown) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  const firstX = pad.left;
  const lastX = pad.left + w;
  const fillPoints = `${firstX},${pad.top} ${points} ${lastX},${pad.top}`;

  return (
    <Card border={false} className="relative">
      <div className="flex items-center justify-between mb-2">
        <SectionLabel className="mb-0">Drawdown</SectionLabel>
        <span className="text-xs font-mono font-bold tabular-nums text-on-surface">
          {maxDd > 0 ? `-${maxDd}%` : "0%"}
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none" role="img" aria-label={`Drawdown chart, max drawdown ${minVal.toFixed(1)}%`}>
        <polygon fill={theme.colors.short + "15"} points={fillPoints} />
        <polyline fill="none" stroke={theme.colors.short} strokeWidth="1.5" strokeLinejoin="round" points={points} />
      </svg>
    </Card>
  );
}

// ─── PairBreakdown ───────────────────────────────────────────────

function PairBreakdown({ data }: { data: SignalStats["by_pair"] }) {
  const pairs = Object.entries(data);
  if (pairs.length === 0) return null;

  return (
    <div className="space-y-3">
      {pairs.map(([pair, stats]) => (
        <Card key={pair} border={false} className="hover:bg-surface-container-high transition-colors">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-surface-container-highest flex items-center justify-center">
              <span className="font-headline font-bold text-xs text-primary">{formatPair(pair).slice(0, 3)}</span>
            </div>
            <div className="flex-1">
              <span className="font-headline font-bold text-sm">{formatPair(pair)}/USDT</span>
              <div className="flex items-center gap-3 text-xs font-mono mt-0.5">
                <span className={stats.win_rate >= 50 ? "text-tertiary-dim" : "text-error"}>
                  {stats.win_rate}% WR
                </span>
                <span className={stats.avg_pnl >= 0 ? "text-tertiary-dim" : "text-error"}>
                  {stats.avg_pnl >= 0 ? "+" : ""}{stats.avg_pnl.toFixed(2)}%
                </span>
                <span className="text-on-surface-variant">{stats.total} trades</span>
              </div>
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

// ─── TimeframeBreakdown ──────────────────────────────────────────

function TimeframeBreakdown({ data }: { data: SignalStats["by_timeframe"] }) {
  const order = ["15m", "1h", "4h"];
  const sorted = order
    .filter((tf) => data[tf])
    .map((tf) => ({ tf, ...data[tf] }));
  if (sorted.length === 0) return null;

  return (
    <Card border={false}>
      <SectionLabel className="mb-3">By Timeframe</SectionLabel>
      <div className="grid grid-cols-3 gap-2">
        {sorted.map(({ tf, win_rate, total }) => (
          <MetricCard
            key={tf}
            label={`${tf} · ${total} trades`}
            value={`${win_rate}%`}
            color={win_rate >= 50 ? "text-tertiary-dim" : "text-error"}
          />
        ))}
      </div>
    </Card>
  );
}

// ─── HourlyHeatmap ──────────────────────────────────────────────

function HourlyHeatmap({ data }: { data: SignalStats["hourly_performance"] }) {
  if (!data || data.length === 0 || data.every((d) => d.count === 0)) return null;

  const magnitudes = data.filter((d) => d.count > 0).map((d) => Math.abs(d.avg_pnl));
  const sorted = [...magnitudes].sort((a, b) => a - b);
  const p90Idx = Math.floor(sorted.length * 0.9);
  const maxMag = sorted[p90Idx] || sorted[sorted.length - 1] || 1;

  const bestHour = data.reduce((best, d) => d.avg_pnl > best.avg_pnl ? d : best, data[0]);
  const worstHour = data.reduce((worst, d) => d.avg_pnl < worst.avg_pnl ? d : worst, data[0]);

  return (
    <Card border={false}>
      <SectionLabel className="mb-3">Best Hours to Trade</SectionLabel>
      <div
        className="grid grid-cols-6 gap-1"
        role="img"
        aria-label={`Hourly heatmap. Best hour: ${bestHour.hour}:00 (${bestHour.avg_pnl >= 0 ? "+" : ""}${bestHour.avg_pnl.toFixed(2)}%). Worst hour: ${worstHour.hour}:00 (${worstHour.avg_pnl >= 0 ? "+" : ""}${worstHour.avg_pnl.toFixed(2)}%)`}
      >
        {data.map((d) => {
          const intensity = d.count > 0 ? Math.min(Math.abs(d.avg_pnl) / maxMag, 1) : 0;
          const opacity = 0.1 + intensity * 0.5;
          const bgColor = d.count === 0
            ? "transparent"
            : d.avg_pnl >= 0
              ? hexToRgba(theme.colors.long, opacity)
              : hexToRgba(theme.colors.short, opacity);

          return (
            <div
              key={d.hour}
              className="aspect-square rounded flex flex-col items-center justify-center"
              style={{ backgroundColor: bgColor }}
            >
              <span className="text-[10px] text-on-surface-variant leading-none">{d.hour}</span>
              {d.count > 0 && (
                <span className={`text-[9px] font-mono tabular-nums leading-none mt-0.5 ${d.avg_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
                  {d.avg_pnl >= 0 ? "+" : ""}{d.avg_pnl.toFixed(1)}
                </span>
              )}
            </div>
          );
        })}
      </div>
      {/* Legend */}
      <div className="mt-2 flex items-center gap-1">
        <span className="text-xs text-on-surface-variant">Loss</span>
        <div className="flex-1 h-3 rounded-sm relative" style={{
          background: `linear-gradient(to right, ${hexToRgba(theme.colors.short, 0.6)}, ${hexToRgba(theme.colors.short, 0.1)}, transparent, ${hexToRgba(theme.colors.long, 0.1)}, ${hexToRgba(theme.colors.long, 0.6)})`,
        }}>
          <span className="absolute left-1/2 -translate-x-1/2 top-0 text-xs text-on-surface-variant leading-3">0</span>
        </div>
        <span className="text-xs text-on-surface-variant">Profit</span>
      </div>
    </Card>
  );
}

// ─── DirectionBreakdown ──────────────────────────────────────────

function DirectionBreakdown({ data }: { data: SignalStats["by_direction"] }) {
  if (!data || Object.keys(data).length === 0) return null;

  const directions = ["LONG", "SHORT"] as const;
  const available = directions.filter((d) => data[d]);
  if (available.length === 0) return null;

  return (
    <div className="grid grid-cols-2 gap-3">
      {available.map((dir) => {
        const d = data[dir];
        const isLong = dir === "LONG";
        return (
          <Card
            key={dir}
            border={false}
            className={`border-l-[3px] ${isLong ? "border-tertiary-dim" : "border-error"}`}
          >
            <div className={`text-sm font-headline font-bold mb-2 ${isLong ? "text-tertiary-dim" : "text-error"}`}>
              {dir}
            </div>
            <div className={`text-2xl font-headline font-bold tabular-nums ${d.win_rate >= 50 ? "text-tertiary-dim" : "text-error"}`}>
              {d.win_rate}%
            </div>
            <div className="text-xs text-on-surface-variant mt-1">{d.total} trades</div>
            <div className={`text-xs font-mono tabular-nums mt-0.5 ${d.avg_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
              {d.avg_pnl >= 0 ? "+" : ""}{d.avg_pnl.toFixed(2)}% avg
            </div>
          </Card>
        );
      })}
    </div>
  );
}

// ─── PnlDistribution ────────────────────────────────────────────

function PnlDistribution({ data }: { data: SignalStats["pnl_distribution"] }) {
  if (data.length === 0) return null;

  const maxCount = Math.max(...data.map((d) => d.count));
  const width = 320;
  const height = 80;
  const pad = { top: 5, right: 10, bottom: 15, left: 10 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;
  const barWidth = Math.max(w / data.length - 2, 4);

  return (
    <Card border={false}>
      <SectionLabel>P&L Distribution</SectionLabel>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none" role="img" aria-label={`P&L distribution across ${data.length} buckets`}>
        {data.map((d, i) => {
          const barH = (d.count / maxCount) * h;
          const x = pad.left + (i / data.length) * w;
          const y = pad.top + h - barH;
          const fill = d.bucket >= 0 ? theme.colors.long : theme.colors.short;
          return (
            <rect key={i} x={x} y={y} width={barWidth} height={barH} fill={fill} opacity={0.7} rx={1} />
          );
        })}
        {(() => {
          const zeroIdx = data.findIndex((d) => d.bucket >= 0);
          if (zeroIdx < 0 || !data.some((d) => d.bucket < 0)) return null;
          const x = pad.left + (zeroIdx / data.length) * w;
          return (
            <line x1={x} y1={pad.top} x2={x} y2={pad.top + h} stroke={theme.colors["outline-variant"]} strokeWidth="0.5" strokeDasharray="3" />
          );
        })()}
      </svg>
    </Card>
  );
}

// ─── StreakTracker ────────────────────────────────────────────────

function StreakTracker({ streaks }: { streaks: SignalStats["streaks"] }) {
  return (
    <Card border={false}>
      <SectionLabel className="mb-3">Streaks</SectionLabel>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className={`text-lg font-headline font-bold tabular-nums ${streaks.current >= 0 ? "text-tertiary-dim" : "text-error"}`}>
            {streaks.current >= 0 ? `+${streaks.current}` : streaks.current}
          </div>
          <div className="text-xs text-on-surface-variant">Current</div>
        </div>
        <div>
          <div className="text-lg font-headline font-bold tabular-nums text-tertiary-dim">+{streaks.best_win}</div>
          <div className="text-xs text-on-surface-variant">Best Win</div>
        </div>
        <div>
          <div className="text-lg font-headline font-bold tabular-nums text-error">{streaks.worst_loss}</div>
          <div className="text-xs text-on-surface-variant">Worst Loss</div>
        </div>
      </div>
    </Card>
  );
}

// ─── NotableTrades ───────────────────────────────────────────────

function NotableTrades({ perf }: { perf: PerformanceMetrics }) {
  if (!perf.best_trade && !perf.worst_trade) return null;

  return (
    <Card border={false}>
      <SectionLabel className="mb-3">Notable Trades</SectionLabel>
      <div className="space-y-1.5">
        {perf.best_trade && (
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <Badge color="long">BEST</Badge>
              <span className="text-on-surface-variant">
                {formatPair(perf.best_trade.pair)} {perf.best_trade.timeframe} {perf.best_trade.direction}
              </span>
            </div>
            <span className="font-mono text-long tabular-nums">+{perf.best_trade.pnl_pct}%</span>
          </div>
        )}
        {perf.worst_trade && (
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <Badge color="short">WORST</Badge>
              <span className="text-on-surface-variant">
                {formatPair(perf.worst_trade.pair)} {perf.worst_trade.timeframe} {perf.worst_trade.direction}
              </span>
            </div>
            <span className="font-mono text-short tabular-nums">{perf.worst_trade.pnl_pct}%</span>
          </div>
        )}
      </div>
    </Card>
  );
}

// ─── RiskProfile ─────────────────────────────────────────────────

function RiskProfile({ perf, totalResolved }: { perf: PerformanceMetrics; totalResolved: number }) {
  const showDash = totalResolved < 5;

  return (
    <Card border={false}>
      <SectionLabel className="mb-3">Risk Profile</SectionLabel>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className={`text-base font-headline font-bold tabular-nums ${
            showDash || perf.profit_factor == null ? "text-on-surface" : perf.profit_factor > 1 ? "text-tertiary-dim" : "text-error"
          }`}>
            {showDash || perf.profit_factor == null ? "—" : perf.profit_factor}
          </div>
          <div className="text-xs text-on-surface-variant">Profit Factor</div>
        </div>
        <div>
          <div className={`text-base font-headline font-bold tabular-nums ${perf.max_drawdown_pct > 3 ? "text-error" : "text-on-surface"}`}>
            {perf.max_drawdown_pct > 0 ? `-${perf.max_drawdown_pct}%` : "0%"}
          </div>
          <div className="text-xs text-on-surface-variant">Max Drawdown</div>
        </div>
        <div>
          <div className="text-base font-headline font-bold tabular-nums text-on-surface">
            {formatDuration(perf.avg_hold_time_minutes)}
          </div>
          <div className="text-xs text-on-surface-variant">Avg Hold Time</div>
        </div>
      </div>
    </Card>
  );
}

