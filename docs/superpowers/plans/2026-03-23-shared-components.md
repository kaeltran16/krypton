# Shared UI Components Extraction Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract 10 repeated UI patterns from feature components into shared reusable components, reducing duplication across ~40 files.

**Architecture:** Create focused, single-responsibility presentational components in `web/src/shared/components/`. Each component encapsulates a repeated className pattern with a clean props API. Card is the foundation — MetricCard composes it internally. All components accept `className` for escape-hatch customization.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v3, Vitest

**Parallelization:** Task 1 (Card) must complete first since Tasks 4 (MetricCard) and 6 (CollapsibleSection) compose it. All other tasks (2, 3, 5, 7, 8, 9, 10) are fully independent and can run in parallel with each other and with Task 1.

---

## File Structure

All new files go in `web/src/shared/components/`:

| File | Responsibility |
|------|---------------|
| `Card.tsx` | Base card container — surface background, border, padding, optional left accent |
| `Badge.tsx` | Colored pill label — direction, status, outcome indicators |
| `ProgressBar.tsx` | Horizontal bar with percentage fill and optional glow |
| `MetricCard.tsx` | Label + bold value stat display (composes Card) |
| `Skeleton.tsx` | Animated loading placeholder |
| `CollapsibleSection.tsx` | Expandable section with chevron toggle (composes Card) |
| `PillSelect.tsx` | Generic toggle pill button group (promoted from SettingsPage) |
| `ParamRow.tsx` | Label-value horizontal row for key/value displays |
| `FormField.tsx` | Uppercase label wrapper for form inputs |
| `SectionLabel.tsx` | Uppercase section heading |

Tests go as sibling files (e.g. `Card.test.tsx`) to match existing convention (`SegmentedControl.test.tsx`).

---

### Task 1: Card Component

**Files:**
- Create: `web/src/shared/components/Card.tsx`
- Create: `web/src/shared/components/Card.test.tsx`
- Modify: `web/src/features/settings/components/SettingsPage.tsx`
- Modify: `web/src/features/system/components/SystemDiagnostics.tsx`
- Modify: `web/src/features/backtest/components/BacktestResults.tsx`
- Modify: `web/src/features/backtest/components/BacktestCompare.tsx`
- Modify: `web/src/features/ml/components/TrainingTab.tsx`
- Modify: `web/src/features/ml/components/HistoryTab.tsx`
- Modify: `web/src/features/ml/components/ResultsTab.tsx`
- Modify: `web/src/features/ml/components/SetupTab.tsx`
- Modify: `web/src/features/ml/components/shared.tsx`
- Modify: `web/src/features/signals/components/AnalyticsView.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/src/shared/components/Card.test.tsx
import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Card } from "./Card";

describe("Card", () => {
  it("renders children with default styling", () => {
    const { container } = render(<Card>Hello</Card>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("bg-surface-container");
    expect(el.className).toContain("rounded-lg");
  });

  it("applies padding variants", () => {
    const { container } = render(<Card padding="sm">Content</Card>);
    expect(container.firstElementChild?.className).toContain("p-3");
  });

  it("applies surface variant", () => {
    const { container } = render(<Card variant="low">Content</Card>);
    expect(container.firstElementChild?.className).toContain("bg-surface-container-low");
  });

  it("renders left accent border", () => {
    const { container } = render(<Card accent="primary">Content</Card>);
    expect(container.firstElementChild?.className).toContain("border-l-2");
    expect(container.firstElementChild?.className).toContain("border-l-primary");
  });

  it("merges custom className", () => {
    const { container } = render(<Card className="overflow-hidden">Content</Card>);
    expect(container.firstElementChild?.className).toContain("overflow-hidden");
  });

  it("renders as section when asSection is true", () => {
    const { container } = render(<Card asSection>Content</Card>);
    expect(container.querySelector("section")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/shared/components/Card.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Write the component**

```tsx
// web/src/shared/components/Card.tsx
import type { ReactNode } from "react";

type Variant = "default" | "low" | "high" | "highest" | "lowest";
type Padding = "none" | "sm" | "md" | "lg";
type Accent = "primary" | "long" | "short" | "error" | "tertiary";

interface CardProps {
  children: ReactNode;
  variant?: Variant;
  padding?: Padding;
  accent?: Accent;
  border?: boolean;
  asSection?: boolean;
  className?: string;
}

const variantMap: Record<Variant, string> = {
  default: "bg-surface-container",
  low: "bg-surface-container-low",
  high: "bg-surface-container-high",
  highest: "bg-surface-container-highest",
  lowest: "bg-surface-container-lowest",
};

const paddingMap: Record<Padding, string> = {
  none: "",
  sm: "p-3",
  md: "p-4",
  lg: "p-5",
};

const accentMap: Record<Accent, string> = {
  primary: "border-l-primary",
  long: "border-l-long",
  short: "border-l-short",
  error: "border-l-error",
  tertiary: "border-l-tertiary-dim",
};

