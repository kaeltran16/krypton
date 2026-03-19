import { useState } from "react";
import SettingsPage from "../../settings/components/SettingsPage";
import RiskPage from "../../settings/components/RiskPage";
import EnginePage from "../../engine/components/EnginePage";
import { BacktestView } from "../../backtest/components/BacktestView";
import { MLTrainingView } from "../../ml/components/MLTrainingView";
import { AlertsPage } from "../../alerts/components/AlertsPage";

const SUB_TABS = ["Settings", "Risk", "Engine", "Backtest", "ML", "Alerts"] as const;
type SubTab = (typeof SUB_TABS)[number];

export function MorePage() {
  const [active, setActive] = useState<SubTab>("Settings");

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1.5 px-3 py-2 overflow-x-auto scrollbar-hide border-b border-border">
        {SUB_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActive(tab)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${
              active === tab
                ? "bg-accent/20 text-accent"
                : "bg-surface text-muted hover:text-foreground"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto">
        {active === "Settings" && <SettingsPage />}
        {active === "Risk" && <RiskPage />}
        {active === "Engine" && <EnginePage />}
        {active === "Backtest" && <BacktestView />}
        {active === "ML" && <MLTrainingView />}
        {active === "Alerts" && <AlertsPage />}
      </div>
    </div>
  );
}
