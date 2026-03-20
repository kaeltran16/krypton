import { useState } from "react";
import { useSignalStats } from "../../home/hooks/useSignalStats";
import { theme } from "../../../shared/theme";
import type { SignalStats } from "../types";

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
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none" />
        ))}
      </div>
    );
  }

  if (!stats || stats.total_resolved === 0) {
    return (
      <div className="p-3">
        <p className="text-on-surface-variant text-center text-sm mt-12">
          No resolved signals yet — analytics will appear as signals resolve
        </p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3 overflow-y-auto">
      {/* Period selector */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1 bg-surface-container-low p-1 rounded-lg">
          {PERIODS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setPeriod(value)}
              className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                period === value
                  ? "bg-surface-container-highest text-primary shadow-[0_0_8px_rgba(105,218,255,0.15)]"
                  : "text-on-surface-variant"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <SummaryBento stats={stats} />
      <EquityCurve data={stats.equity_curve} />
      <PairBreakdown data={stats.by_pair} />
      <StreakTracker streaks={stats.streaks} />
    </div>
  );
}

function SummaryBento({ stats }: { stats: SignalStats }) {
  const netPnl = stats.equity_curve.length > 0
    ? stats.equity_curve[stats.equity_curve.length - 1].cumulative_pnl
    : 0;

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* P&L card — spans 2 cols */}
      <div className="col-span-2 bg-surface-container rounded-lg p-4 border-l-4 border-tertiary-dim">
        <div className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-1">Net P&L</div>
        <div className={`font-headline text-3xl font-bold tabular-nums ${netPnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
          {netPnl >= 0 ? "+" : ""}{netPnl.toFixed(1)}%
        </div>
      </div>
      <div className="bg-surface-container rounded-lg p-4">
        <div className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-1">Win Rate</div>
        <div className={`font-headline text-2xl font-bold tabular-nums ${stats.win_rate >= 50 ? "text-tertiary-dim" : "text-error"}`}>
          {stats.win_rate}%
        </div>
      </div>
      <div className="bg-surface-container rounded-lg p-4">
        <div className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-1">Avg R:R</div>
        <div className="font-headline text-2xl font-bold tabular-nums text-on-surface">{stats.avg_rr}</div>
      </div>
      <div className="bg-surface-container rounded-lg p-4 col-span-2">
        <div className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-1">Signals Resolved</div>
        <div className="font-headline text-2xl font-bold tabular-nums text-on-surface">{stats.total_resolved}</div>
      </div>
    </div>
  );
}

function EquityCurve({ data }: { data: SignalStats["equity_curve"] }) {
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

  // Build area fill points
  const areaPoints = data
    .map((d, i) => {
      const x = pad.left + (i / (data.length - 1)) * w;
      const y = pad.top + h - ((d.cumulative_pnl - minVal) / range) * h;
      return `${x},${y}`;
    });
  const fillPath = `${pad.left},${pad.top + h} ${areaPoints.join(" ")} ${pad.left + w},${pad.top + h}`;

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-2">Equity Curve</h3>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none">
        <defs>
          <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.3" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
          </linearGradient>
        </defs>
        <polygon fill="url(#chartGradient)" points={fillPath} />
        <polyline fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" points={points} />
      </svg>
    </div>
  );
}

function PairBreakdown({ data }: { data: SignalStats["by_pair"] }) {
  const pairs = Object.entries(data);
  if (pairs.length === 0) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest px-1">Pair Breakdown</h3>
      {pairs.map(([pair, stats]) => (
        <div key={pair} className="bg-surface-container rounded-lg p-4 hover:bg-surface-container-high transition-colors">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-surface-container-highest flex items-center justify-center">
              <span className="font-headline font-bold text-xs text-primary">{pair.replace("-USDT-SWAP", "").slice(0, 3)}</span>
            </div>
            <div className="flex-1">
              <span className="font-headline font-bold text-sm">{pair.replace("-USDT-SWAP", "")}/USDT</span>
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
        </div>
      ))}
    </div>
  );
}

function StreakTracker({ streaks }: { streaks: SignalStats["streaks"] }) {
  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-3">Streaks</h3>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className={`text-lg font-headline font-bold tabular-nums ${streaks.current >= 0 ? "text-tertiary-dim" : "text-error"}`}>
            {streaks.current >= 0 ? `+${streaks.current}` : streaks.current}
          </div>
          <div className="text-[10px] text-on-surface-variant">Current</div>
        </div>
        <div>
          <div className="text-lg font-headline font-bold tabular-nums text-tertiary-dim">+{streaks.best_win}</div>
          <div className="text-[10px] text-on-surface-variant">Best Win</div>
        </div>
        <div>
          <div className="text-lg font-headline font-bold tabular-nums text-error">{streaks.worst_loss}</div>
          <div className="text-[10px] text-on-surface-variant">Worst Loss</div>
        </div>
      </div>
    </div>
  );
}
