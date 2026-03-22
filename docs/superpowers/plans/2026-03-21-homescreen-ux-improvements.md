# Homescreen UX Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix critical accessibility and interaction issues on the homescreen — minimum text sizes, touch targets, tappable rows, animated expand/collapse, outcome badges, and improved empty states.

**Architecture:** All changes are scoped to `web/src/features/home/components/`. Signal rows gain click-to-open-detail behavior by calling `useSignalStore().selectSignal()` (existing pattern from `SignalCard`), with `SignalDetail` rendered directly in `HomeView` so the dialog works without depending on the Signals tab being mounted. Position expand/collapse uses CSS `grid-rows` transition (no new deps). News items become external links via their existing `url` field.

**Implementation note:** Line numbers referenced throughout this plan are based on the initial file state. Earlier tasks may shift line numbers for later tasks. Agents should locate code by content/pattern matching, not line numbers.

**Tech Stack:** React 19, Tailwind CSS v3, motion/react (already available), Zustand (signal store), Vitest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `web/src/features/home/components/HomeView.tsx` | Modify | Fix text sizes, touch targets, skeleton heights, empty states, PortfolioStrip dedup, position animation, news links |
| `web/src/features/home/components/RecentSignals.tsx` | Modify | Tappable signal rows, outcome badges, text sizes |

No new files created. All changes are in-place modifications.

---

## Task 1: Bump text-[10px] to text-xs across home components

**Files:**
- Modify: `web/src/features/home/components/HomeView.tsx` (19 instances)
- Modify: `web/src/features/home/components/RecentSignals.tsx` (2 instances)

All `text-[10px]` instances in the home feature become `text-xs` (12px) to meet mobile readability minimums. This is a global find-replace within these two files only.

**Note:** Task 4 later replaces the expanded position detail block entirely with new code that already uses `text-xs`. Task 6 replaces news items with new code that already uses `text-xs`. So in practice: do the global find-replace in Step 1, and later tasks will be consistent.

- [ ] **Step 1: Replace all text-[10px] in HomeView.tsx**

In `HomeView.tsx`, replace every `text-[10px]` with `text-xs`. There are 19 instances across these sections:
- `AccountHeader`: label ("Total Equity")
- `OpenPositions`: side/leverage badge, size label, mark price, expanded detail labels
- `LatestNewsCard`: source, sentiment, timestamp
- `PerformanceCard`: header label, all three stat sub-labels (Win Rate, Avg R:R, Net P&L)

- [ ] **Step 2: Replace all text-[10px] in RecentSignals.tsx**

In `RecentSignals.tsx`, replace every `text-[10px]` with `text-xs`. 2 instances:
- Timeframe label (line 55)
- Timestamp (line 57)

- [ ] **Step 3: Visual check**

Run: `cd web && pnpm dev`

Open homescreen in mobile viewport (375px). Verify all labels are legible and no layout overflow occurs. Check:
- AccountHeader labels
- PortfolioStrip stat labels
- Position row badges and sub-text
- Signal row metadata
- News card metadata
- Performance stat sub-labels

---

## Task 2: Fix Retry button touch target

**Files:**
- Modify: `web/src/features/home/components/HomeView.tsx` (line 28-31)

The error-state Retry button has `py-1.5` yielding ~28px height, below the 44px minimum touch target.

- [ ] **Step 1: Increase Retry button size**

Change the Retry button className from:
```
className="mt-2 px-4 py-1.5 text-xs font-medium rounded-lg bg-surface-container-highest text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
```
to:
```
className="mt-2 px-5 py-2.5 min-h-[44px] text-sm font-medium rounded-lg bg-surface-container-highest text-primary active:scale-95 transition-transform focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
```

Changes: `py-1.5` -> `py-2.5`, add `min-h-[44px]`, `px-4` -> `px-5`, `text-xs` -> `text-sm`, add `active:scale-95 transition-transform` for tap feedback.

- [ ] **Step 2: Visual check**

Trigger the error state (disconnect backend or set invalid API key). Verify the Retry button is comfortably tappable and shows press feedback.

---

## Task 3: Make signal rows tappable with outcome badges

**Files:**
- Modify: `web/src/features/home/components/RecentSignals.tsx` (lines 41-59)

Signal rows should open the signal detail modal on tap (same pattern as `SignalCard` in the signals tab). Each row also gains an outcome badge.

