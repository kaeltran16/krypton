import { useState } from "react";
import { Cpu, LineChart, Brain, BellRing, Shield, Settings, ChevronRight } from "lucide-react";
import { SubPageShell } from "../../../shared/components/SubPageShell";
import SettingsPage from "../../settings/components/SettingsPage";
import RiskPage from "../../settings/components/RiskPage";
import EnginePage from "../../engine/components/EnginePage";
import { BacktestView } from "../../backtest/components/BacktestView";
import { MLTrainingView } from "../../ml/components/MLTrainingView";
import { AlertsPage } from "../../alerts/components/AlertsPage";
import { hapticTap } from "../../../shared/lib/haptics";

type SubPage = "engine" | "backtest" | "ml" | "alerts" | "risk" | "settings" | null;

interface NavItem {
  id: SubPage;
  icon: typeof Cpu;
  iconColor: string;
  iconBg: string;
  label: string;
  description: string;
  chevronHover: string;
}

const CLUSTERS: { label: string; items: NavItem[] }[] = [
  {
    label: "Execution Layer",
    items: [
      { id: "engine", icon: Cpu, iconColor: "text-primary", iconBg: "bg-primary/10", label: "Engine", description: "Active Instances & Latency", chevronHover: "group-hover:text-primary" },
      { id: "backtest", icon: LineChart, iconColor: "text-long", iconBg: "bg-long/10", label: "Backtest", description: "Historical Simulation Hub", chevronHover: "group-hover:text-long" },
    ],
  },
  {
    label: "Intelligence Hub",
    items: [
      { id: "ml", icon: Brain, iconColor: "text-primary", iconBg: "bg-primary/10", label: "ML Training", description: "Neural Net Performance", chevronHover: "group-hover:text-primary" },
      { id: "alerts", icon: BellRing, iconColor: "text-short", iconBg: "bg-short/10", label: "Alerts", description: "Critical Signal Configurations", chevronHover: "group-hover:text-short" },
    ],
  },
  {
    label: "Safety & Security",
    items: [
      { id: "risk", icon: Shield, iconColor: "text-primary", iconBg: "bg-primary/10", label: "Risk", description: "Exposure Limits & Kill Switches", chevronHover: "group-hover:text-primary" },
      { id: "settings", icon: Settings, iconColor: "text-outline", iconBg: "bg-outline/10", label: "Settings", description: "Global System Preferences", chevronHover: "group-hover:text-on-surface" },
    ],
  },
];

const SUB_PAGE_TITLES: Record<string, string> = {
  engine: "Engine Dashboard",
  backtest: "Backtest",
  ml: "ML Training",
  alerts: "Alerts",
  risk: "Risk Management",
  settings: "Settings",
};

export function MorePage() {
  const [active, setActive] = useState<SubPage>(null);

  if (active) {
    return (
      <SubPageShell title={SUB_PAGE_TITLES[active] ?? ""} onBack={() => setActive(null)}>
        {active === "settings" && <SettingsPage />}
        {active === "risk" && <RiskPage />}
        {active === "engine" && <EnginePage />}
        {active === "backtest" && <BacktestView />}
        {active === "ml" && <MLTrainingView />}
        {active === "alerts" && <AlertsPage />}
      </SubPageShell>
    );
  }

  return (
    <div className="min-h-full terminal-grid relative overflow-hidden">
      {/* Header */}
      <header className="px-6 py-8">
        <h1 className="font-headline text-3xl font-bold tracking-tight">System Hub</h1>
        <p className="text-on-surface-variant text-sm mt-1 uppercase tracking-widest opacity-70">
          Core Protocol v4.0
        </p>
      </header>

      {/* Navigation Clusters */}
      <div className="px-4 space-y-6 relative z-10">
        {CLUSTERS.map((cluster) => (
          <section key={cluster.label}>
            <div className="px-2 mb-2">
              <span className="text-[10px] font-bold text-primary tracking-widest uppercase opacity-80">{cluster.label}</span>
            </div>
            <div className="bg-surface-container rounded-lg overflow-hidden border border-outline-variant/10">
              {cluster.items.map((item, i) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    onClick={() => { hapticTap(); setActive(item.id); }}
                    className={`w-full flex items-center justify-between p-4 hover:bg-surface-container-highest transition-colors group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary ${
                      i < cluster.items.length - 1 ? "border-b border-outline-variant/5" : ""
                    }`}
                  >
                    <div className="flex items-center gap-4">
                      <div className={`w-10 h-10 rounded flex items-center justify-center ${item.iconBg}`}>
                        <Icon size={20} className={item.iconColor} />
                      </div>
                      <div className="text-left">
                        <span className="block text-on-surface font-semibold">{item.label}</span>
                        <span className="block text-xs text-on-surface-variant">{item.description}</span>
                      </div>
                    </div>
                    <ChevronRight size={20} className={`text-outline transition-colors ${item.chevronHover}`} />
                  </button>
                );
              })}
            </div>
          </section>
        ))}

        <div className="pb-8" />
      </div>
    </div>
  );
}
