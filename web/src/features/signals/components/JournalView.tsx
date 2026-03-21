import { useState } from "react";
import { AnalyticsView } from "./AnalyticsView";
import { CalendarView } from "./CalendarView";
import { DeepDiveView } from "./DeepDiveView";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";

type JournalTab = "analytics" | "calendar" | "deepdive";

const TABS: { value: JournalTab; label: string }[] = [
  { value: "analytics", label: "Analytics" },
  { value: "calendar", label: "Calendar" },
  { value: "deepdive", label: "Deep Dive" },
];

export function JournalView() {
  const [tab, setTab] = useState<JournalTab>("analytics");

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 pt-3">
        <SegmentedControl
          options={TABS}
          value={tab}
          onChange={setTab}
          fullWidth
        />
      </div>

      {tab === "analytics" && <AnalyticsView />}
      {tab === "calendar" && <CalendarView />}
      {tab === "deepdive" && <DeepDiveView />}
    </div>
  );
}
