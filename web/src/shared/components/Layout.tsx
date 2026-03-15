import { useState, type ReactNode } from "react";
import { TickerBar } from "./TickerBar";
import { hapticTap } from "../lib/haptics";

type Tab = "home" | "chart" | "signals" | "news" | "more";

interface LayoutProps {
  home: ReactNode;
  chart: ReactNode;
  signals: ReactNode;
  news: ReactNode;
  more: ReactNode;
  price: number | null;
  change24h: number | null;
  selectedPair: string;
  onPairChange: (pair: string) => void;
}

export function Layout({
  home, chart, signals, news, more,
  price, change24h, selectedPair, onPairChange,
}: LayoutProps) {
  const [tab, setTab] = useState<Tab>("home");

  const content = { home, chart, signals, news, more }[tab];

  return (
    <div className="min-h-screen bg-surface text-foreground flex flex-col">
      <TickerBar
        price={price}
        change24h={change24h}
        pair={selectedPair}
        onPairChange={onPairChange}
      />
      <main className="flex-1 overflow-y-auto pb-16 scroll-container transition-opacity duration-150 ease-in-out">{content}</main>
      <nav className="fixed bottom-0 left-0 right-0 bg-card/95 backdrop-blur-md border-t border-border flex safe-bottom z-30">
        <TabButton active={tab === "home"} onClick={() => setTab("home")} label="Home" icon={<IconHome />} />
        <TabButton active={tab === "chart"} onClick={() => setTab("chart")} label="Chart" icon={<IconChart />} />
        <TabButton active={tab === "signals"} onClick={() => setTab("signals")} label="Signals" icon={<IconSignals />} />
        <TabButton active={tab === "news"} onClick={() => setTab("news")} label="News" icon={<IconNews />} />
        <TabButton active={tab === "more"} onClick={() => setTab("more")} label="More" icon={<IconMore />} />
      </nav>
    </div>
  );
}

function TabButton({ active, onClick, label, icon }: {
  active: boolean; onClick: () => void; label: string; icon: ReactNode;
}) {
  return (
    <button
      onClick={() => { hapticTap(); onClick(); }}
      className={`flex-1 py-2 flex flex-col items-center gap-0.5 text-[10px] font-medium transition-colors min-h-[44px] ${
        active ? "text-accent" : "text-muted"
      }`}
    >
      <span className="w-5 h-5">{icon}</span>
      {label}
    </button>
  );
}

function IconHome() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <rect x="3" y="3" width="8" height="8" rx="1.5" />
      <rect x="13" y="3" width="8" height="8" rx="1.5" />
      <rect x="3" y="13" width="8" height="8" rx="1.5" />
      <rect x="13" y="13" width="8" height="8" rx="1.5" />
    </svg>
  );
}

function IconChart() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M3 3v18h18" />
      <path d="M7 16l4-6 4 4 5-8" />
    </svg>
  );
}

function IconSignals() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
    </svg>
  );
}

function IconNews() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M4 22h16a2 2 0 002-2V4a2 2 0 00-2-2H8a2 2 0 00-2 2v16a2 2 0 01-2 2zm0 0a2 2 0 01-2-2v-9c0-1.1.9-2 2-2h2" />
      <path d="M18 14h-8" />
      <path d="M15 18h-5" />
      <path d="M10 6h8v4h-8z" />
    </svg>
  );
}

function IconMore() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
      <circle cx="12" cy="5" r="1.5" />
      <circle cx="12" cy="12" r="1.5" />
      <circle cx="12" cy="19" r="1.5" />
    </svg>
  );
}
