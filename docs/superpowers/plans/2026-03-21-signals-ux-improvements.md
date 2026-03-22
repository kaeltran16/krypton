# Signals Page UX Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix critical accessibility, touch target, and consistency issues across the signals page and all its sub-components — extract a shared SegmentedControl, enforce minimum text sizes, add missing close button / aria-labels / color-not-only indicators, fix chart a11y, improve empty states, and correct minor inconsistencies.

**Architecture:** The core fix is extracting a `SegmentedControl` shared component used by 6 files — this solves touch targets (44px min) and visual consistency in one shot. Remaining changes are in-place modifications to signal components: text-size bumps, aria attributes, a dialog close button, chart accessibility, and empty state enrichment. No backend changes.

**Implementation note:** Line numbers referenced throughout this plan are based on the initial file state. Earlier tasks may shift line numbers for later tasks. Agents should locate code by content/pattern matching, not line numbers.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v3, Lucide icons (already available), Vitest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `web/src/shared/components/SegmentedControl.tsx` | Create | Shared segmented control with 44px touch targets, consistent styling |
| `web/src/features/signals/components/SignalsView.tsx` | Modify | Use SegmentedControl |
| `web/src/features/signals/components/SignalFeed.tsx` | Modify | Use SegmentedControl, improve empty state |
| `web/src/features/signals/components/JournalView.tsx` | Modify | Use SegmentedControl |
| `web/src/features/signals/components/AnalyticsView.tsx` | Modify | Use SegmentedControl, bump text sizes, improve empty state, fix gradient ID |
| `web/src/features/signals/components/DeepDiveView.tsx` | Modify | Use SegmentedControl, bump text sizes, add motion-reduce, improve empty state |
| `web/src/features/signals/components/SignalCard.tsx` | Modify | Bump text sizes, add aria-label to Newspaper icon |
| `web/src/features/signals/components/SignalDetail.tsx` | Modify | Add close button, bump text sizes, fix tracking-tighter, add loading state to status buttons |
| `web/src/features/signals/components/IndicatorAudit.tsx` | Modify | Bump text sizes |
| `web/src/features/signals/components/ReasoningChain.tsx` | Modify | Bump text sizes, add text labels alongside sentiment dots |
| `web/src/features/signals/components/PatternBadges.tsx` | Modify | Bump text sizes |
| `web/src/features/signals/components/CalendarView.tsx` | Modify | Add aria-labels to nav arrows, bump text sizes |
| `web/src/features/signals/components/ConnectionStatus.tsx` | Modify | Bump text size |
| `web/src/features/signals/components/PairDeepDive.tsx` | Modify | Bump text sizes |

---

## Task 1: Create shared SegmentedControl component

This fixes issues #1 (touch targets < 44px) and #6 (inconsistent segmented control styling) across all 6 files that use inline segmented controls. Note: this introduces haptic feedback on tab switches, consistent with how `Layout.tsx` tabs already work.

**Files:**
- Create: `web/src/shared/components/SegmentedControl.tsx`

- [ ] **Step 1: Create the SegmentedControl component**

