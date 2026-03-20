# Kinetic Terminal — Plan 2: Core Views

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reskin the 5 main tab views and their direct sub-components from the OKX-style design to the Kinetic Terminal M3 design system.

**Architecture:** Pure visual reskin — swap Tailwind classes from legacy tokens (`bg-card`, `text-muted`, `text-accent`, `border-border`) to M3 tokens (`bg-surface-container`, `text-on-surface-variant`, `text-primary`, `border-outline-variant/15`). Replace inline SVGs with Lucide React icons. Add `font-headline` (Space Grotesk) to headlines/scores, `tabular` to numeric displays. No business logic, hook, store, or type changes.

**Tech Stack:** React 19, Tailwind CSS 3, Lucide React, Motion (motion.dev) — all installed in Plan 1.

**Depends on:** Plan 1 (Foundation + Layout) must be complete. Verify: `web/src/shared/theme.ts` exports M3 tokens, `tailwind.config.ts` wires them, Layout.tsx uses Lucide icons + motion tabs.

**Deferred to Plan 3:** The spec lists `onPairDrillDown` callback props for `HomeView.tsx` and `SignalCard.tsx` (for Pair Deep Dive drill-down). These are omitted from this plan because PairDeepDive is a Plan 3 deliverable. Plan 3 implementers will need to thread these callbacks through Layout → HomeView/SignalCard at that time.

**Stitch reference screens:** `web/.stitch-screens/` — open these HTML files in a browser to compare against your implementation.

---

## Token Migration Cheat Sheet

Use this for every file in this plan. The left column is what you'll find in current code; the right is the replacement.

| Old Token | New M3 Token | Notes |
|-----------|-------------|-------|
| `bg-card` | `bg-surface-container` | Default card background |
| `bg-card-hover` | `bg-surface-container-highest` | Hover/selected states |
| `border-border` | `border-outline-variant/10` or `/15` | Ghost borders only; remove borders where tonal layering suffices |
| `divide-border` | `divide-outline-variant/10` | List dividers |
| `text-muted` | `text-on-surface-variant` | Secondary text |
| `text-dim` | `text-outline` | Tertiary/disabled text |
| `text-foreground` | `text-on-surface` | Primary text |
| `text-accent` | `text-primary` | Links, accents |
| `bg-accent/15` (active pill) | `bg-surface-container-highest text-primary` | Active filter/tab state |
| `border-accent/30` (active pill) | *(remove)* | No border on active pills |
| `text-muted border border-border` (inactive pill) | `text-on-surface-variant` | Inactive filter — no border, no bg |
| Section labels | `text-[10px] uppercase tracking-widest text-on-surface-variant` | Was `text-[11px] font-semibold uppercase tracking-wider text-muted` |
| Headlines/pair names | Add `font-headline` | Space Grotesk |
| Numeric displays | Add `tabular` class | Tabular figures |
| `rounded-lg` | `rounded-lg` | Same name, now maps to 4px via theme |
| `glass-card` | `bg-surface-container rounded-lg p-*` | Use surface-container for regular cards; keep glass-card only for AccountHeader/PerformanceCard |
| Inline SVG icons | `import { IconName } from "lucide-react"` | Tree-shaken |

**Legacy aliases (`text-long`, `text-short`, `bg-long/*`, `bg-short/*`) are valid** — they map to the new green/red. No need to replace these.

---

## Cross-Cutting Patterns

Apply these patterns across **every** task in this plan.

### Dialog Base Styles

All `<dialog>` elements must include proper base classes. Without these, dialogs render with browser defaults (white background, no backdrop, no sizing).

| Dialog | Base Classes |
|--------|-------------|
| IndicatorSheet (bottom sheet) | `className="fixed inset-x-0 bottom-0 top-auto m-0 w-full max-h-[70dvh] overflow-y-auto rounded-t-xl bg-surface-container text-on-surface p-0 backdrop:bg-black/60"` |
| SignalDetail (modal) | `className="bg-surface-container text-on-surface rounded-xl w-[calc(100%-2rem)] max-w-lg max-h-[90dvh] overflow-y-auto p-0 m-auto backdrop:bg-black/60"` |
| OrderDialog (modal) | `className="bg-surface-container text-on-surface rounded-xl w-[calc(100%-2rem)] max-w-md max-h-[85dvh] overflow-y-auto p-0 m-auto backdrop:bg-black/60"` |

### Focus-Visible on All Interactive Elements

Every `<button>` and interactive element must include a keyboard focus ring. Use this class set on all buttons, pills, toggles, and cards:

```
focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary
```

### Reduced Motion

Decorative and entrance animations (`animate-pulse-glow`, `animate-card-enter`, `stagger-*`) must use the `motion-safe:` prefix so they are suppressed when the user has `prefers-reduced-motion` enabled. Example: `motion-safe:animate-pulse-glow`. Skeleton loading pulses (`animate-pulse` on placeholder elements) are functional feedback and remain unconditional.

### Animation Classes from Plan 1

The following CSS classes are defined in Plan 1's global styles and must be present before this plan executes:

- `animate-pulse-glow` — subtle glow pulse on active signal cards
- `animate-card-enter` — slide-up + fade-in for card list items
- `stagger-1` through `stagger-10` — incremental animation-delay classes (30-50ms per step)
- `terminal-grid` — subtle grid background pattern for More hub

Verify these exist in `web/src/index.css` or equivalent before starting.

### Section Label Tiers

Two tiers of section labels are used:

| Tier | Usage | Classes |
|------|-------|---------|
| **Section heading** (h2) | Top-level section titles on Home tab ("Open Positions", "Recent Signals", "Latest News") | `text-xs font-bold uppercase tracking-widest text-on-surface-variant` |
| **Subsection label** | Labels within cards and detail views ("Total Equity", "Performance (7D)", "Intelligence Components") | `text-[10px] uppercase tracking-widest text-on-surface-variant` |

Section headings intentionally omit `font-headline` to stay subordinate to data values that use it.

---

## File Map

| # | File | Action | Task |
|---|------|--------|------|
| 1 | `web/src/features/home/components/HomeView.tsx` | Modify | 1 |
| 2 | `web/src/features/home/components/RecentSignals.tsx` | Modify | 1 |
| 3 | `web/src/features/chart/components/ChartView.tsx` | Modify | 2 |
| 4 | `web/src/features/chart/components/IndicatorSheet.tsx` | Modify | 2 |
| 5 | `web/src/features/signals/components/SignalsView.tsx` | Modify | 3 |
| 6 | `web/src/features/signals/components/SignalFeed.tsx` | Modify | 3 |
| 7 | `web/src/features/signals/components/ConnectionStatus.tsx` | Modify | 3 |
| 8 | `web/src/features/signals/components/SignalCard.tsx` | Modify | 4 |
| 9 | `web/src/features/signals/components/PatternBadges.tsx` | Modify | 4 |
| 10 | `web/src/features/signals/components/SignalDetail.tsx` | Modify | 5 |
| 11 | `web/src/features/signals/components/DeepDiveView.tsx` | Modify | 6 |
| 12 | `web/src/features/news/components/NewsFeed.tsx` | Modify | 7 |
| 13 | `web/src/features/news/components/NewsCard.tsx` | Modify | 7 |
| 14 | `web/src/features/more/components/MorePage.tsx` | Modify | 8 |
| 15 | `web/src/features/trading/components/OrderDialog.tsx` | Modify | 9 |

`NewsView.tsx` is a 4-line wrapper (`return <NewsFeed />`) — no changes needed.

---

## Task 1: Home Tab (HomeView + RecentSignals)

**Files:**
- Modify: `web/src/features/home/components/HomeView.tsx`
- Modify: `web/src/features/home/components/RecentSignals.tsx`
- Reference: `web/.stitch-screens/dashboard.html`

**Changes summary:**
- AccountHeader: `glass-card` stays (hero card), add `font-headline` + `tabular` to equity, use `text-on-surface-variant` for label, `text-[10px] uppercase tracking-widest`
- PortfolioStrip: `bg-card` → `bg-surface-container-low`, labels → `text-[10px] uppercase tracking-widest text-on-surface-variant`, values → `font-headline font-bold tabular`
- OpenPositions: `bg-card` → `bg-surface-container`, `border-border` → `border-outline-variant/10`, add direction icon + leverage badge, labels `text-on-surface-variant`, pair name `font-headline font-bold`
- LatestNewsCard: same token migration, headline `font-headline`
- PerformanceCard: `glass-card` stays, values `font-headline tabular`
- RecentSignals: replace inline SVG bolt with Lucide `Zap`, token migration, pair name `font-headline`

- [ ] **Step 1: Update HomeView.tsx**

Write the full updated file:

