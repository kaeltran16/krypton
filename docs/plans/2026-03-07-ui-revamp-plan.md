# UI Revamp Implementation Plan — OKX-Inspired Trading Terminal

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete visual and UX overhaul of the Krypton frontend — deeper backgrounds, gold accent, 5-tab navigation, OKX-inspired pro trading terminal feel.

**Architecture:** Centralized theme system (`theme.ts`) as single source of truth for design tokens. Tailwind imports from it. Navigation restructured from 4 tabs to 5 (Signals split from Journal). Every component restyled to new color system.

**Tech Stack:** React 19, TypeScript, Tailwind CSS 3, Zustand, Vite

**Reference Design:** `docs/plans/2026-03-07-ui-revamp-design.md`

---

## Task 1: Theme Foundation

**Files:**
- Create: `web/src/shared/theme.ts`
- Modify: `web/tailwind.config.ts`
- Modify: `web/src/index.css`

**Step 1: Create `web/src/shared/theme.ts`**

```typescript
export const theme = {
  colors: {
    surface: "#0B0E11",
    card: "#12161C",
    "card-hover": "#1A1F28",
    border: "#1E2530",
    foreground: "#EAECEF",
    muted: "#848E9C",
    dim: "#5E6673",
    long: "#0ECB81",
    short: "#F6465D",
    accent: "#F0B90B",
  },
  fontFamily: {
    sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
    mono: ["JetBrains Mono", "Fira Code", "monospace"],
  },
} as const;
```

**Step 2: Replace `web/tailwind.config.ts`**

```typescript
import type { Config } from "tailwindcss";
import { theme } from "./src/shared/theme";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: theme.colors,
      fontFamily: theme.fontFamily,
    },
  },
  safelist: [
    "text-long", "text-short",
    "bg-long/5", "bg-short/5",
    "bg-long/10", "bg-short/10",
    "bg-long/15", "bg-short/15",
    "bg-long/20", "bg-short/20",
    "border-long/20", "border-short/20",
    "border-long/30", "border-short/30",
    "border-long/40", "border-short/40",
    "bg-accent/15", "bg-accent/20",
    "text-accent",
  ],
  plugins: [],
} satisfies Config;
```

**Step 3: Replace `web/src/index.css`**

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');

@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --safe-top: env(safe-area-inset-top, 0px);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
}

body {
  background-color: #0B0E11;
  color: #EAECEF;
  font-family: Inter, system-ui, -apple-system, sans-serif;
  margin: 0;
  -webkit-font-smoothing: antialiased;
  -webkit-tap-highlight-color: transparent;
  overscroll-behavior: none;
}

dialog::backdrop {
  background: rgba(0, 0, 0, 0.6);
}

dialog {
  margin: 0;
  margin-top: auto;
  padding: 0;
  border: none;
  max-height: 85vh;
  width: 100%;
  max-width: 32rem;
  border-radius: 1rem 1rem 0 0;
  overflow-y: auto;
  background: #12161C;
  color: #EAECEF;
}

.safe-top {
  padding-top: var(--safe-top);
}

.safe-bottom {
  padding-bottom: max(var(--safe-bottom), 0.5rem);
}

.scroll-container {
  -webkit-overflow-scrolling: touch;
  overflow-y: auto;
}