```tsx
// web/src/shared/components/SegmentedControl.tsx
import { hapticTap } from "../lib/haptics";

interface SegmentedControlProps<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  fullWidth?: boolean;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  fullWidth = false,
}: SegmentedControlProps<T>) {
  return (
    <div
      className={`flex gap-1 bg-surface-container-lowest p-1 rounded-lg ${fullWidth ? "w-full" : "w-fit"}`}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          aria-pressed={value === opt.value}
          onClick={() => {
            hapticTap();
            onChange(opt.value);
          }}
          className={`min-h-[44px] px-4 text-xs font-semibold rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
            fullWidth ? "flex-1" : ""
          } ${
            value === opt.value
              ? "bg-surface-container-highest text-primary"
              : "text-on-surface-variant hover:bg-surface-container-highest"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Add a basic unit test**

Create `web/src/shared/components/SegmentedControl.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SegmentedControl } from "./SegmentedControl";

const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Beta" },
  { value: "c", label: "Charlie" },
];

describe("SegmentedControl", () => {
  it("renders all options", () => {
    render(<SegmentedControl options={OPTIONS} value="a" onChange={() => {}} />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("Charlie")).toBeInTheDocument();
  });

  it("marks active option with aria-pressed", () => {
    render(<SegmentedControl options={OPTIONS} value="b" onChange={() => {}} />);
    expect(screen.getByText("Beta")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Alpha")).toHaveAttribute("aria-pressed", "false");
  });

  it("calls onChange on click", () => {
    const onChange = vi.fn();
    render(<SegmentedControl options={OPTIONS} value="a" onChange={onChange} />);
    fireEvent.click(screen.getByText("Charlie"));
    expect(onChange).toHaveBeenCalledWith("c");
  });
});
```

- [ ] **Step 3: Verify it builds and tests pass**

Run: `cd web && npx tsc --noEmit && npx vitest run src/shared/components/SegmentedControl.test.tsx`
Expected: No type errors, all tests pass

---

## Task 2: Replace inline segmented controls in SignalsView and SignalFeed

**Files:**
- Modify: `web/src/features/signals/components/SignalsView.tsx`
- Modify: `web/src/features/signals/components/SignalFeed.tsx`

- [ ] **Step 1: Replace SignalsView segmented control**

Replace lines 13-35 (the `<div className="p-3 pb-0">` block containing the two inline buttons) with:

```tsx
import { SegmentedControl } from "../../../shared/components/SegmentedControl";

// Inside the return, replace the segmented control div:
<div className="p-3 pb-0">
  <SegmentedControl
    options={[
      { value: "signals", label: "Signals" },
      { value: "journal", label: "Journal" },
    ]}
    value={activeView}
    onChange={setActiveView}
  />
</div>
```

- [ ] **Step 2: Replace SignalFeed filter control**

Replace lines 42-56 (the filter `<div className="flex gap-1 ...">` block) with:

```tsx
import { SegmentedControl } from "../../../shared/components/SegmentedControl";

// Inside the flex container, replace the filter div:
<SegmentedControl
  options={FILTERS}
  value={statusFilter}
  onChange={setStatusFilter}
/>
```

Note: `FILTERS` already has the correct `{ value, label }` shape, so it works directly.

- [ ] **Step 3: Verify it builds**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

---

## Task 3: Replace inline segmented controls in JournalView, AnalyticsView, DeepDiveView

**Files:**
- Modify: `web/src/features/signals/components/JournalView.tsx`
- Modify: `web/src/features/signals/components/AnalyticsView.tsx`
- Modify: `web/src/features/signals/components/DeepDiveView.tsx`

- [ ] **Step 1: Replace JournalView tab control**

Replace lines 20-34 (the `<div className="flex bg-surface-container-low ...">` block) with:

```tsx
import { SegmentedControl } from "../../../shared/components/SegmentedControl";

// Inside the return:
<div className="px-3 pt-3">
  <SegmentedControl
    options={TABS.map(({ key, label }) => ({ value: key, label }))}
    value={tab}
    onChange={setTab}
    fullWidth
  />
</div>
```

Note: the old JournalView tabs used `font-bold uppercase tracking-wider` and a glow shadow on active state. The SegmentedControl intentionally normalizes this to match the rest of the app. This is the desired consistency fix from issue #6.

- [ ] **Step 2: Replace AnalyticsView period selector**

Replace lines 42-56 (the period selector div) with:

```tsx
import { SegmentedControl } from "../../../shared/components/SegmentedControl";

// Inside the return:
<SegmentedControl
  options={PERIODS}
  value={period}
  onChange={setPeriod}
/>
```

Note: `PERIODS` already has the correct `{ value, label }` shape. Remove the wrapping `<div className="flex items-center justify-between">` since it only has one child after this change — keep the structure flat like DeepDiveView.

- [ ] **Step 3: Replace DeepDiveView period selector**

Replace lines 42-56 (the period selector div) with:

```tsx
import { SegmentedControl } from "../../../shared/components/SegmentedControl";

// Inside the return:
<SegmentedControl
  options={PERIODS}
  value={period}
  onChange={setPeriod}
/>
```

Note: `PERIODS` already has the correct `{ value, label }` shape.

- [ ] **Step 4: Verify it builds**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

---

## Task 4: Add close button to SignalDetail dialog

Fixes issue #3 — dialog has no visible dismiss affordance.

**Files:**
- Modify: `web/src/features/signals/components/SignalDetail.tsx`

- [ ] **Step 1: Add X close button to dialog header**

Add the `X` import from lucide-react at the top of the file:

```tsx
import { X } from "lucide-react";
```

Inside the dialog, at the very top of the content (before the Hero Score Section comment on line 41), add a sticky close button:

```tsx
<div className="sticky top-0 z-10 flex justify-end p-2">
  <button
    onClick={onClose}
    aria-label="Close signal detail"
    className="p-3 rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
  >
    <X size={20} />
  </button>
</div>
```

Note: uses `p-3` (not `p-2`) so the touch target is 20 + 12 + 12 = 44px, meeting the minimum.

Adjust the Hero Score Section to remove its top padding since the close button row now provides spacing — change its `className` `p-5` to `px-5 pb-5`.

- [ ] **Step 2: Verify it builds**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

---

## Task 5: Bump text-[10px] to text-xs across SignalCard

Fixes issue #2 for SignalCard — all `text-[10px]` labels carry critical trading info (direction badge, timestamps, price labels, risk labels).

**Files:**
- Modify: `web/src/features/signals/components/SignalCard.tsx`

- [ ] **Step 1: Bump all text-[10px] and text-[11px] to text-xs in SignalCard**

Find and replace **all** `text-[10px]` with `text-xs` in SignalCard.tsx. There are instances in:

1. Line 29: direction badge — `text-[10px]` → `text-xs`
2. Line 37: timestamp — `text-[10px]` → `text-xs`
3. Line 68: "Entry Price" label — `text-[10px]` → `text-xs`
4. Line 73: "Stop Loss" label — `text-[10px]` → `text-xs`
5. Line 78: "Take Profit 1" label — `text-[10px]` → `text-xs`
6. Line 82: "Take Profit 2" label — `text-[10px]` → `text-xs`
7. Line 91: "Risk" label — `text-[10px]` → `text-xs`
8. Line 96: "R:R" label — `text-[10px]` → `text-xs`
9. Line 107: "Status" label — `text-[10px]` → `text-xs`
10. Line 134: RRFallback "R:R" label — `text-[10px]` → `text-xs`
11. Line 155: OutcomeBadge — `text-[10px]` → `text-xs`

Also bump all `text-[11px]` to `text-xs`:
- Line 92: risk value — `text-[11px]` → `text-xs`
- Line 97: R:R value — `text-[11px]` → `text-xs`
- Line 108: status value — `text-[11px]` → `text-xs`
- Line 135: RRFallback R:R value — `text-[11px]` → `text-xs`

Simplest approach: global find-and-replace `text-[10px]` → `text-xs` and `text-[11px]` → `text-xs` within this file.

- [ ] **Step 2: Add aria-label to Newspaper icon**

At line 60, add an aria-label to the Newspaper icon:

```tsx
<Newspaper size={16} className="text-primary ml-auto flex-shrink-0" aria-label="Has correlated news" />
```

- [ ] **Step 3: Verify it builds**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

---

## Task 6: Bump text sizes in SignalDetail and fix tracking

Fixes issue #2 for SignalDetail and issue #10 (tracking-tighter on uppercase).

**Files:**
- Modify: `web/src/features/signals/components/SignalDetail.tsx`

- [ ] **Step 1: Bump all text-[10px] to text-xs in SignalDetail**

Find and replace **all** `text-[10px]` with `text-xs` in SignalDetail.tsx. There are instances at:

1. Line 43: "Overall Signal Score" label
2. Line 70: "Intelligence Components" heading
3. Line 102: "AI Analysis" heading
4. Line 109: "Execution Matrix" heading
5. Line 112: "Entry Range" label
6. Line 116: "Stop Loss" label (inside Execution Matrix grid)
7. Line 120: "Take Profit 1" label
8. Line 124: "Take Profit 2" label
9. Line 132: "Outcome" heading
10. Line 258: "Your Notes" heading

Simplest approach: global find-and-replace `text-[10px]` → `text-xs` within this file.

- [ ] **Step 2: Fix ScoreBar tracking**

In the `ScoreBar` component (line 159), change `tracking-tighter` to `tracking-wide`:

```tsx
// Before:
<div className="flex justify-between text-xs font-medium uppercase tracking-tighter">
// After:
<div className="flex justify-between text-xs font-medium uppercase tracking-wide">
```

- [ ] **Step 3: Add loading state to journal status buttons**

In the `JournalSection` component, add a `savingStatus` state to track which button is saving. Modify the `handleStatusChange` function and buttons:

```tsx
const [savingStatus, setSavingStatus] = useState<UserStatus | null>(null);

const handleStatusChange = async (status: UserStatus) => {
  setSavingStatus(status);
  setSaveState("saving");
  try {
    await api.patchSignalJournal(signal.id, { status });
    updateSignal(signal.id, { user_status: status });
    setSaveState("saved");
    if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
    savedTimerRef.current = setTimeout(() => setSaveState("idle"), 2000);
  } catch {
    setSaveState("idle");
  } finally {
    setSavingStatus(null);
  }
};
```

On each status button, add disabled + opacity when saving:

```tsx
<button
  key={value}
  onClick={() => handleStatusChange(value)}
  disabled={savingStatus !== null}
  className={`flex-1 min-h-[44px] text-xs font-medium rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
    savingStatus === value ? "opacity-60" : ""
  } ${
    signal.user_status === value
      ? value === "TRADED"
        ? "bg-long/20 text-long border border-long/40"
        : "bg-surface-container-highest text-on-surface border border-outline-variant/15"
      : "text-on-surface-variant border border-outline-variant/10"
  }`}
>
  {savingStatus === value ? "..." : label}
</button>
```

