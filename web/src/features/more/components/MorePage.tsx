import { useState } from "react";
import { Cpu, LineChart, Brain, BellRing, Shield, Settings, ChevronRight, Activity, Zap, Newspaper, BarChart3 } from "lucide-react";
import { SubPageShell } from "../../../shared/components/SubPageShell";
import SettingsPage from "../../settings/components/SettingsPage";
import RiskPage from "../../settings/components/RiskPage";
import EnginePage from "../../engine/components/EnginePage";
import { BacktestView } from "../../backtest/components/BacktestView";
import { MLTrainingView } from "../../ml/components/MLTrainingView";
import { AlertsPage } from "../../alerts/components/AlertsPage";
import { JournalView } from "../../signals/components/JournalView";
import { SystemDiagnostics } from "../../system/components/SystemDiagnostics";
import OptimizerPage from "../../optimizer/components/OptimizerPage";
import { NewsView } from "../../news/components/NewsView";
import { MonitorPage } from "../../monitor/components/MonitorPage";
import { hapticTap } from "../../../shared/lib/haptics";

type SubPage = "engine" | "backtest" | "ml" | "alerts" | "risk" | "settings" | "journal" | "system" | "optimizer" | "news" | "monitor" | null;

const CLUSTERS = [
  {
    label: "Execution Layer",
    items: [
      { key: "engine" as SubPage, icon: Cpu, label: "Engine", desc: "Pipeline parameters & weights", color: "text-primary" },
      { key: "backtest" as SubPage, icon: LineChart, label: "Backtest", desc: "Historical simulation hub", color: "text-primary" },
      { key: "optimizer" as SubPage, icon: Zap, label: "Optimizer", desc: "Auto-tune parameters", color: "text-purple-400" },
    ],
  },
  {
    label: "Intelligence Hub",
    items: [
      { key: "ml" as SubPage, icon: Brain, label: "ML Training", desc: "Neural net optimization", color: "text-primary" },
      { key: "alerts" as SubPage, icon: BellRing, label: "Alerts", desc: "Critical signal configurations", color: "text-error" },
      { key: "news" as SubPage, icon: Newspaper, label: "News", desc: "Market news & sentiment", color: "text-primary" },
      { key: "journal" as SubPage, icon: LineChart, label: "Journal", desc: "Trading analytics & calendar", color: "text-primary" },
    ],
  },
  {
    label: "Safety & Security",
    items: [
      { key: "risk" as SubPage, icon: Shield, label: "Risk", desc: "Exposure limits & controls", color: "text-primary" },
      { key: "monitor" as SubPage, icon: BarChart3, label: "Pipeline Monitor", desc: "Evaluation history & stats", color: "text-primary" },
      { key: "system" as SubPage, icon: Activity, label: "System", desc: "Health & diagnostics", color: "text-primary" },
      { key: "settings" as SubPage, icon: Settings, label: "Settings", desc: "Global system preferences", color: "text-outline" },
    ],
  },
];

const PAGE_TITLES: Record<string, string> = {
  engine: "Engine Parameters",
  backtest: "Backtest",
  ml: "ML Training",
  alerts: "Alerts",
  risk: "Risk Management",
  settings: "Settings",
  news: "News",
  journal: "Journal & Analytics",
  system: "System Diagnostics",
  optimizer: "Optimizer",
  monitor: "Pipeline Monitor",
};

export function MorePage() {
  const [activePage, setActivePage] = useState<SubPage>(null);

  if (activePage) {
    return (
      <SubPageShell title={PAGE_TITLES[activePage] ?? ""} onBack={() => setActivePage(null)}>
        {activePage === "engine" && <EnginePage />}
        {activePage === "backtest" && <BacktestView />}
        {activePage === "ml" && <MLTrainingView />}
        {activePage === "alerts" && <AlertsPage />}
        {activePage === "risk" && <RiskPage />}
        {activePage === "settings" && <SettingsPage />}
        {activePage === "news" && <NewsView />}
        {activePage === "journal" && <JournalView />}
        {activePage === "system" && <SystemDiagnostics />}
        {activePage === "optimizer" && <OptimizerPage />}
        {activePage === "monitor" && <MonitorPage />}
      </SubPageShell>
    );
  }

  return (
    <div className="min-h-full relative">
      {/* Terminal grid background */}
      <div className="absolute inset-0 pointer-events-none opacity-[0.03]" style={{
        backgroundSize: "40px 40px",
        backgroundImage: "linear-gradient(to right, rgba(0,207,252,0.5) 1px, transparent 1px), linear-gradient(to bottom, rgba(0,207,252,0.5) 1px, transparent 1px)",
      }} />

      <div className="relative z-10 px-4 pb-8">
        {/* Header */}
        <header className="py-8">
          <h1 className="font-headline text-3xl font-bold text-on-surface tracking-tight">System Hub</h1>
          <p className="text-on-surface-variant text-sm mt-1 uppercase tracking-widest opacity-70">v1.0.0</p>
        </header>

        {/* Navigation Clusters */}
        <div className="space-y-6">
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
                      key={item.key}
                      onClick={() => { hapticTap(); setActivePage(item.key); }}
                      className={`w-full flex items-center justify-between p-4 hover:bg-surface-container-highest transition-colors group focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                        i < cluster.items.length - 1 ? "border-b border-outline-variant/5" : ""
                      }`}
                    >
                      <div className="flex items-center gap-4">
                        <div className={`w-10 h-10 rounded-lg bg-surface-container-highest flex items-center justify-center ${item.color}`}>
                          <Icon size={20} />
                        </div>
                        <div className="text-left">
                          <span className="block text-on-surface font-semibold text-sm">{item.label}</span>
                          <span className="block text-xs text-on-surface-variant">{item.desc}</span>
                        </div>
                      </div>
                      <ChevronRight size={20} className="text-outline group-hover:text-primary transition-colors" />
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>

        {/* Connection Status Card */}
        <section className="mt-8">
          <button
            onClick={() => { hapticTap(); setActivePage("system"); }}
            className="w-full bg-surface-container-lowest p-5 border-l-4 border-primary rounded-r-lg text-left hover:bg-surface-container-low transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
          >
            <div className="flex justify-between items-start">
              <div>
                <h3 className="font-headline font-bold text-on-surface uppercase text-sm tracking-widest">Connection Secure</h3>
                <p className="text-xs text-on-surface-variant mt-1 font-mono">ENCRYPTED_NODE: LOCAL</p>
              </div>
              <div className="bg-primary/20 px-2 py-0.5 rounded-full">
                <span className="text-[10px] font-bold text-primary uppercase">System Status</span>
              </div>
            </div>
          </button>
        </section>
      </div>
    </div>
  );
}