.no-scrollbar::-webkit-scrollbar {
  display: none;
}
.no-scrollbar {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
```

**Step 4: Verify**

```bash
cd web && npx tsc --noEmit && npx vite build
```

---

## Task 2: Layout & Navigation (4 → 5 Tabs)

**Files:**
- Modify: `web/src/shared/components/Layout.tsx`
- Modify: `web/src/App.tsx`
- Create: `web/src/features/signals/components/SignalsView.tsx` (placeholder)

**Step 1: Create placeholder `web/src/features/signals/components/SignalsView.tsx`**

```tsx
import { SignalFeed } from "./SignalFeed";

export function SignalsView() {
  return <SignalFeed />;
}
```

**Step 2: Replace `web/src/shared/components/Layout.tsx`**

5 tabs: Home, Chart, Signals, Journal, More. SVG icons. Gold accent on active tab.

```tsx
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
```

**Step 3: Replace `web/src/App.tsx`**

```tsx
import { useState } from "react";
import { Layout } from "./shared/components/Layout";
import { HomeView } from "./features/home/components/HomeView";
import { ChartView } from "./features/chart/components/ChartView";
import { SignalsView } from "./features/signals/components/SignalsView";
import { JournalView } from "./features/signals/components/JournalView";
import { MorePage } from "./features/more/components/MorePage";
import { useSignalWebSocket } from "./features/signals/hooks/useSignalWebSocket";
import { useLivePrice } from "./shared/hooks/useLivePrice";
import { AVAILABLE_PAIRS } from "./shared/lib/constants";

export default function App() {
  const [selectedPair, setSelectedPair] = useState<string>(AVAILABLE_PAIRS[0]);
  useSignalWebSocket();
  const { price, change24h } = useLivePrice(selectedPair);

  return (
    <Layout
      home={<HomeView pair={selectedPair} />}
      chart={<ChartView pair={selectedPair} />}
      signals={<SignalsView />}
      journal={<JournalView />}
      more={<MorePage />}
      price={price}
      change24h={change24h}
      selectedPair={selectedPair}
      onPairChange={setSelectedPair}
    />
  );
}
```

**Step 4: Verify**

```bash
cd web && npx tsc --noEmit && npx vite build
```

---

## Task 3: TickerBar Restyle

**Files:**
- Modify: `web/src/shared/components/TickerBar.tsx`

**Step 1: Replace `web/src/shared/components/TickerBar.tsx`**

Deep bg-card background, gold highlight on pair name, no backdrop blur.

```tsx
import { formatPrice } from "../lib/format";
import { AVAILABLE_PAIRS } from "../lib/constants";

interface TickerBarProps {
  price: number | null;
  change24h: number | null;
  pair: string;
  onPairChange: (pair: string) => void;
}

export function TickerBar({ price, change24h, pair, onPairChange }: TickerBarProps) {
  const isPositive = (change24h ?? 0) >= 0;

  return (
    <div className="sticky top-0 z-30 bg-card border-b border-border safe-top">
      <div className="flex items-center justify-between px-3 py-2">
        <select
          value={pair}
          onChange={(e) => onPairChange(e.target.value)}
          className="bg-transparent text-accent font-bold text-sm border-none outline-none appearance-none pr-4"
          style={{
            backgroundImage: "url(\"data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%23848E9C' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e\")",
            backgroundPosition: "right 0 center",
            backgroundRepeat: "no-repeat",
            backgroundSize: "16px",
          }}
        >
          {AVAILABLE_PAIRS.map((p) => (
            <option key={p} value={p} className="bg-card">{p.replace("-SWAP", "")}</option>
          ))}
        </select>
        <div className="flex items-center gap-2">
          {price !== null && (
            <span className="font-mono font-bold text-sm">${formatPrice(price)}</span>
          )}
          {change24h !== null && (
            <span className={`text-xs font-mono ${isPositive ? "text-long" : "text-short"}`}>
              {isPositive ? "+" : ""}{change24h.toFixed(2)}%
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
```

**Step 2: Verify**

```bash
cd web && npx tsc --noEmit && npx vite build
```

---

## Task 4: Home Tab Redesign

**Files:**
- Modify: `web/src/features/home/components/HomeView.tsx` (full rewrite)
- Modify: `web/src/features/home/components/RecentSignals.tsx` (full rewrite)
- Modify: `web/src/shared/lib/format.ts` (add formatRelativeTime)

**Step 1: Add `formatRelativeTime` to `web/src/shared/lib/format.ts`**

Append to end of file:

```typescript
export function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
```

**Step 2: Replace `web/src/features/home/components/HomeView.tsx`**

Full account overview: account header, account strip, open positions, recent signals, performance strip.

```tsx
import { useAccount } from "../../dashboard/hooks/useAccount";
import { useSignalStats } from "../hooks/useSignalStats";
import { RecentSignals } from "./RecentSignals";
import { formatPrice } from "../../../shared/lib/format";
import type { AccountBalance, Position } from "../../../shared/lib/api";
import type { SignalStats } from "../../signals/types";

interface Props {
  pair: string;
}

export function HomeView({ pair }: Props) {
  const { balance, positions, loading: accountLoading } = useAccount();
  const { stats, loading: statsLoading } = useSignalStats();

  return (
    <div className="flex flex-col gap-2 p-3">
      <AccountHeader balance={balance} loading={accountLoading} />
      <AccountStrip balance={balance} loading={accountLoading} />
      <OpenPositions positions={positions} loading={accountLoading} />
      <RecentSignals />
      <PerformanceCard stats={stats} loading={statsLoading} />
    </div>
  );
}

function AccountHeader({ balance, loading }: { balance: AccountBalance | null; loading: boolean }) {
  if (loading) return <div className="h-20 bg-card rounded-lg animate-pulse" />;
  if (!balance) return null;

  const pnl = balance.unrealized_pnl;
  const pct = balance.total_equity > 0 ? (pnl / balance.total_equity) * 100 : 0;
  const isPositive = pnl >= 0;

  return (
    <div className="bg-card rounded-lg p-4 border border-border">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] text-muted uppercase tracking-wider">Account Balance</div>
          <div className="text-2xl font-mono font-bold mt-1">${formatPrice(balance.total_equity)}</div>
        </div>
        <div className="text-right">
          <div className={`text-sm font-mono font-bold ${isPositive ? "text-long" : "text-short"}`}>
            {isPositive ? "+" : ""}{pct.toFixed(1)}%
          </div>
          <div className={`text-xs font-mono ${isPositive ? "text-long" : "text-short"}`}>
            {isPositive ? "+" : ""}${formatPrice(Math.abs(pnl))}
          </div>
        </div>
      </div>
    </div>
  );
}

function AccountStrip({ balance, loading }: { balance: AccountBalance | null; loading: boolean }) {
  if (loading || !balance) return null;

  const available = balance.currencies[0]?.available ?? 0;
  const margin = balance.total_equity > 0
    ? ((balance.total_equity - available) / balance.total_equity * 100)
    : 0;

  return (
    <div className="bg-card rounded-lg p-3 border border-border">
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className={`text-sm font-mono font-bold ${balance.unrealized_pnl >= 0 ? "text-long" : "text-short"}`}>
            {balance.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(balance.unrealized_pnl)}
          </div>
          <div className="text-[10px] text-muted uppercase">Unrealized P&L</div>
        </div>
        <div>
          <div className="text-sm font-mono font-bold">${formatPrice(available)}</div>
          <div className="text-[10px] text-muted uppercase">Available</div>
        </div>
        <div>
          <div className="text-sm font-mono font-bold">{margin.toFixed(1)}%</div>
          <div className="text-[10px] text-muted uppercase">Margin</div>
        </div>
      </div>
    </div>
  );
}

function OpenPositions({ positions, loading }: { positions: Position[]; loading: boolean }) {
  if (loading) return <div className="h-16 bg-card rounded-lg animate-pulse" />;

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      <div className="px-3 pt-3 pb-2">
        <span className="text-[10px] text-muted uppercase tracking-wider">
          Open Positions ({positions.length})
        </span>
      </div>
      {positions.length === 0 ? (
        <p className="px-3 pb-3 text-sm text-dim">No open positions</p>
      ) : (
        <div className="divide-y divide-border">
          {positions.map((pos) => {
            const isLong = pos.side === "long";
            return (
              <div key={`${pos.pair}-${pos.side}`} className="px-3 py-2.5 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{pos.pair.replace("-USDT-SWAP", "")}</span>
                  <span className={`text-xs font-mono font-bold uppercase ${isLong ? "text-long" : "text-short"}`}>
                    {pos.side}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs font-mono">
                  <span className={pos.unrealized_pnl >= 0 ? "text-long" : "text-short"}>
                    {pos.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(pos.unrealized_pnl)}
                  </span>
                  <span className="text-muted">${formatPrice(pos.mark_price)}</span>
                  <span className="text-dim">{pos.size}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PerformanceCard({ stats, loading }: { stats: SignalStats | null; loading: boolean }) {
  if (loading) return <div className="h-16 bg-card rounded-lg animate-pulse" />;
  if (!stats || stats.total_resolved === 0) return null;

  const netPnl = stats.equity_curve.length > 0
    ? stats.equity_curve[stats.equity_curve.length - 1].cumulative_pnl
    : 0;

  return (
    <div className="bg-card rounded-lg p-3 border border-border">
      <div className="text-[10px] text-muted uppercase tracking-wider mb-2">Performance (7D)</div>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className={`text-lg font-mono font-bold ${stats.win_rate >= 50 ? "text-long" : "text-short"}`}>
            {stats.win_rate}%
          </div>
          <div className="text-[10px] text-muted">Win Rate</div>
        </div>
        <div>
          <div className="text-lg font-mono font-bold">{stats.avg_rr}</div>
          <div className="text-[10px] text-muted">Avg R:R</div>
        </div>
        <div>
          <div className={`text-lg font-mono font-bold ${netPnl >= 0 ? "text-long" : "text-short"}`}>
            {netPnl >= 0 ? "+" : ""}{netPnl.toFixed(1)}%
          </div>
          <div className="text-[10px] text-muted">Net P&L</div>
        </div>
      </div>
    </div>
  );
}
```

**Step 3: Replace `web/src/features/home/components/RecentSignals.tsx`**

Compact single-line rows with relative timestamps. Arrow links to Signals tab.

```tsx
import { useShallow } from "zustand/react/shallow";
import { useSignalStore } from "../../signals/store";
import { formatScore, formatRelativeTime } from "../../../shared/lib/format";
import type { Signal } from "../../signals/types";

export function RecentSignals() {
  const signals = useSignalStore(useShallow((s) => s.signals.slice(0, 3)));

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden">
      <div className="px-3 pt-3 pb-2 flex items-center justify-between">
        <span className="text-[10px] text-muted uppercase tracking-wider">
          Recent Signals ({signals.length})
        </span>
        <span className="text-[10px] text-accent">&rarr;</span>
      </div>
      {signals.length === 0 ? (
        <p className="px-3 pb-3 text-sm text-dim">Waiting for signals...</p>
      ) : (
        <div className="divide-y divide-border">
          {signals.map((signal) => (
            <SignalRow key={signal.id} signal={signal} />
          ))}
        </div>
      )}
    </div>
  );
}

function SignalRow({ signal }: { signal: Signal }) {
  const isLong = signal.direction === "LONG";

  return (
    <div className="px-3 py-2.5 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className="text-accent text-xs">&#9889;</span>
        <span className="text-sm font-medium">{signal.pair.replace("-USDT-SWAP", "")}</span>
        <span className={`text-xs font-mono font-bold ${isLong ? "text-long" : "text-short"}`}>
          {signal.direction}
        </span>
        <span className={`text-xs font-mono ${isLong ? "text-long" : "text-short"}`}>
          {formatScore(signal.final_score)}
        </span>
        <span className="text-xs text-dim">{signal.timeframe}</span>
      </div>
      <span className="text-xs text-dim">{formatRelativeTime(signal.created_at)}</span>
    </div>
  );
}
```

**Step 4: Verify**

```bash
cd web && npx tsc --noEmit && npx vite build
```

---

## Task 5: Chart Tab Update

**Files:**
- Modify: `web/src/features/chart/components/ChartView.tsx`
- Modify: `web/src/shared/hooks/useLivePrice.ts`

**Step 1: Extend `web/src/shared/hooks/useLivePrice.ts`**

Add open24h, high24h, low24h, vol24h to the return value. The OKX ticker WebSocket already sends this data.

```tsx
import { useEffect, useState, useRef } from "react";

const OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public";

interface TickerData {
  price: number | null;
  change24h: number | null;
  open24h: number | null;
  high24h: number | null;
  low24h: number | null;
  vol24h: number | null;
}

export function useLivePrice(pair: string): TickerData {
  const [data, setData] = useState<TickerData>({
    price: null, change24h: null, open24h: null,
    high24h: null, low24h: null, vol24h: null,
  });
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let ws: WebSocket;
    let shouldReconnect = true;
    let timer: ReturnType<typeof setTimeout>;

    function connect() {
      ws = new WebSocket(OKX_WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({
          op: "subscribe",
          args: [{ channel: "tickers", instId: pair }],
        }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.data?.[0]) {
            const d = msg.data[0];
            const last = Number(d.last);
            const open = d.open24h ? Number(d.open24h) : null;
            setData({
              price: last,
              change24h: open ? ((last - open) / open) * 100 : null,
              open24h: open,
              high24h: d.high24h ? Number(d.high24h) : null,
              low24h: d.low24h ? Number(d.low24h) : null,
              vol24h: d.vol24h ? Number(d.vol24h) : null,
            });
          }
        } catch { /* ignore */ }
      };

      ws.onclose = () => {
        if (shouldReconnect) timer = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      shouldReconnect = false;
      clearTimeout(timer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [pair]);

  return data;
}
```

**Step 2: Replace `web/src/features/chart/components/ChartView.tsx`**

Add 1D timeframe. Add OHLC strip at bottom with Open, High, Low, Close, Volume, 24h change.

```tsx
import { useState } from "react";
import { CandlestickChart } from "./CandlestickChart";
import { useLivePrice } from "../../../shared/hooks/useLivePrice";
import { formatPrice } from "../../../shared/lib/format";

type ChartTimeframe = "15m" | "1h" | "4h" | "1D";
const TIMEFRAMES: ChartTimeframe[] = ["15m", "1h", "4h", "1D"];

interface Props {
  pair: string;
}

export function ChartView({ pair }: Props) {
  const [timeframe, setTimeframe] = useState<ChartTimeframe>("1h");
  const { price, open24h, high24h, low24h, vol24h, change24h } = useLivePrice(pair);

  return (
    <div className="flex flex-col h-[calc(100dvh-6.5rem)]">
      {/* Timeframe selector */}
      <div className="flex gap-1 px-3 py-2">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            onClick={() => setTimeframe(tf)}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              timeframe === tf
                ? "bg-accent/15 text-accent"
                : "text-muted active:bg-card-hover"
            }`}
          >
            {tf}
          </button>
        ))}
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0 px-2">
        <div className="relative w-full h-full rounded-lg overflow-hidden">
          <CandlestickChart pair={pair} timeframe={timeframe} />
        </div>
      </div>

      {/* OHLC Strip */}
      <div className="px-3 py-2 border-t border-border">
        <div className="flex items-center justify-between text-xs font-mono text-muted">
          <div className="flex gap-3">
            <span>O <span className="text-foreground">{open24h ? formatPrice(open24h) : "—"}</span></span>
            <span>H <span className="text-foreground">{high24h ? formatPrice(high24h) : "—"}</span></span>
            <span>L <span className="text-foreground">{low24h ? formatPrice(low24h) : "—"}</span></span>
            <span>C <span className="text-foreground">{price ? formatPrice(price) : "—"}</span></span>
          </div>
        </div>
        <div className="flex items-center justify-between text-xs font-mono mt-0.5">
          <span className="text-muted">
            Vol <span className="text-foreground">{vol24h ? formatVolume(vol24h) : "—"}</span>
          </span>
          {change24h !== null && (
            <span className={change24h >= 0 ? "text-long" : "text-short"}>
              24h {change24h >= 0 ? "+" : ""}{change24h.toFixed(2)}%
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function formatVolume(vol: number): string {
  if (vol >= 1_000_000) return `${(vol / 1_000_000).toFixed(1)}M`;
  if (vol >= 1_000) return `${(vol / 1_000).toFixed(1)}K`;
  return vol.toFixed(1);
}
```

**Step 3: Verify**

```bash
cd web && npx tsc --noEmit && npx vite build
```

---

## Task 6: Signals Tab

**Files:**
- Modify: `web/src/features/signals/components/SignalsView.tsx` (replace placeholder)
- Modify: `web/src/features/signals/components/SignalFeed.tsx`
- Modify: `web/src/features/signals/components/SignalCard.tsx`
- Modify: `web/src/features/signals/components/ConnectionStatus.tsx`
- Delete: `web/src/features/home/components/PerformanceStrip.tsx`

**Step 1: Replace `web/src/features/signals/components/SignalsView.tsx`**

Thin wrapper — dedicated signals tab with header and connection status.

```tsx
import { SignalFeed } from "./SignalFeed";

export function SignalsView() {
  return <SignalFeed />;
}
```

**Step 2: Replace `web/src/features/signals/components/SignalFeed.tsx`**

Add "Active" filter (PENDING outcome signals). Remove PerformanceStrip. Restyle to new palette.

```tsx
import { useState } from "react";
import { useSignalStore } from "../store";
import { SignalCard } from "./SignalCard";
import { SignalDetail } from "./SignalDetail";
import { ConnectionStatus } from "./ConnectionStatus";
import { OrderDialog } from "../../trading/components/OrderDialog";
import type { Signal, UserStatus } from "../types";

type StatusFilter = "ALL" | "ACTIVE" | UserStatus;

const FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "ALL", label: "All" },
  { value: "ACTIVE", label: "Active" },
  { value: "TRADED", label: "Traded" },
  { value: "SKIPPED", label: "Skipped" },
];

export function SignalFeed() {
  const { signals, selectedSignal, selectSignal, clearSelection } = useSignalStore();
  const [tradingSignal, setTradingSignal] = useState<Signal | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");

  const filtered =
    statusFilter === "ALL"
      ? signals
      : statusFilter === "ACTIVE"
        ? signals.filter((s) => !s.outcome || s.outcome === "PENDING")
        : signals.filter((s) => s.user_status === statusFilter);

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-1.5">
          {FILTERS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setStatusFilter(value)}
              className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                statusFilter === value
                  ? "bg-accent/15 text-accent"
                  : "text-muted border border-border"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <ConnectionStatus />
      </div>

      {filtered.length === 0 ? (
        <p className="text-muted text-center text-sm mt-8">
          {statusFilter === "ALL" ? "Waiting for signals..." : `No ${statusFilter.toLowerCase()} signals`}
        </p>
      ) : (
        <div className="space-y-2">
          {filtered.map((signal) => (
            <SignalCard
              key={signal.id}
              signal={signal}
              onSelect={selectSignal}
              onExecute={setTradingSignal}
            />
          ))}
        </div>
      )}

      <SignalDetail signal={selectedSignal} onClose={clearSelection} />
      <OrderDialog signal={tradingSignal} onClose={() => setTradingSignal(null)} />
    </div>
  );
}
```

**Step 3: Replace `web/src/features/signals/components/SignalCard.tsx`**

Restyle to new palette. Score bar fill. New layout matching design: header (pair, direction badge, timeframe pill), score with visual bar, levels, footer (timestamp + status badge).

```tsx
import type { Signal } from "../types";
import { formatScore, formatPrice, formatRelativeTime } from "../../../shared/lib/format";

interface SignalCardProps {
  signal: Signal;
  onSelect: (signal: Signal) => void;
  onExecute?: (signal: Signal) => void;
}

export function SignalCard({ signal, onSelect, onExecute }: SignalCardProps) {
  const isLong = signal.direction === "LONG";
  const dirColor = isLong ? "text-long" : "text-short";
  const borderColor = isLong ? "border-long/20" : "border-short/20";
  const bgColor = isLong ? "bg-long/5" : "bg-short/5";
  const isPending = !signal.outcome || signal.outcome === "PENDING";

  return (
    <button
      onClick={() => onSelect(signal)}
      className={`w-full p-3 rounded-lg border text-left transition-colors active:opacity-80 ${borderColor} ${bgColor}`}
    >
      {/* Header: pair, direction badge, timeframe */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-accent text-xs">&#9889;</span>
          <span className="font-medium text-sm">{signal.pair.replace("-USDT-SWAP", "")}</span>
          <span className={`text-xs font-mono font-bold px-1.5 py-0.5 rounded ${
            isLong ? "bg-long/15 text-long" : "bg-short/15 text-short"
          }`}>
            {signal.direction}
          </span>
          <span className="text-xs text-dim px-1.5 py-0.5 rounded bg-card-hover">
            {signal.timeframe}
          </span>
        </div>
        {!isPending && <OutcomeBadge outcome={signal.outcome} />}
      </div>

      {/* Score with visual bar */}
      <div className="flex items-center gap-2 mt-2">
        <span className="text-xs text-muted">Score</span>
        <span className={`font-mono font-bold text-sm ${dirColor}`}>
          {formatScore(signal.final_score)}
        </span>
        <div className="flex-1 h-1.5 bg-card-hover rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${isLong ? "bg-long" : "bg-short"}`}
            style={{ width: `${Math.min(Math.max(signal.final_score, 0), 100)}%` }}
          />
        </div>
      </div>

      {/* Price levels */}
      <div className="flex items-center gap-3 mt-2 text-xs font-mono text-muted">
        <span>Entry <span className="text-foreground">{formatPrice(signal.levels.entry)}</span></span>
        <span>SL <span className="text-short">{formatPrice(signal.levels.stop_loss)}</span></span>
        <span>TP <span className="text-long">{formatPrice(signal.levels.take_profit_1)}</span></span>
      </div>

      {/* Footer: timestamp + badges */}
      <div className="flex items-center justify-between mt-2">
        <span className="text-xs text-dim">{formatRelativeTime(signal.created_at)}</span>
        <div className="flex items-center gap-1.5">
          {signal.user_status === "TRADED" && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border border-long/40 text-long">Traded</span>
          )}
          {signal.user_status === "SKIPPED" && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border border-border text-muted">Skipped</span>
          )}
          {!isPending && signal.outcome_pnl_pct != null && (
            <span className={`text-xs font-mono ${signal.outcome_pnl_pct >= 0 ? "text-long" : "text-short"}`}>
              {signal.outcome_pnl_pct >= 0 ? "+" : ""}{signal.outcome_pnl_pct.toFixed(2)}%
            </span>
          )}
        </div>
      </div>

      {/* Execute button */}
      {onExecute && isPending && (
        <button
          onClick={(e) => { e.stopPropagation(); onExecute(signal); }}
          className={`mt-2 w-full py-2 rounded text-xs font-medium transition-colors active:opacity-80 ${
            isLong ? "bg-long/15 text-long" : "bg-short/15 text-short"
          }`}
        >
          Execute {signal.direction}
        </button>
      )}
    </button>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    TP1_HIT: "bg-long/20 text-long",
    TP2_HIT: "bg-long/20 text-long",
    SL_HIT: "bg-short/20 text-short",
    EXPIRED: "bg-card-hover text-dim",
  };
  const labels: Record<string, string> = {
    TP1_HIT: "TP1 Hit",
    TP2_HIT: "TP2 Hit",
    SL_HIT: "SL Hit",
    EXPIRED: "Expired",
  };

  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${styles[outcome] ?? ""}`}>
      {labels[outcome] ?? outcome}
    </span>
  );
}
```

**Step 4: Replace `web/src/features/signals/components/ConnectionStatus.tsx`**

```tsx
import { useSignalStore } from "../store";

export function ConnectionStatus() {
  const connected = useSignalStore((s) => s.connected);

  return (
    <div className="flex items-center gap-1.5 text-xs text-muted">
      <div className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-long" : "bg-short animate-pulse"}`} />
      {connected ? "Live" : "..."}
    </div>
  );
}
```

**Step 5: Delete `web/src/features/home/components/PerformanceStrip.tsx`**

This component is no longer imported by any file (HomeView has inline PerformanceCard, SignalFeed no longer uses it).

```bash
rm web/src/features/home/components/PerformanceStrip.tsx
```

**Step 6: Verify**

```bash
cd web && npx tsc --noEmit && npx vite build
```

---

## Task 7: Journal Tab Simplification

**Files:**
- Modify: `web/src/features/signals/components/JournalView.tsx` (remove Feed tab)
- Modify: `web/src/features/signals/components/AnalyticsView.tsx` (remove heatmap, restyle, use theme.colors)
- Modify: `web/src/features/signals/components/CalendarView.tsx` (restyle)

**Step 1: Replace `web/src/features/signals/components/JournalView.tsx`**

Two sub-views only: Analytics and Calendar. Feed moved to Signals tab.

```tsx
import { useState } from "react";
import { AnalyticsView } from "./AnalyticsView";
import { CalendarView } from "./CalendarView";

type JournalTab = "analytics" | "calendar";

const TABS: { key: JournalTab; label: string }[] = [
  { key: "analytics", label: "Analytics" },
  { key: "calendar", label: "Calendar" },
];

export function JournalView() {
  const [tab, setTab] = useState<JournalTab>("analytics");

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 pt-3">
        <div className="flex bg-card rounded-lg p-0.5 border border-border">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                tab === key
                  ? "bg-card-hover text-foreground"
                  : "text-muted"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === "analytics" && <AnalyticsView />}
      {tab === "calendar" && <CalendarView />}
    </div>
  );
}
```

**Step 2: Replace `web/src/features/signals/components/AnalyticsView.tsx`**

Remove HourlyHeatmap. Restyle to new palette. Use `theme.colors` for SVG colors in equity curve.

```tsx
import { useState } from "react";
import { useSignalStats } from "../../home/hooks/useSignalStats";
import { theme } from "../../../shared/theme";
import type { SignalStats } from "../types";

type Period = "7" | "30" | "365";

const PERIODS: { value: Period; label: string }[] = [
  { value: "7", label: "7D" },
  { value: "30", label: "30D" },
  { value: "365", label: "All" },
];

export function AnalyticsView() {
  const [period, setPeriod] = useState<Period>("7");
  const [tradedOnly, setTradedOnly] = useState(false);
  const { stats, loading } = useSignalStats(Number(period));

  if (loading) {
    return (
      <div className="p-3 space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 bg-card rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (!stats || stats.total_resolved === 0) {
    return (
      <div className="p-3">
        <p className="text-muted text-center text-sm mt-12">
          No resolved signals yet — analytics will appear as signals resolve
        </p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3 overflow-y-auto">
      {/* Period selector */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1.5">
          {PERIODS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setPeriod(value)}
              className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                period === value ? "bg-accent/15 text-accent" : "text-muted border border-border"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          onClick={() => setTradedOnly(!tradedOnly)}
          className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
            tradedOnly ? "bg-long/20 text-long border border-long/40" : "text-muted border border-border"
          }`}
        >
          Traded only
        </button>
      </div>

      <SummaryStrip stats={stats} />
      <EquityCurve data={stats.equity_curve} />
      <PairBreakdown data={stats.by_pair} />
      <StreakTracker streaks={stats.streaks} />
    </div>
  );
}

function SummaryStrip({ stats }: { stats: SignalStats }) {
  const netPnl = stats.equity_curve.length > 0
    ? stats.equity_curve[stats.equity_curve.length - 1].cumulative_pnl
    : 0;

  return (
    <div className="bg-card rounded-lg p-3 border border-border">
      <div className="grid grid-cols-4 gap-2 text-center">
        <StatCell label="Win Rate" value={`${stats.win_rate}%`} color={stats.win_rate >= 50 ? "text-long" : "text-short"} />
        <StatCell label="Avg R:R" value={`${stats.avg_rr}`} color="text-foreground" />
        <StatCell label="Signals" value={`${stats.total_resolved}`} color="text-foreground" />
        <StatCell
          label="Net P&L"
          value={`${netPnl >= 0 ? "+" : ""}${netPnl.toFixed(1)}%`}
          color={netPnl >= 0 ? "text-long" : "text-short"}
        />
      </div>
    </div>
  );
}

function StatCell({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div className={`text-base font-mono font-bold ${color}`}>{value}</div>
      <div className="text-[10px] text-muted">{label}</div>
    </div>
  );
}

function EquityCurve({ data }: { data: SignalStats["equity_curve"] }) {
  if (data.length < 2) return null;

  const width = 320;
  const height = 120;
  const pad = { top: 10, right: 10, bottom: 20, left: 10 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;

  const values = data.map((d) => d.cumulative_pnl);
  const minVal = Math.min(0, ...values);
  const maxVal = Math.max(0, ...values);
  const range = maxVal - minVal || 1;

  const points = data
    .map((d, i) => {
      const x = pad.left + (i / (data.length - 1)) * w;
      const y = pad.top + h - ((d.cumulative_pnl - minVal) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  const zeroY = pad.top + h - ((0 - minVal) / range) * h;
  const lastVal = values[values.length - 1];
  const lineColor = lastVal >= 0 ? theme.colors.long : theme.colors.short;

  return (
    <div className="bg-card rounded-lg p-3 border border-border">
      <h3 className="text-[10px] text-muted uppercase tracking-wider mb-2">Equity Curve</h3>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none">
        <line x1={pad.left} y1={zeroY} x2={width - pad.right} y2={zeroY} stroke={theme.colors.border} strokeWidth="0.5" strokeDasharray="4" />
        <polyline fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" points={points} />
      </svg>
    </div>
  );
}

function PairBreakdown({ data }: { data: SignalStats["by_pair"] }) {
  const pairs = Object.entries(data);
  if (pairs.length === 0) return null;

  return (
    <div className="bg-card rounded-lg p-3 border border-border">
      <h3 className="text-[10px] text-muted uppercase tracking-wider mb-2">Pair Breakdown</h3>
      <div className="space-y-2">
        {pairs.map(([pair, stats]) => (
          <div key={pair} className="flex items-center justify-between text-sm">
            <span className="font-medium">{pair.replace("-USDT-SWAP", "")}</span>
            <div className="flex items-center gap-3 text-xs font-mono">
              <span className={stats.win_rate >= 50 ? "text-long" : "text-short"}>
                {stats.win_rate}%
              </span>
              <span className={stats.avg_pnl >= 0 ? "text-long" : "text-short"}>
                {stats.avg_pnl >= 0 ? "+" : ""}{stats.avg_pnl.toFixed(2)}%
              </span>
              <span className="text-dim">{stats.total} trades</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StreakTracker({ streaks }: { streaks: SignalStats["streaks"] }) {
  return (
    <div className="bg-card rounded-lg p-3 border border-border">
      <h3 className="text-[10px] text-muted uppercase tracking-wider mb-2">Streaks</h3>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className={`text-lg font-mono font-bold ${streaks.current >= 0 ? "text-long" : "text-short"}`}>
            {streaks.current >= 0 ? `+${streaks.current}` : streaks.current}
          </div>
          <div className="text-[10px] text-muted">Current</div>
        </div>
        <div>
          <div className="text-lg font-mono font-bold text-long">+{streaks.best_win}</div>
          <div className="text-[10px] text-muted">Best Win</div>
        </div>
        <div>
          <div className="text-lg font-mono font-bold text-short">{streaks.worst_loss}</div>
          <div className="text-[10px] text-muted">Worst Loss</div>
        </div>
      </div>
    </div>
  );
}
```

**Step 3: Restyle `web/src/features/signals/components/CalendarView.tsx`**

Apply these replacements throughout the file:
- `bg-card` stays (same token name, new hex)
- `text-gray-400` → `text-muted`
- `text-gray-500` → `text-muted`
- `text-gray-600` → `text-dim`
- `border-gray-800` → `border-border`
- `border-gray-600` → `border-border`
- `bg-gray-700` → `bg-card-hover`
- `text-white` → `text-foreground`
- `text-long` → `text-accent` (for the "today" day number highlight — gold instead of green)

Specific changes in CalendarView:

In the month navigation section, replace `text-gray-400 hover:text-white` with `text-muted hover:text-foreground`.

In the calendar grid, update day cell classes:
- `isToday ? "text-long font-bold" : "text-gray-400"` → `isToday ? "text-accent font-bold" : "text-muted"`
- `ring-1 ring-long` → `ring-1 ring-accent`
- `border border-gray-600` → `border border-border`

In DaySignalsList, update:
- `text-gray-400` → `text-muted`
- `text-gray-500` → `text-muted`
- `text-white` → `text-foreground`

**Step 4: Verify**

```bash
cd web && npx tsc --noEmit && npx vite build
```

---

## Task 8: More Tab Restyle

**Files:**
- Modify: `web/src/features/more/components/MorePage.tsx` (full rewrite)
- Delete: `web/src/features/dashboard/components/AccountSummary.tsx` (moved to HomeView)
- Delete: `web/src/features/dashboard/components/PositionList.tsx` (moved to HomeView)

**Step 1: Replace `web/src/features/more/components/MorePage.tsx`**

OKX-style grouped settings. Account section removed (now in Home tab). Grouped rows with uppercase section headers, chevrons, toggles, sliders.

```tsx
import { useState } from "react";
import { useSettingsStore } from "../../settings/store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";
import { useSignalStore } from "../../signals/store";
import type { Timeframe } from "../../signals/types";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

function toggleItem<T>(list: T[], item: T, minOne = true): T[] {
  if (list.includes(item)) {
    if (minOne && list.length <= 1) return list;
    return list.filter((i) => i !== item);
  }
  return [...list, item];
}

export function MorePage() {
  const {
    pairs, timeframes, threshold, notificationsEnabled, apiBaseUrl,
    setPairs, setTimeframes, setThreshold, setNotificationsEnabled, setApiBaseUrl,
  } = useSettingsStore();
  const connected = useSignalStore((s) => s.connected);
  const [pushStatus, setPushStatus] = useState<"idle" | "subscribing" | "error">("idle");

  async function handleNotificationToggle(enabled: boolean) {
    setNotificationsEnabled(enabled);
    if (enabled) {
      setPushStatus("subscribing");
      const ok = await subscribeToPush(pairs, timeframes, threshold);
      setPushStatus(ok ? "idle" : "error");
      if (!ok) setNotificationsEnabled(false);
    } else {
      await unsubscribeFromPush();
    }
  }

  return (
    <div className="p-3 space-y-4">
      {/* TRADING */}
      <SettingsGroup title="Trading">
        {/* Pairs */}
        <div className="px-3 py-3 border-b border-border">
          <div className="text-[10px] text-dim uppercase tracking-wider mb-2">Pairs</div>
          <div className="flex gap-1.5">
            {AVAILABLE_PAIRS.map((pair) => (
              <button
                key={pair}
                onClick={() => setPairs(toggleItem(pairs, pair))}
                className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
                  pairs.includes(pair)
                    ? "bg-accent/15 text-accent border border-accent/30"
                    : "bg-card-hover text-muted"
                }`}
              >
                {pair.replace("-USDT-SWAP", "")}
              </button>
            ))}
          </div>
        </div>

        {/* Timeframes */}
        <div className="px-3 py-3 border-b border-border">
          <div className="text-[10px] text-dim uppercase tracking-wider mb-2">Timeframes</div>
          <div className="flex gap-1.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframes(toggleItem(timeframes, tf))}
                className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
                  timeframes.includes(tf)
                    ? "bg-accent/15 text-accent border border-accent/30"
                    : "bg-card-hover text-muted"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        {/* Threshold */}
        <div className="px-3 py-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm">Signal Threshold</span>
            <span className="text-sm font-mono text-accent">{threshold}</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-full accent-accent"
          />
          <div className="flex justify-between text-[10px] text-dim mt-0.5">
            <span>All</span>
            <span>Strong only</span>
          </div>
        </div>
      </SettingsGroup>

      {/* NOTIFICATIONS */}
      <SettingsGroup title="Notifications">
        <div className="px-3 py-3 flex items-center justify-between">
          <div>
            <span className="text-sm">Push Notifications</span>
            {pushStatus === "error" && (
              <p className="text-xs text-short mt-0.5">Permission denied</p>
            )}
          </div>
          <input
            type="checkbox"
            checked={notificationsEnabled}
            disabled={pushStatus === "subscribing"}
            onChange={(e) => handleNotificationToggle(e.target.checked)}
            className="accent-accent w-4 h-4"
          />
        </div>
      </SettingsGroup>

      {/* CONNECTION */}
      <SettingsGroup title="Connection">
        <div className="px-3 py-3 border-b border-border">
          <div className="text-[10px] text-dim uppercase tracking-wider mb-2">API URL</div>
          <input
            type="url"
            value={apiBaseUrl}
            onChange={(e) => setApiBaseUrl(e.target.value)}
            className="w-full p-2.5 bg-card-hover rounded-lg border border-border text-sm font-mono focus:border-accent/50 focus:outline-none"
          />
        </div>
        <div className="px-3 py-3 flex items-center justify-between">
          <span className="text-sm">Status</span>
          <div className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${connected ? "bg-long" : "bg-short animate-pulse"}`} />
            <span className="text-sm text-muted">{connected ? "Connected" : "Disconnected"}</span>
          </div>
        </div>
      </SettingsGroup>

      {/* ABOUT */}
      <SettingsGroup title="About">
        <div className="px-3 py-3 flex items-center justify-between">
          <span className="text-sm">Version</span>
          <span className="text-sm text-muted font-mono">1.0.0</span>
        </div>
      </SettingsGroup>
    </div>
  );
}

function SettingsGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-[10px] text-dim font-medium uppercase tracking-wider mb-1.5 px-1">{title}</h2>
      <div className="bg-card rounded-lg border border-border overflow-hidden">
        {children}
      </div>
    </div>
  );
}
```

**Step 2: Delete unused dashboard components**

```bash
rm web/src/features/dashboard/components/AccountSummary.tsx
rm web/src/features/dashboard/components/PositionList.tsx
```

Note: Keep `web/src/features/dashboard/hooks/useAccount.ts` — it's used by the new HomeView.

**Step 3: Verify**

```bash
cd web && npx tsc --noEmit && npx vite build
```

---

## Task 9: Signal Detail & Remaining Component Migration

**Files:**
- Modify: `web/src/features/signals/components/SignalDetail.tsx`

**Step 1: Restyle `web/src/features/signals/components/SignalDetail.tsx`**

Apply these replacements throughout the file (replace_all):

| Old | New |
|-----|-----|
| `border-gray-800` | `border-border` |
| `text-gray-400` | `text-muted` |
| `text-gray-500` | `text-muted` |
| `text-gray-600` | `text-dim` |
| `text-gray-300` | `text-foreground` |
| `text-white` | `text-foreground` |
| `text-xl` (close button) | `text-xl text-muted hover:text-foreground` |
| `bg-surface` (textarea) | `bg-card-hover` |
| `focus:border-gray-600` | `focus:border-accent/50` |
| `placeholder-gray-600` | `placeholder-dim` |
| `bg-gray-700 text-white border border-gray-600` (OBSERVED button active) | `bg-card-hover text-foreground border border-border` |
| `bg-gray-700 text-gray-300 border border-gray-600` (SKIPPED button active) | `bg-card-hover text-muted border border-border` |
| `text-gray-500 border border-gray-800` (inactive status button) | `text-muted border border-border` |

In the JournalSection status buttons:
- Traded active: `bg-long/20 text-long border border-long/40` (keep as-is)
- OBSERVED active: `bg-card-hover text-foreground border border-border`
- SKIPPED active: `bg-card-hover text-muted border border-border`
- Inactive: `text-muted border border-border`

**Step 2: Delete unused component**

```bash
rm web/src/features/home/components/IndicatorStrip.tsx
```

This component was never used in JSX (imported but unused).

**Step 3: Final Verify**

```bash
cd web && npx tsc --noEmit && npx vite build
```

---

## Final Commit

After all tasks pass verification, commit everything together:

```bash
cd web && git add -A && git status
```

Review staged files, then commit:

```bash
git commit -m "feat: OKX-inspired UI revamp with new theme system and 5-tab navigation

- Add centralized theme.ts with OKX-inspired color palette (deep backgrounds, gold accent)
- Restructure from 4 tabs to 5: Home, Chart, Signals, Journal, More
- Home: full account overview with balance, positions, recent signals, performance
- Chart: add 1D timeframe, OHLC strip with 24h data
- Signals: dedicated tab with Active/Traded/Skipped filters and score bars
- Journal: simplified to Analytics + Calendar (feed moved to Signals)
- More: OKX-style grouped settings, account info moved to Home
- Update all components to new color tokens and Inter/JetBrains Mono fonts"
```

---

## Color Token Quick Reference

Use this when migrating any component:

| Old Class | New Class |
|-----------|-----------|
| `bg-surface` | `bg-surface` (same name, new hex #0B0E11) |
| `bg-card` | `bg-card` (same name, new hex #12161C) |
| `bg-card-hover` | `bg-card-hover` (same name, new hex #1A1F28) |
| `text-white` | `text-foreground` |
| `text-gray-400` | `text-muted` |
| `text-gray-500` | `text-muted` |
| `text-gray-600` | `text-dim` |
| `border-gray-800` | `border-border` |
| `border-gray-800/50` | `border-border` |
| `bg-gray-700` | `bg-card-hover` |
| `bg-gray-800` | `bg-card-hover` |
| `text-long` (for active UI) | `text-accent` |
| `bg-long/15` (for active UI) | `bg-accent/15` |
| `accent-long` (form controls) | `accent-accent` |

**When to use `text-accent` vs `text-long`:**
- `text-accent` (gold): Active tabs, selected pills, UI highlights, pair name, interactive elements
- `text-long` (green): LONG direction badges, profit numbers, positive P&L
- `text-short` (red): SHORT direction badges, loss numbers, negative P&L