Note: also adds `min-h-[44px]` to fix touch targets and removes old `py-1.5`.

- [ ] **Step 4: Verify it builds**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

---

## Task 7: Bump text sizes in IndicatorAudit, ReasoningChain, PatternBadges, ConnectionStatus

Fixes issue #2 for remaining components.

**Files:**
- Modify: `web/src/features/signals/components/IndicatorAudit.tsx`
- Modify: `web/src/features/signals/components/ReasoningChain.tsx`
- Modify: `web/src/features/signals/components/PatternBadges.tsx`
- Modify: `web/src/features/signals/components/ConnectionStatus.tsx`

- [ ] **Step 1: Bump text sizes in IndicatorAudit**

Replace all `text-[10px]` with `text-xs`. Instances at lines: 77, 143.

- [ ] **Step 2: Bump text sizes and fix color-not-only in ReasoningChain**

This fixes issue #5 (color-not-only) for the reasoning chain and issue #2 (text sizes).

First, replace all `text-[10px]` with `text-xs`. Instances at lines: 102 (heading), 121 (step value).

Then, add a text-based sentiment indicator alongside the color dot. In the content `<div>` (lines 116-125), after the existing value `<span>` (the one with `text-[10px] font-mono tabular-nums text-primary`), add a **new** directional arrow span that provides meaning without relying on color alone:

