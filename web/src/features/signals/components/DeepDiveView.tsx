import { useState } from "react";
import { useSignalStats } from "../../home/hooks/useSignalStats";
import { theme } from "../../../shared/theme";
import { formatPair } from "../../../shared/lib/format";
import type { SignalStats, PerformanceMetrics } from "../types";

type Period = "7" | "30" | "365";

const PERIODS: { value: Period; label: string }[] = [
  { value: "7", label: "7D" },
  { value: "30", label: "30D" },
  { value: "365", label: "All" },
];

export function DeepDiveView() {
  const [period, setPeriod] = useState<Period>("30");
  const { stats, loading } = useSignalStats(Number(period));

  if (loading) {
    return (
      <div className="p-3 space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 bg-surface-container rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (!stats || stats.total_resolved < 5) {
    return (
      <div className="p-3">
        <p className="text-on-surface-variant text-center text-sm mt-12">
          Need more resolved trades to show metrics
        </p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3 overflow-y-auto">
      {/* Period selector */}
      <div className="flex gap-1 bg-surface-container-lowest p-1 rounded-lg w-fit">
        {PERIODS.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => setPeriod(value)}
            className={`px-3 py-1.5 text-xs font-semibold rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              period === value
                ? "bg-surface-container-highest text-primary"
                : "text-on-surface-variant hover:bg-surface-container-highest"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <MetricsGrid perf={stats.performance} totalResolved={stats.total_resolved} />
      <BestWorstTrades perf={stats.performance} />
      <DrawdownChart data={stats.drawdown_series} />
      <PnlDistribution data={stats.pnl_distribution} />
    </div>
  );
}

function MetricsGrid({ perf, totalResolved }: { perf: PerformanceMetrics; totalResolved: number }) {
  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-3">Performance Metrics</h3>
      <div className="grid grid-cols-3 gap-3 text-center">
        <MetricCell
          label="Sharpe"
          value={perf.sharpe_ratio != null ? String(perf.sharpe_ratio) : "—"}
          tooltip={perf.sharpe_ratio == null ? "Not enough data (need 7+ days)" : undefined}
          color={perf.sharpe_ratio != null && perf.sharpe_ratio > 0 ? "text-long" : perf.sharpe_ratio != null ? "text-short" : "text-outline"}
        />
        <MetricCell
          label="Profit F"
          value={perf.profit_factor != null ? String(perf.profit_factor) : "—"}
          tooltip={perf.profit_factor == null ? "No losing trades" : undefined}
          color={perf.profit_factor != null && perf.profit_factor > 1 ? "text-long" : perf.profit_factor != null ? "text-short" : "text-outline"}
        />
        <MetricCell
          label="Max DD"
          value={perf.max_drawdown_pct > 0 ? `-${perf.max_drawdown_pct}%` : "0%"}
          color={perf.max_drawdown_pct > 3 ? "text-short" : "text-on-surface"}
        />
        <MetricCell
          label="Expectancy"
          value={perf.expectancy != null ? `${perf.expectancy >= 0 ? "+" : ""}${perf.expectancy}%` : "—"}
          color={perf.expectancy != null && perf.expectancy >= 0 ? "text-long" : perf.expectancy != null ? "text-short" : "text-outline"}
        />
        <MetricCell
          label="Avg Hold"
          value={perf.avg_hold_time_minutes != null ? formatHoldTime(perf.avg_hold_time_minutes) : "—"}
          color="text-on-surface"
        />
        <MetricCell
          label="Trades"
          value={String(totalResolved)}
          color="text-on-surface"
        />
      </div>
    </div>
  );
}

function MetricCell({ label, value, color, tooltip }: {
  label: string;
  value: string;
  color: string;
  tooltip?: string;
}) {
  return (
    <div title={tooltip}>
      <div className={`text-base font-headline font-bold tabular-nums ${color}`}>{value}</div>
      <div className="text-[10px] text-on-surface-variant">{label}</div>
    </div>
  );
}

function BestWorstTrades({ perf }: { perf: PerformanceMetrics }) {
  if (!perf.best_trade && !perf.worst_trade) return null;

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-3">Notable Trades</h3>
      <div className="space-y-1.5">
        {perf.best_trade && (
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-long bg-long/10 px-1.5 py-0.5 rounded">BEST</span>
              <span className="text-on-surface-variant">
                {formatPair(perf.best_trade.pair)} {perf.best_trade.timeframe} {perf.best_trade.direction}
              </span>
            </div>
            <span className="font-mono text-long tabular">+{perf.best_trade.pnl_pct}%</span>
          </div>
        )}
        {perf.worst_trade && (
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-short bg-short/10 px-1.5 py-0.5 rounded">WORST</span>
              <span className="text-on-surface-variant">
                {formatPair(perf.worst_trade.pair)} {perf.worst_trade.timeframe} {perf.worst_trade.direction}
              </span>
            </div>
            <span className="font-mono text-short tabular">{perf.worst_trade.pnl_pct}%</span>
          </div>
        )}
      </div>
    </div>
  );
}

function DrawdownChart({ data }: { data: SignalStats["drawdown_series"] }) {
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
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">Drawdown</h3>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none">
        <polygon fill={theme.colors.short + "15"} points={fillPoints} />
        <polyline fill="none" stroke={theme.colors.short} strokeWidth="1.5" strokeLinejoin="round" points={points} />
        <text x={width - pad.right} y={height - 2} textAnchor="end" fontSize="8" fill={theme.colors.outline}>
          {minVal.toFixed(1)}%
        </text>
      </svg>
    </div>
  );
}

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
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">P&L Distribution</h3>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none">
        {data.map((d, i) => {
          const barH = (d.count / maxCount) * h;
          const x = pad.left + (i / data.length) * w;
          const y = pad.top + h - barH;
          const fill = d.bucket >= 0 ? theme.colors.long : theme.colors.short;
          return (
            <rect
              key={i}
              x={x}
              y={y}
              width={barWidth}
              height={barH}
              fill={fill}
              opacity={0.7}
              rx={1}
            />
          );
        })}
        {(() => {
          const zeroIdx = data.findIndex(d => d.bucket >= 0);
          if (zeroIdx < 0 || !data.some(d => d.bucket < 0)) return null;
          const x = pad.left + (zeroIdx / data.length) * w;
          return (
            <line x1={x} y1={pad.top} x2={x} y2={pad.top + h}
              stroke={theme.colors["outline-variant"]}
              strokeWidth="0.5"
              strokeDasharray="3"
            />
          );
        })()}
      </svg>
    </div>
  );
}

function formatHoldTime(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}
