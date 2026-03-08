import { useState } from "react";
import { SignalFeed } from "./SignalFeed";
import { JournalView } from "./JournalView";

type ActiveView = "signals" | "journal";

export function SignalsView() {
  const [activeView, setActiveView] = useState<ActiveView>("signals");

  return (
    <div className="flex flex-col h-full">
      {/* Segmented control */}
      <div className="flex gap-1 p-3 pb-0">
        <button
          onClick={() => setActiveView("signals")}
          className={`flex-1 py-2 rounded-lg text-xs font-medium transition-colors ${
            activeView === "signals"
              ? "bg-accent/15 text-accent border border-accent/30"
              : "bg-card text-muted border border-border"
          }`}
        >
          Signals
        </button>
        <button
          onClick={() => setActiveView("journal")}
          className={`flex-1 py-2 rounded-lg text-xs font-medium transition-colors ${
            activeView === "journal"
              ? "bg-accent/15 text-accent border border-accent/30"
              : "bg-card text-muted border border-border"
          }`}
        >
          Journal
        </button>
      </div>

      {/* Content */}
      {activeView === "signals" ? <SignalFeed /> : <JournalView />}
    </div>
  );
}