```tsx
{/* NEW — add this block immediately after the existing step.value span */}
{step.sentiment && step.sentiment !== "neutral" && (
  <span className={`text-xs font-medium ${step.sentiment === "bullish" ? "text-long" : "text-short"}`}>
    {step.sentiment === "bullish" ? "\u25B2" : "\u25BC"}
  </span>
)}
```

- [ ] **Step 3: Bump text sizes in PatternBadges**

Replace all `text-[10px]` with `text-xs`. Instances at lines: 15, 39, 45.

Simplest approach: global find-and-replace `text-[10px]` → `text-xs` within this file.

- [ ] **Step 4: Bump text size in ConnectionStatus**

Replace `text-[10px]` with `text-xs` at line 9.

- [ ] **Step 5: Verify it builds**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

---

## Task 8: CalendarView — aria-labels and text sizes

Fixes issue #4 (missing aria-labels on nav arrows) and issue #2 (text sizes) for CalendarView.

**Files:**
- Modify: `web/src/features/signals/components/CalendarView.tsx`

- [ ] **Step 1: Add aria-labels to month navigation buttons**

At line 106 (prev button), add `aria-label="Previous month"`:

```tsx
<button onClick={prevMonth} aria-label="Previous month" className="text-on-surface-variant hover:text-on-surface px-2 py-1 text-lg focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">&larr;</button>
```