export function Card({
  children,
  variant = "default",
  padding = "md",
  accent,
  border = true,
  asSection = false,
  className = "",
}: CardProps) {
  const Tag = asSection ? "section" : "div";
  return (
    <Tag
      className={[
        variantMap[variant],
        "rounded-lg",
        border ? "border border-outline-variant/10" : "",
        paddingMap[padding],
        accent ? `border-l-2 ${accentMap[accent]}` : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </Tag>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/shared/components/Card.test.tsx`
Expected: PASS

- [ ] **Step 5: Replace usages in consumer files**

**Pattern:** Replace `<div className="bg-surface-container rounded-lg border border-outline-variant/10 p-4">` with `<Card>`, and `<section className="bg-surface-container border border-outline-variant/10 rounded-lg p-4">` with `<Card asSection>`.

**SettingsPage.tsx** — Replace local `SettingsCard` with shared `Card`:
```tsx
// Before (lines 22-31):
function SettingsCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-surface-container border border-outline-variant/10 rounded-lg p-4">
      <h3 className="font-headline text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant mb-3">
        {title}
      </h3>
      {children}
    </section>
  );
}

// After:
import { Card } from "../../../shared/components/Card";

function SettingsCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card asSection>
      <h3 className="font-headline text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant mb-3">
        {title}
      </h3>
      {children}
    </Card>
  );
}
```
Also replace the standalone `<section className="bg-surface-container border border-outline-variant/10 rounded-lg p-4">` at line 213 with `<Card asSection>`.

**SystemDiagnostics.tsx** — Replace card containers at lines 83, 113, 163, 203 with `<Card>` variants.

**BacktestResults.tsx** — Replace card containers at lines 160, 240, 254 with `<Card>`.

**TrainingTab.tsx** — Replace card containers at lines 73, 102, 139, 158, 168 with `<Card padding="sm">`.

**AnalyticsView.tsx** — Replace card containers at lines 92, 186, 230, 254 with `<Card>`.

**BacktestCompare.tsx** — Replace card containers at lines 61, 125, 246, 287 with `<Card>`.

**HistoryTab.tsx** — Replace card containers at lines 20, 56 with `<Card>`.

**ResultsTab.tsx** — Replace card containers at lines 36, 116, 125, 160, 186, 262, 289 with `<Card>`.

**SetupTab.tsx** — Replace card container at line 297 with `<Card>`.

**ml/shared.tsx** — Replace `SettingsSection`'s inner div with `<Card>`.

- [ ] **Step 6: Verify build**

Run: `cd web && npx vitest run && pnpm build`
Expected: All tests pass, build succeeds

---

### Task 2: Badge Component

**Files:**
- Create: `web/src/shared/components/Badge.tsx`
- Create: `web/src/shared/components/Badge.test.tsx`
- Modify: `web/src/features/signals/components/SignalCard.tsx`
- Modify: `web/src/features/home/components/RecentSignals.tsx`
- Modify: `web/src/features/home/components/HomeView.tsx`
- Modify: `web/src/features/backtest/components/BacktestResults.tsx`
- Modify: `web/src/features/signals/components/AnalyticsView.tsx`
- Modify: `web/src/features/signals/components/PatternBadges.tsx`
- Modify: `web/src/features/ml/components/shared.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/src/shared/components/Badge.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Badge } from "./Badge";

