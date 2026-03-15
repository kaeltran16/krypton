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
  // 0=Mon, 6=Sun
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
        <div className="bg-card rounded-lg p-3">
          <div className="grid grid-cols-4 gap-2 text-center text-xs">
            <div>
              <div className="font-mono font-bold text-foreground">{summary.total_signals}</div>
              <div className="text-muted">Signals</div>
            </div>
            <div>
              <div className={`font-mono font-bold ${summary.net_pnl >= 0 ? "text-long" : "text-short"}`}>
                {summary.net_pnl >= 0 ? "+" : ""}{summary.net_pnl.toFixed(1)}%
              </div>
              <div className="text-muted">Net P&L</div>
            </div>
            <div>
              <div className="font-mono font-bold text-long">{summary.best_day?.slice(8) ?? "—"}</div>
              <div className="text-muted">Best Day</div>
            </div>
            <div>
              <div className="font-mono font-bold text-short">{summary.worst_day?.slice(8) ?? "—"}</div>
              <div className="text-muted">Worst Day</div>
            </div>
          </div>
        </div>
      )}

      {/* Month navigation */}
      <div className="flex items-center justify-between">
        <button onClick={prevMonth} className="text-muted hover:text-foreground px-2 py-1 text-lg">&larr;</button>
        <span className="text-sm font-medium">{getMonthName(year, month)}</span>
        <button onClick={nextMonth} className="text-muted hover:text-foreground px-2 py-1 text-lg">&rarr;</button>
      </div>

      {loading ? (
        <div className="h-64 bg-card rounded-lg animate-pulse" />
      ) : error ? (
        <div className="text-center py-8">
          <p className="text-muted text-sm mb-2">Failed to load calendar</p>
          <button onClick={() => { setLoading(true); setError(false); api.getSignalCalendar(formatMonth(year, month)).then(setData).catch(() => setError(true)).finally(() => setLoading(false)); }} className="text-xs text-long">Retry</button>
        </div>
      ) : (
        <>
          {/* Calendar grid */}
          <div className="bg-card rounded-lg p-2">
            {/* Weekday headers */}
            <div className="grid grid-cols-7 gap-0.5 mb-1">
              {WEEKDAYS.map((d) => (
                <div key={d} className="text-center text-[11px] text-muted py-1">{d}</div>
              ))}
            </div>

            {/* Day cells */}
            <div className="grid grid-cols-7 gap-0.5">
              {/* Empty cells for offset */}
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
                  if (dayData.net_pnl > 0) bgTint = "bg-long/10";
                  else if (dayData.net_pnl < 0) bgTint = "bg-short/10";
                }

                return (
                  <button
                    key={dayNum}
                    onClick={() => setSelectedDay(isSelected ? null : dateStr)}
                    className={`aspect-square rounded-md flex flex-col items-center justify-center p-0.5 transition-colors ${bgTint} ${
                      isSelected ? "ring-1 ring-accent" : ""
                    } ${isToday ? "border border-border" : ""}`}
                  >
                    <span className={`text-xs ${isToday ? "text-accent font-bold" : "text-muted"}`}>
                      {dayNum}
                    </span>
                    {dayData && (
                      <>
                        <span className="text-[10px] text-muted">{dayData.signal_count}s</span>
                        <span className={`text-[10px] font-mono ${dayData.net_pnl >= 0 ? "text-long" : "text-short"}`}>
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
      <div className="bg-card rounded-lg p-3 text-center">
        <p className="text-muted text-sm">No signals on {date}</p>
      </div>
    );
  }

  return (
    <div className="bg-card rounded-lg p-3">
      <h3 className="text-xs text-muted mb-2">{date}</h3>
      <div className="grid grid-cols-3 gap-2 text-center text-sm">
        <div>
          <div className="font-mono font-bold text-foreground">{dayData.signal_count}</div>
          <div className="text-xs text-muted">Signals</div>
        </div>
        <div>
          <div className="font-mono font-bold text-long">{dayData.wins}W</div>
          <div className="text-xs text-muted">Wins</div>
        </div>
        <div>
          <div className="font-mono font-bold text-short">{dayData.losses}L</div>
          <div className="text-xs text-muted">Losses</div>
        </div>
      </div>
      <div className={`text-center mt-2 font-mono font-bold ${dayData.net_pnl >= 0 ? "text-long" : "text-short"}`}>
        {dayData.net_pnl >= 0 ? "+" : ""}{dayData.net_pnl.toFixed(2)}% P&L
      </div>
    </div>
  );
}