At line 108 (next button), add `aria-label="Next month"`:

```tsx
<button onClick={nextMonth} aria-label="Next month" className="text-on-surface-variant hover:text-on-surface px-2 py-1 text-lg focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">&rarr;</button>
```

- [ ] **Step 2: Bump text sizes**

Replace all `text-[10px]` with `text-xs` in CalendarView.tsx. The actual `text-[10px]` instances are at:
- Line 125: weekday headers
- Line 161: signal count inside day cell
- Line 162: pnl value inside day cell

Note: lines 81-98 (monthly summary grid) do NOT contain `text-[10px]` — they already use `text-xs`. Do not modify those lines.

- [ ] **Step 3: Verify it builds**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

---

## Task 9: Bump text sizes in PairDeepDive

Fixes issue #2 for PairDeepDive.

**Files:**
- Modify: `web/src/features/signals/components/PairDeepDive.tsx`

- [ ] **Step 1: Bump text sizes**

Replace all `text-[10px]` with `text-xs`. Instances at lines: 50, 63, 67, 72, 78, 116, 125, 144, 172.

Simplest approach: global find-and-replace `text-[10px]` → `text-xs` within this file.

- [ ] **Step 2: Verify it builds**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

---

## Task 10: Bump text sizes in AnalyticsView, fix gradient ID, add chart a11y

Fixes issue #2 (text sizes), issue #7 (SVG gradient ID collision), and issue #11 (no chart a11y) for AnalyticsView.

**Files:**
- Modify: `web/src/features/signals/components/AnalyticsView.tsx`

- [ ] **Step 1: Bump all text-[10px] to text-xs in AnalyticsView**

Find and replace **all** `text-[10px]` with `text-xs` in AnalyticsView.tsx. There are 12 instances across:

1. Line 76: SummaryBento "Net P&L" label
2. Line 82: SummaryBento "Win Rate" label
3. Line 88: SummaryBento "Avg R:R" label
4. Line 92: SummaryBento "Signals Resolved" label
5. Line 135: EquityCurve heading
6. Line 156: PairBreakdown heading
7. Line 183: DrawdownChart heading
8. Line 185: StreakTracker heading
9. Line 191: StreakTracker "Current" label
10. Line 195: StreakTracker "Best Win" label
11. Line 199: StreakTracker "Worst Loss" label
12. Line 208: PnlDistribution heading

Simplest approach: global find-and-replace `text-[10px]` → `text-xs` within this file.

- [ ] **Step 2: Fix gradient ID collision**

Add `useId` to the React import:

```tsx
import { useState, useId } from "react";
```

In the `EquityCurve` component, generate a unique ID:

```tsx
function EquityCurve({ data }: { data: SignalStats["equity_curve"] }) {
  const gradientId = useId();
  // ... existing code ...
```