```tsx
import { useState } from "react";
import { useAccount } from "../../dashboard/hooks/useAccount";
import { useSignalStats } from "../hooks/useSignalStats";
import { useRecentNews } from "../../news/hooks/useNews";
import { RecentSignals } from "./RecentSignals";
import { formatPrice, formatRelativeTime } from "../../../shared/lib/format";
import { TrendingUp, TrendingDown } from "lucide-react";
import type { Portfolio, Position } from "../../../shared/lib/api";
import type { SignalStats } from "../../signals/types";
import type { NewsEvent } from "../../news/types";

export function HomeView() {
  const { portfolio, positions, loading: accountLoading, error, refresh } = useAccount();
  const { stats, loading: statsLoading } = useSignalStats();
  const { news: recentNews, loading: newsLoading } = useRecentNews(5);

  if (error && !portfolio) {
    return (
      <div className="flex flex-col gap-3 p-4">
        <div className="bg-surface-container rounded-lg p-4 text-center">
          <p className="text-on-surface-variant text-sm">Unable to load portfolio</p>
          <button
            onClick={refresh}
            className="mt-2 px-4 py-1.5 text-xs font-medium rounded-lg bg-surface-container-highest text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            Retry
          </button>
        </div>
        <RecentSignals />
        <LatestNewsCard news={recentNews} loading={newsLoading} />
        <PerformanceCard stats={stats} loading={statsLoading} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      <AccountHeader portfolio={portfolio} loading={accountLoading} />
      <PortfolioStrip portfolio={portfolio} loading={accountLoading} />
      <OpenPositions positions={positions} loading={accountLoading} />
      <RecentSignals />
      <LatestNewsCard news={recentNews} loading={newsLoading} />
      <PerformanceCard stats={stats} loading={statsLoading} />
    </div>
  );
}

function AccountHeader({ portfolio, loading }: { portfolio: Portfolio | null; loading: boolean }) {
  if (loading) return <div className="h-24 bg-surface-container rounded-lg animate-pulse" />;
  if (!portfolio) return null;

  const pnl = portfolio.unrealized_pnl;
  const pct = portfolio.total_equity > 0 ? (pnl / portfolio.total_equity) * 100 : 0;
  const isPositive = pnl >= 0;

  return (
    <div className="bg-surface-container rounded-lg p-5">
      <span className="text-on-surface-variant text-[10px] uppercase tracking-widest">Total Equity</span>
      <div className="font-headline text-3xl font-bold mt-1 tabular">${formatPrice(portfolio.total_equity)}</div>
      <div className="flex items-center gap-2 mt-3">
        <span className={`font-headline font-bold text-lg tabular ${isPositive ? "text-long" : "text-short"}`}>
          {isPositive ? "+" : ""}${formatPrice(Math.abs(pnl))}
        </span>
        <span className={`text-xs font-bold px-2 py-0.5 rounded tabular ${
          isPositive ? "bg-long/10 text-long" : "bg-short/10 text-short"
        }`}>
          {isPositive ? "+" : ""}{pct.toFixed(1)}%
        </span>
      </div>
    </div>
  );
}

function PortfolioStrip({ portfolio, loading }: { portfolio: Portfolio | null; loading: boolean }) {
  if (loading || !portfolio) return null;

  const exposurePct = portfolio.total_equity > 0
    ? (portfolio.total_exposure / portfolio.total_equity * 100)
    : 0;

  return (
    <div className="bg-surface-container-low rounded-lg p-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          <span className="text-on-surface-variant text-[10px] uppercase tracking-widest block">Unrealized</span>
          <span className={`font-headline font-bold text-sm tabular ${portfolio.unrealized_pnl >= 0 ? "text-long" : "text-short"}`}>
            {portfolio.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(portfolio.unrealized_pnl)}
          </span>
        </div>
        <div>
          <span className="text-on-surface-variant text-[10px] uppercase tracking-widest block">Available</span>
          <span className="font-headline font-bold text-sm tabular">${formatPrice(portfolio.available_balance)}</span>
        </div>
        <div>
          <span className="text-on-surface-variant text-[10px] uppercase tracking-widest block">Margin</span>
          <span className="font-headline font-bold text-sm tabular">{portfolio.margin_utilization.toFixed(1)}%</span>
        </div>
        <div>
          <span className="text-on-surface-variant text-[10px] uppercase tracking-widest block">Exposure</span>
          <span className={`font-headline font-bold text-sm tabular ${exposurePct > 100 ? "text-primary" : ""}`}>
            {exposurePct.toFixed(0)}%
          </span>
        </div>
      </div>
    </div>
  );
}

function OpenPositions({ positions, loading }: { positions: Position[]; loading: boolean }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (loading) return <div className="h-16 bg-surface-container rounded-lg animate-pulse" />;

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-baseline px-1">
        <h2 className="text-xs font-bold tracking-widest uppercase text-on-surface-variant">
          Open Positions ({positions.length})
        </h2>
      </div>
      {positions.length === 0 ? (
        <p className="px-1 text-sm text-outline">No open positions</p>
      ) : (
        <div className="space-y-2">
          {positions.map((pos) => {
            const key = `${pos.pair}-${pos.side}`;
            const isLong = pos.side === "long";
            const isExpanded = expanded === key;
            const DirIcon = isLong ? TrendingUp : TrendingDown;

            return (
              <div key={key} className="bg-surface-container-high rounded-lg overflow-hidden">
                <button
                  onClick={() => setExpanded(isExpanded ? null : key)}
                  aria-expanded={isExpanded}
                  aria-label={`${pos.pair.replace("-USDT-SWAP", "")} ${pos.side} position details`}
                  className="w-full p-3 flex items-center justify-between text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  <div className="flex items-center gap-3">
                    <div className={`p-1.5 rounded ${isLong ? "bg-long/10" : "bg-short/10"}`}>
                      <DirIcon size={16} className={isLong ? "text-long" : "text-short"} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-headline font-bold text-sm">{pos.pair.replace("-USDT-SWAP", "")}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
                          isLong ? "bg-long/20 text-long" : "bg-short/20 text-short"
                        }`}>
                          {pos.side.toUpperCase()} {pos.leverage}x
                        </span>
                      </div>
                      <span className="text-[10px] text-on-surface-variant tabular">Size: {pos.size}</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className={`font-headline font-bold text-sm block tabular ${pos.unrealized_pnl >= 0 ? "text-long" : "text-short"}`}>
                      {pos.unrealized_pnl >= 0 ? "+" : ""}{formatPrice(pos.unrealized_pnl)}
                    </span>
                    <span className="text-[10px] text-on-surface-variant tabular">${formatPrice(pos.mark_price)}</span>
                  </div>
                </button>
                {isExpanded && (
                  <div className="px-3 pb-3 grid grid-cols-3 gap-2 bg-surface-container-lowest/30">
                    <div>
                      <span className="text-[10px] text-on-surface-variant block uppercase">Entry</span>
                      <span className="text-xs font-medium tabular">${formatPrice(pos.avg_price)}</span>
                    </div>
                    <div>
                      <span className="text-[10px] text-on-surface-variant block uppercase">Mark</span>
                      <span className="text-xs font-medium tabular">${formatPrice(pos.mark_price)}</span>
                    </div>
                    {pos.liquidation_price && (
                      <div>
                        <span className="text-[10px] text-on-surface-variant block uppercase">Liq. Price</span>
                        <span className="text-xs font-medium text-short tabular">${formatPrice(pos.liquidation_price)}</span>
                      </div>
                    )}
                    <div>
                      <span className="text-[10px] text-on-surface-variant block uppercase">Margin</span>
                      <span className="text-xs font-medium tabular">${formatPrice(pos.margin)}</span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

const IMPACT_BORDER: Record<string, string> = {
  high: "border-l-error",
  medium: "border-l-primary/40",
};

const SENTIMENT_COLOR: Record<string, string> = {
  bullish: "text-long",
  bearish: "text-short",
  neutral: "text-on-surface-variant",
};

function LatestNewsCard({ news, loading }: { news: NewsEvent[]; loading: boolean }) {
  if (loading) return <div className="h-16 bg-surface-container rounded-lg animate-pulse" />;
  if (news.length === 0) return null;

  return (
    <div className="space-y-3">
      <h2 className="text-xs font-bold tracking-widest uppercase text-on-surface-variant px-1">
        Latest News
      </h2>
      <div className="space-y-2">
        {news.map((n) => (
          <div key={n.id} className={`bg-surface-container-low rounded-lg p-3 border-l-4 ${IMPACT_BORDER[n.impact ?? ""] ?? "border-l-outline-variant/20"}`}>
            <p className="text-sm font-medium leading-snug">{n.headline}</p>
            <div className="flex items-center gap-2 mt-1.5">
              <span className="text-[10px] text-on-surface-variant tabular">{n.source}</span>
              {n.sentiment && (
                <span className={`text-[10px] font-medium ${SENTIMENT_COLOR[n.sentiment] ?? ""}`}>
                  {n.sentiment}
                </span>
              )}
              <span className="text-[10px] text-outline">{n.published_at ? formatRelativeTime(n.published_at) : ""}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PerformanceCard({ stats, loading }: { stats: SignalStats | null; loading: boolean }) {
  if (loading) return <div className="h-16 bg-surface-container rounded-lg animate-pulse" />;
  if (!stats || stats.total_resolved === 0) return null;

  const netPnl = stats.equity_curve.length > 0
    ? stats.equity_curve[stats.equity_curve.length - 1].cumulative_pnl
    : 0;

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <div className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-3">Performance (7D)</div>
      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <div className={`text-xl font-headline font-bold tabular ${stats.win_rate >= 50 ? "text-long" : "text-short"}`}>
            {stats.win_rate}%
          </div>
          <div className="text-[10px] text-on-surface-variant">Win Rate</div>
        </div>
        <div>
          <div className="text-xl font-headline font-bold tabular">{stats.avg_rr}</div>
          <div className="text-[10px] text-on-surface-variant">Avg R:R</div>
        </div>
        <div>
          <div className={`text-xl font-headline font-bold tabular ${netPnl >= 0 ? "text-long" : "text-short"}`}>
            {netPnl >= 0 ? "+" : ""}{netPnl.toFixed(1)}%
          </div>
          <div className="text-[10px] text-on-surface-variant">Net P&L</div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update RecentSignals.tsx**

```tsx
import { useEffect, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { Zap } from "lucide-react";
import { useSignalStore } from "../../signals/store";
import { formatScore, formatRelativeTime } from "../../../shared/lib/format";
import type { Signal } from "../../signals/types";

export function RecentSignals() {
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  const signals = useSignalStore(useShallow((s) =>
    s.signals.filter((sig) => new Date(sig.created_at).getTime() > cutoff).slice(0, 3)
  ));

  return (
    <div className="space-y-3">
      <div className="px-1">
        <h2 className="text-xs font-bold tracking-widest uppercase text-on-surface-variant">
          Recent Signals ({signals.length})
        </h2>
      </div>
      {signals.length === 0 ? (
        <p className="px-1 text-sm text-outline">No signals in the last 24 hours</p>
      ) : (
        <div className="bg-surface-container rounded-lg overflow-hidden divide-y divide-outline-variant/10">
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
        <Zap size={14} className="text-primary flex-shrink-0" />
        <span className="font-headline font-bold text-sm">{signal.pair.replace("-USDT-SWAP", "")}</span>
        <span className={`text-xs font-mono font-bold ${isLong ? "text-long" : "text-short"}`}>
          {signal.direction}
        </span>
        <span className={`text-xs font-mono tabular ${isLong ? "text-long" : "text-short"}`}>
          {formatScore(signal.final_score)}
        </span>
        <span className="text-[10px] text-outline">{signal.timeframe}</span>
      </div>
      <span className="text-[10px] text-outline tabular">{formatRelativeTime(signal.created_at)}</span>
    </div>
  );
}
```

- [ ] **Step 3: Build and verify**

Run: `cd web && pnpm build`
Expected: Clean build, zero errors.

---

## Task 2: Chart Tab (ChartView + IndicatorSheet)

**Files:**
- Modify: `web/src/features/chart/components/ChartView.tsx`
- Modify: `web/src/features/chart/components/IndicatorSheet.tsx`
- Reference: `web/.stitch-screens/chart.html`

**Changes summary:**
- Timeframe pills: `bg-surface-container-highest text-primary` active, `font-headline font-bold`, inactive `text-on-surface-variant`
- Gear icon → Lucide `SlidersHorizontal`, badge uses `bg-primary-container text-on-primary-fixed`
- OHLC strip: M3 tokens, `text-[10px] uppercase tracking-widest text-on-surface-variant`
- IndicatorSheet: group headers `font-headline`, toggle `bg-primary` (not `bg-accent`), sheet close → Lucide `X`

- [ ] **Step 1: Update ChartView.tsx**

```tsx
import { useState, useCallback } from "react";
import { SlidersHorizontal } from "lucide-react";
import { CandlestickChart } from "./CandlestickChart";
import { IndicatorSheet, getStoredIndicators, hasOscillator } from "./IndicatorSheet";
import { useChartData } from "../hooks/useChartData";
import { useLivePrice } from "../../../shared/hooks/useLivePrice";
import { formatPrice } from "../../../shared/lib/format";

type ChartTimeframe = "15m" | "1h" | "4h" | "1D";
const TIMEFRAMES: ChartTimeframe[] = ["15m", "1h", "4h", "1D"];

interface Props {
  pair: string;
}

export function ChartView({ pair }: Props) {
  const [timeframe, setTimeframe] = useState<ChartTimeframe>("1h");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [enabledIds, setEnabledIds] = useState<Set<string>>(getStoredIndicators);
  const { price, open24h, high24h, low24h, vol24h, change24h } = useLivePrice(pair);
  const { candles, loading, onTickRef } = useChartData(pair, timeframe);

  const fullScreen = hasOscillator(enabledIds);

  const handleToggle = useCallback((id: string) => {
    setEnabledIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    {/* Heights assume 4rem nav bar; 6.5rem = nav + OHLC strip. Update if Layout nav height changes. */}
    <div className={`flex flex-col ${fullScreen ? "h-[calc(100dvh-4rem)]" : "h-[calc(100dvh-6.5rem)]"}`}>
      {/* Timeframe selector + indicator gear */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-surface-container border-b border-outline-variant/10">
        <div className="flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-3 py-1 text-xs font-bold font-headline rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                timeframe === tf
                  ? "bg-surface-container-highest text-primary"
                  : "text-on-surface-variant hover:bg-surface-container-highest"
              }`}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>
        <button
          onClick={() => setSheetOpen(true)}
          aria-label={`Indicators${enabledIds.size > 0 ? ` (${enabledIds.size} active)` : ""}`}
          className={`relative p-2 rounded-lg transition-colors active:bg-surface-container-highest focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
            enabledIds.size > 0 ? "text-primary" : "text-on-surface-variant"
          }`}
        >
          <SlidersHorizontal size={18} />
          {enabledIds.size > 0 && (
            <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-primary-container text-on-primary-fixed text-[10px] font-bold rounded-full flex items-center justify-center">
              {enabledIds.size}
            </span>
          )}
        </button>
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0 px-2">
        <div className="w-full h-full rounded-lg overflow-hidden">
          <CandlestickChart candles={candles} enabledIndicators={enabledIds} loading={loading} onTickRef={onTickRef} />
        </div>
      </div>

      {/* OHLC Strip — hidden when oscillators are active */}
      {!fullScreen && (
        <div className="px-3 py-2 border-t border-outline-variant/10">
          <div className="flex items-center justify-between text-[10px] uppercase tracking-widest text-on-surface-variant font-medium">
            <div className="flex gap-3">
              <span>O <span className="text-on-surface tabular">{open24h ? formatPrice(open24h) : "—"}</span></span>
              <span>H <span className="text-on-surface tabular">{high24h ? formatPrice(high24h) : "—"}</span></span>
              <span>L <span className="text-on-surface tabular">{low24h ? formatPrice(low24h) : "—"}</span></span>
              <span>C <span className="text-on-surface tabular">{price ? formatPrice(price) : "—"}</span></span>
            </div>
          </div>
          <div className="flex items-center justify-between text-xs font-mono mt-0.5">
            <span className="text-on-surface-variant">
              Vol <span className="text-on-surface tabular">{vol24h ? formatVolume(vol24h) : "—"}</span>
            </span>
            {change24h !== null && (
              <span className={`tabular ${change24h >= 0 ? "text-long" : "text-short"}`}>
                24h {change24h >= 0 ? "+" : ""}{change24h.toFixed(2)}%
              </span>
            )}
          </div>
        </div>
      )}

      {/* Indicator Bottom Sheet */}
      <IndicatorSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        enabled={enabledIds}
        onToggle={handleToggle}
      />
    </div>
  );
}

function formatVolume(vol: number): string {
  if (vol >= 1_000_000) return `${(vol / 1_000_000).toFixed(1)}M`;
  if (vol >= 1_000) return `${(vol / 1_000).toFixed(1)}K`;
  return vol.toFixed(1);
}
```

- [ ] **Step 2: Update IndicatorSheet.tsx**

Replace the `IndicatorSheet` component rendering (lines 97-172). Keep all data definitions (lines 1-95) unchanged. Add `import { X } from "lucide-react";` to the existing imports at line 1. Only the JSX changes:

```tsx
// Lines 1-95 stay exactly the same (imports, INDICATOR_GROUPS, INDICATOR_MAP, etc.)
// Add to imports: import { X } from "lucide-react";
// Only the IndicatorSheet component rendering changes:

export function IndicatorSheet({ open, onClose, enabled, onToggle }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      dialog.showModal();
    } else {
      dialog.close();
    }
  }, [open]);

  const handleToggle = (id: string) => {
    const next = new Set(enabled);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    saveIndicators(next);
    onToggle(id);
  };

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose();
      }}
      className="fixed inset-x-0 bottom-0 top-auto m-0 w-full max-h-[70dvh] overflow-y-auto rounded-t-xl bg-surface-container text-on-surface p-0 backdrop:bg-black/60"
    >
      <div className="p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-headline font-bold text-base">Indicators</h2>
          <button onClick={onClose} aria-label="Close indicators" className="text-on-surface-variant p-2 hover:text-on-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-lg">
            <X size={20} />
          </button>
        </div>

        {INDICATOR_GROUPS.map((group) => (
          <div key={group.label} className="mb-4">
            <h3 className="text-[10px] font-headline font-bold text-on-surface-variant uppercase tracking-widest mb-2">
              {group.label}
            </h3>
            <div className="space-y-1">
              {group.items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => handleToggle(item.id)}
                  className={`flex items-center justify-between w-full px-3 py-2.5 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                    enabled.has(item.id) ? "bg-primary/10 border border-primary/20" : "active:bg-surface-container-highest"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="text-sm">{item.label}</span>
                  </div>
                  <div
                    className={`w-9 h-5 rounded-full relative transition-colors ${
                      enabled.has(item.id) ? "bg-primary" : "bg-outline-variant"
                    }`}
                  >
                    <div
                      className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                        enabled.has(item.id) ? "translate-x-4" : "translate-x-0.5"
                      }`}
                    />
                  </div>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </dialog>
  );
}
```

- [ ] **Step 3: Build and verify**

Run: `cd web && pnpm build`
Expected: Clean build.

---

## Task 3: Signals View + Feed + ConnectionStatus

**Files:**
- Modify: `web/src/features/signals/components/SignalsView.tsx`
- Modify: `web/src/features/signals/components/SignalFeed.tsx`
- Modify: `web/src/features/signals/components/ConnectionStatus.tsx`
- Reference: `web/.stitch-screens/signals.html`

**Changes summary:**
- SignalsView segmented control: `bg-surface-container-lowest` wrapper, active `bg-surface-container-highest text-primary`, inactive `text-on-surface-variant`
- SignalFeed filter pills: same pattern in `bg-surface-container-lowest` wrapper
- ConnectionStatus: green glow dot + "Connected (Live OKX Feed)" text

- [ ] **Step 1: Update SignalsView.tsx**

```tsx
import { useState } from "react";
import { SignalFeed } from "./SignalFeed";
import { JournalView } from "./JournalView";

type ActiveView = "signals" | "journal";

export function SignalsView() {
  const [activeView, setActiveView] = useState<ActiveView>("signals");

  return (
    <div className="flex flex-col h-full">
      {/* Segmented control */}
      <div className="p-3 pb-0">
        <div className="flex gap-1 bg-surface-container-lowest p-1 rounded-lg w-fit">
          <button
            onClick={() => setActiveView("signals")}
            className={`px-4 py-1.5 rounded text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              activeView === "signals"
                ? "bg-surface-container-highest text-primary"
                : "text-on-surface-variant hover:bg-surface-container-highest"
            }`}
          >
            Signals
          </button>
          <button
            onClick={() => setActiveView("journal")}
            className={`px-4 py-1.5 rounded text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              activeView === "journal"
                ? "bg-surface-container-highest text-primary"
                : "text-on-surface-variant hover:bg-surface-container-highest"
            }`}
          >
            Journal
          </button>
        </div>
      </div>

      {/* Content */}
      {activeView === "signals" ? <SignalFeed /> : <JournalView />}
    </div>
  );
}
```

- [ ] **Step 2: Update SignalFeed.tsx**

```tsx
import { useEffect, useState } from "react";
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
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  const recent = signals.filter((s) => new Date(s.created_at).getTime() > cutoff);

  const filtered =
    statusFilter === "ALL"
      ? recent
      : statusFilter === "ACTIVE"
        ? recent.filter((s) => !s.outcome || s.outcome === "PENDING")
        : recent.filter((s) => s.user_status === statusFilter);

  return (
    <div className="p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-1 bg-surface-container-lowest p-1 rounded-lg">
          {FILTERS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setStatusFilter(value)}
              className={`px-3 py-1.5 text-xs font-semibold rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                statusFilter === value
                  ? "bg-surface-container-highest text-primary"
                  : "text-on-surface-variant hover:bg-surface-container-highest"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <ConnectionStatus />
      </div>

      {filtered.length === 0 ? (
        <p className="text-on-surface-variant text-center text-sm mt-8">
          {statusFilter === "ALL" ? "No signals in the last 24 hours" : `No ${statusFilter.toLowerCase()} signals`}
        </p>
      ) : (
        <div className="space-y-2">
          {filtered.map((signal, i) => (
            <div key={signal.id} className={`motion-safe:animate-card-enter motion-safe:stagger-${Math.min(i + 1, 10)}`}>
              <SignalCard
                signal={signal}
                onSelect={selectSignal}
                onExecute={setTradingSignal}
              />
            </div>
          ))}
        </div>
      )}

      <SignalDetail signal={selectedSignal} onClose={clearSelection} />
      <OrderDialog signal={tradingSignal} onClose={() => setTradingSignal(null)} />
    </div>
  );
}
```

- [ ] **Step 3: Update ConnectionStatus.tsx**

```tsx
import { useSignalStore } from "../store";

export function ConnectionStatus() {
  const connected = useSignalStore((s) => s.connected);

  return (
    <div className="flex items-center gap-2 px-2 py-1 bg-surface-container rounded-lg" role="status" aria-live="polite">
      <div className={`w-2 h-2 rounded-full ${connected ? "bg-long shadow-[0_0_8px_rgba(86,239,159,0.5)]" : "bg-short motion-safe:animate-pulse"}`} />
      <span className="text-[10px] font-medium text-on-surface-variant uppercase tracking-wider tabular">
        {connected ? "Connected (Live OKX Feed)" : "Reconnecting..."}
      </span>
    </div>
  );
}
```

- [ ] **Step 4: Build and verify**

Run: `cd web && pnpm build`
Expected: Clean build.

---

## Task 4: SignalCard + PatternBadges

**Files:**
- Modify: `web/src/features/signals/components/SignalCard.tsx`
- Modify: `web/src/features/signals/components/PatternBadges.tsx`
- Reference: `web/.stitch-screens/signals.html`

**Changes summary:**
- SignalCard: outer element is `<div role="button">` (not `<button>`) to avoid nested interactive elements with Execute button. `bg-surface-container border-outline-variant/15`, pair name `font-headline font-bold`, direction badge pill with rounded, score bar `bg-primary`, 2x2 price grid with labels, Execute button `bg-primary-container text-on-primary-fixed`
- PatternBadges: use `bg-surface-container-highest` bg, Lucide check icon for detail row. `compact` prop removed.

- [ ] **Step 1: Update SignalCard.tsx**

```tsx
import { Zap, Newspaper } from "lucide-react";
import type { Signal } from "../types";
import { formatScore, formatPrice, formatRelativeTime } from "../../../shared/lib/format";
import { PatternBadges } from "./PatternBadges";

interface SignalCardProps {
  signal: Signal;
  onSelect: (signal: Signal) => void;
  onExecute?: (signal: Signal) => void;
}

export function SignalCard({ signal, onSelect, onExecute }: SignalCardProps) {
  const isLong = signal.direction === "LONG";
  const isPending = !signal.outcome || signal.outcome === "PENDING";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(signal)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(signal); } }}
      className={`w-full bg-surface-container border border-outline-variant/15 rounded-lg overflow-hidden text-left transition-all hover:bg-surface-container-high cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary${isPending ? " motion-safe:animate-pulse-glow" : ""}`}
    >
      {/* Header: pair, direction badge, score */}
      <div className="p-4 flex justify-between items-start border-b border-outline-variant/10">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-headline text-lg font-bold tracking-tight">{signal.pair.replace("-USDT-SWAP", "")}</span>
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold border ${
              isLong
                ? "bg-long/20 text-long border-long/30"
                : "bg-short/20 text-short border-short/30"
            }`}>
              {signal.direction} {signal.timeframe}
            </span>
          </div>
          <span className="text-on-surface-variant text-[10px] uppercase tracking-widest mt-1 block">
            {formatRelativeTime(signal.created_at)}
          </span>
        </div>
        <div className="text-right">
          <div className="text-xl font-headline font-bold text-primary tabular">
            {formatScore(signal.final_score)}<span className="text-xs text-on-surface-variant font-medium">/100</span>
          </div>
          <div className="w-16 h-1 bg-surface-container-lowest mt-1 rounded-full overflow-hidden ml-auto">
            <div
              className="h-full bg-primary rounded-full shadow-[0_0_8px_rgba(105,218,255,0.4)]"
              style={{ width: `${Math.min(Math.max(signal.final_score, 0), 100)}%` }}
            />
          </div>
          {!isPending && <OutcomeBadge outcome={signal.outcome} />}
        </div>
      </div>

      {/* Pattern badges */}
      {signal.detected_patterns && signal.detected_patterns.length > 0 && (
        <div className="px-4 py-3 flex items-center gap-2 overflow-x-auto [mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)]">
          <PatternBadges patterns={signal.detected_patterns} />
          {signal.correlated_news_ids && signal.correlated_news_ids.length > 0 && (
            <Newspaper size={16} className="text-primary ml-auto flex-shrink-0" />
          )}
        </div>
      )}

      {/* Price grid */}
      <div className="px-4 py-3 grid grid-cols-2 gap-y-3 gap-x-6 bg-surface-container-low/50">
        <div>
          <span className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-1 block">Entry Price</span>
          <span className="font-headline font-bold text-sm tabular">{formatPrice(signal.levels.entry)}</span>
        </div>
        <div>
          <span className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-1 block">Stop Loss</span>
          <span className="font-headline font-bold text-sm text-short tabular">{formatPrice(signal.levels.stop_loss)}</span>
        </div>
        <div>
          <span className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-1 block">Take Profit 1</span>
          <span className="font-headline font-bold text-sm text-long tabular">{formatPrice(signal.levels.take_profit_1)}</span>
        </div>
        <div>
          <span className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-1 block">Take Profit 2</span>
          <span className="font-headline font-bold text-sm text-long tabular">{formatPrice(signal.levels.take_profit_2)}</span>
        </div>
      </div>

      {/* Footer: risk metrics + execute */}
      <div className="p-4 border-t border-outline-variant/10 flex items-center justify-between">
        <div className="flex gap-4">
          {signal.risk_metrics ? (
            <>
              <div className="flex flex-col">
                <span className="text-[10px] uppercase text-on-surface-variant">Risk</span>
                <span className="text-[11px] font-bold tabular">{signal.risk_metrics.risk_pct}%</span>
              </div>
              {signal.risk_metrics.tp1_rr != null && (
                <div className="flex flex-col">
                  <span className="text-[10px] uppercase text-on-surface-variant">R:R</span>
                  <span className="text-[11px] font-bold tabular">
                    {signal.risk_metrics.tp1_rr}{signal.risk_metrics.tp2_rr != null ? ` / ${signal.risk_metrics.tp2_rr}` : ""}
                  </span>
                </div>
              )}
            </>
          ) : (
            <RRFallback levels={signal.levels} />
          )}
          <div className="flex flex-col">
            <span className="text-[10px] uppercase text-on-surface-variant">Status</span>
            <span className={`text-[11px] font-bold uppercase flex items-center gap-1 ${isPending ? "text-long" : "text-on-surface-variant"}`}>
              {isPending && <span className="w-1 h-1 rounded-full bg-long motion-safe:animate-pulse" />}
              {isPending ? "Active" : signal.user_status ?? signal.outcome}
            </span>
          </div>
        </div>
        {onExecute && isPending && (
          <button
            onClick={(e) => { e.stopPropagation(); onExecute(signal); }}
            className="bg-primary-container text-on-primary-fixed px-5 py-2 rounded-lg font-bold text-xs hover:opacity-90 active:scale-95 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            Execute
          </button>
        )}
      </div>
    </div>
  );
}

function RRFallback({ levels }: { levels: Signal["levels"] }) {
  const slDist = Math.abs(levels.entry - levels.stop_loss);
  if (slDist === 0) return null;
  const tp1rr = (Math.abs(levels.take_profit_1 - levels.entry) / slDist).toFixed(1);
  const tp2rr = (Math.abs(levels.take_profit_2 - levels.entry) / slDist).toFixed(1);
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase text-on-surface-variant">R:R</span>
      <span className="text-[11px] font-bold tabular">1:{tp1rr} / 1:{tp2rr}</span>
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    TP1_HIT: "bg-long/20 text-long",
    TP2_HIT: "bg-long/20 text-long",
    SL_HIT: "bg-short/20 text-short",
    EXPIRED: "bg-surface-container-highest text-outline",
  };
  const labels: Record<string, string> = {
    TP1_HIT: "TP1 Hit",
    TP2_HIT: "TP2 Hit",
    SL_HIT: "SL Hit",
    EXPIRED: "Expired",
  };

  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium mt-1 inline-block ${styles[outcome] ?? ""}`}>
      {labels[outcome] ?? outcome}
    </span>
  );
}
```

- [ ] **Step 2: Update PatternBadges.tsx**

```tsx
import type { DetectedPattern } from "../types";

interface PatternBadgesProps {
  patterns: DetectedPattern[];
}

export function PatternBadges({ patterns }: PatternBadgesProps) {
  if (!patterns.length) return null;

  return (
    <div className="flex flex-wrap gap-1.5">
      {patterns.map((p) => (
        <span
          key={p.name}
          className={`flex items-center gap-1 whitespace-nowrap bg-surface-container-highest px-2 py-1 rounded text-[10px] font-medium ${
            p.bias === "bullish"
              ? "text-long"
              : p.bias === "bearish"
                ? "text-short"
                : "text-on-surface"
          }`}
        >
          {p.name}
        </span>
      ))}
    </div>
  );
}

interface PatternDetailRowProps {
  patterns: DetectedPattern[];
}

export function PatternDetailRow({ patterns }: PatternDetailRowProps) {
  if (!patterns.length) return null;

  return (
    <div className="p-4 border-b border-outline-variant/10">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-3">Detected Patterns</h3>
      <div className="space-y-1.5">
        {patterns.map((p) => (
          <div key={p.name} className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span
                className={`text-[10px] px-2 py-0.5 rounded ${
                  p.bias === "bullish"
                    ? "bg-long/10 text-long"
                    : p.bias === "bearish"
                      ? "bg-short/10 text-short"
                      : "bg-surface-container-highest text-on-surface-variant"
                }`}
              >
                {p.bias}
              </span>
              <span className="text-on-surface">{p.name}</span>
            </div>
            <span className="text-xs text-on-surface-variant font-mono tabular">+{p.strength}pts</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Build and verify**

Run: `cd web && pnpm build`
Expected: Clean build.

---

## Task 5: SignalDetail

**Files:**
- Modify: `web/src/features/signals/components/SignalDetail.tsx`
- Reference: `web/.stitch-screens/signal-deepdive.html`

**Changes summary:**
- Hero score section with circular SVG gauge
- Execution matrix: 2x2 price grid with colored left borders
- Intelligence components: score breakdown as progress bars
- Journal section: M3 tokens, status buttons updated
- Engine params: M3 tokens

- [ ] **Step 1: Update SignalDetail.tsx**

```tsx
import { useEffect, useRef, useState, useCallback } from "react";
import type { Signal, UserStatus } from "../types";
import { formatPrice, formatScore } from "../../../shared/lib/format";
import { api } from "../../../shared/lib/api";
import { useSignalStore } from "../store";
import { PatternDetailRow } from "./PatternBadges";
import ParameterRow from "../../engine/components/ParameterRow";

interface SignalDetailProps {
  signal: Signal | null;
  onClose: () => void;
}

export function SignalDetail({ signal, onClose }: SignalDetailProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;

    if (signal) {
      dialog.showModal();
    } else {
      dialog.close();
    }
  }, [signal]);

  if (!signal) return null;

  const isLong = signal.direction === "LONG";
  const scoreNum = Math.abs(signal.final_score);
  const sentimentLabel = isLong ? "Long Sentiment" : "Short Sentiment";

  return (
    <dialog ref={ref} onClose={onClose} onClick={(e) => {
      if (e.target === ref.current) onClose();
    }} className="bg-surface-container text-on-surface rounded-xl w-[calc(100%-2rem)] max-w-lg max-h-[90dvh] overflow-y-auto p-0 m-auto backdrop:bg-black/60">
      {/* Hero Score Section */}
      <div className="p-5 border-b border-outline-variant/10 flex justify-between items-center relative overflow-hidden">
        <div className="relative z-10">
          <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-1">Overall Signal Score</p>
          <div className="flex items-baseline gap-2">
            <span className="font-headline font-bold text-5xl text-primary tabular">{formatScore(signal.final_score)}</span>
            <span className="text-on-surface-variant font-headline font-medium text-lg">/100</span>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${isLong ? "bg-long" : "bg-short"}`} />
            <span className={`text-xs font-medium uppercase tracking-wider ${isLong ? "text-long" : "text-short"}`}>
              {sentimentLabel}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-headline font-bold text-on-surface">{signal.pair}</span>
            <span className="text-on-surface-variant text-sm">{signal.timeframe}</span>
          </div>
        </div>
        <div className="relative z-10 h-24 w-24">
          <svg className="h-full w-full" viewBox="0 0 36 36">
            <path className="stroke-surface-container-highest" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" strokeWidth="3" />
            <path className="stroke-primary" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" strokeDasharray={`${scoreNum}, 100`} strokeLinecap="butt" strokeWidth="3" />
          </svg>
        </div>
        <div className="absolute -right-10 -top-10 h-40 w-40 bg-primary/5 blur-3xl rounded-full" />
      </div>

      {/* Score Breakdown */}
      <div className="p-5 border-b border-outline-variant/10 space-y-4">
        <h2 className="text-[10px] uppercase tracking-widest text-on-surface-variant">Intelligence Components</h2>
        <ScoreBar label="Technical Analysis" value={Math.abs(signal.traditional_score)} />
        {signal.llm_contribution != null && (
          <ScoreBar label="LLM Consensus" value={Math.min(Math.abs(signal.llm_contribution) * 2, 100)} />
        )}
        {signal.llm_factors && signal.llm_factors.length > 0 && (
          <div className="mt-2 space-y-1">
            {signal.llm_factors.map((f, i) => (
              <div key={i} className="flex items-center gap-2 text-xs" title={f.reason}>
                <span className={f.direction === "bullish" ? "text-long" : "text-short"}>
                  {f.direction === "bullish" ? "+" : "-"}
                </span>
                <span className="text-on-surface-variant">{f.type.replace(/_/g, " ")}</span>
                <span className="font-mono">{"*".repeat(f.strength)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {signal.detected_patterns && signal.detected_patterns.length > 0 && (
        <PatternDetailRow patterns={signal.detected_patterns} />
      )}

      {signal.explanation && (
        <div className="p-5 border-b border-outline-variant/10">
          <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-3">AI Analysis</h3>
          <p className="text-sm text-on-surface leading-relaxed">{signal.explanation}</p>
        </div>
      )}

      {/* Execution Matrix */}
      <div className="p-5 border-b border-outline-variant/10">
        <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-4">Execution Matrix</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="p-3 rounded bg-surface-container-lowest border-l-2 border-primary">
            <p className="text-[10px] font-medium text-primary uppercase mb-1">Entry Range</p>
            <p className="font-headline font-bold text-lg tabular">{formatPrice(signal.levels.entry)}</p>
          </div>
          <div className="p-3 rounded bg-surface-container-lowest border-l-2 border-short">
            <p className="text-[10px] font-medium text-short uppercase mb-1">Stop Loss</p>
            <p className="font-headline font-bold text-lg tabular">{formatPrice(signal.levels.stop_loss)}</p>
          </div>
          <div className="p-3 rounded bg-surface-container-lowest border-l-2 border-long">
            <p className="text-[10px] font-medium text-long uppercase mb-1">Take Profit 1</p>
            <p className="font-headline font-bold text-lg tabular">{formatPrice(signal.levels.take_profit_1)}</p>
          </div>
          <div className="p-3 rounded bg-surface-container-lowest border-l-2 border-long/60">
            <p className="text-[10px] font-medium text-long uppercase mb-1">Take Profit 2</p>
            <p className="font-headline font-bold text-lg tabular">{formatPrice(signal.levels.take_profit_2)}</p>
          </div>
        </div>
      </div>

      {signal.outcome && signal.outcome !== "PENDING" && (
        <div className="p-5 border-b border-outline-variant/10">
          <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">Outcome</h3>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>Result: <span className={`font-mono font-bold ${signal.outcome.includes("TP") ? "text-long" : "text-short"}`}>{signal.outcome.replace("_", " ")}</span></div>
            {signal.outcome_pnl_pct != null && (
              <div>P&L: <span className={`font-mono tabular ${signal.outcome_pnl_pct >= 0 ? "text-long" : "text-short"}`}>{signal.outcome_pnl_pct >= 0 ? "+" : ""}{signal.outcome_pnl_pct.toFixed(2)}%</span></div>
            )}
            {signal.outcome_duration_minutes != null && (
              <div>Duration: <span className="font-mono tabular">{signal.outcome_duration_minutes < 60 ? `${signal.outcome_duration_minutes}m` : `${Math.floor(signal.outcome_duration_minutes / 60)}h ${signal.outcome_duration_minutes % 60}m`}</span></div>
            )}
          </div>
        </div>
      )}

      <JournalSection signal={signal} />

      {signal.engine_snapshot ? (
        <SnapshotSection snapshot={signal.engine_snapshot} />
      ) : (
        <p className="text-xs text-on-surface-variant px-4 py-2">Parameter snapshot not available</p>
      )}
    </dialog>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs font-medium uppercase tracking-tighter">
        <span className="text-on-surface">{label}</span>
        <span className="text-primary tabular">{Math.round(value)}%</span>
      </div>
      <div className="h-1 w-full bg-surface-container-highest rounded-full overflow-hidden">
        <div className="h-full bg-primary rounded-full" style={{ width: `${Math.min(value, 100)}%` }} />
      </div>
    </div>
  );
}

function SnapshotSection({ snapshot }: { snapshot: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-t border-outline-variant/10">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full flex items-center justify-between px-4 py-2 text-xs text-on-surface-variant hover:text-on-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
      >
        Engine Parameters
        <span>{open ? "\u2212" : "+"}</span>
      </button>
      {open && (
        <div>
          {Object.entries(snapshot).map(([key, value]) => (
            <ParameterRow
              key={key}
              name={key}
              value={value as unknown}
              source="configurable"
            />
          ))}
        </div>
      )}
    </div>
  );
}

function JournalSection({ signal }: { signal: Signal }) {
  const updateSignal = useSignalStore((s) => s.updateSignal);
  const [note, setNote] = useState(signal.user_note ?? "");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    setNote(signal.user_note ?? "");
  }, [signal.id, signal.user_note]);

  const saveNote = useCallback(
    (value: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(async () => {
        setSaveState("saving");
        try {
          await api.patchSignalJournal(signal.id, { note: value });
          updateSignal(signal.id, { user_note: value || null });
          setSaveState("saved");
          if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
          savedTimerRef.current = setTimeout(() => setSaveState("idle"), 2000);
        } catch {
          setSaveState("idle");
        }
      }, 800);
    },
    [signal.id, updateSignal],
  );

  const handleStatusChange = async (status: UserStatus) => {
    setSaveState("saving");
    try {
      await api.patchSignalJournal(signal.id, { status });
      updateSignal(signal.id, { user_status: status });
      setSaveState("saved");
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
      savedTimerRef.current = setTimeout(() => setSaveState("idle"), 2000);
    } catch {
      setSaveState("idle");
    }
  };

  const statuses: { value: UserStatus; label: string }[] = [
    { value: "OBSERVED", label: "Observed" },
    { value: "TRADED", label: "Traded" },
    { value: "SKIPPED", label: "Skipped" },
  ];

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant">Your Notes</h3>
        {saveState === "saving" && <span className="text-xs text-on-surface-variant">Saving...</span>}
        {saveState === "saved" && <span className="text-xs text-long">Saved</span>}
      </div>

      <div className="flex gap-1.5 mb-3">
        {statuses.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => handleStatusChange(value)}
            className={`flex-1 py-1.5 text-xs font-medium rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              signal.user_status === value
                ? value === "TRADED"
                  ? "bg-long/20 text-long border border-long/40"
                  : "bg-surface-container-highest text-on-surface border border-outline-variant/15"
                : "text-on-surface-variant border border-outline-variant/10"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <textarea
        value={note}
        onChange={(e) => {
          const v = e.target.value;
          setNote(v);
          saveNote(v);
        }}
        maxLength={500}
        rows={3}
        placeholder="Add a note about this signal..."
        className="w-full bg-surface-container-lowest border border-outline-variant/10 rounded-lg p-2.5 text-sm text-on-surface placeholder-outline resize-none focus:outline-none focus:border-primary/50"
      />
      <div className="text-xs text-outline text-right mt-1">{note.length}/500</div>
    </div>
  );
}
```

- [ ] **Step 2: Build and verify**

Run: `cd web && pnpm build`
Expected: Clean build.

---

## Task 6: DeepDiveView (Analytics)

**Files:**
- Modify: `web/src/features/signals/components/DeepDiveView.tsx`

**Changes summary:**
- Period selector pills: M3 active/inactive pattern
- MetricsGrid: `bg-surface-container`, `font-headline` values, `tabular`
- BestWorstTrades: same token migration
- SVG charts: colors already use `theme.colors.*` which updated in Plan 1 — no changes needed in chart code

- [ ] **Step 1: Update DeepDiveView.tsx**

```tsx
import { useState } from "react";
import { useSignalStats } from "../../home/hooks/useSignalStats";
import { theme } from "../../../shared/theme";
import type { SignalStats, PerformanceMetrics } from "../types";

