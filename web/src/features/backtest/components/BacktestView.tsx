import { useEffect } from "react";
import { useBacktestStore } from "../store";
import { BacktestSetup } from "./BacktestSetup";
import { BacktestResults } from "./BacktestResults";
import { BacktestCompare } from "./BacktestCompare";
import OptimizeTab from "./OptimizeTab";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";

const TABS = [
  { value: "setup" as const, label: "Setup" },
  { value: "results" as const, label: "Results" },
  { value: "compare" as const, label: "Compare" },
  { value: "optimize" as const, label: "Optimize" },
];

export function BacktestView() {
  const { tab, setTab, fetchRuns } = useBacktestStore();

  useEffect(() => {
    fetchRuns();
  }, []);

  return (
    <div className="p-3 space-y-3">
      <SegmentedControl options={TABS} value={tab} onChange={setTab} fullWidth />

      {tab === "setup" && <BacktestSetup />}
      {tab === "results" && <BacktestResults />}
      {tab === "compare" && <BacktestCompare />}
      {tab === "optimize" && <OptimizeTab />}
    </div>
  );
}
