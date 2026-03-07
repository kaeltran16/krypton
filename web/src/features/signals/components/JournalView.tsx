import { useState } from "react";
import { SignalFeed } from "./SignalFeed";
import { AnalyticsView } from "./AnalyticsView";
import { CalendarView } from "./CalendarView";

type JournalTab = "feed" | "analytics" | "calendar";

const TABS: { key: JournalTab; label: string }[] = [
  { key: "feed", label: "Feed" },
  { key: "analytics", label: "Analytics" },
  { key: "calendar", label: "Calendar" },
];

export function JournalView() {
  const [tab, setTab] = useState<JournalTab>("feed");

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 pt-3">
        <div className="flex bg-card rounded-lg p-0.5">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                tab === key
                  ? "bg-gray-700 text-white"
                  : "text-gray-500"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === "feed" && <SignalFeed />}
      {tab === "analytics" && <AnalyticsView />}
      {tab === "calendar" && <CalendarView />}
    </div>
  );
}
