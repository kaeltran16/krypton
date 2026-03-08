import { useEffect } from "react";
import { useBacktestStore } from "../store";
import { BacktestSetup } from "./BacktestSetup";
import { BacktestResults } from "./BacktestResults";
import { BacktestCompare } from "./BacktestCompare";

const TABS = [
  { key: "setup" as const, label: "Setup" },
  { key: "results" as const, label: "Results" },
  { key: "compare" as const, label: "Compare" },
];

export function BacktestView({ onBack }: { onBack: () => void }) {
  const { tab, setTab, fetchRuns } = useBacktestStore();

  useEffect(() => {
    fetchRuns();
  }, []);

  return (
    <div className="p-3 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="text-muted hover:text-foreground transition-colors"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <h1 className="text-lg font-semibold">Backtester</h1>
      </div>

      {/* Tab bar */}
      <div className="flex bg-card rounded-lg border border-border p-0.5">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 py-2 rounded-md text-sm font-medium transition-colors ${
              tab === t.key
                ? "bg-accent/15 text-accent"
                : "text-muted hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {tab === "setup" && <BacktestSetup />}
      {tab === "results" && <BacktestResults />}
      {tab === "compare" && <BacktestCompare />}
    </div>
  );
}
