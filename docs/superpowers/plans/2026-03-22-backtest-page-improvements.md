# Backtest Page Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the backtest page with M3 token migration, collapsible setup sections, per-pair breakdown + trade filtering in results, and config summary labels + config diff in compare tab.

**Architecture:** Four sequential phases of frontend-only changes. Phase 1 migrates legacy CSS classes to M3 tokens across 5 files. Phase 2 adds collapsible behavior to the `Section` component in `BacktestSetup`. Phase 3 adds `PairBreakdown` and enhances `TradeList` with filter/sort in `BacktestResults`. Phase 4 adds `configLabel()` and `ConfigDiff` to `BacktestCompare`.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v3, lightweight-charts, Vitest

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `web/src/features/backtest/components/ParameterOverridePanel.tsx` | M3 token migration |
| Modify | `web/src/features/backtest/components/OptimizeTab.tsx` | M3 token migration |
| Modify | `web/src/features/backtest/components/ApplyModal.tsx` | M3 token migration |
| Modify | `web/src/features/backtest/components/BacktestResults.tsx` | M3 token migration + PairBreakdown + TradeList filter/sort |
| Modify | `web/src/features/backtest/components/BacktestCompare.tsx` | M3 token migration + config labels + ConfigDiff |
| Modify | `web/src/features/backtest/components/BacktestSetup.tsx` | Collapsible Section component |

---

### Task 1: M3 Token Migration — ParameterOverridePanel

**Files:**
- Modify: `web/src/features/backtest/components/ParameterOverridePanel.tsx`

- [ ] **Step 1: Apply token replacements**

Replace all legacy classes in `ParameterOverridePanel.tsx` using this mapping:

Line 46 — outer container border:
```
- "border border-border/50 rounded-lg overflow-hidden"
+ "border border-outline-variant/30 rounded-lg overflow-hidden"
```

Line 49 — button background:
```
- "bg-surface/50"
+ "bg-surface-container/50"
```

Line 51 — label text:
```
- "text-xs font-medium text-muted"
+ "text-xs font-medium text-on-surface-variant"
```

Line 52 — toggle icon:
```
- "text-muted text-xs"
+ "text-on-surface-variant text-xs"
```

Line 61 — param label (non-edited):
```
- `text-xs ${edited ? "text-foreground" : "text-muted"}`
+ `text-xs ${edited ? "text-on-surface" : "text-on-surface-variant"}`
```

Line 68-69 — input styling:
```
- `w-20 text-right text-xs font-mono px-2 py-1 bg-surface border rounded ${
-   edited ? "border-accent text-accent" : "border-border text-muted"
- }`
+ `w-20 text-right text-xs font-mono px-2 py-1 bg-surface-container border rounded ${
+   edited ? "border-primary text-primary" : "border-outline-variant text-on-surface-variant"
+ }`
```

Line 77 — reset button:
```
- "text-xs text-muted hover:text-foreground"
+ "text-xs text-on-surface-variant hover:text-on-surface"
```

- [ ] **Step 2: Visual check**

Run: `cd web && pnpm dev`
Open the Backtest > Setup tab, scroll to Parameter Overrides. Expand it, toggle some values, verify colors match the M3 system (indigo accents, blue-gray text).

---

### Task 2: M3 Token Migration — OptimizeTab

**Files:**
- Modify: `web/src/features/backtest/components/OptimizeTab.tsx`

- [ ] **Step 1: Apply token replacements**

Line 63 — container border:
```
- "border border-border/50 rounded-lg p-3"
+ "border border-outline-variant/30 rounded-lg p-3"
```

Line 67 — optimize button:
```
- "px-3 py-1.5 text-xs bg-accent/20 text-accent rounded-lg disabled:opacity-50"
+ "px-3 py-1.5 text-xs bg-primary/15 text-primary rounded-lg disabled:opacity-50"
```

Line 72 — error text:
```
- "text-xs text-red-400"
+ "text-xs text-error"
```