describe("Badge", () => {
  it("renders children", () => {
    render(<Badge color="long">LONG</Badge>);
    expect(screen.getByText("LONG")).toBeTruthy();
  });

  it("applies color classes for long", () => {
    const { container } = render(<Badge color="long">LONG</Badge>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("bg-long/");
    expect(el.className).toContain("text-long");
  });

  it("applies color classes for short", () => {
    const { container } = render(<Badge color="short">SHORT</Badge>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("text-short");
  });

  it("renders with border when border prop is true", () => {
    const { container } = render(<Badge color="primary" border>Test</Badge>);
    expect(container.firstElementChild?.className).toContain("border");
  });

  it("renders pill shape", () => {
    const { container } = render(<Badge color="long" pill>Test</Badge>);
    expect(container.firstElementChild?.className).toContain("rounded-full");
  });

  it("renders default rounded shape", () => {
    const { container } = render(<Badge color="long">Test</Badge>);
    expect(container.firstElementChild?.className).toContain("rounded");
    expect(container.firstElementChild?.className).not.toContain("rounded-full");
  });

  it("applies aria-label when provided", () => {
    render(<Badge color="long" aria-label="Bullish bias">+</Badge>);
    expect(screen.getByLabelText("Bullish bias")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/shared/components/Badge.test.tsx`
Expected: FAIL

- [ ] **Step 3: Write the component**

```tsx
// web/src/shared/components/Badge.tsx
import type { ReactNode } from "react";

type BadgeColor = "long" | "short" | "error" | "primary" | "tertiary" | "accent" | "muted";

interface BadgeProps {
  color: BadgeColor;
  border?: boolean;
  pill?: boolean;
  weight?: "medium" | "bold";
  children: ReactNode;
  "aria-label"?: string;
  className?: string;
}

const colorMap: Record<BadgeColor, { bg: string; text: string; border: string }> = {
  long:     { bg: "bg-long/15",                       text: "text-long",               border: "border-long/30" },
  short:    { bg: "bg-short/15",                      text: "text-short",              border: "border-short/30" },
  error:    { bg: "bg-error/15",                      text: "text-error",              border: "border-error/30" },
  primary:  { bg: "bg-primary/15",                    text: "text-primary",            border: "border-primary/30" },
  tertiary: { bg: "bg-tertiary-dim/15",               text: "text-tertiary-dim",       border: "border-tertiary-dim/30" },
  accent:   { bg: "bg-accent/15",                     text: "text-primary",            border: "border-accent/30" },
  muted:    { bg: "bg-surface-container-highest",     text: "text-on-surface-variant", border: "border-outline-variant/30" },
};

export function Badge({
  color,
  border = false,
  pill = false,
  weight = "bold",
  children,
  "aria-label": ariaLabel,
  className = "",
}: BadgeProps) {
  const c = colorMap[color];
  return (
    <span
      aria-label={ariaLabel}
      className={[
        "inline-flex items-center text-xs px-1.5 py-0.5",
        weight === "medium" ? "font-medium" : "font-bold",
        c.bg,
        c.text,
        pill ? "rounded-full" : "rounded",
        border ? `border ${c.border}` : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </span>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/shared/components/Badge.test.tsx`
Expected: PASS

- [ ] **Step 5: Replace usages in consumer files**

**SignalCard.tsx** — Replace direction badge (lines 30-36):
```tsx
// Before:
<span className={`text-xs px-2 py-0.5 rounded-full font-bold border ${
  isLong ? "bg-long/20 text-long border-long/30" : "bg-short/20 text-short border-short/30"
}`}>{signal.direction} {signal.timeframe}</span>

// After:
<Badge color={isLong ? "long" : "short"} border pill className="px-2">
  {signal.direction} {signal.timeframe}
</Badge>
```
Also replace `OutcomeBadge` function (lines 142-161) to use `<Badge>` internally.

**RecentSignals.tsx** — Replace `OUTCOME_BADGE` color map (lines 8-14) and badge rendering with `<Badge>`.

**HomeView.tsx** — Replace PnL badge (lines 66-69) and position direction badge (lines 150-152) with `<Badge>`.

**BacktestResults.tsx** — Replace `OutcomeBadge` (lines 448-459), trade direction badges (lines 387-393), and pattern badges (lines 433-441) with `<Badge>`.

**AnalyticsView.tsx** — Replace BEST/WORST badges with `<Badge>`.

**PatternBadges.tsx** — Replace bias color logic (lines 46-51) with `<Badge>`.

**ml/shared.tsx** — Replace `StatusBadge` (lines 64-80) to use `<Badge>` internally.

- [ ] **Step 6: Verify build**

Run: `cd web && npx vitest run && pnpm build`
Expected: All tests pass, build succeeds

---

### Task 3: ProgressBar Component

**Files:**
- Create: `web/src/shared/components/ProgressBar.tsx`
- Create: `web/src/shared/components/ProgressBar.test.tsx`
- Modify: `web/src/features/signals/components/SignalCard.tsx`
- Modify: `web/src/features/signals/components/SignalDetail.tsx`
- Modify: `web/src/features/signals/components/IndicatorAudit.tsx`
- Modify: `web/src/features/system/components/SystemDiagnostics.tsx`
- Modify: `web/src/features/backtest/components/BacktestResults.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/src/shared/components/ProgressBar.test.tsx
import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ProgressBar } from "./ProgressBar";

describe("ProgressBar", () => {
  it("renders with correct width style", () => {
    const { container } = render(<ProgressBar value={75} />);
    const inner = container.querySelector("[role=progressbar] > div") ?? container.querySelector("div > div");
    expect(inner?.getAttribute("style")).toContain("width: 75%");
  });

  it("clamps value to 0-100", () => {
    const { container } = render(<ProgressBar value={150} />);
    const inner = container.querySelector("div > div");
    expect(inner?.getAttribute("style")).toContain("width: 100%");
  });

  it("applies custom color class", () => {
    const { container } = render(<ProgressBar value={50} color="bg-error" />);
    const inner = container.querySelector("div > div");
    expect(inner?.className).toContain("bg-error");
  });

  it("has progressbar role with aria attributes", () => {
    const { container } = render(<ProgressBar value={60} label="Score" />);
    const bar = container.querySelector("[role=progressbar]");
    expect(bar).toBeTruthy();
    expect(bar?.getAttribute("aria-valuenow")).toBe("60");
    expect(bar?.getAttribute("aria-label")).toBe("Score");
  });

  it("applies glow shadow when glow is true", () => {
    const { container } = render(<ProgressBar value={50} glow />);
    const inner = container.querySelector("div > div");
    expect(inner?.className).toContain("shadow-primary/40");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/shared/components/ProgressBar.test.tsx`
Expected: FAIL

- [ ] **Step 3: Write the component**

```tsx
// web/src/shared/components/ProgressBar.tsx
interface ProgressBarProps {
  value: number;
  color?: string;
  glow?: boolean;
  height?: "sm" | "md";
  label?: string;
  track?: string;
  className?: string;
}

export function ProgressBar({
  value,
  color = "bg-primary",
  glow = false,
  height = "md",
  label,
  track = "bg-surface-container-lowest",
  className = "",
}: ProgressBarProps) {
  const clamped = Math.min(Math.max(value, 0), 100);
  const h = height === "sm" ? "h-1" : "h-1.5";

  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      className={`${h} w-full ${track} rounded-full overflow-hidden ${className}`}
    >
      <div
        className={[
          "h-full rounded-full transition-all",
          color,
          glow ? "shadow-[0_0_8px] shadow-primary/40" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/shared/components/ProgressBar.test.tsx`
Expected: PASS

- [ ] **Step 5: Replace usages in consumer files**

**SignalCard.tsx** — Replace score bar (lines 46-51):
```tsx
// Before:
<div className="w-16 h-1 bg-surface-container-lowest mt-1 rounded-full overflow-hidden ml-auto">
  <div className="h-full bg-primary rounded-full shadow-[0_0_8px_rgba(105,218,255,0.4)]"
    style={{ width: `${Math.min(Math.max(signal.final_score, 0), 100)}%` }} />
</div>

// After:
<ProgressBar value={signal.final_score} height="sm" glow className="w-16 mt-1 ml-auto" />
```

**SignalDetail.tsx** — Replace `ScoreBar` helper with `<ProgressBar>` using `track="bg-surface-container-highest"`.

**IndicatorAudit.tsx** — Replace indicator bars (lines 89-101) with `<ProgressBar>`. Keep the `RegimeBar` multi-segment variant as-is (it's a unique stacked bar, not a simple progress bar).

**SystemDiagnostics.tsx** — Replace DB pool bar (lines 250-252) and freshness bars (lines 318-322) with `<ProgressBar>`.

**BacktestResults.tsx** — Replace loading progress bar (lines 21-23) with `<ProgressBar>`.

**RiskPage.tsx** — Replace progress bars at lines 315, 362, 456 with `<ProgressBar>`. Use dynamic `color` prop based on status (e.g. `color={status === "OK" ? "bg-tertiary-dim" : status === "WARNING" ? "bg-primary" : "bg-error"}`).

- [ ] **Step 6: Verify build**

Run: `cd web && npx vitest run && pnpm build`
Expected: All tests pass, build succeeds

---

### Task 4: MetricCard Component

**Files:**
- Create: `web/src/shared/components/MetricCard.tsx`
- Create: `web/src/shared/components/MetricCard.test.tsx`
- Modify: `web/src/features/system/components/SystemDiagnostics.tsx`
- Modify: `web/src/features/home/components/HomeView.tsx`
- Modify: `web/src/features/backtest/components/BacktestResults.tsx`
- Modify: `web/src/features/signals/components/AnalyticsView.tsx`
- Modify: `web/src/features/signals/components/CalendarView.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/src/shared/components/MetricCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MetricCard } from "./MetricCard";

describe("MetricCard", () => {
  it("renders label and value", () => {
    render(<MetricCard label="Win Rate" value="65%" />);
    expect(screen.getByText("Win Rate")).toBeTruthy();
    expect(screen.getByText("65%")).toBeTruthy();
  });

  it("applies custom value color", () => {
    render(<MetricCard label="PnL" value="+5%" color="text-long" />);
    const valueEl = screen.getByText("+5%");
    expect(valueEl.className).toContain("text-long");
  });

  it("renders label with uppercase styling", () => {
    render(<MetricCard label="Score" value="80" />);
    expect(screen.getByText("Score")).toBeTruthy();
    expect(screen.getByText("80")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/shared/components/MetricCard.test.tsx`
Expected: FAIL

- [ ] **Step 3: Write the component**

```tsx
// web/src/shared/components/MetricCard.tsx
import { Card } from "./Card";
import type { ComponentProps } from "react";

type Accent = ComponentProps<typeof Card>["accent"];

interface MetricCardProps {
  label: string;
  value: string | number;
  color?: string;
  size?: "sm" | "md" | "lg";
  accent?: Accent;
  className?: string;
}

const sizeMap = {
  sm: "text-sm",
  md: "text-lg",
  lg: "text-2xl",
};

export function MetricCard({
  label,
  value,
  color = "text-on-surface",
  size = "sm",
  accent,
  className = "",
}: MetricCardProps) {
  return (
    <Card variant="low" padding="sm" border={false} accent={accent} className={className}>
      <p className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">
        {label}
      </p>
      <p className={`font-headline font-bold tabular-nums mt-1 ${sizeMap[size]} ${color}`}>
        {value}
      </p>
    </Card>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/shared/components/MetricCard.test.tsx`
Expected: PASS

- [ ] **Step 5: Replace usages in consumer files**

**SystemDiagnostics.tsx** — Delete local `MetricCard` (lines 201-208) and import from shared. The API is identical.

**HomeView.tsx PortfolioStrip** — Replace the grid items (lines 89-106) with `<MetricCard>` instances.

**BacktestResults.tsx StatsStrip** — Replace stat items (lines 112-118) with `<MetricCard accent="primary">` to get the left accent border.

**AnalyticsView.tsx** — Replace stat grid items in summary bento and per-timeframe sections.

**CalendarView.tsx** — Replace summary stat grid items (lines 100-120).

- [ ] **Step 6: Verify build**

Run: `cd web && npx vitest run && pnpm build`
Expected: All tests pass, build succeeds

---

### Task 5: Skeleton Component

**Files:**
- Create: `web/src/shared/components/Skeleton.tsx`
- Create: `web/src/shared/components/Skeleton.test.tsx`
- Modify: `web/src/features/settings/components/SettingsPage.tsx`
- Modify: `web/src/features/settings/components/RiskPage.tsx`
- Modify: `web/src/features/alerts/components/AlertList.tsx`
- Modify: `web/src/features/alerts/components/AlertHistoryList.tsx`
- Modify: `web/src/features/home/components/HomeView.tsx`
- Modify: `web/src/features/signals/components/AnalyticsView.tsx`
- Modify: `web/src/features/signals/components/CalendarView.tsx`
- Modify: `web/src/features/news/components/NewsFeed.tsx`
- Modify: `web/src/features/system/components/SystemDiagnostics.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/src/shared/components/Skeleton.test.tsx
import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Skeleton } from "./Skeleton";

describe("Skeleton", () => {
  it("renders with default height", () => {
    const { container } = render(<Skeleton />);
    const el = container.firstElementChild!;
    expect(el.className).toContain("animate-pulse");
    expect(el.className).toContain("bg-surface-container");
    expect(el.className).toContain("rounded-lg");
  });

  it("applies custom height", () => {
    const { container } = render(<Skeleton height="h-28" />);
    expect(container.firstElementChild?.className).toContain("h-28");
  });

  it("renders multiple skeletons when count > 1", () => {
    const { container } = render(<Skeleton count={3} height="h-20" />);
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBe(3);
  });

  it("respects reduced motion", () => {
    const { container } = render(<Skeleton />);
    expect(container.firstElementChild?.className).toContain("motion-reduce:animate-none");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/shared/components/Skeleton.test.tsx`
Expected: FAIL

- [ ] **Step 3: Write the component**

```tsx
// web/src/shared/components/Skeleton.tsx
interface SkeletonProps {
  height?: string;
  count?: number;
  border?: boolean;
  className?: string;
}

export function Skeleton({
  height = "h-20",
  count = 1,
  border = true,
  className = "",
}: SkeletonProps) {
  const base = [
    height,
    "bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none",
    border ? "border border-outline-variant/10" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  if (count === 1) return <div className={base} />;

  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className={base} />
      ))}
    </>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/shared/components/Skeleton.test.tsx`
Expected: PASS

- [ ] **Step 5: Replace usages in consumer files**

**SettingsPage.tsx** — Replace loading state (lines 106-111):
```tsx
// Before:
<div className="h-28 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
<div className="h-20 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
<div className="h-24 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />

// After:
<Skeleton height="h-28" />
<Skeleton height="h-20" />
<Skeleton height="h-24" />
```

**AlertList.tsx** — Replace skeleton loop (lines 52-56) with `<Skeleton count={3} />`.

**HomeView.tsx** — Replace all `animate-pulse` divs (lines 51, 116, 237, 282) with `<Skeleton>`.

**AnalyticsView.tsx** — Replace skeleton grid (lines 24-27) with `<Skeleton count={6} height="h-24" border={false} />`.

**SystemDiagnostics.tsx** — Replace local `Skeleton` function (lines 330-340) with import from shared, wrapping in a `<div className="space-y-4">` with appropriate `<Skeleton>` calls.

**AlertHistoryList.tsx** — Replace skeleton at line 43 with `<Skeleton>`.

**RiskPage.tsx** — Replace skeleton loop at line 71 with `<Skeleton count={3}>`.

**NewsFeed.tsx** — Replace skeleton loop at line 94 with `<Skeleton>`.

**CalendarView.tsx** — Replace skeletons at lines 131, 235 with `<Skeleton>`.

- [ ] **Step 6: Verify build**

Run: `cd web && npx vitest run && pnpm build`
Expected: All tests pass, build succeeds

---

### Task 6: CollapsibleSection Component

**Files:**
- Create: `web/src/shared/components/CollapsibleSection.tsx`
- Create: `web/src/shared/components/CollapsibleSection.test.tsx`
- Modify: `web/src/features/system/components/SystemDiagnostics.tsx`
- Modify: `web/src/features/backtest/components/BacktestSetup.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/src/shared/components/CollapsibleSection.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CollapsibleSection } from "./CollapsibleSection";

describe("CollapsibleSection", () => {
  it("renders title", () => {
    render(
      <CollapsibleSection title="Pipeline" summary="OK" open={false} onToggle={() => {}}>
        <p>Content</p>
      </CollapsibleSection>
    );
    expect(screen.getByText("Pipeline")).toBeTruthy();
  });

  it("shows summary when closed", () => {
    render(
      <CollapsibleSection title="Pipeline" summary="3 signals" open={false} onToggle={() => {}}>
        <p>Content</p>
      </CollapsibleSection>
    );
    expect(screen.getByText("3 signals")).toBeTruthy();
  });

  it("hides summary when open", () => {
    render(
      <CollapsibleSection title="Pipeline" summary="3 signals" open={true} onToggle={() => {}}>
        <p>Content</p>
      </CollapsibleSection>
    );
    expect(screen.queryByText("3 signals")).toBeNull();
  });

  it("shows children when open", () => {
    render(
      <CollapsibleSection title="Test" open={true} onToggle={() => {}}>
        <p>Inner content</p>
      </CollapsibleSection>
    );
    expect(screen.getByText("Inner content")).toBeTruthy();
  });

  it("hides children when closed", () => {
    render(
      <CollapsibleSection title="Test" open={false} onToggle={() => {}}>
        <p>Inner content</p>
      </CollapsibleSection>
    );
    expect(screen.queryByText("Inner content")).toBeNull();
  });

  it("calls onToggle when clicked", () => {
    const onToggle = vi.fn();
    render(
      <CollapsibleSection title="Test" open={false} onToggle={onToggle}>
        <p>Content</p>
      </CollapsibleSection>
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onToggle).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/shared/components/CollapsibleSection.test.tsx`
Expected: FAIL

- [ ] **Step 3: Write the component**

```tsx
// web/src/shared/components/CollapsibleSection.tsx
import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Card } from "./Card";

interface CollapsibleSectionProps {
  title: string;
  summary?: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}

export function CollapsibleSection({
  title,
  summary,
  open,
  onToggle,
  children,
}: CollapsibleSectionProps) {
  return (
    <Card padding="none" className="overflow-hidden">
      <button
        aria-expanded={open}
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 min-h-[44px] hover:bg-surface-container-highest transition-colors"
      >
        <div className="text-left min-w-0">
          <span className="text-[11px] font-headline font-bold text-primary uppercase tracking-widest">
            {title}
          </span>
          {!open && summary && (
            <p className="text-[10px] text-on-surface-variant truncate mt-0.5">
              {summary}
            </p>
          )}
        </div>
        <ChevronDown
          size={16}
          className={`text-on-surface-variant shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="px-4 pb-4 pt-1">{children}</div>}
    </Card>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/shared/components/CollapsibleSection.test.tsx`
Expected: PASS

- [ ] **Step 5: Replace usages in consumer files**

**SystemDiagnostics.tsx** — Delete local `Section` component (lines 149-180). Import `CollapsibleSection` from shared. Replace all `<Section>` usages (lines 380-394) with `<CollapsibleSection>`.

**BacktestSetup.tsx** — If there's a local collapsible section pattern, replace with `<CollapsibleSection>`.

- [ ] **Step 6: Verify build**

Run: `cd web && npx vitest run && pnpm build`
Expected: All tests pass, build succeeds

---

### Task 7: PillSelect Component

**Files:**
- Create: `web/src/shared/components/PillSelect.tsx`
- Create: `web/src/shared/components/PillSelect.test.tsx`
- Modify: `web/src/features/settings/components/SettingsPage.tsx`
- Modify: `web/src/features/alerts/components/AlertForm.tsx`
- Modify: `web/src/features/backtest/components/BacktestResults.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/src/shared/components/PillSelect.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { PillSelect } from "./PillSelect";

vi.mock("../lib/haptics", () => ({ hapticTap: vi.fn() }));

describe("PillSelect", () => {
  it("renders all options", () => {
    render(
      <PillSelect options={["A", "B", "C"]} selected="A" onToggle={() => {}} />
    );
    expect(screen.getByText("A")).toBeTruthy();
    expect(screen.getByText("B")).toBeTruthy();
    expect(screen.getByText("C")).toBeTruthy();
  });

  it("highlights active option", () => {
    render(
      <PillSelect options={["A", "B"]} selected="A" onToggle={() => {}} />
    );
    expect(screen.getByText("A").className).toContain("text-primary");
    expect(screen.getByText("B").className).toContain("text-on-surface-variant");
  });

  it("calls onToggle with clicked value", () => {
    const onToggle = vi.fn();
    render(
      <PillSelect options={["A", "B"]} selected="A" onToggle={onToggle} />
    );
    fireEvent.click(screen.getByText("B"));
    expect(onToggle).toHaveBeenCalledWith("B");
  });

  it("supports multi-select", () => {
    render(
      <PillSelect options={["A", "B", "C"]} selected={["A", "C"]} onToggle={() => {}} multi />
    );
    expect(screen.getByText("A").className).toContain("text-primary");
    expect(screen.getByText("B").className).toContain("text-on-surface-variant");
    expect(screen.getByText("C").className).toContain("text-primary");
  });

  it("uses custom renderLabel", () => {
    render(
      <PillSelect options={["X"]} selected="X" onToggle={() => {}} renderLabel={(v) => `Label-${v}`} />
    );
    expect(screen.getByText("Label-X")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/shared/components/PillSelect.test.tsx`
Expected: FAIL

- [ ] **Step 3: Write the component**

```tsx
// web/src/shared/components/PillSelect.tsx
import { hapticTap } from "../lib/haptics";

interface PillSelectProps<T extends string | number> {
  options: readonly T[];
  selected: T | readonly T[];
  onToggle: (value: T) => void;
  multi?: boolean;
  renderLabel?: (value: T) => string;
  size?: "sm" | "md";
  equalWidth?: boolean;
  wrap?: boolean;
  className?: string;
}

export function PillSelect<T extends string | number>({
  options,
  selected,
  onToggle,
  multi = false,
  renderLabel,
  size = "md",
  equalWidth = false,
  wrap = false,
  className = "",
}: PillSelectProps<T>) {
  const isActive = (v: T) =>
    multi ? (selected as readonly T[]).includes(v) : selected === v;

  const sizeStyles = size === "sm"
    ? "px-3 py-1.5 text-xs min-h-[36px]"
    : "px-4 min-h-[44px] py-2 text-sm";

  const gapClass = size === "sm" ? "gap-1.5" : "gap-3";

  return (
    <div className={`flex ${wrap ? "flex-wrap" : ""} ${gapClass} ${className}`}>
      {options.map((opt) => (
        <button
          key={String(opt)}
          type="button"
          onClick={() => {
            hapticTap();
            onToggle(opt);
          }}
          className={[
            sizeStyles,
            equalWidth ? "flex-1" : "",
            "font-medium rounded-lg border transition-colors",
            "focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none",
            isActive(opt)
              ? "bg-primary/15 text-primary border-primary/30 font-bold"
              : size === "sm"
                ? "bg-transparent text-on-surface-variant border-outline-variant/30"
                : "bg-surface-container-lowest text-on-surface-variant border-transparent",
          ].join(" ")}
        >
          {renderLabel ? renderLabel(opt) : String(opt)}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/shared/components/PillSelect.test.tsx`
Expected: PASS — note: `hapticTap` may need mocking. If it fails on import, add a mock in the test setup or use `vi.mock("../lib/haptics", () => ({ hapticTap: vi.fn() }))`.

- [ ] **Step 5: Replace usages in consumer files**

**SettingsPage.tsx** — Delete local `PillSelect` component (lines 35-68). Import from shared. Add `equalWidth` prop to usages that currently have `flex-1` buttons (the settings toggles).

**AlertForm.tsx** — Replace inline pill button loops (lines 123-138 and 251-267) with `<PillSelect size="sm" wrap>`.

**BacktestResults.tsx** — Replace filter pill buttons (lines 322-351). The `pill()` helper and inline buttons become `<PillSelect size="sm" wrap>` instances. This requires slight restructuring since the current pills are in one continuous flex row with dividers — keep the dividers between PillSelect groups.

- [ ] **Step 6: Verify build**

Run: `cd web && npx vitest run && pnpm build`
Expected: All tests pass, build succeeds

---

### Task 8: ParamRow Component

**Files:**
- Create: `web/src/shared/components/ParamRow.tsx`
- Create: `web/src/shared/components/ParamRow.test.tsx`
- Modify: `web/src/features/engine/components/ParameterRow.tsx`
- Modify: `web/src/features/system/components/SystemDiagnostics.tsx`
- Modify: `web/src/features/backtest/components/BacktestResults.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/src/shared/components/ParamRow.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ParamRow } from "./ParamRow";

describe("ParamRow", () => {
  it("renders label and value", () => {
    render(<ParamRow label="RSI" value="65.2" />);
    expect(screen.getByText("RSI")).toBeTruthy();
    expect(screen.getByText("65.2")).toBeTruthy();
  });

  it("renders border by default", () => {
    const { container } = render(<ParamRow label="Test" value="42" />);
    expect(container.firstElementChild?.className).toContain("border-b");
  });

  it("omits border when last is true", () => {
    const { container } = render(<ParamRow label="Test" value="42" last />);
    expect(container.firstElementChild?.className).not.toContain("border-b");
  });

  it("accepts ReactNode as value", () => {
    render(<ParamRow label="Status" value={<span data-testid="custom">OK</span>} />);
    expect(screen.getByTestId("custom")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/shared/components/ParamRow.test.tsx`
Expected: FAIL

- [ ] **Step 3: Write the component**

```tsx
// web/src/shared/components/ParamRow.tsx
import type { ReactNode } from "react";

interface ParamRowProps {
  label: string;
  value: ReactNode;
  last?: boolean;
  className?: string;
}

export function ParamRow({ label, value, last = false, className = "" }: ParamRowProps) {
  return (
    <div
      className={[
        "flex items-center justify-between px-3 py-2",
        last ? "" : "border-b border-outline-variant/10",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="text-xs text-on-surface-variant">{label}</span>
      <span className="text-xs font-mono text-on-surface">{value}</span>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/shared/components/ParamRow.test.tsx`
Expected: PASS

- [ ] **Step 5: Replace usages in consumer files**

**ParameterRow.tsx** — Refactor to use shared `ParamRow` internally. Keep the `SourceBadge` as part of the value prop. Note: ParameterRow uses legacy color tokens (`text-muted`, `border-border`, `text-foreground`) — also fix these to use M3 tokens (`text-on-surface-variant`, `border-outline-variant`, `text-on-surface`) as part of this replacement.

**SystemDiagnostics.tsx ResourcesSection** — Replace the label/value rows (lines 239-261) with `<ParamRow>`.

**BacktestResults.tsx PairBreakdown** — Replace the 2-col grid rows (lines 162-171) with `<ParamRow>`.

- [ ] **Step 6: Verify build**

Run: `cd web && npx vitest run && pnpm build`
Expected: All tests pass, build succeeds

---

### Task 9: FormField Component

**Files:**
- Create: `web/src/shared/components/FormField.tsx`
- Create: `web/src/shared/components/FormField.test.tsx`
- Modify: `web/src/features/alerts/components/AlertForm.tsx`
- Modify: `web/src/features/alerts/components/QuietHoursSettings.tsx`
- Modify: `web/src/features/trading/components/OrderDialog.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/src/shared/components/FormField.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { FormField } from "./FormField";

describe("FormField", () => {
  it("renders label text", () => {
    render(
      <FormField label="Name">
        <input />
      </FormField>
    );
    expect(screen.getByText("Name")).toBeTruthy();
  });

  it("renders children (input)", () => {
    render(
      <FormField label="Email">
        <input data-testid="email-input" />
      </FormField>
    );
    expect(screen.getByTestId("email-input")).toBeTruthy();
  });

  it("applies uppercase tracking to label", () => {
    const { container } = render(
      <FormField label="Test">
        <input />
      </FormField>
    );
    const label = container.querySelector("span");
    expect(label?.className).toContain("uppercase");
    expect(label?.className).toContain("tracking-widest");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/shared/components/FormField.test.tsx`
Expected: FAIL

- [ ] **Step 3: Write the component**

```tsx
// web/src/shared/components/FormField.tsx
import type { ReactNode } from "react";

interface FormFieldProps {
  label: string;
  children: ReactNode;
  className?: string;
}

export const INPUT_STYLES =
  "w-full bg-surface-container-lowest border border-outline-variant/20 rounded px-3 py-2 text-sm min-h-[44px] focus:border-primary focus:ring-1 focus:ring-primary focus:outline-none";

export function FormField({ label, children, className = "" }: FormFieldProps) {
  return (
    <label className={className}>
      <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-1.5 mt-1 block">
        {label}
      </span>
      {children}
    </label>
  );
}
```

Also exports `INPUT_STYLES` constant so consumers can apply consistent input styling.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/shared/components/FormField.test.tsx`
Expected: PASS

- [ ] **Step 5: Replace usages in consumer files**

**AlertForm.tsx** — Delete local `labelCls`/`inputCls` constants (lines 40-41). Import `FormField` and `INPUT_STYLES`. Replace all `<label><span className={labelCls}>...` blocks with `<FormField label="...">`.

**QuietHoursSettings.tsx** — Replace label+input patterns (lines 54-71) with `<FormField>`.

**OrderDialog.tsx** — Replace label+input patterns with `<FormField>`.

- [ ] **Step 6: Verify build**

Run: `cd web && npx vitest run && pnpm build`
Expected: All tests pass, build succeeds

---

### Task 10: SectionLabel Component

**Files:**
- Create: `web/src/shared/components/SectionLabel.tsx`
- Create: `web/src/shared/components/SectionLabel.test.tsx`
- Modify: `web/src/features/settings/components/SettingsPage.tsx`
- Modify: `web/src/features/home/components/HomeView.tsx`
- Modify: `web/src/features/backtest/components/BacktestResults.tsx`
- Modify: `web/src/features/backtest/components/BacktestCompare.tsx`
- Modify: `web/src/features/backtest/components/BacktestSetup.tsx`
- Modify: `web/src/features/signals/components/AnalyticsView.tsx`
- Modify: `web/src/features/ml/components/ResultsTab.tsx`
- Modify: `web/src/features/ml/components/shared.tsx`

- [ ] **Step 1: Write the test**

```tsx
// web/src/shared/components/SectionLabel.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { SectionLabel } from "./SectionLabel";

describe("SectionLabel", () => {
  it("renders text content", () => {
    render(<SectionLabel>Summary</SectionLabel>);
    expect(screen.getByText("Summary")).toBeTruthy();
  });

  it("uses uppercase tracking styling", () => {
    const { container } = render(<SectionLabel>Test</SectionLabel>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("uppercase");
    expect(el.className).toContain("tracking-wider");
  });

  it("renders as h3 by default", () => {
    const { container } = render(<SectionLabel>Test</SectionLabel>);
    expect(container.querySelector("h3")).toBeTruthy();
  });

  it("renders as custom heading level", () => {
    const { container } = render(<SectionLabel as="h2">Test</SectionLabel>);
    expect(container.querySelector("h2")).toBeTruthy();
    expect(container.querySelector("h3")).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/shared/components/SectionLabel.test.tsx`
Expected: FAIL

- [ ] **Step 3: Write the component**

```tsx
// web/src/shared/components/SectionLabel.tsx
import type { ReactNode } from "react";

interface SectionLabelProps {
  children: ReactNode;
  as?: "h2" | "h3" | "h4";
  color?: "default" | "primary";
  className?: string;
}

export function SectionLabel({ children, as: Tag = "h3", color = "default", className = "" }: SectionLabelProps) {
  const colorClass = color === "primary" ? "text-primary" : "text-on-surface-variant";
  return (
    <Tag
      className={`text-[10px] font-headline font-bold uppercase tracking-wider ${colorClass} px-1 mb-1.5 ${className}`}
    >
      {children}
    </Tag>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/shared/components/SectionLabel.test.tsx`
Expected: PASS

- [ ] **Step 5: Replace usages in consumer files**

**SettingsPage.tsx** — Delete local `SectionLabel` (lines 72-78), import from shared. Use `<SectionLabel color="primary">` since the existing local version uses `text-primary`.

**HomeView.tsx** — Replace `<h2 className="text-xs font-bold tracking-widest uppercase text-on-surface-variant px-1">` (lines 121, 241) with `<SectionLabel>`.

**BacktestResults.tsx** — Replace `<h3 className="text-[10px] font-headline font-bold uppercase tracking-wider mb-1.5 px-1 text-on-surface-variant">` (lines 109, 157, 239, 253, 317) with `<SectionLabel>`.

**BacktestCompare.tsx** — Replace section headings at lines 60, 124, 245, 286 with `<SectionLabel>`.

**BacktestSetup.tsx** — Replace section headings at lines 346, 371 with `<SectionLabel>`.

**AnalyticsView.tsx** — Replace section heading patterns with `<SectionLabel>`.

**ResultsTab.tsx** — Replace section headings at lines 161, 187, 290 with `<SectionLabel>`.

**ml/shared.tsx** — Replace `SettingsSection` title with `<SectionLabel>`.

- [ ] **Step 6: Verify build**

Run: `cd web && npx vitest run && pnpm build`
Expected: All tests pass, build succeeds

---

### Task 11: Final Verification and Barrel Export

**Files:**
- Create: `web/src/shared/components/index.ts`

- [ ] **Step 1: Create barrel export**

```ts
// web/src/shared/components/index.ts
export { Badge } from "./Badge";
export { Button } from "./Button";
export { Card } from "./Card";
export { CollapsibleSection } from "./CollapsibleSection";
export { Dropdown } from "./Dropdown";
export { EmptyState } from "./EmptyState";
export { FormField, INPUT_STYLES } from "./FormField";
export { Layout } from "./Layout";
export { MetricCard } from "./MetricCard";
export { ParamRow } from "./ParamRow";
export { PillSelect } from "./PillSelect";
export { ProgressBar } from "./ProgressBar";
export { SectionLabel } from "./SectionLabel";
export { SegmentedControl } from "./SegmentedControl";
export { Skeleton } from "./Skeleton";
export { SplashScreen } from "./SplashScreen";
export { SubPageShell } from "./SubPageShell";
export { TickerBar } from "./TickerBar";
export { Toggle } from "./Toggle";
export { UpdateModal } from "./UpdateModal";
```

- [ ] **Step 2: Run full test suite**

Run: `cd web && npx vitest run`
Expected: All tests pass

- [ ] **Step 3: Run production build**

Run: `cd web && pnpm build`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 4: Commit**

```bash
git add web/src/shared/components/ web/src/features/
git commit -m "refactor: extract 10 shared UI components — Card, Badge, ProgressBar, MetricCard, Skeleton, CollapsibleSection, PillSelect, ParamRow, FormField, SectionLabel"
```
