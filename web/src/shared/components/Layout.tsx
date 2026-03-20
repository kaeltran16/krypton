import { useState, type ReactNode } from "react";
import { motion, MotionConfig } from "motion/react";
import { Home, BarChart3, Zap, Newspaper, MoreHorizontal } from "lucide-react";
import { TickerBar } from "./TickerBar";
import { EngineHeader } from "./EngineHeader";
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

  const isMarketTab = tab !== "more";
  const views = { home, chart, signals, news, more } as const;

  return (
    <MotionConfig reducedMotion="user">
      <div className="min-h-screen min-h-dvh text-on-surface flex flex-col">
        {isMarketTab ? (
          <TickerBar
            price={price}
            change24h={change24h}
            pair={selectedPair}
            onPairChange={onPairChange}
          />
        ) : (
          <EngineHeader />
        )}

        <main className="flex-1 overflow-y-auto pb-20 scroll-container relative">
          {TABS.map((t) => (
            <motion.div
              key={t}
              animate={{
                opacity: tab === t ? 1 : 0,
                y: tab === t ? 0 : 8,
              }}
              transition={{ duration: 0.15, ease: "easeOut" }}
              className={tab === t
                ? ""
                : "pointer-events-none absolute inset-0 overflow-hidden"
              }
            >
              {views[t]}
            </motion.div>
          ))}
        </main>

        <nav className="fixed bottom-0 left-0 right-0 flex justify-around items-center pt-2 px-2 safe-bottom bg-[var(--glass-nav)] backdrop-blur-xl z-30 border-t border-outline-variant/15 shadow-[0_-12px_32px_rgba(0,0,0,0.2)]">
          {TABS.map((t) => {
            const Icon = TAB_ICONS[t];
            const active = tab === t;
            return (
              <button
                key={t}
                onClick={() => { hapticTap(); setTab(t); }}
                aria-current={active ? "page" : undefined}
                className={`flex flex-col items-center justify-center min-h-[44px] py-2 px-3 transition-all duration-200 active:scale-95 ${
                  active
                    ? "text-primary-container shadow-[0_0_8px_rgba(105,218,255,0.15)]"
                    : "text-on-surface-variant hover:text-on-surface"
                }`}
              >
                <Icon
                  size={20}
                  strokeWidth={active ? 2.5 : 1.5}
                  className="mb-0.5"
                />
                <span className="font-sans font-medium text-[10px] uppercase tracking-wider">
                  {TAB_LABELS[t]}
                </span>
              </button>
            );
          })}
        </nav>
      </div>
    </MotionConfig>
  );
}