- [ ] **Step 1: Add outcome badge config**

`useSignalStore` is already imported on line 4 of `RecentSignals.tsx`. Add the outcome badge config after the existing imports (after line 6):

```tsx
const OUTCOME_BADGE: Record<string, { label: string; cls: string }> = {
  PENDING: { label: "PENDING", cls: "bg-accent/15 text-primary" },
  TP1_HIT: { label: "TP1", cls: "bg-long/15 text-long" },
  TP2_HIT: { label: "TP2", cls: "bg-long/15 text-long" },
  SL_HIT: { label: "SL", cls: "bg-short/15 text-short" },
  EXPIRED: { label: "EXP", cls: "bg-outline-variant/20 text-on-surface-variant" },
};
```

- [ ] **Step 2: Convert SignalRow from div to button**

Replace the `SignalRow` component with a tappable version:

```tsx
function SignalRow({ signal }: { signal: Signal }) {
  const selectSignal = useSignalStore((s) => s.selectSignal);
  const isLong = signal.direction === "LONG";
  const badge = OUTCOME_BADGE[signal.outcome] ?? OUTCOME_BADGE.PENDING;

  return (
    <button
      onClick={() => selectSignal(signal)}
      className="w-full px-3 py-2.5 flex items-center justify-between text-left active:bg-surface-container-high/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      <div className="flex items-center gap-2 min-w-0">
        <Zap size={14} className="text-primary flex-shrink-0" />
        <span className="font-headline font-bold text-sm">{formatPair(signal.pair)}</span>
        <span className={`text-xs font-mono font-bold ${isLong ? "text-long" : "text-short"}`}>
          {signal.direction}
        </span>
        <span className={`text-xs font-mono tabular ${isLong ? "text-long" : "text-short"}`}>
          {formatScore(signal.final_score)}
        </span>
        <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${badge.cls}`}>
          {badge.label}
        </span>
      </div>
      <span className="text-xs text-outline tabular flex-shrink-0 ml-2">{formatRelativeTime(signal.created_at)}</span>
    </button>
  );
}
```

Key changes:
- `<div>` -> `<button>` with `w-full text-left`
- Added `active:bg-surface-container-high/50` for tap feedback
- Added `focus-visible:ring-2` for keyboard accessibility
- Added outcome badge after the score
- Calls `selectSignal(signal)` on click to open detail modal
- Wrapped left content in `min-w-0` to prevent overflow
- Added `flex-shrink-0 ml-2` on timestamp to prevent it from being pushed off-screen

- [ ] **Step 3: Render SignalDetail in HomeView**

`SignalDetail` is currently only rendered inside `SignalFeed` (Signals tab). Without this step, tapping a signal row would set store state but no dialog would appear since `HomeView` is the active view. Add `SignalDetail` rendering directly to `HomeView.tsx`:

1. Add imports at the top of `HomeView.tsx`:
```tsx
import { SignalDetail } from "../../signals/components/SignalDetail";
import { useSignalStore } from "../../signals/store";
```

2. Inside the `HomeView` component, pull `selectedSignal` and `clearSelection` from the store:
```tsx
const { selectedSignal, clearSelection } = useSignalStore();
```

3. Add `SignalDetail` at the bottom of **both** return blocks (error state and normal state), just before the closing `</div>`:
```tsx
<SignalDetail signal={selectedSignal} onClose={clearSelection} />
```

This ensures the dialog renders regardless of which tab is active. The Signals tab's `SignalFeed` also renders `SignalDetail`, but since only one can have a non-null `selectedSignal` at a time (the store is shared), there's no conflict — closing the dialog via `clearSelection()` clears it everywhere.

- [ ] **Step 4: Verify interaction**

Run dev server. On the homescreen, tap a signal row. It should:
1. Show tap feedback (background color flash)
2. Open the signal detail modal dialog
3. Display correct signal data in the modal

---

## Task 4: Animate position expand/collapse

**Files:**
- Modify: `web/src/features/home/components/HomeView.tsx` (lines 171-192)

The expanded position detail section currently snaps open. Add a CSS grid-rows transition for smooth expand/collapse.

- [ ] **Step 1: Add animated expand container**

Replace the conditional render block (the `{isExpanded && (...)}` section inside the positions `.map()`) with a grid-based animated container:

```tsx
<div
  className={`grid transition-[grid-template-rows] duration-200 ease-out ${
    isExpanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
  }`}
