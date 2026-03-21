import { useState, useEffect } from "react";
import { api } from "../../../shared/lib/api";
import type { CalendarDay, CalendarResponse } from "../types";

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

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
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
  }, [year, month]);

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
          <button onClick={() => { setLoading(true); setError(false); api.getSignalCalendar(formatMonth(year, month)).then(setData).catch(() => setError(true)).finally(() => setLoading(false)); }} className="text-xs text-primary focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">Retry</button>
        </div>
      ) : (
        <>
          {/* Calendar grid */}
          <div className="bg-surface-container rounded-lg p-2">
            {/* Weekday headers */}
            <div className="grid grid-cols-7 gap-0.5 mb-1">
              {WEEKDAYS.map((d) => (
                <div key={d} className="text-center text-xs text-on-surface-variant font-bold uppercase py-1">{d}</div>
              ))}
            </div>

            {/* Day cells */}
            <div className="grid grid-cols-7 gap-0.5">
              {Array.from({ length: startDay }).map((_, i) => (
                <div key={`empty-${i}`} />
              ))}

              {Array.from({ length: daysInMonth }).map((_, i) => {
                const dayNum = i + 1;
                const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(dayNum).padStart(2, "0")}`;
                const dayData = dayMap.get(dateStr);
                const isToday = dateStr === today;
                const isSelected = dateStr === selectedDay;

                let bgTint = "";
                if (dayData) {
                  if (dayData.net_pnl > 0) bgTint = "bg-tertiary-dim/10";
                  else if (dayData.net_pnl < 0) bgTint = "bg-error/10";
                }

                return (
                  <button
                    key={dayNum}
                    onClick={() => setSelectedDay(isSelected ? null : dateStr)}
                    className={`aspect-square rounded-md flex flex-col items-center justify-center p-0.5 transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${bgTint} ${
                      isSelected ? "ring-1 ring-primary" : ""
                    } ${isToday ? "border border-outline-variant/10" : ""}`}
                  >
                    <span className={`text-xs ${isToday ? "text-primary font-bold" : "text-on-surface-variant"}`}>
                      {dayNum}
                    </span>
                    {dayData && (
                      <>
                        <span className="text-xs text-on-surface-variant">{dayData.signal_count}s</span>
                        <span className={`text-xs font-mono tabular-nums ${dayData.net_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
                          {dayData.net_pnl >= 0 ? "+" : ""}{dayData.net_pnl.toFixed(1)}
                        </span>
                      </>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Selected day signals list */}
          {selectedDay && <DaySignalsList date={selectedDay} dayData={dayMap.get(selectedDay)} />}
        </>
      )}
    </div>
  );
}

function DaySignalsList({ date, dayData }: { date: string; dayData?: CalendarDay }) {
  if (!dayData || dayData.signal_count === 0) {
    return (
      <div className="bg-surface-container rounded-lg p-3 text-center">
        <p className="text-on-surface-variant text-sm">No signals on {date}</p>
      </div>
    );
  }

  return (
    <div className="bg-surface-container rounded-lg p-3">
      <h3 className="text-xs text-on-surface-variant mb-2">{date}</h3>
      <div className="grid grid-cols-3 gap-2 text-center text-sm">
        <div>
          <div className="font-mono font-bold text-on-surface tabular-nums">{dayData.signal_count}</div>
          <div className="text-xs text-on-surface-variant">Signals</div>
        </div>
        <div>
          <div className="font-mono font-bold text-tertiary-dim tabular-nums">{dayData.wins}W</div>
          <div className="text-xs text-on-surface-variant">Wins</div>
        </div>
        <div>
          <div className="font-mono font-bold text-error tabular-nums">{dayData.losses}L</div>
          <div className="text-xs text-on-surface-variant">Losses</div>
        </div>
      </div>
      <div className={`text-center mt-2 font-mono font-bold tabular-nums ${dayData.net_pnl >= 0 ? "text-tertiary-dim" : "text-error"}`}>
        {dayData.net_pnl >= 0 ? "+" : ""}{dayData.net_pnl.toFixed(2)}% P&L
      </div>
    </div>
  );
}
