import { useState, type ReactNode } from "react";

type Tab = "feed" | "settings";

interface LayoutProps {
  feed: ReactNode;
  settings: ReactNode;
}

export function Layout({ feed, settings }: LayoutProps) {
  const [tab, setTab] = useState<Tab>("feed");

  return (
    <div className="min-h-screen bg-surface text-white flex flex-col">
      <main className="flex-1 overflow-y-auto pb-16">{tab === "feed" ? feed : settings}</main>
      <nav className="fixed bottom-0 left-0 right-0 bg-card border-t border-gray-800 flex safe-bottom">
        <TabButton active={tab === "feed"} onClick={() => setTab("feed")} label="Signals" />
        <TabButton active={tab === "settings"} onClick={() => setTab("settings")} label="Settings" />
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