type Period = "7" | "30" | "365";

const PERIODS: { value: Period; label: string }[] = [
  { value: "7", label: "7D" },
  { value: "30", label: "30D" },
  { value: "365", label: "All" },
];

export function DeepDiveView() {
  const [period, setPeriod] = useState<Period>("30");
  const { stats, loading } = useSignalStats(Number(period));

  if (loading) {
    return (
      <div className="p-3 space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 bg-surface-container rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (!stats || stats.total_resolved < 5) {
    return (
      <div className="p-3">
        <p className="text-on-surface-variant text-center text-sm mt-12">
          Need more resolved trades to show metrics
        </p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3 overflow-y-auto">
      {/* Period selector */}
      <div className="flex gap-1 bg-surface-container-lowest p-1 rounded-lg w-fit">
        {PERIODS.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => setPeriod(value)}
            className={`px-3 py-1.5 text-xs font-semibold rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              period === value
                ? "bg-surface-container-highest text-primary"
                : "text-on-surface-variant hover:bg-surface-container-highest"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <MetricsGrid perf={stats.performance} totalResolved={stats.total_resolved} />
      <BestWorstTrades perf={stats.performance} />
      <DrawdownChart data={stats.drawdown_series} />
      <PnlDistribution data={stats.pnl_distribution} />
    </div>
  );
}

function MetricsGrid({ perf, totalResolved }: { perf: PerformanceMetrics; totalResolved: number }) {
  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-3">Performance Metrics</h3>
      <div className="grid grid-cols-3 gap-3 text-center">
        <MetricCell
          label="Sharpe"
          value={perf.sharpe_ratio != null ? String(perf.sharpe_ratio) : "—"}
          tooltip={perf.sharpe_ratio == null ? "Not enough data (need 7+ days)" : undefined}
          color={perf.sharpe_ratio != null && perf.sharpe_ratio > 0 ? "text-long" : perf.sharpe_ratio != null ? "text-short" : "text-outline"}
        />
        <MetricCell
          label="Profit F"
          value={perf.profit_factor != null ? String(perf.profit_factor) : "—"}
          tooltip={perf.profit_factor == null ? "No losing trades" : undefined}
          color={perf.profit_factor != null && perf.profit_factor > 1 ? "text-long" : perf.profit_factor != null ? "text-short" : "text-outline"}
        />
        <MetricCell
          label="Max DD"
          value={perf.max_drawdown_pct > 0 ? `-${perf.max_drawdown_pct}%` : "0%"}
          color={perf.max_drawdown_pct > 3 ? "text-short" : "text-on-surface"}
        />
        <MetricCell
          label="Expectancy"
          value={perf.expectancy != null ? `${perf.expectancy >= 0 ? "+" : ""}${perf.expectancy}%` : "—"}
          color={perf.expectancy != null && perf.expectancy >= 0 ? "text-long" : perf.expectancy != null ? "text-short" : "text-outline"}
        />
        <MetricCell
          label="Avg Hold"
          value={perf.avg_hold_time_minutes != null ? formatHoldTime(perf.avg_hold_time_minutes) : "—"}
          color="text-on-surface"
        />
        <MetricCell
          label="Trades"
          value={String(totalResolved)}
          color="text-on-surface"
        />
      </div>
    </div>
  );
}

function MetricCell({ label, value, color, tooltip }: {
  label: string;
  value: string;
  color: string;
  tooltip?: string;
}) {
  return (
    <div title={tooltip}>
      <div className={`text-base font-headline font-bold tabular ${color}`}>{value}</div>
      <div className="text-[10px] text-on-surface-variant">{label}</div>
    </div>
  );
}

function BestWorstTrades({ perf }: { perf: PerformanceMetrics }) {
  if (!perf.best_trade && !perf.worst_trade) return null;

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-3">Notable Trades</h3>
      <div className="space-y-1.5">
        {perf.best_trade && (
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-long bg-long/10 px-1.5 py-0.5 rounded">BEST</span>
              <span className="text-on-surface-variant">
                {perf.best_trade.pair.replace("-USDT-SWAP", "")} {perf.best_trade.timeframe} {perf.best_trade.direction}
              </span>
            </div>
            <span className="font-mono text-long tabular">+{perf.best_trade.pnl_pct}%</span>
          </div>
        )}
        {perf.worst_trade && (
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-short bg-short/10 px-1.5 py-0.5 rounded">WORST</span>
              <span className="text-on-surface-variant">
                {perf.worst_trade.pair.replace("-USDT-SWAP", "")} {perf.worst_trade.timeframe} {perf.worst_trade.direction}
              </span>
            </div>
            <span className="font-mono text-short tabular">{perf.worst_trade.pnl_pct}%</span>
          </div>
        )}
      </div>
    </div>
  );
}

function DrawdownChart({ data }: { data: SignalStats["drawdown_series"] }) {
  if (data.length < 2) return null;

  const width = 320;
  const height = 100;
  const pad = { top: 5, right: 10, bottom: 15, left: 10 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;

  const values = data.map((d) => d.drawdown);
  const minVal = Math.min(...values, 0);
  const range = Math.abs(minVal) || 1;

  const points = data
    .map((d, i) => {
      const x = pad.left + (i / (data.length - 1)) * w;
      const y = pad.top + (Math.abs(d.drawdown) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  const firstX = pad.left;
  const lastX = pad.left + w;
  const fillPoints = `${firstX},${pad.top} ${points} ${lastX},${pad.top}`;

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">Drawdown</h3>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none">
        <polygon fill={theme.colors.short + "15"} points={fillPoints} />
        <polyline fill="none" stroke={theme.colors.short} strokeWidth="1.5" strokeLinejoin="round" points={points} />
        <text x={width - pad.right} y={height - 2} textAnchor="end" fontSize="8" fill={theme.colors.outline}>
          {minVal.toFixed(1)}%
        </text>
      </svg>
    </div>
  );
}

function PnlDistribution({ data }: { data: SignalStats["pnl_distribution"] }) {
  if (data.length === 0) return null;

  const maxCount = Math.max(...data.map((d) => d.count));
  const width = 320;
  const height = 80;
  const pad = { top: 5, right: 10, bottom: 15, left: 10 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;
  const barWidth = Math.max(w / data.length - 2, 4);

  return (
    <div className="bg-surface-container rounded-lg p-4">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-2">P&L Distribution</h3>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none">
        {data.map((d, i) => {
          const barH = (d.count / maxCount) * h;
          const x = pad.left + (i / data.length) * w;
          const y = pad.top + h - barH;
          const fill = d.bucket >= 0 ? theme.colors.long : theme.colors.short;
          return (
            <rect
              key={i}
              x={x}
              y={y}
              width={barWidth}
              height={barH}
              fill={fill}
              opacity={0.7}
              rx={1}
            />
          );
        })}
        {data.some(d => d.bucket < 0) && data.some(d => d.bucket >= 0) && (
          <line
            x1={pad.left + (data.findIndex(d => d.bucket >= 0) / data.length) * w}
            y1={pad.top}
            x2={pad.left + (data.findIndex(d => d.bucket >= 0) / data.length) * w}
            y2={pad.top + h}
            stroke={theme.colors["outline-variant"]}
            strokeWidth="0.5"
            strokeDasharray="3"
          />
        )}
      </svg>
    </div>
  );
}

function formatHoldTime(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}
```

- [ ] **Step 2: Build and verify**

Run: `cd web && pnpm build`
Expected: Clean build.

---

## Task 7: News Tab (NewsFeed + NewsCard)

**Files:**
- Modify: `web/src/features/news/components/NewsFeed.tsx`
- Modify: `web/src/features/news/components/NewsCard.tsx`
- Reference: `web/.stitch-screens/news.html`

**Changes summary:**
- NewsFeed: category pills in `bg-surface-container-low` wrapper, impact toggles with colored dots
- NewsCard: left border by impact color, `font-headline` on headlines, sentiment with direction icon, affected pair chips, expandable AI summary with bullet points

- [ ] **Step 1: Update NewsFeed.tsx**

```tsx
import { useState } from "react";
import { useNews } from "../hooks/useNews";
import { NewsCard } from "./NewsCard";
import type { NewsCategory, NewsImpact } from "../types";

type CategoryFilter = "all" | NewsCategory;
type ImpactFilter = "all" | NewsImpact;

export function NewsFeed() {
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [impact, setImpact] = useState<ImpactFilter>("all");

  const { news, loading } = useNews({
    category: category === "all" ? undefined : category,
    impact: impact === "all" ? undefined : impact,
    limit: 100,
  });

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Category filter pills */}
      <div className="flex flex-wrap gap-3">
        <div className="bg-surface-container-low p-1 rounded-lg flex gap-1">
          {(["all", "crypto", "macro"] as CategoryFilter[]).map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`px-3 py-1.5 text-xs uppercase tracking-widest rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                category === c
                  ? "bg-surface-container-highest text-primary shadow-[0_0_8px_rgba(105,218,255,0.15)]"
                  : "text-on-surface-variant hover:text-on-surface"
              }`}
            >
              {c === "all" ? "All" : c.charAt(0).toUpperCase() + c.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Impact level toggles — gradient fade hints at horizontal scroll */}
      <div className="flex items-center gap-3 overflow-x-auto pb-1 [mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)]">
        <span className="text-[10px] uppercase tracking-widest text-on-surface-variant shrink-0">Impact:</span>
        {(["all", "high", "medium", "low"] as ImpactFilter[]).map((i) => {
          const dotColor = i === "high" ? "bg-short" : i === "medium" ? "bg-primary" : i === "low" ? "bg-on-surface-variant" : "";
          return (
            <button
              key={i}
              onClick={() => setImpact(i)}
              className={`flex items-center gap-2 px-3 py-1 rounded-full bg-surface-container border border-outline-variant/20 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                impact === i ? "border-primary/40" : "opacity-60"
              }`}
            >
              {dotColor && <div className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />}
              <span className="text-xs text-on-surface">
                {i === "all" ? "All" : i.charAt(0).toUpperCase() + i.slice(1)}
              </span>
            </button>
          );
        })}
      </div>

      {/* News list */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 bg-surface-container rounded-lg animate-pulse" />
          ))}
        </div>
      ) : news.length === 0 ? (
        <div className="bg-surface-container rounded-lg p-8 text-center">
          <p className="text-on-surface-variant text-sm">No news events yet</p>
          <p className="text-outline text-xs mt-1">Headlines will appear as they are collected</p>
        </div>
      ) : (
        <div className="space-y-3">
          {news.map((event) => (
            <NewsCard key={event.id} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Update NewsCard.tsx**

```tsx
import { useState } from "react";
import { TrendingUp, TrendingDown, Minus, ChevronDown, Zap } from "lucide-react";
import type { NewsEvent } from "../types";
import { formatRelativeTime } from "../../../shared/lib/format";

interface NewsCardProps {
  event: NewsEvent;
}

const IMPACT_BORDER: Record<string, string> = {
  high: "border-l-error",
  medium: "border-l-primary/40",
  low: "border-l-on-surface-variant/20",
};

const IMPACT_BADGE: Record<string, string> = {
  high: "bg-error-container text-on-error",
  medium: "bg-surface-container-highest text-on-surface-variant",
  low: "bg-surface-container-highest text-on-surface-variant",
};

const SENTIMENT_ICON: Record<string, typeof TrendingUp> = {
  bullish: TrendingUp,
  bearish: TrendingDown,
  neutral: Minus,
};

const SENTIMENT_COLOR: Record<string, string> = {
  bullish: "text-long",
  bearish: "text-short",
  neutral: "text-on-surface-variant",
};

export function NewsCard({ event }: NewsCardProps) {
  const [expanded, setExpanded] = useState(false);
  const SentimentIcon = event.sentiment ? SENTIMENT_ICON[event.sentiment] : null;

  return (
    <div
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      onClick={() => setExpanded(!expanded)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpanded(!expanded); } }}
      className={`w-full bg-surface-container-low rounded-lg p-4 border-l-4 text-left transition-all hover:bg-surface-container cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${IMPACT_BORDER[event.impact ?? "low"] ?? "border-l-outline-variant/20"}`}
    >
      {/* Header: impact badge + time + sentiment */}
      <div className="flex justify-between items-start mb-2">
        <div className="flex items-center gap-3">
          {event.impact && (
            <span className={`text-[10px] tracking-widest px-2 py-0.5 uppercase rounded font-medium ${IMPACT_BADGE[event.impact] ?? ""}`}>
              {event.impact} Impact
            </span>
          )}
          <span className="text-xs text-on-surface-variant tabular">
            {event.published_at ? formatRelativeTime(event.published_at) : ""} {event.source ? `\u00B7 ${event.source}` : ""}
          </span>
        </div>
        {SentimentIcon && (
          <div className={`flex items-center gap-1 ${SENTIMENT_COLOR[event.sentiment!] ?? ""}`}>
            <SentimentIcon size={14} />
            <span className="text-[10px] uppercase tracking-widest">{event.sentiment}</span>
          </div>
        )}
      </div>

      {/* Headline */}
      <h3 className="font-headline text-base font-bold leading-tight mb-3">{event.headline}</h3>

      {/* Affected pairs */}
      {event.affected_pairs.length > 0 && event.affected_pairs[0] !== "ALL" && (
        <div className="flex flex-wrap gap-2 mb-2">
          {event.affected_pairs.map((pair) => (
            <div key={pair} className="bg-surface-container-highest px-2 py-1 rounded flex items-center gap-2">
              <span className="text-[10px] font-mono font-bold text-on-surface">{pair.replace("-USDT-SWAP", "")}</span>
            </div>
          ))}
        </div>
      )}

      {/* Expandable AI summary */}
      {event.llm_summary && !expanded && (
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-primary/60">
          <ChevronDown size={14} />
          View AI Analysis
        </div>
      )}
      {expanded && event.llm_summary && (
        <div className="bg-surface-container-lowest rounded-lg p-4 border border-outline-variant/10 mt-2">
          <div className="flex items-center gap-2 mb-2">
            <Zap size={14} className="text-primary" />
            <span className="text-[10px] uppercase tracking-widest text-primary">Krypton AI Summary</span>
          </div>
          <p className="text-sm text-on-surface-variant leading-relaxed">{event.llm_summary}</p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Build and verify**

Run: `cd web && pnpm build`
Expected: Clean build.

---

## Task 8: More Hub (MorePage)

**Files:**
- Modify: `web/src/features/more/components/MorePage.tsx`
- Reference: `web/.stitch-screens/more.html`

**Changes summary:**
- Replace inline tab bar with navigation cluster hub layout
- 3 clusters: Execution Layer (Engine, Backtest), Intelligence Hub (ML, Alerts), Safety & Security (Risk, Settings)
- Each cluster: section label, card with icon tiles + chevron + description
- Connection status card at bottom
- SubPageShell wraps sub-pages when selected
- Terminal grid background via existing `.terminal-grid` CSS class

- [ ] **Step 1: Update MorePage.tsx**

```tsx
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

        {/* Connection Status Card */}
        <section className="mt-2 pb-8">
          <div className="bg-surface-container-lowest p-5 border-l-4 border-primary rounded-r-lg">
            <div className="flex justify-between items-start">
              <div>
                <h3 className="font-headline font-bold text-on-surface uppercase text-sm tracking-widest">Connection Secure</h3>
                <p className="text-xs text-on-surface-variant mt-1 font-mono">ENCRYPTED_NODE: WS-OKX-01</p>
              </div>
              <div className="bg-primary/20 px-2 py-0.5 rounded-full">
                <span className="text-[10px] font-bold text-primary uppercase">Online</span>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build and verify**

Run: `cd web && pnpm build`
Expected: Clean build. More tab shows navigation clusters instead of inline tab bar.

---

## Task 9: OrderDialog

**Files:**
- Modify: `web/src/features/trading/components/OrderDialog.tsx`

**Changes summary:**
- M3 token migration on all text/bg classes
- Header: `font-headline`, `border-outline-variant/10`
- Grid labels: `text-on-surface-variant`
- Inputs: `bg-surface-container-lowest`, `border-outline-variant/10`
- Buttons: Buy `bg-long text-on-tertiary-fixed`, Sell `bg-short text-white`

- [ ] **Step 1: Update OrderDialog.tsx**

The structure stays identical. Only CSS class tokens change. Replace the full file:

```tsx
import { useState, useRef, useEffect } from "react";
import { X } from "lucide-react";
import type { Signal } from "../../signals/types";
import { api, type RiskCheckResult } from "../../../shared/lib/api";
import { formatPrice } from "../../../shared/lib/format";

interface Props {
  signal: Signal | null;
  onClose: () => void;
}

export function OrderDialog({ signal, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [size, setSize] = useState("1");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ success: boolean; error?: string; warning?: string } | null>(null);
  const [riskCheck, setRiskCheck] = useState<RiskCheckResult | null>(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [overrideText, setOverrideText] = useState("");
  const [showOverride, setShowOverride] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (signal) {
      setResult(null);
      setRiskCheck(null);
      setRiskLoading(true);
      setOverrideText("");
      setShowOverride(false);

      if (signal.risk_metrics) {
        setSize(String(signal.risk_metrics.position_size_base));
      } else {
        setSize("1");
      }

      dialog.showModal();

      const sizeUsd = signal.risk_metrics?.position_size_usd ?? signal.levels.entry * 1;
      api.checkRisk({
        pair: signal.pair,
        direction: signal.direction,
        size_usd: sizeUsd,
      }).then(setRiskCheck).catch(() => {
        setRiskCheck(null);
      }).finally(() => setRiskLoading(false));
    } else {
      dialog.close();
    }
  }, [signal]);

  if (!signal) return null;

  const side = signal.direction === "LONG" ? "buy" : "sell";
  const isBlocked = riskCheck?.status === "BLOCKED";
  const isWarning = riskCheck?.status === "WARNING";
  const overrideConfirmed = overrideText === "OVERRIDE";

  async function handleSubmit() {
    if (!signal) return;
    setSubmitting(true);
    try {
      const orderReq: Parameters<typeof api.placeOrder>[0] = {
        pair: signal.pair,
        side,
        size,
        sl_price: String(signal.levels.stop_loss),
        tp_price: String(signal.levels.take_profit_1),
      };
      if (isBlocked && overrideConfirmed) {
        orderReq.override = true;
        orderReq.override_rules = riskCheck!.rules
          .filter(r => r.status === "BLOCKED")
          .map(r => r.rule);
      }
      const res = await api.placeOrder(orderReq);
      setResult(res);
    } catch (e) {
      setResult({ success: false, error: e instanceof Error ? e.message : "Order failed" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <dialog ref={ref} onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose(); }} className="bg-surface-container text-on-surface rounded-xl w-[calc(100%-2rem)] max-w-md max-h-[85dvh] overflow-y-auto p-0 m-auto backdrop:bg-black/60">
      <div className="p-4 border-b border-outline-variant/10">
        <div className="flex items-center justify-between">
          <span className="text-lg font-headline font-bold">Confirm Order</span>
          <button onClick={onClose} aria-label="Close" className="text-on-surface-variant hover:text-on-surface p-2 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
            <X size={20} />
          </button>
        </div>
      </div>

      <div className="p-4 space-y-3">
        {riskLoading && (
          <div className="p-3 rounded-lg bg-surface-container-highest text-on-surface-variant text-sm animate-pulse">
            Checking risk rules...
          </div>
        )}
        {!riskLoading && riskCheck && isBlocked && (
          <div className="p-3 rounded-lg bg-short/10 border border-short/30">
            <div className="text-sm font-medium text-short mb-1">Trade Blocked</div>
            {riskCheck.rules.filter(r => r.status === "BLOCKED").map(r => (
              <div key={r.rule} className="text-xs text-short/80">{r.reason}</div>
            ))}
            {!showOverride ? (
              <button
                onClick={() => setShowOverride(true)}
                className="mt-2 text-xs text-on-surface-variant underline"
              >
                Override
              </button>
            ) : (
              <div className="mt-2">
                <div className="text-xs text-on-surface-variant mb-1">Type OVERRIDE to confirm</div>
                <input
                  type="text"
                  value={overrideText}
                  onChange={(e) => setOverrideText(e.target.value)}
                  placeholder="OVERRIDE"
                  className="w-full p-2 bg-surface-container-lowest rounded border border-outline-variant/10 text-sm font-mono focus:border-short/50 focus:outline-none"
                />
              </div>
            )}
          </div>
        )}
        {!riskLoading && riskCheck && isWarning && (
          <div className="p-3 rounded-lg bg-primary/10 border border-primary/30">
            <div className="text-sm font-medium text-primary mb-1">Risk Advisory</div>
            {riskCheck.rules.filter(r => r.status === "WARNING").map(r => (
              <div key={r.rule} className="text-xs text-primary/80">{r.reason}</div>
            ))}
          </div>
        )}
        {!riskLoading && !riskCheck && !result && (
          <div className="p-2 rounded-lg bg-primary/10 text-primary text-xs">
            Risk check unavailable — proceed with caution
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="text-on-surface-variant">Pair</div>
          <div className="font-mono">{signal.pair}</div>
          <div className="text-on-surface-variant">Side</div>
          <div className={`font-mono ${side === "buy" ? "text-long" : "text-short"}`}>{side.toUpperCase()}</div>
          <div className="text-on-surface-variant">Entry</div>
          <div className="font-mono tabular">{formatPrice(signal.levels.entry)}</div>
          <div className="text-on-surface-variant">Stop Loss</div>
          <div className="font-mono text-short tabular">{formatPrice(signal.levels.stop_loss)}</div>
          <div className="text-on-surface-variant">Take Profit</div>
          <div className="font-mono text-long tabular">{formatPrice(signal.levels.take_profit_1)}</div>
          {signal.risk_metrics && (
            <>
              <div className="text-on-surface-variant">Risk</div>
              <div className="font-mono text-short tabular">${signal.risk_metrics.risk_amount_usd.toFixed(0)} ({signal.risk_metrics.risk_pct}%)</div>
              <div className="text-on-surface-variant">R:R</div>
              <div className="font-mono text-long tabular">
                {signal.risk_metrics.tp1_rr != null ? `1:${signal.risk_metrics.tp1_rr}` : "—"}
                {signal.risk_metrics.tp2_rr != null ? ` / 1:${signal.risk_metrics.tp2_rr}` : ""}
              </div>
            </>
          )}
        </div>

        <div>
          <label className="text-sm text-on-surface-variant block mb-1">
            Size {signal.risk_metrics ? `(recommended: ${signal.risk_metrics.position_size_base})` : "(contracts)"}
          </label>
          <input
            type="text"
            inputMode="decimal"
            value={size}
            onChange={(e) => setSize(e.target.value)}
            className="w-full p-3 bg-surface-container-lowest rounded-lg border border-outline-variant/10 font-mono focus:border-primary/50 focus:outline-none"
          />
        </div>

        {result && (
          <div className={`p-3 rounded-lg text-sm ${result.success ? "bg-long/10 text-long" : "bg-short/10 text-short"}`}>
            {result.success ? "Order placed successfully" : result.error}
          </div>
        )}
        {result?.warning && (
          <div className="p-3 rounded-lg text-sm bg-primary/10 text-primary">
            {result.warning}
          </div>
        )}
      </div>

      <div className="p-4 border-t border-outline-variant/10">
        {result?.success ? (
          <button onClick={onClose} className="w-full py-3 rounded-lg bg-surface-container-highest text-on-surface font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
            Close
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={submitting || (isBlocked && !overrideConfirmed)}
            className={`w-full py-3 rounded-lg font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              side === "buy" ? "bg-long text-on-tertiary-fixed" : "bg-short text-white"
            } disabled:opacity-50`}
          >
            {submitting ? "Placing order..." : `${side.toUpperCase()} ${signal.pair}`}
          </button>
        )}
      </div>
    </dialog>
  );
}
```

- [ ] **Step 2: Build and verify**

Run: `cd web && pnpm build`
Expected: Clean build.

---

## Task 10: Full Build + Visual Smoke Test

- [ ] **Step 1: Run full build**

Run: `cd web && pnpm build`
Expected: Zero errors, zero warnings.

- [ ] **Step 2: Run tests**

Run: `cd web && pnpm test`
Expected: All existing tests pass. These are visual-only changes — no logic changed.

- [ ] **Step 3: Visual verification checklist**

Open `pnpm dev` and verify each tab at 375px width. Compare against the corresponding Stitch screen in `web/.stitch-screens/`.

- [ ] **Home tab:** Account balance uses Space Grotesk, portfolio strip has M3 surface hierarchy, positions use direction icons + leverage badges, news cards have impact left borders.
- [ ] **Chart tab:** Timeframe pills use `surface-container-highest` active state with Space Grotesk bold, OHLC strip uses M3 tokens, indicator badge is cyan.
- [ ] **Signals tab:** Filter pills in `surface-container-lowest` wrapper, signal cards have 2x2 price grid + score gauge + execute button, connection status shows glow dot.
- [ ] **Signal detail:** Hero score with circular SVG gauge, execution matrix with colored left borders, intelligence component progress bars.
- [ ] **News tab:** Impact left borders (red=high, cyan=medium, muted=low), sentiment icons, affected pair chips, expandable AI summary.
- [ ] **More tab:** Navigation clusters with icons + chevrons, terminal grid background, connection status card at bottom.
- [ ] **Order dialog:** M3 tokens throughout, inputs use `surface-container-lowest`.
- [ ] **No regressions:** Chart renders correctly, WebSocket connection still works, signal cards animate in with stagger.
- [ ] **Accessibility:** Tab through all interactive elements — every button/card shows a visible focus ring. Test with `prefers-reduced-motion: reduce` — no animations should play. Verify no nested `<button>` elements in DOM (SignalCard, NewsCard must be `<div role="button">`).
- [ ] **Touch targets:** Indicator sheet close button, filter pills, and timeframe pills are all >= 44px tap area.
- [ ] **Dialogs:** IndicatorSheet, SignalDetail, and OrderDialog all render with dark backdrop, proper border-radius, and scroll correctly when content overflows.
- [ ] **PortfolioStrip:** Verify 4 metrics fit at 375px without text overflow. Grid should collapse to 2 columns if viewport is too narrow.

- [ ] **Step 4: Commit**

Single commit for all Plan 2 changes (per CLAUDE.md — no incremental commits per task):

```bash
git add -A web/src/features/ web/src/shared/
git commit -m "feat(ui): reskin core views to Kinetic Terminal M3 design system"
```