Line 78 — table header:
```
- "text-muted border-b border-border"
+ "text-on-surface-variant border-b border-outline-variant"
```

Line 86 — table row border:
```
- "border-b border-border/30"
+ "border-b border-outline-variant/10"
```

Line 87 — row label:
```
- "py-1.5 text-muted"
+ "py-1.5 text-on-surface-variant"
```

Line 89 — proposed value:
```
- "text-right py-1.5 font-mono text-accent"
+ "text-right py-1.5 font-mono text-primary"
```

Line 94 — metrics text:
```
- "text-xs text-muted"
+ "text-xs text-on-surface-variant"
```

Line 99 — apply link:
```
- "text-xs text-accent hover:text-accent/80"
+ "text-xs text-primary hover:text-primary/80"
```

- [ ] **Step 2: Visual check**

Open the Backtest > Optimize tab, verify colors.

---

### Task 3: M3 Token Migration — ApplyModal

**Files:**
- Modify: `web/src/features/backtest/components/ApplyModal.tsx`

- [ ] **Step 1: Apply token replacements**

Line 47 — modal background:
```
- "bg-card rounded-xl p-4 max-w-md w-full mx-4 max-h-[80vh] overflow-y-auto"
+ "bg-surface-container rounded-xl p-4 max-w-md w-full mx-4 max-h-[80vh] overflow-y-auto"
```

Line 52 — error text:
```
- "text-xs text-red-400 mb-2"
+ "text-xs text-error mb-2"
```

Line 57 — table header:
```
- "text-muted border-b border-border"
+ "text-on-surface-variant border-b border-outline-variant"
```

Line 65 — table row border:
```
- "border-b border-border/30"
+ "border-b border-outline-variant/10"
```

Line 66 — param name:
```
- "py-1.5 text-muted font-mono"
+ "py-1.5 text-on-surface-variant font-mono"
```

Line 68 — proposed value:
```
- "text-right py-1.5 font-mono text-accent"
+ "text-right py-1.5 font-mono text-primary"
```

Line 76 — cancel button:
```
- "px-3 py-1.5 text-xs text-muted hover:text-foreground"
+ "px-3 py-1.5 text-xs text-on-surface-variant hover:text-on-surface"
```

Line 83 — confirm button:
```
- "px-3 py-1.5 text-xs bg-accent/20 text-accent rounded-lg hover:bg-accent/30 disabled:opacity-50"
+ "px-3 py-1.5 text-xs bg-primary/15 text-primary rounded-lg hover:bg-primary/30 disabled:opacity-50"
```

- [ ] **Step 2: Visual check**

Open OptimizeTab, run an optimization, click "Apply to Live", verify modal colors.

---

### Task 4: M3 Token Migration — BacktestResults (tertiary-dim to long/short + chart color)

**Files:**
- Modify: `web/src/features/backtest/components/BacktestResults.tsx`

- [ ] **Step 1: Replace all tertiary-dim references with long equivalents**

In `StatsStrip` (lines 123-124):
```
- { label: "Win Rate", value: `...`, color: stats.win_rate >= 50 ? "text-tertiary-dim" : "text-error", border: "border-tertiary-dim" },
- { label: "Net P&L", value: `...`, color: stats.net_pnl >= 0 ? "text-tertiary-dim" : "text-error", border: "border-tertiary-dim" },
+ { label: "Win Rate", value: `...`, color: stats.win_rate >= 50 ? "text-long" : "text-error", border: "border-long" },
+ { label: "Net P&L", value: `...`, color: stats.net_pnl >= 0 ? "text-long" : "text-error", border: "border-long" },
```

In `MonthlyPnl` (line 228):
```
- pnl >= 0 ? "bg-tertiary-dim/10 text-tertiary-dim" : "bg-error/10 text-error"
+ pnl >= 0 ? "bg-long/10 text-long" : "bg-error/10 text-error"
```