>
  <div className="overflow-hidden">
    <div className="px-3 pb-3 pt-1 grid grid-cols-3 gap-2">
      <div>
        <span className="text-xs text-on-surface-variant block uppercase">Entry</span>
        <span className="text-xs font-medium tabular">${formatPrice(pos.avg_price)}</span>
      </div>
      <div>
        <span className="text-xs text-on-surface-variant block uppercase">Mark</span>
        <span className="text-xs font-medium tabular">${formatPrice(pos.mark_price)}</span>
      </div>
      {pos.liquidation_price && (
        <div>
          <span className="text-xs text-on-surface-variant block uppercase">Liq. Price</span>
          <span className="text-xs font-medium text-short tabular">${formatPrice(pos.liquidation_price)}</span>
        </div>
      )}
      <div>
        <span className="text-xs text-on-surface-variant block uppercase">Margin</span>
        <span className="text-xs font-medium tabular">${formatPrice(pos.margin)}</span>
      </div>
    </div>
  </div>
</div>
```

Note: This also replaces the old `text-[10px]` labels with `text-xs` (from Task 1) and removes the `bg-surface-container-lowest/30` background (detail rows now inherit the card background for cleaner look). The outer `<div>` uses `grid-rows-[0fr]`/`grid-rows-[1fr]` with `transition-[grid-template-rows]` for a smooth height animation without JS.

- [ ] **Step 2: Visual check**

Tap a position row. Verify:
- Detail slides open smoothly (~200ms)
- Tapping again slides it closed
- No layout jump or CLS

---

## Task 5: Improve empty states

**Files:**
- Modify: `web/src/features/home/components/HomeView.tsx` (OpenPositions + LatestNewsCard)
- Modify: `web/src/features/home/components/RecentSignals.tsx` (empty signals)

Empty states should provide context, not just state a fact. Currently `LatestNewsCard` returns `null` on empty data — inconsistent with positions and signals which show messages.

- [ ] **Step 1: Improve "No open positions" empty state**

In `HomeView.tsx`, find the OpenPositions empty state:
```tsx
<p className="px-1 text-sm text-outline">No open positions</p>
```
Replace with:
```tsx
<p className="px-1 text-sm text-outline">No open positions &mdash; the engine is monitoring for opportunities</p>
```

- [ ] **Step 2: Improve "No signals" empty state**

In `RecentSignals.tsx`, find the empty signals message:
```tsx
<p className="px-1 text-sm text-outline">No signals in the last 24 hours</p>
```
Replace with:
```tsx
<p className="px-1 text-sm text-outline">No signals in the last 24h &mdash; markets are being monitored</p>
```

- [ ] **Step 3: Add news empty state**

In `HomeView.tsx`, in the `LatestNewsCard` component, replace:
```tsx
if (news.length === 0) return null;
```
with:
```tsx
if (news.length === 0) return (
  <div className="space-y-3">
    <h2 className="text-xs font-bold tracking-widest uppercase text-on-surface-variant px-1">
      Latest News
    </h2>
    <p className="px-1 text-sm text-outline">No recent news &mdash; feeds are being monitored</p>
  </div>
);
```

This keeps the section header visible and provides the same contextual messaging pattern as positions and signals.

---

## Task 6: Make news items tappable external links

**Files:**
- Modify: `web/src/features/home/components/HomeView.tsx` (lines 223-236)

`NewsEvent` has a `url` field. Cards should link to the source article.

- [ ] **Step 1: Wrap news items in anchor tags**

Replace the news item `<div>` (the inner one with `key={n.id}`) with an `<a>` tag. Handle empty `url` by falling back to a non-clickable `<div>`:

```tsx
{news.map((n) => {
  const cls = `bg-surface-container-low rounded-lg p-3 border-l-4 ${IMPACT_BORDER[n.impact ?? ""] ?? "border-l-outline-variant/20"}`;
  const inner = (
    <>
      <p className="text-sm font-medium leading-snug">{n.headline}</p>
      <div className="flex items-center gap-2 mt-1.5">
        <span className="text-xs text-on-surface-variant tabular">{n.source}</span>
        {n.sentiment && (
          <span className={`text-xs font-medium ${SENTIMENT_COLOR[n.sentiment] ?? ""}`}>
            {n.sentiment}
          </span>
        )}
        <span className="text-xs text-outline">{n.published_at ? formatRelativeTime(n.published_at) : ""}</span>
      </div>
    </>
  );

  return n.url ? (
    <a key={n.id} href={n.url} target="_blank" rel="noopener noreferrer" className={`block active:bg-surface-container/50 transition-colors ${cls}`}>
      {inner}
    </a>
  ) : (
    <div key={n.id} className={cls}>
      {inner}
    </div>
  );
})}
```

Changes:
- `<div>` -> `<a>` with `href={n.url}` `target="_blank"` `rel="noopener noreferrer"` when URL is present
- Falls back to plain `<div>` when `n.url` is empty (prevents page reload on empty href)
- Added `block` for display, `active:bg-surface-container/50 transition-colors` for tap feedback
- Text sizes already `text-xs` from Task 1

- [ ] **Step 2: Visual check**

Tap a news card. Verify it opens the source URL in a new tab/window. Check that the tap feedback (background flash) is visible.

---

## Task 7: Fix skeleton heights to reduce layout shift

**Files:**
- Modify: `web/src/features/home/components/HomeView.tsx` (lines 55, 121, 214, 243)

Skeleton heights should approximate actual rendered content height to minimize CLS.

- [ ] **Step 1: Update skeleton dimensions**

Apply these changes to the loading skeletons:

1. **AccountHeader skeleton** (line 55) — keep `h-24`, it's close enough to the ~100px rendered size.

2. **OpenPositions skeleton** (line 121) — change from `h-16` to `h-20`:
```tsx
if (loading) return <div className="h-20 bg-surface-container rounded-lg animate-pulse" />;
```

3. **LatestNewsCard skeleton** (line 214) — change from `h-16` to `h-24` (news cards are taller with headline + metadata):
```tsx
if (loading) return <div className="h-24 bg-surface-container rounded-lg animate-pulse" />;
```

4. **PerformanceCard skeleton** (line 243) — change from `h-16` to `h-28` (performance card has header + 3-col grid):
```tsx
if (loading) return <div className="h-28 bg-surface-container rounded-lg animate-pulse" />;
```

---

## Task 8: Replace duplicated "Unrealized" in PortfolioStrip

**Files:**
- Modify: `web/src/features/home/components/HomeView.tsx` (lines 93-98)

The AccountHeader already shows unrealized PnL prominently. The PortfolioStrip repeating it is redundant. Replace with position count which is actually useful context.

- [ ] **Step 1: Replace Unrealized with Positions count**

This requires adding `positions` as a prop to `PortfolioStrip`. Update the component signature and first cell:

Update the function signature:
```tsx
function PortfolioStrip({ portfolio, positions, loading }: { portfolio: Portfolio | null; positions: Position[]; loading: boolean }) {
```

Replace the first grid cell (Unrealized) with:
```tsx
<div>
  <span className="text-xs text-on-surface-variant uppercase tracking-widest block">Positions</span>
  <span className={`font-headline font-bold text-sm tabular ${positions.length > 0 ? "text-primary" : ""}`}>{positions.length}</span>
</div>
```

The `text-primary` on non-zero counts maintains visual weight parity with the other cells (which use colored values), preventing the strip from looking unbalanced.

- [ ] **Step 2: Update PortfolioStrip call site**

In the `HomeView` return (line 45), pass `positions`:
```tsx
<PortfolioStrip portfolio={portfolio} positions={positions} loading={accountLoading} />
```

- [ ] **Step 3: Visual check**

Verify the PortfolioStrip now shows: Positions | Available | Margin | Exposure. The position count should match the Open Positions section.

---

## Task 9: Final visual regression check

No file changes. End-to-end visual verification.

- [ ] **Step 1: Run build to catch type errors**

Run: `cd web && pnpm build`
Expected: Clean build, no TypeScript errors.

- [ ] **Step 2: Full homescreen walkthrough**

Open the app at mobile viewport (375px). Check:
- All text is legible (no sub-12px text)
- Retry button is 44px+ tall with tap feedback
- Signal rows are tappable and open detail modal **from the homescreen** (not just from Signals tab)
- Position expand/collapse animates smoothly
- Empty states show contextual messages for positions, signals, **and news**
- News cards link to external URLs
- Skeleton heights don't cause layout jumps
- PortfolioStrip shows "Positions" (with primary color when > 0) instead of "Unrealized"
- All `tabular` number formatting still works
- Focus rings visible on keyboard navigation