Replace `id="chartGradient"` with `id={gradientId}` and `url(#chartGradient)` with `` url(#${gradientId}) ``:

```tsx
<linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
```

```tsx
<polygon fill={`url(#${gradientId})`} points={fillPath} />
```

- [ ] **Step 3: Add aria-label to EquityCurve SVG**

Add `role="img"` and `aria-label` to the `<svg>`:

```tsx
<svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none" role="img" aria-label={`Equity curve, current P&L ${lastVal >= 0 ? "+" : ""}${lastVal.toFixed(1)}%`}>
```

- [ ] **Step 4: Verify it builds**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

---

## Task 11: Bump text sizes in DeepDiveView, fix motion-reduce, add chart a11y

Fixes issue #2 (text sizes), issue #8 (missing motion-reduce), and issue #11 (chart a11y) for DeepDiveView.

**Files:**
- Modify: `web/src/features/signals/components/DeepDiveView.tsx`

- [ ] **Step 1: Bump all text-[10px] to text-xs in DeepDiveView**

Find and replace **all** `text-[10px]` with `text-xs` in DeepDiveView.tsx. There are 7 instances across:

1. Line 69: MetricsGrid "Performance Metrics" heading
2. Line 117: MetricCell label
3. Line 127: BestWorstTrades heading
4. Line 132: BEST badge
5. Line 143: WORST badge (this is `text-[10px]` inside the badge span)
6. Line 183: DrawdownChart heading
7. Line 208: PnlDistribution heading

Simplest approach: global find-and-replace `text-[10px]` → `text-xs` within this file.

- [ ] **Step 2: Fix motion-reduce on loading skeletons**

At line 23, change:
```tsx
<div key={i} className="h-24 bg-surface-container rounded-lg animate-pulse" />
```
to:
```tsx
<div key={i} className="h-24 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none" />
```

- [ ] **Step 3: Add aria-labels to DrawdownChart and PnlDistribution SVGs**

**DrawdownChart** — add to the `<svg>`:
```tsx
<svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none" role="img" aria-label={`Drawdown chart, max drawdown ${minVal.toFixed(1)}%`}>
```

**PnlDistribution** — add to the `<svg>`:
```tsx
<svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none" role="img" aria-label={`P&L distribution across ${data.length} buckets`}>
```

- [ ] **Step 4: Verify it builds**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

---

## Task 12: Improve empty states with icons and guidance

Fixes issue #9 — plain text empty states lack icons or actions.

**Files:**
- Modify: `web/src/features/signals/components/SignalFeed.tsx`
- Modify: `web/src/features/signals/components/AnalyticsView.tsx`
- Modify: `web/src/features/signals/components/DeepDiveView.tsx`

- [ ] **Step 1: Improve SignalFeed empty state**

Add `Radio` icon import from lucide-react. Replace the empty state paragraph (lines 61-63) with:

```tsx
import { Radio } from "lucide-react";

// In the empty state:
<div className="flex flex-col items-center gap-3 mt-12 text-center">
  <Radio size={32} className="text-outline" />
  <p className="text-on-surface-variant text-sm">
    {statusFilter === "ALL" ? "No signals in the last 24 hours" : `No ${statusFilter.toLowerCase()} signals`}
  </p>
  <p className="text-outline text-xs">Signals appear as the engine detects opportunities</p>
</div>
```

- [ ] **Step 2: Improve AnalyticsView empty state**

Add `BarChart3` icon import from lucide-react. Replace the empty state (lines 30-34) with:

```tsx
import { BarChart3 } from "lucide-react";

// In the empty state return:
<div className="p-3">
  <div className="flex flex-col items-center gap-3 mt-12 text-center">
    <BarChart3 size={32} className="text-outline" />
    <p className="text-on-surface-variant text-sm">No resolved signals yet</p>
    <p className="text-outline text-xs">Analytics will appear as signals resolve</p>
  </div>
</div>
```

- [ ] **Step 3: Improve DeepDiveView empty state**

Add `Activity` icon import from lucide-react. Replace the empty state (lines 30-36) with:

```tsx
import { Activity } from "lucide-react";

// In the empty state return:
<div className="p-3">
  <div className="flex flex-col items-center gap-3 mt-12 text-center">
    <Activity size={32} className="text-outline" />
    <p className="text-on-surface-variant text-sm">Need at least 5 resolved trades</p>
    <p className="text-outline text-xs">Deep dive metrics require more data</p>
  </div>
</div>
```

- [ ] **Step 4: Verify it builds**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

---

## Task 13: Final build verification and commit

- [ ] **Step 1: Run full TypeScript check**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 2: Run Vite build**

Run: `cd web && pnpm build`
Expected: Build succeeds

- [ ] **Step 3: Run tests**

Run: `cd web && pnpm test -- --run`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add web/src/shared/components/SegmentedControl.tsx web/src/features/signals/
git commit -m "fix(ui): signals page UX — touch targets, text sizes, a11y, empty states, chart fixes"
```
