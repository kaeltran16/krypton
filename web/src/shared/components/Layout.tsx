import { useState, type ReactNode } from "react";

type Tab = "dashboard" | "chart" | "signals" | "settings";

interface LayoutProps {
  dashboard: ReactNode;
  chart: ReactNode;
  signals: ReactNode;
  settings: ReactNode;
}

const TABS: { key: Tab; label: string }[] = [
  { key: "dashboard", label: "Dashboard" },
  { key: "chart", label: "Chart" },
  { key: "signals", label: "Signals" },
  { key: "settings", label: "Settings" },
];

export function Layout({ dashboard, chart, signals, settings }: LayoutProps) {
  const [tab, setTab] = useState<Tab>("dashboard");

  const content = { dashboard, chart, signals, settings }[tab];

  return (
    <div className="min-h-screen bg-surface text-white flex flex-col">
      <main className="flex-1 overflow-y-auto pb-16">{content}</main>
      <nav className="fixed bottom-0 left-0 right-0 bg-card border-t border-gray-800 flex safe-bottom">
        {TABS.map(({ key, label }) => (
          <TabButton key={key} active={tab === key} onClick={() => setTab(key)} label={label} />
        ))}
      </nav>
    </div>
  );
}

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  label: string;
}

function TabButton({ active, onClick, label }: TabButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 py-3 text-center text-sm font-medium transition-colors ${
        active ? "text-long" : "text-gray-500"
      }`}
    >
      {label}
    </button>
  );
}
