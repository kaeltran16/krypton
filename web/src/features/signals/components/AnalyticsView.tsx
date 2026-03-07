import { useState } from "react";
import { useSignalStats } from "../../home/hooks/useSignalStats";
import type { SignalStats } from "../types";

type Period = "7" | "30" | "365";

const PERIODS: { value: Period; label: string }[] = [
  { value: "7", label: "7D" },
  { value: "30", label: "30D" },
  { value: "365", label: "All" },
];

export function AnalyticsView() {
  const [period, setPeriod] = useState<Period>("7");
  const [tradedOnly, setTradedOnly] = useState(false);
  const { stats, loading } = useSignalStats(Number(period));

  if (loading) {
    return (
      <div className="p-3 space-y-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 bg-card rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (!stats || stats.total_resolved === 0) {
    return (
      <div className="p-3">
        <p className="text-gray-500 text-center text-sm mt-12">
          No resolved signals yet — analytics will appear as signals resolve
        </p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3 overflow-y-auto">
      {/* Period selector */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1.5">
          {PERIODS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setPeriod(value)}
              className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                period === value ? "bg-gray-700 text-white" : "text-gray-500 border border-gray-800"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          onClick={() => setTradedOnly(!tradedOnly)}
          className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
            tradedOnly ? "bg-long/20 text-long border border-long/40" : "text-gray-500 border border-gray-800"
          }`}
        >
          Traded only
        </button>
      </div>

      {/* Performance Summary */}
      <SummaryStrip stats={stats} />

      {/* Equity Curve */}
      <EquityCurve data={stats.equity_curve} />

      {/* Time-of-Day Heatmap */}
      <HourlyHeatmap data={stats.hourly_performance} />

      {/* Pair Breakdown */}
      <PairBreakdown data={stats.by_pair} />

      {/* Streak Tracker */}
      <StreakTracker streaks={stats.streaks} />
    </div>
  );
}

function SummaryStrip({ stats }: { stats: SignalStats }) {
  const netPnl = stats.equity_curve.length > 0
    ? stats.equity_curve[stats.equity_curve.length - 1].cumulative_pnl
    : 0;

  return (
    <div className="bg-card rounded-lg p-3">
      <div className="grid grid-cols-4 gap-2 text-center">
        <StatCell label="Win Rate" value={`${stats.win_rate}%`} color={stats.win_rate >= 50 ? "text-long" : "text-short"} />
        <StatCell label="Avg R:R" value={`${stats.avg_rr}`} color="text-white" />
        <StatCell label="Signals" value={`${stats.total_resolved}`} color="text-white" />
        <StatCell
          label="Net P&L"
          value={`${netPnl >= 0 ? "+" : ""}${netPnl.toFixed(1)}%`}
          color={netPnl >= 0 ? "text-long" : "text-short"}
        />
      </div>
    </div>
  );
}

function StatCell({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div className={`text-base font-mono font-bold ${color}`}>{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
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

  const zeroY = pad.top + h - ((0 - minVal) / range) * h;
  const lastVal = values[values.length - 1];
  const lineColor = lastVal >= 0 ? "#22C55E" : "#EF4444";

  return (
    <div className="bg-card rounded-lg p-3">
      <h3 className="text-xs text-gray-400 mb-2">Equity Curve</h3>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none">
        <line x1={pad.left} y1={zeroY} x2={width - pad.right} y2={zeroY} stroke="#374151" strokeWidth="0.5" strokeDasharray="4" />
        <polyline fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" points={points} />
      </svg>
    </div>
  );
}

function HourlyHeatmap({ data }: { data: SignalStats["hourly_performance"] }) {
  const maxAbs = Math.max(...data.map((d) => Math.abs(d.avg_pnl)), 0.01);

  return (
    <div className="bg-card rounded-lg p-3">
      <h3 className="text-xs text-gray-400 mb-2">Time of Day</h3>
      <div className="grid grid-cols-12 gap-0.5">
        {data.map((d) => {
          const intensity = Math.min(Math.abs(d.avg_pnl) / maxAbs, 1);
          const bg =
            d.count === 0
              ? "bg-gray-800"
              : d.avg_pnl >= 0
                ? `bg-long`
                : `bg-short`;
          return (
            <div
              key={d.hour}
              className={`aspect-square rounded-sm flex items-center justify-center ${bg}`}
              style={{ opacity: d.count === 0 ? 0.3 : 0.2 + intensity * 0.8 }}
              title={`${d.hour}:00 — avg ${d.avg_pnl.toFixed(2)}% (${d.count} signals)`}
            >
              <span className="text-[8px] text-white/70">{d.hour}</span>
            </div>
          );
        })}
      </div>
      <div className="flex justify-between mt-1 text-[9px] text-gray-600">
        <span>0h</span>
        <span>12h</span>
        <span>23h</span>
      </div>
    </div>
  );
}

function PairBreakdown({ data }: { data: SignalStats["by_pair"] }) {
  const pairs = Object.entries(data);
  if (pairs.length === 0) return null;

  return (
    <div className="bg-card rounded-lg p-3">
      <h3 className="text-xs text-gray-400 mb-2">Pair Breakdown</h3>
      <div className="space-y-2">
        {pairs.map(([pair, stats]) => (
          <div key={pair} className="flex items-center justify-between text-sm">
            <span className="font-medium">{pair.replace("-USDT-SWAP", "")}</span>
            <div className="flex items-center gap-3 text-xs font-mono">
              <span className={stats.win_rate >= 50 ? "text-long" : "text-short"}>
                {stats.win_rate}%
              </span>
              <span className={stats.avg_pnl >= 0 ? "text-long" : "text-short"}>
                {stats.avg_pnl >= 0 ? "+" : ""}{stats.avg_pnl.toFixed(2)}%
              </span>
              <span className="text-gray-500">{stats.total} trades</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StreakTracker({ streaks }: { streaks: SignalStats["streaks"] }) {
  return (
    <div className="bg-card rounded-lg p-3">
      <h3 className="text-xs text-gray-400 mb-2">Streaks</h3>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className={`text-lg font-mono font-bold ${streaks.current >= 0 ? "text-long" : "text-short"}`}>
            {streaks.current >= 0 ? `+${streaks.current}` : streaks.current}
          </div>
          <div className="text-xs text-gray-500">Current</div>
        </div>
        <div>
          <div className="text-lg font-mono font-bold text-long">+{streaks.best_win}</div>
          <div className="text-xs text-gray-500">Best Win</div>
        </div>
        <div>
          <div className="text-lg font-mono font-bold text-short">{streaks.worst_loss}</div>
          <div className="text-xs text-gray-500">Worst Loss</div>
        </div>
      </div>
    </div>
  );
}
