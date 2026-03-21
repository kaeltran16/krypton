import { useState } from "react";
import { SignalFeed } from "./SignalFeed";
import { JournalView } from "./JournalView";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { useSignalStore } from "../store";

type ActiveView = "feed" | "journal";

const VIEWS: { value: ActiveView; label: string }[] = [
  { value: "feed", label: "Feed" },
  { value: "journal", label: "Journal" },
];

export function SignalsView() {
  const [activeView, setActiveView] = useState<ActiveView>("feed");
  const connected = useSignalStore((s) => s.connected);

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-2 pb-1 flex items-end justify-between">
        <SegmentedControl
          options={VIEWS}
          value={activeView}
          onChange={setActiveView}
          variant="underline"
        />
        <div
          className="flex items-center gap-1.5 pb-2"
          role="status"
          aria-live="polite"
          aria-label={connected ? "Live connection active" : "Reconnecting"}
        >
          <div
            className={`w-1.5 h-1.5 rounded-full ${
              connected
                ? "bg-long shadow-[0_0_6px_rgba(86,239,159,0.5)]"
                : "bg-short motion-safe:animate-pulse"
            }`}
          />
          <span className="text-[10px] font-medium text-on-surface-variant uppercase tracking-wider">
            {connected ? "Live" : "..."}
          </span>
        </div>
      </div>

      {activeView === "feed" ? <SignalFeed /> : <JournalView />}
    </div>
  );
}
