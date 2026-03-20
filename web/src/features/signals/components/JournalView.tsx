import { useState } from "react";
import { AnalyticsView } from "./AnalyticsView";
import { CalendarView } from "./CalendarView";
import { DeepDiveView } from "./DeepDiveView";

type JournalTab = "analytics" | "calendar" | "deepdive";

const TABS: { key: JournalTab; label: string }[] = [
  { key: "analytics", label: "Analytics" },
  { key: "calendar", label: "Calendar" },
  { key: "deepdive", label: "Deep Dive" },
];

export function JournalView() {
  const [tab, setTab] = useState<JournalTab>("analytics");

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 pt-3">
        <div className="flex bg-surface-container-low p-1 rounded-lg gap-1 w-full">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex-1 py-1.5 text-xs font-bold uppercase tracking-wider rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                tab === key
                  ? "bg-surface-container-highest text-primary shadow-[0_0_8px_rgba(105,218,255,0.15)]"
                  : "text-on-surface-variant hover:bg-surface-bright"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === "analytics" && <AnalyticsView />}
      {tab === "calendar" && <CalendarView />}
      {tab === "deepdive" && <DeepDiveView />}
    </div>
  );
}