In `TradeList` — direction badge (line 259):
```
- trade.direction === "LONG" ? "bg-tertiary-dim/15 text-tertiary-dim" : "bg-error/15 text-error"
+ trade.direction === "LONG" ? "bg-long/15 text-long" : "bg-error/15 text-error"
```

In `TradeList` — P&L text (line 271):
```
- trade.pnl_pct >= 0 ? "text-tertiary-dim" : "text-error"
+ trade.pnl_pct >= 0 ? "text-long" : "text-error"
```

In `TradeDetail` — TP values (line 296):
```
- <span className="text-tertiary-dim font-mono tabular-nums">{trade.tp1.toLocaleString()}</span> / TP2: <span className="text-tertiary-dim font-mono tabular-nums">{trade.tp2.toLocaleString()}</span>
+ <span className="text-long font-mono tabular-nums">{trade.tp1.toLocaleString()}</span> / TP2: <span className="text-long font-mono tabular-nums">{trade.tp2.toLocaleString()}</span>
```

In `TradeDetail` — pattern badges (line 304):
```
- trade.direction === "LONG" ? "bg-tertiary-dim/10 text-tertiary-dim" : "bg-error/10 text-error"
+ trade.direction === "LONG" ? "bg-long/10 text-long" : "bg-error/10 text-error"
```

In `OutcomeBadge` (line 321):
```
- isWin ? "bg-tertiary-dim/10 text-tertiary-dim" : "bg-error/10 text-error"
+ isWin ? "bg-long/10 text-long" : "bg-error/10 text-error"
```

- [ ] **Step 2: Migrate equity curve chart color**

In `EquityCurve` (line 172), change the JS line color:
```
- color: theme.colors.accent,
+ color: theme.colors.primary,
```

- [ ] **Step 3: Visual check**

Open Backtest > Results with an existing run. Verify green values use `#2DD4A0` (long) and the equity curve line is `#8B9AFF` (primary).

---

### Task 5: M3 Token Migration — BacktestCompare (tertiary-dim to long/short)

**Files:**
- Modify: `web/src/features/backtest/components/BacktestCompare.tsx`

- [ ] **Step 1: Replace tertiary-dim in run selection list**

Line 78:
```
- run.net_pnl >= 0 ? "text-tertiary-dim" : "text-error"
+ run.net_pnl >= 0 ? "text-long" : "text-error"
```

---

### Task 6: Collapsible Section Component

**Files:**
- Modify: `web/src/features/backtest/components/BacktestSetup.tsx`

- [ ] **Step 1: Rewrite the Section component with collapsible support**

Replace the `Section` function (lines 326-333) with:

