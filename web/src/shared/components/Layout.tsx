import { useState, type ReactNode } from "react";
import { AVAILABLE_PAIRS } from "../lib/constants";
import { TickerBar } from "./TickerBar";

type Tab = "home" | "chart" | "signals" | "more";

interface LayoutProps {
  home: ReactNode;
  chart: ReactNode;
  signals: ReactNode;
  more: ReactNode;
  price: number | null;
  change24h: number | null;
  selectedPair: string;
  onPairChange: (pair: string) => void;
}

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: "home", label: "Home", icon: "◉" },
  { key: "chart", label: "Chart", icon: "◧" },
  { key: "signals", label: "Journal", icon: "⚡" },
  { key: "more", label: "More", icon: "≡" },
];

export function Layout({ home, chart, signals, more, price, change24h, selectedPair, onPairChange }: LayoutProps) {
  const [tab, setTab] = useState<Tab>("home");

  const content = { home, chart, signals, more }[tab];

  return (
    <div className="min-h-screen bg-surface text-white flex flex-col">
      <TickerBar
        price={price}
        change24h={change24h}
        pair={selectedPair}
        onPairChange={onPairChange}
      />
      <main className="flex-1 overflow-y-auto pb-16 scroll-container">{content}</main>
      <nav className="fixed bottom-0 left-0 right-0 bg-card/95 backdrop-blur-md border-t border-gray-800/50 flex safe-bottom z-30">
        {TABS.map(({ key, label, icon }) => (
          <TabButton key={key} active={tab === key} onClick={() => setTab(key)} label={label} icon={icon} />
        ))}
      </nav>
    </div>
  );
}

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  label: string;
  icon: string;
}

function TabButton({ active, onClick, label, icon }: TabButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 py-2 flex flex-col items-center gap-0.5 text-xs font-medium transition-colors ${
        active ? "text-long" : "text-gray-500"
      }`}
    >
      <span className="text-base">{icon}</span>
      {label}
    </button>
  );
}
