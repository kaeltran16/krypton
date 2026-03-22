import { useState, useRef, useCallback, type ReactNode } from "react";
import { Home, BarChart3, Zap, Newspaper, MoreHorizontal } from "lucide-react";
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

const TAB_ICONS = {
  home: Home,
  chart: BarChart3,
  signals: Zap,
  news: Newspaper,
  more: MoreHorizontal,
} as const;

const TAB_LABELS: Record<Tab, string> = {
  home: "Home",
  chart: "Chart",
  signals: "Signals",
  news: "News",
  more: "More",
};

const TABS: Tab[] = ["home", "chart", "signals", "news", "more"];

export function Layout({
  home, chart, signals, news, more,
  price, change24h, selectedPair, onPairChange,
}: LayoutProps) {
  const [tab, setTab] = useState<Tab>("home");
  const mainRef = useRef<HTMLElement>(null);

  const views = { home, chart, signals, news, more } as const;

  const switchTab = useCallback((t: Tab) => {
    hapticTap();
    setTab(t);
    mainRef.current?.scrollTo(0, 0);
  }, []);

  return (
    <div className="h-screen h-dvh text-on-surface flex flex-col overflow-hidden">
      <TickerBar
        price={price}
        change24h={change24h}
        pair={selectedPair}
        onPairChange={onPairChange}
      />

      <main ref={mainRef} className="flex-1 min-h-0 overflow-y-auto pb-20 scroll-container relative">
        {TABS.map((t) => {
          const active = tab === t;
          return (
            <div
              key={t}
              className={active
                ? ""
                : "pointer-events-none absolute inset-0 overflow-hidden opacity-0"
              }
              aria-hidden={!active}
            >
              {views[t]}
            </div>
          );
        })}
      </main>

      <nav className="fixed bottom-0 left-0 right-0 flex justify-around items-center pt-1.5 px-2 safe-bottom bg-[var(--glass-nav)] backdrop-blur-xl z-30 border-t border-outline-variant/15">
        {TABS.map((t) => {
          const Icon = TAB_ICONS[t];
          const active = tab === t;
          return (
            <button
              key={t}
              onClick={() => switchTab(t)}
              aria-current={active ? "page" : undefined}
              className={`relative flex flex-col items-center justify-center min-h-[48px] min-w-[48px] py-1.5 px-3 transition-colors duration-200 active:scale-[0.92] ${
                active
                  ? "text-primary"
                  : "text-on-surface-variant"
              }`}
            >
              <div className={`relative flex items-center justify-center w-8 h-8 rounded-full transition-all duration-200 ${
                active ? "bg-primary/12" : ""
              }`}>
                <Icon
                  size={20}
                  strokeWidth={active ? 2.5 : 1.5}
                />
              </div>
              <span className={`font-sans text-[10px] tracking-wider mt-0.5 transition-colors duration-200 ${
                active ? "font-bold" : "font-medium text-on-surface-variant/70"
              }`}>
                {TAB_LABELS[t]}
              </span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