```tsx
function Section({
  title,
  children,
  collapsible,
  defaultOpen = false,
  summary,
}: {
  title: string;
  children: React.ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  summary?: string;
}) {
  const [isOpen, setIsOpen] = useState(!collapsible || defaultOpen);
  const contentId = `section-${title.toLowerCase().replace(/\s+/g, "-")}`;

  if (!collapsible) {
    return (
      <div>
        <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-1.5 px-1 text-on-surface-variant">
          {title}
        </h3>
        <div className="bg-surface-container p-5 rounded">{children}</div>
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-controls={contentId}
        className="w-full flex items-center gap-2 mb-1.5 px-1 text-left focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          className={`text-on-surface-variant transition-transform duration-200 ${isOpen ? "rotate-90" : ""}`}
        >
          <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider text-on-surface-variant flex-1">
          {title}
        </h3>
        {!isOpen && summary && (
          <span className="text-[10px] text-on-surface-variant/70 font-mono truncate max-w-[60%] text-right">
            {summary}
          </span>
        )}
      </button>
      <div
        id={contentId}
        role="region"
        className={`grid motion-reduce:transition-none transition-[grid-template-rows] duration-200 ease-out ${
          isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden">
          <div className="bg-surface-container p-5 rounded">{children}</div>
        </div>
      </div>
    </div>
  );
}
```

Note: `useState` is already imported at line 1.

- [ ] **Step 2: Add collapsible props to each Section usage**

Update each `<Section>` call in `BacktestSetup` (the return JSX starting at line 30):

Pairs, Timeframe, Date Range — **no change** (remain non-collapsible).

Scoring Weights (line 102):
```tsx
<Section title="Scoring Weights" collapsible summary={`Tech ${config.tech_weight}% / Pattern ${config.pattern_weight}%`}>
```

Thresholds (line 136):
```tsx
<Section title="Thresholds" collapsible summary={`Signal \u2265 ${config.signal_threshold}`}>
```

ML Blending (line 156):
```tsx
<Section title="ML Blending" collapsible summary={config.ml_enabled ? `On \u00b7 \u2265 ${config.ml_confidence_threshold}%` : "Off"}>
```

Indicators (line 187):
```tsx
<Section title="Indicators" collapsible summary={`ADX RSI BB OBV${config.enable_patterns ? " + Patterns" : ""}`}>
```

Risk & Levels (line 211):
```tsx
<Section title="Risk & Levels" collapsible summary={`SL ${config.sl_atr_multiplier}x \u00b7 TP1 ${config.tp1_atr_multiplier}x \u00b7 TP2 ${config.tp2_atr_multiplier}x \u00b7 Max ${config.max_concurrent_positions}`}>
```

Historical Data (line 247):
```tsx
<Section title="Historical Data" collapsible summary={importStatus ? `${importStatus.total_imported} candles imported` : "No data imported"}>
```

- [ ] **Step 3: Visual check**

Open Backtest > Setup. Verify:
- Pairs, Timeframe, Date Range are always visible (not collapsible)
- Scoring Weights through Historical Data are collapsed by default with summary text visible
- Clicking the header or chevron expands/collapses with smooth animation
- Chevron rotates right (collapsed) → down (expanded)
- Tab/Enter/Space toggles sections
- Parameter Overrides (below the sections) retains its own collapse behavior

---

### Task 7: Per-Pair Breakdown Component

**Files:**
- Modify: `web/src/features/backtest/components/BacktestResults.tsx`

- [ ] **Step 1: Add useMemo import**

Line 1 — add `useMemo` to the React import:
```tsx
import { useEffect, useRef, useState, useMemo } from "react";
```

- [ ] **Step 2: Add the PairBreakdown component**

Add this component after `StatsStrip` (after line 145):

```tsx
function PairBreakdown({ trades }: { trades: BacktestTrade[] }) {
  const pairs = useMemo(() => {
    const map = new Map<string, { total: number; wins: number; net_pnl: number; rr_sum: number; rr_count: number }>();
    for (const t of trades) {
      let entry = map.get(t.pair);
      if (!entry) {
        entry = { total: 0, wins: 0, net_pnl: 0, rr_sum: 0, rr_count: 0 };
        map.set(t.pair, entry);
      }
      entry.total++;
      if (t.outcome.includes("TP") || t.outcome === "WIN") entry.wins++;
      entry.net_pnl += t.pnl_pct;
      if (t.exit_price != null) {
        const rr = Math.abs(t.exit_price - t.entry_price) / Math.abs(t.entry_price - t.sl);
        if (isFinite(rr)) {
          entry.rr_sum += rr;
          entry.rr_count++;
        }
      }
    }
    return Array.from(map, ([pair, d]) => ({
      pair,
      total: d.total,
      win_rate: d.total > 0 ? (d.wins / d.total) * 100 : 0,
      net_pnl: d.net_pnl,
      avg_rr: d.rr_count > 0 ? d.rr_sum / d.rr_count : 0,
    }));
  }, [trades]);

  if (pairs.length <= 1) return null;

  return (
    <div>
      <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-1.5 px-1 text-on-surface-variant">Per-Pair Breakdown</h3>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {pairs.map((p) => (
          <div key={p.pair} className="bg-surface-container rounded-lg border border-outline-variant/10 p-3">
            <div className="text-sm font-medium text-on-surface mb-1">{p.pair.replace("-USDT-SWAP", "")}/USDT</div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
              <span className="text-on-surface-variant">Trades</span>
              <span className="text-right text-on-surface font-mono tabular-nums">{p.total}</span>
              <span className="text-on-surface-variant">Win Rate</span>
              <span className={`text-right font-mono tabular-nums ${p.win_rate >= 50 ? "text-long" : "text-short"}`}>{p.win_rate.toFixed(1)}%</span>
              <span className="text-on-surface-variant">Net P&L</span>
              <span className={`text-right font-mono tabular-nums ${p.net_pnl >= 0 ? "text-long" : "text-short"}`}>{p.net_pnl >= 0 ? "+" : ""}{p.net_pnl.toFixed(2)}%</span>
              <span className="text-on-surface-variant">Avg R:R</span>
              <span className="text-right text-on-surface font-mono tabular-nums">{p.avg_rr.toFixed(2)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Insert PairBreakdown into ResultsContent**

Update `ResultsContent` (lines 110-118) to insert `PairBreakdown` between `StatsStrip` and `EquityCurve`:

```tsx
function ResultsContent({ run }: { run: BacktestRun }) {
  const stats = run.results!.stats;
  const trades = run.results!.trades;

  return (
    <div className="space-y-4">
      <StatsStrip stats={stats} />
      <PairBreakdown trades={trades} />
      <EquityCurve data={stats.equity_curve} />
      <MonthlyPnl data={stats.monthly_pnl} />
      <TradeList trades={trades} />
    </div>
  );
}
```

- [ ] **Step 4: Visual check**

Open Backtest > Results with a multi-pair run. Verify 3 cards in a row on desktop, stacked on mobile, correct colors for win rate and P&L.

---

### Task 8: Trade Filter Bar + Sort

**Files:**
- Modify: `web/src/features/backtest/components/BacktestResults.tsx`

- [ ] **Step 1: Rewrite the TradeList component with filter/sort state**

Replace the entire `TradeList` function (lines 241-283) with:

```tsx
type SortOption = "date-desc" | "date-asc" | "pnl-desc" | "pnl-asc" | "duration" | "score";

function TradeList({ trades }: { trades: BacktestTrade[] }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [pairFilter, setPairFilter] = useState("all");
  const [dirFilter, setDirFilter] = useState<"both" | "LONG" | "SHORT">("both");
  const [outcomeFilter, setOutcomeFilter] = useState<"all" | "wins" | "losses">("all");
  const [sort, setSort] = useState<SortOption>("date-desc");
  const [fadeTick, setFadeTick] = useState(0);

  const allPairs = useMemo(() => [...new Set(trades.map((t) => t.pair))], [trades]);

  const filtered = useMemo(() => {
    let result = trades;
    if (pairFilter !== "all") result = result.filter((t) => t.pair === pairFilter);
    if (dirFilter !== "both") result = result.filter((t) => t.direction === dirFilter);
    if (outcomeFilter === "wins") result = result.filter((t) => t.outcome.includes("TP") || t.outcome === "WIN");
    if (outcomeFilter === "losses") result = result.filter((t) => !t.outcome.includes("TP") && t.outcome !== "WIN");

    const sorted = [...result];
    switch (sort) {
      case "date-desc": sorted.sort((a, b) => new Date(b.entry_time).getTime() - new Date(a.entry_time).getTime()); break;
      case "date-asc": sorted.sort((a, b) => new Date(a.entry_time).getTime() - new Date(b.entry_time).getTime()); break;
      case "pnl-desc": sorted.sort((a, b) => b.pnl_pct - a.pnl_pct); break;
      case "pnl-asc": sorted.sort((a, b) => a.pnl_pct - b.pnl_pct); break;
      case "duration": sorted.sort((a, b) => a.duration_minutes - b.duration_minutes); break;
      case "score": sorted.sort((a, b) => b.score - a.score); break;
    }
    return sorted;
  }, [trades, pairFilter, dirFilter, outcomeFilter, sort]);

  const clearFilters = () => {
    setPairFilter("all");
    setDirFilter("both");
    setOutcomeFilter("all");
    setFadeTick((t) => t + 1);
  };

  const pill = (active: boolean) =>
    active
      ? "bg-primary/15 text-primary border-primary/30"
      : "bg-transparent text-on-surface-variant border-outline-variant/30";

  return (
    <div>
      <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-1.5 px-1 text-on-surface-variant">
        Trades ({filtered.length}{filtered.length !== trades.length ? ` of ${trades.length}` : ""})
      </h3>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-2 mb-2 items-center">
        {/* Pair filters */}
        <button onClick={() => { setPairFilter("all"); setFadeTick((t) => t + 1); }}
          className={`min-h-[44px] px-3 py-2 rounded-lg text-xs font-bold border transition-colors ${pill(pairFilter === "all")}`}>
          All Pairs
        </button>
        {allPairs.map((p) => (
          <button key={p} onClick={() => { setPairFilter(p); setFadeTick((t) => t + 1); }}
            className={`min-h-[44px] px-3 py-2 rounded-lg text-xs font-bold border transition-colors ${pill(pairFilter === p)}`}>
            {p.replace("-USDT-SWAP", "")}
          </button>
        ))}
        <div className="border-r border-outline-variant/20 h-6 self-center" />

        {/* Direction filters */}
        {(["both", "LONG", "SHORT"] as const).map((d) => (
          <button key={d} onClick={() => { setDirFilter(d); setFadeTick((t) => t + 1); }}
            className={`min-h-[44px] px-3 py-2 rounded-lg text-xs font-bold border transition-colors ${pill(dirFilter === d)}`}>
            {d === "both" ? "Both" : d === "LONG" ? "Long" : "Short"}
          </button>
        ))}
        <div className="border-r border-outline-variant/20 h-6 self-center" />

        {/* Outcome filters */}
        {(["all", "wins", "losses"] as const).map((o) => (
          <button key={o} onClick={() => { setOutcomeFilter(o); setFadeTick((t) => t + 1); }}
            className={`min-h-[44px] px-3 py-2 rounded-lg text-xs font-bold border transition-colors ${pill(outcomeFilter === o)}`}>
            {o === "all" ? "All" : o === "wins" ? "Wins" : "Losses"}
          </button>
        ))}
        <div className="border-r border-outline-variant/20 h-6 self-center" />

        {/* Sort dropdown */}
        <select
          value={sort}
          onChange={(e) => { setSort(e.target.value as SortOption); setFadeTick((t) => t + 1); }}
          aria-label="Sort trades"
          className="min-h-[44px] px-3 py-2 rounded-lg text-xs font-bold bg-surface-container-lowest border border-outline-variant/30 text-on-surface-variant focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none"
        >
          <option value="date-desc">Date (newest)</option>
          <option value="date-asc">Date (oldest)</option>
          <option value="pnl-desc">P&L (high → low)</option>
          <option value="pnl-asc">P&L (low → high)</option>
          <option value="duration">Duration</option>
          <option value="score">Score</option>
        </select>
      </div>

      {/* Trade list */}
      <div key={fadeTick} className="bg-surface-container rounded-lg border border-outline-variant/10 overflow-hidden divide-y divide-outline-variant/10 transition-opacity duration-150">
        {filtered.length === 0 ? (
          <div className="py-12 text-center text-on-surface-variant">
            <p className="text-sm">No trades match filters</p>
            <button onClick={clearFilters} className="mt-2 text-xs text-primary">Clear filters</button>
          </div>
        ) : (
          filtered.map((trade, i) => (
            <div key={`${trade.pair}-${trade.entry_time}-${i}`}>
              <button
                onClick={() => setExpanded(expanded === i ? null : i)}
                className="w-full px-3 py-2.5 flex items-center justify-between text-left hover:bg-surface-container-high transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                      trade.direction === "LONG" ? "bg-long/15 text-long" : "bg-error/15 text-error"
                    }`}
                  >
                    {trade.direction}
                  </span>
                  <span className="text-sm text-on-surface">{trade.pair.replace("-USDT-SWAP", "")}</span>
                </div>
                <div className="flex items-center gap-3">
                  <OutcomeBadge outcome={trade.outcome} />
                  <span
                    className={`text-sm font-mono tabular-nums ${
                      trade.pnl_pct >= 0 ? "text-long" : "text-error"
                    }`}
                  >
                    {trade.pnl_pct >= 0 ? "+" : ""}{trade.pnl_pct.toFixed(2)}%
                  </span>
                </div>
              </button>
              {expanded === i && <TradeDetail trade={trade} />}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Visual check**

Open Backtest > Results. Verify:
- Filter pills appear in a flex-wrap row with 44px height
- Clicking a pair/direction/outcome pill filters the trade list
- Sort dropdown works for all 6 options
- Empty state shows "No trades match filters" with a "Clear filters" link
- Crossfade transition on filter change

---

### Task 9: Config Summary Labels in Compare Tab

**Files:**
- Modify: `web/src/features/backtest/components/BacktestCompare.tsx`

- [ ] **Step 1: Add the configLabel helper function**

Add after the `CURVE_COLORS` line (line 14), before `METRIC_ROWS`:

```tsx
function configLabel(config: BacktestConfig): string {
  const pairs = config.pairs.map((p) => p.replace("-USDT-SWAP", "")).join(", ");
  return `${pairs} \u00b7 ${config.timeframe} \u00b7 Thresh ${config.signal_threshold} \u00b7 SL ${config.sl_atr_multiplier}x`;
}
```

Add the import for `BacktestConfig` to the existing type import (line 12):
```tsx
import type { BacktestRun, BacktestStats, BacktestConfig } from "../types";
```

**Note on run selection list:** The spec mentions config labels in the run selection list, but that list uses `BacktestRunSummary` (no `config` object). It already shows pairs + timeframe + date + trades + WR — richer than `configLabel`. No change needed there. Config labels apply to the comparison results where full `BacktestRun` with `config` is available (Steps 2-3 below).

- [ ] **Step 2: Update CompareTable column headers**

In `CompareTable`, replace the `<th>` content for runs (lines 126-133):

```tsx
{runs.map((run, i) => (
  <th key={run.id} className="text-right px-3 py-2">
    <div className="flex items-center justify-end gap-1.5">
      <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: CURVE_COLORS[i] }} />
      <div className="text-right">
        <span className="text-[10px] font-headline font-bold text-on-surface-variant uppercase tracking-wider block">
          Run {i + 1}
        </span>
        <span className="text-[10px] text-on-surface-variant/70 font-mono block truncate max-w-[200px]">
          {configLabel(run.config)}
        </span>
      </div>
    </div>
  </th>
))}
```

- [ ] **Step 3: Update CompareEquityCurves legend**

In `CompareEquityCurves`, update the legend items (lines 239-246):

```tsx
{runs.map((run, i) => (
  <div key={run.id} className="flex items-center gap-1.5">
    <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: CURVE_COLORS[i] }} />
    <span className="text-[10px] text-on-surface-variant">
      Run {i + 1}: {configLabel(run.config)}
    </span>
  </div>
))}
```

- [ ] **Step 4: Visual check**

Open Backtest > Compare, select 2+ runs, click Compare. Verify:
- Table column headers show "Run N" + config fingerprint below
- Equity curve legend shows "Run N: config fingerprint"

---

### Task 10: Config Diff Table

**Files:**
- Modify: `web/src/features/backtest/components/BacktestCompare.tsx`

- [ ] **Step 1: Add the ConfigDiff component**

Add after `CompareEquityCurves` (after line 251):

```tsx
const CONFIG_DIFF_KEYS: { key: keyof BacktestConfig; label: string }[] = [
  { key: "signal_threshold", label: "Signal Threshold" },
  { key: "tech_weight", label: "Tech Weight" },
  { key: "pattern_weight", label: "Pattern Weight" },
  { key: "enable_patterns", label: "Patterns Enabled" },
  { key: "sl_atr_multiplier", label: "SL (ATR x)" },
  { key: "tp1_atr_multiplier", label: "TP1 (ATR x)" },
  { key: "tp2_atr_multiplier", label: "TP2 (ATR x)" },
  { key: "max_concurrent_positions", label: "Max Positions" },
  { key: "ml_enabled", label: "ML Enabled" },
  { key: "ml_confidence_threshold", label: "ML Confidence" },
];

function ConfigDiff({ runs }: { runs: BacktestRun[] }) {
  const diffs = useMemo(() => {
    return CONFIG_DIFF_KEYS.filter(({ key }) => {
      const values = runs.map((r) => String(r.config[key]));
      return new Set(values).size > 1;
    });
  }, [runs]);

  return (
    <div>
      <h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-1.5 px-1 text-on-surface-variant">Config Differences</h3>
      <div className="bg-surface-container rounded-lg border border-outline-variant/10 overflow-x-auto">
        {diffs.length === 0 ? (
          <p className="px-3 py-4 text-sm text-on-surface-variant text-center">All parameters identical across runs</p>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-outline-variant/10">
                  <th className="text-left px-3 py-2 text-[10px] font-headline font-bold text-on-surface-variant uppercase tracking-wider">Parameter</th>
                  {runs.map((run, i) => (
                    <th key={run.id} className="text-right px-3 py-2">
                      <div className="flex items-center justify-end gap-1.5">
                        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: CURVE_COLORS[i] }} />
                        <span className="text-[10px] font-headline font-bold text-on-surface-variant uppercase tracking-wider">Run {i + 1}</span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {diffs.map(({ key, label }) => (
                  <tr key={key} className="border-b border-outline-variant/10 last:border-0">
                    <td className="px-3 py-2 text-on-surface-variant">{label}</td>
                    {runs.map((run, i) => (
                      <td
                        key={run.id}
                        className="px-3 py-2 text-right font-mono tabular-nums font-bold"
                        style={{ color: CURVE_COLORS[i] }}
                      >
                        {String(run.config[key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="px-3 py-2 text-[10px] text-on-surface-variant border-t border-outline-variant/10">
              {diffs.length} of {CONFIG_DIFF_KEYS.length} parameters differ — identical parameters hidden
            </p>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add useMemo import**

Update the React import at line 1:
```tsx
import { useEffect, useRef, useMemo } from "react";
```

- [ ] **Step 3: Insert ConfigDiff into the compare results**

Update the comparison results section (lines 106-111) to insert `ConfigDiff` between `CompareEquityCurves` and `CompareTable`:

```tsx
{compareResult && compareResult.length >= 2 && (
  <>
    <CompareEquityCurves runs={compareResult} />
    <ConfigDiff runs={compareResult} />
    <CompareTable runs={compareResult} />
  </>
)}
```

- [ ] **Step 4: Visual check**

Open Backtest > Compare, select 2+ runs with different configs, click Compare. Verify:
- ConfigDiff table appears between equity curves and side-by-side metrics
- Only differing parameters are shown
- Each run's values use its curve color
- Footer shows "N of M parameters differ"
- If all params match, shows "All parameters identical across runs"

---

### Task 11: Build Verification + Commit

- [ ] **Step 1: Run TypeScript check + build**

```bash
cd web && pnpm build
```

Expected: No errors.

- [ ] **Step 2: Run lint**

```bash
cd web && pnpm lint
```

Expected: No new lint errors.

- [ ] **Step 3: Commit all changes**

Per CLAUDE.md convention, commit once at the end of the feature batch:

```bash
git add web/src/features/backtest/
git commit -m "feat(backtest): page improvements — M3 tokens, collapsible sections, pair breakdown, trade filters, config diff"
```
