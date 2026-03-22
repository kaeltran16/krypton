import { useState, useEffect } from "react";
import { TrendingUp, TrendingDown } from "lucide-react";
import { api } from "../../../shared/lib/api";
import { formatPair, formatTime } from "../../../shared/lib/format";
import { hexToRgba, theme } from "../../../shared/theme";
import { useSignalsByDate } from "../hooks/useSignalsByDate";
import type { CalendarDay, CalendarResponse, Signal } from "../types";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function formatMonth(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

function getMonthName(year: number, month: number): string {
  return new Date(year, month - 1).toLocaleString("en", { month: "long", year: "numeric" });
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

function getStartDay(year: number, month: number): number {
  const day = new Date(year, month - 1, 1).getDay();
  return day === 0 ? 6 : day - 1;
}

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function CalendarView() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [prevFetchKey, setPrevFetchKey] = useState("");

  const fetchKey = `${year}-${month}-${retryCount}`;
  if (fetchKey !== prevFetchKey) {
    setPrevFetchKey(fetchKey);
    setLoading(true);
    setError(false);
  }

  useEffect(() => {
    let cancelled = false;
    api
      .getSignalCalendar(formatMonth(year, month))
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setSelectedDay(null);
        }
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [year, month, retryCount]);

  const prevMonth = () => {
    if (month === 1) { setYear(year - 1); setMonth(12); }
    else setMonth(month - 1);
  };
  const nextMonth = () => {
    if (month === 12) { setYear(year + 1); setMonth(1); }
    else setMonth(month + 1);
  };

  const dayMap = new Map<string, CalendarDay>();
  data?.days.forEach((d) => dayMap.set(d.date, d));

  const daysInMonth = getDaysInMonth(year, month);
  const startDay = getStartDay(year, month);
  const today = todayStr();
  const summary = data?.monthly_summary;

  const pnlMagnitudes = data?.days
    .map((d) => Math.abs(d.net_pnl))
    .filter((v) => v > 0)
    .sort((a, b) => a - b) ?? [];
  const p90 = pnlMagnitudes.length > 0
    ? pnlMagnitudes[Math.floor(pnlMagnitudes.length * 0.9)] || pnlMagnitudes[pnlMagnitudes.length - 1]
    : 1;

  return (
    <div className="p-3 space-y-3">
      {/* Monthly summary */}
      {summary && summary.total_signals > 0 && (
        <div className="bg-surface-container rounded-lg p-3">
          <div className="grid grid-cols-4 gap-2 text-center text-xs">
            <div>
              <div className="font-mono font-bold text-on-surface tabular-nums">{summary.total_signals}</div>
              <div className="text-on-surface-variant">Signals</div>
            </div>
            <div>
              <div className={`font-mono font-bold tabular-nums ${summary.net_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
                {summary.net_pnl >= 0 ? "+" : ""}{summary.net_pnl.toFixed(1)}%
              </div>
              <div className="text-on-surface-variant">Net P&L</div>
            </div>
            <div>
              <div className="font-mono font-bold tabular-nums text-tertiary-dim">{summary.best_day?.slice(8) ?? "—"}</div>
              <div className="text-on-surface-variant">Best Day</div>
            </div>
            <div>
              <div className="font-mono font-bold tabular-nums text-error">{summary.worst_day?.slice(8) ?? "—"}</div>
              <div className="text-on-surface-variant">Worst Day</div>
            </div>
          </div>
        </div>
      )}

      {/* Month navigation */}
      <div className="flex items-center justify-between">
        <button onClick={prevMonth} aria-label="Previous month" className="text-on-surface-variant hover:text-on-surface px-2 py-1 text-lg focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">&larr;</button>
        <span className="text-sm font-headline font-bold">{getMonthName(year, month)}</span>
        <button onClick={nextMonth} aria-label="Next month" className="text-on-surface-variant hover:text-on-surface px-2 py-1 text-lg focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">&rarr;</button>
      </div>

      {loading ? (
        <div className="h-64 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none" />
      ) : error ? (
        <div className="text-center py-8">
          <p className="text-on-surface-variant text-sm mb-2">Failed to load calendar</p>
          <button onClick={() => setRetryCount((c) => c + 1)} className="text-xs text-primary focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">Retry</button>
        </div>
      ) : (
        <>
          {/* Calendar grid */}
          <div className="bg-surface-container rounded-lg p-2">
            {/* Weekday headers */}
            <div className="grid grid-cols-7 gap-1 mb-1">
              {WEEKDAYS.map((d) => (
                <div key={d} className="text-center text-xs text-on-surface-variant font-bold uppercase py-1">{d}</div>
              ))}
            </div>

            {/* Day cells */}
            <div className="grid grid-cols-7 gap-1">
              {Array.from({ length: startDay }).map((_, i) => (
                <div key={`empty-${i}`} className="aspect-square rounded-lg bg-surface-container-highest/30" />
              ))}

              {Array.from({ length: daysInMonth }).map((_, i) => {
                const dayNum = i + 1;
                const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(dayNum).padStart(2, "0")}`;
                const dayData = dayMap.get(dateStr);
                const isToday = dateStr === today;
                const isSelected = dateStr === selectedDay;

                // P&L tinting with intensity scaled to magnitude, capped at p90
                let bgStyle: React.CSSProperties | undefined;
                if (dayData && dayData.net_pnl !== 0) {
                  const intensity = Math.min(Math.abs(dayData.net_pnl) / p90, 1);
                  const opacity = 0.05 + intensity * 0.15;
                  bgStyle = {
                    backgroundColor: dayData.net_pnl > 0
                      ? hexToRgba(theme.colors.long, opacity)
                      : hexToRgba(theme.colors.short, opacity),
                  };
                }

                return (
                  <button
                    key={dayNum}
                    onClick={() => setSelectedDay(isSelected ? null : dateStr)}
                    className={`aspect-square rounded-lg flex flex-col items-center justify-center p-1 transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                      !dayData && !isToday ? "bg-surface-container-highest/30" : ""
                    } ${
                      isSelected ? "ring-2 ring-primary" : ""
                    } ${isToday ? "border border-primary/40" : ""}`}
                    style={bgStyle}
                  >
                    <span className={`text-xs ${isToday ? "text-primary font-bold" : "text-on-surface-variant"}`}>
                      {dayNum}
                    </span>
                    {isToday && (
                      <span className="text-[8px] text-primary font-bold leading-none">TODAY</span>
                    )}
                    {dayData && (
                      <span className={`text-[10px] font-mono tabular-nums leading-none ${dayData.net_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
                        {dayData.net_pnl >= 0 ? "+" : ""}{dayData.net_pnl.toFixed(1)}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Selected day detail with signal cards */}
          {selectedDay && <DayDetail date={selectedDay} dayData={dayMap.get(selectedDay)} />}
        </>
      )}
    </div>
  );
}

// ─── DayDetail ───────────────────────────────────────────────────

function DayDetail({ date, dayData }: { date: string; dayData?: CalendarDay }) {
  const { signals, loading: signalsLoading, error: signalsError, retry } = useSignalsByDate(date);

  return (
    <div className="max-h-[400px] overflow-y-auto space-y-3">
      {/* Summary bar */}
      {dayData && dayData.signal_count > 0 && (
        <div className="bg-surface-container rounded-lg p-3">
          <div className="flex items-center justify-center gap-4 text-sm">
            <span className={`font-mono font-bold tabular-nums ${dayData.net_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
              {dayData.net_pnl >= 0 ? "+" : ""}{dayData.net_pnl.toFixed(2)}% P&L
            </span>
            <span className="text-outline-variant">|</span>
            <span className="font-mono font-bold text-tertiary-dim tabular-nums">{dayData.wins}W</span>
            <span className="text-outline-variant">|</span>
            <span className="font-mono font-bold text-error tabular-nums">{dayData.losses}L</span>
          </div>
        </div>
      )}

      {/* Signal cards */}
      {signalsLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none" />
          ))}
        </div>
      ) : signalsError ? (
        <div className="bg-surface-container rounded-lg p-3 text-center">
          <p className="text-on-surface-variant text-sm mb-2">Failed to load signals</p>
          <button onClick={retry} className="text-xs text-primary focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">Retry</button>
        </div>
      ) : signals.length === 0 ? (
        <div className="bg-surface-container rounded-lg p-3 text-center">
          <p className="text-on-surface-variant text-sm">No signals on {date}</p>
        </div>
      ) : (
        signals.map((signal) => <SignalDayCard key={signal.id} signal={signal} />)
      )}
    </div>
  );
}

// ─── SignalDayCard ────────────────────────────────────────────────

function SignalDayCard({ signal }: { signal: Signal }) {
  const isLong = signal.direction === "LONG";

  const outcomeBadge = signal.outcome !== "PENDING" ? (
    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
      (signal.outcome === "TP1_HIT" || signal.outcome === "TP2_HIT") ? "bg-long/10 text-long" :
      signal.outcome === "EXPIRED" ? "bg-outline-variant/20 text-on-surface-variant" :
      "bg-short/10 text-short"
    }`}>
      {signal.outcome.replace("_", " ")}
    </span>
  ) : null;

  return (
    <div className={`bg-surface-container rounded-lg p-3 flex items-center gap-3 border-l-[3px] ${isLong ? "border-tertiary-dim" : "border-error"}`}>
      {/* Direction icon */}
      <div className={`w-8 h-8 rounded-full flex items-center justify-center ${isLong ? "bg-long/10" : "bg-short/10"}`}>
        {isLong ? <TrendingUp size={16} className="text-long" /> : <TrendingDown size={16} className="text-short" />}
      </div>

      {/* Middle: pair, direction, timeframe, score, time */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-headline font-bold text-sm">{formatPair(signal.pair)}/USDT</span>
          <span className={`text-[10px] font-bold uppercase ${isLong ? "text-long" : "text-short"}`}>{signal.direction}</span>
        </div>
        <div className="text-xs text-on-surface-variant mt-0.5">
          {signal.timeframe} &middot; Score {Math.abs(signal.final_score).toFixed(0)} &middot; {formatTime(signal.created_at)}
        </div>
      </div>

      {/* Right: P&L, outcome */}
      <div className="text-right shrink-0">
        {signal.outcome_pnl_pct != null && (
          <div className={`font-mono font-bold text-sm tabular-nums ${signal.outcome_pnl_pct >= 0 ? "text-long" : "text-short"}`}>
            {signal.outcome_pnl_pct >= 0 ? "+" : ""}{signal.outcome_pnl_pct.toFixed(2)}%
          </div>
        )}
        {outcomeBadge}
      </div>
    </div>
  );
}
