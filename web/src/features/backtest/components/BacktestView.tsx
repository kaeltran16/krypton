import { useEffect } from "react";
import { useBacktestStore } from "../store";
import { BacktestSetup } from "./BacktestSetup";
import { BacktestResults } from "./BacktestResults";
import { BacktestCompare } from "./BacktestCompare";
import OptimizeTab from "./OptimizeTab";

const TABS = [
  { key: "setup" as const, label: "Setup" },
  { key: "results" as const, label: "Results" },
  { key: "compare" as const, label: "Compare" },
  { key: "optimize" as const, label: "Optimize" },
];

export function BacktestView() {
  const { tab, setTab, fetchRuns } = useBacktestStore();

  useEffect(() => {
    fetchRuns();
  }, []);

  return (
    <div className="p-3 space-y-3">
      {/* Tab bar */}
      <div className="flex bg-surface-container rounded-lg border border-outline-variant/10 p-0.5">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 py-2 rounded-md text-xs font-bold uppercase tracking-wider transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
              tab === t.key
                ? "bg-primary/15 text-primary"
                : "text-on-surface-variant hover:text-on-surface"
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
      {tab === "optimize" && <OptimizeTab />}
    </div>
  );
}
