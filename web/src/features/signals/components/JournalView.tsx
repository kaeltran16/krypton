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
        <div className="flex bg-card rounded-lg p-0.5 border border-border">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                tab === key
                  ? "bg-card-hover text-foreground"
                  : "text-muted"
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
