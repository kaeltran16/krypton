import { useState } from "react";
import { SignalFeed } from "./SignalFeed";
import { JournalView } from "./JournalView";

type ActiveView = "signals" | "journal";

export function SignalsView() {
  const [activeView, setActiveView] = useState<ActiveView>("signals");

  return (
    <div className="flex flex-col h-full">
      {/* Segmented control */}
      <div className="p-3 pb-0">
        <div className="flex gap-1 bg-surface-container-lowest p-1 rounded-lg w-fit">
          <button
            onClick={() => setActiveView("signals")}
            className={`px-4 py-1.5 rounded text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              activeView === "signals"
                ? "bg-surface-container-highest text-primary"
                : "text-on-surface-variant hover:bg-surface-container-highest"
            }`}
          >
            Signals
          </button>
          <button
            onClick={() => setActiveView("journal")}
            className={`px-4 py-1.5 rounded text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              activeView === "journal"
                ? "bg-surface-container-highest text-primary"
                : "text-on-surface-variant hover:bg-surface-container-highest"
            }`}
          >
            Journal
          </button>
        </div>
      </div>

      {/* Content */}
      {activeView === "signals" ? <SignalFeed /> : <JournalView />}
    </div>
  );
}
