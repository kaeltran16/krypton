import { useState } from "react";
import { SignalFeed } from "./SignalFeed";
import { JournalView } from "./JournalView";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";

type ActiveView = "signals" | "journal";

export function SignalsView() {
  const [activeView, setActiveView] = useState<ActiveView>("signals");

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 pb-0">
        <SegmentedControl
          options={[
            { value: "signals", label: "Signals" },
            { value: "journal", label: "Journal" },
          ]}
          value={activeView}
          onChange={setActiveView}
        />
      </div>

      {/* Content */}
      {activeView === "signals" ? <SignalFeed /> : <JournalView />}
    </div>
  );
}
