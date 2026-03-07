import { useState, type ReactNode } from "react";
import { TickerBar } from "./TickerBar";

type Tab = "home" | "chart" | "signals" | "journal" | "more";

interface LayoutProps {
  home: ReactNode;
  chart: ReactNode;
  signals: ReactNode;
  journal: ReactNode;
  more: ReactNode;
  price: number | null;
  change24h: number | null;
  selectedPair: string;
  onPairChange: (pair: string) => void;
}

export function Layout({
  home, chart, signals, journal, more,
  price, change24h, selectedPair, onPairChange,
}: LayoutProps) {
  const [tab, setTab] = useState<Tab>("home");

  const content = { home, chart, signals, journal, more }[tab];

  return (
    <div className="min-h-screen bg-surface text-foreground flex flex-col">
      <TickerBar
        price={price}
        change24h={change24h}
        pair={selectedPair}
        onPairChange={onPairChange}
      />
      <main className="flex-1 overflow-y-auto pb-16 scroll-container">{content}</main>
      <nav className="fixed bottom-0 left-0 right-0 bg-card/95 backdrop-blur-md border-t border-border flex safe-bottom z-30">
        <TabButton active={tab === "home"} onClick={() => setTab("home")} label="Home" icon={<IconHome />} />
        <TabButton active={tab === "chart"} onClick={() => setTab("chart")} label="Chart" icon={<IconChart />} />
        <TabButton active={tab === "signals"} onClick={() => setTab("signals")} label="Signals" icon={<IconSignals />} />
        <TabButton active={tab === "journal"} onClick={() => setTab("journal")} label="Journal" icon={<IconJournal />} />
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
      onClick={onClick}
      className={`flex-1 py-2 flex flex-col items-center gap-0.5 text-[10px] font-medium transition-colors ${
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

function IconJournal() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
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
