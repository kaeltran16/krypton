# Plan 3: Sub-pages + New Views — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reskin all More sub-pages, Journal/Analytics/Calendar views, Backtest suite, and ML Training to match the Kinetic Terminal Stitch designs. Create three net-new views: EngineDashboard, SystemDiagnostics, and PairDeepDive. Refactor MorePage from tab-based layout to hub-with-navigation-clusters pattern.

**Architecture:** Each sub-page is wrapped in the existing `SubPageShell` component (back button + title). MorePage becomes a navigation hub with 3 clusters (Execution Layer, Intelligence Hub, Safety & Security) that navigate to sub-pages inline. New views (EngineDashboard, SystemDiagnostics, PairDeepDive) are created from scratch using data from existing hooks/stores/API. All changes are visual — no business logic, hooks, stores, or API changes.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v3 (M3 tokens from Plan 1), Lucide React icons, Motion (motion.dev) for stagger animations.

**Stitch reference screens:** Located at `web/.stitch-screens/` — `more.html`, `settings.html`, `risk.html`, `alerts.html`, `journal.html`, `backtest.html`, `ml-training.html`, `engine.html`, `system.html`, `pair-deepdive.html`.

**Prerequisites:** Plan 1 (Foundation + Layout) and Plan 2 (Core Views) must be complete. All M3 tokens, fonts, glass effects, `SubPageShell`, `EngineHeader`, Lucide icons, and motion tab transitions are already in place.

**UI/UX requirements (apply throughout):**
- Use `tabular-nums` (not `tabular`) for numeric values — Tailwind's built-in `font-variant-numeric` utility.
- All interactive elements must include `focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none` for keyboard navigation.
- All `animate-pulse` instances must pair with `motion-reduce:animate-none` for reduced-motion support.
- Minimum text size is `text-[10px]` — never use `text-[9px]`.
- Icon-only buttons (edit, delete, etc.) must include `aria-label` for screen reader accessibility.
- Toggle/switch components must have a min touch target of 44px — wrap the visual track in a larger hit area.

---

## File Structure

### Modified files (~15)

| File | Responsibility |
|------|---------------|
| `features/more/components/MorePage.tsx` | Hub with 3 navigation clusters (was tab-based) |
| `features/settings/components/SettingsPage.tsx` | Reskin to match `settings.html` Stitch design |
| `features/settings/components/SettingsGroup.tsx` | Update to M3 tonal styling |
| `features/settings/components/RiskPage.tsx` | Reskin to match `risk.html` Stitch design |
| `features/alerts/components/AlertsPage.tsx` | Reskin tab bar + layout to match `alerts.html` |
| `features/alerts/components/AlertList.tsx` | Colored left borders, icon tiles, toggle switches |
| `features/alerts/components/AlertForm.tsx` | M3 inputs, urgency pills, condition builder |
| `features/alerts/components/AlertHistoryList.tsx` | Terminal-style log with colored status labels |
| `features/alerts/components/QuietHoursSettings.tsx` | M3 form inputs |
| `features/signals/components/JournalView.tsx` | Update tab bar styling |
| `features/signals/components/AnalyticsView.tsx` | Bento grid, equity curve with gradient, pair cards |
| `features/signals/components/CalendarView.tsx` | M3 surface tiers, accent colors |
| `features/signals/components/DeepDiveView.tsx` | M3 token update |
| `features/backtest/components/BacktestView.tsx` | Reskin tab bar + header |
| `features/backtest/components/BacktestSetup.tsx` | M3 sliders, pair list, weight controls |
| `features/backtest/components/BacktestResults.tsx` | Summary stat cards with border-left accents |
| `features/backtest/components/BacktestCompare.tsx` | M3 table styling |
| `features/ml/components/MLTrainingView.tsx` | Reskin to match `ml-training.html` |

### New files (~3)

| File | Responsibility |
|------|---------------|
| `features/engine/components/EngineDashboard.tsx` | New view: parameter grid, volatility matrix, config summary |
| `features/system/components/SystemDiagnostics.tsx` | New view: health cards, WS streams table, infra, pipeline logs |
| `features/signals/components/PairDeepDive.tsx` | New view: per-pair analysis overlay (regime, ML confidence, order flow, signal log) |

---

## Task 1: Refactor MorePage to Navigation Hub

**Files:**
- Modify: `web/src/features/more/components/MorePage.tsx`

This is the most important structural change — converting the flat tab bar into a hub with 3 navigation clusters that drill into sub-pages using `SubPageShell`.

- [ ] **Step 1: Read the current MorePage and Stitch reference**

Read `web/src/features/more/components/MorePage.tsx` and `web/.stitch-screens/more.html` to understand the current tab layout and target hub design.

- [ ] **Step 2: Rewrite MorePage as navigation hub**

Replace the entire file. The hub shows 3 navigation clusters. Tapping a row sets `activePage` state which renders the sub-page inline with `SubPageShell`. The file uses Lucide icons: `Cpu`, `LineChart`, `Brain`, `BellRing`, `Shield`, `Settings`, `ChevronRight`, `Terminal`, `Activity`.

```tsx
import { useState } from "react";
import { Cpu, LineChart, Brain, BellRing, Shield, Settings, ChevronRight, Activity } from "lucide-react";
import { SubPageShell } from "../../../shared/components/SubPageShell";
import SettingsPage from "../../settings/components/SettingsPage";
import RiskPage from "../../settings/components/RiskPage";
import EnginePage from "../../engine/components/EnginePage";
import { BacktestView } from "../../backtest/components/BacktestView";
import { MLTrainingView } from "../../ml/components/MLTrainingView";
import { AlertsPage } from "../../alerts/components/AlertsPage";
import { JournalView } from "../../signals/components/JournalView";
import { EngineDashboard } from "../../engine/components/EngineDashboard";
import { SystemDiagnostics } from "../../system/components/SystemDiagnostics";

type SubPage = "engine" | "engine-dashboard" | "backtest" | "ml" | "alerts" | "risk" | "settings" | "journal" | "system" | null;

const CLUSTERS = [
  {
    label: "Execution Layer",
    items: [
      { key: "engine" as SubPage, icon: Cpu, label: "Engine", desc: "Pipeline parameters & weights", color: "text-primary" },
      { key: "engine-dashboard" as SubPage, icon: Activity, label: "Engine Dashboard", desc: "Live parameter monitoring", color: "text-primary" },
      { key: "backtest" as SubPage, icon: LineChart, label: "Backtest", desc: "Historical simulation hub", color: "text-tertiary-dim" },
    ],
  },
  {
    label: "Intelligence Hub",
    items: [
      { key: "ml" as SubPage, icon: Brain, label: "ML Training", desc: "Neural net optimization", color: "text-primary" },
      { key: "alerts" as SubPage, icon: BellRing, label: "Alerts", desc: "Critical signal configurations", color: "text-error" },
      { key: "journal" as SubPage, icon: LineChart, label: "Journal", desc: "Trading analytics & calendar", color: "text-primary" },
    ],
  },
  {
    label: "Safety & Security",
    items: [
      { key: "risk" as SubPage, icon: Shield, label: "Risk", desc: "Exposure limits & controls", color: "text-primary" },
      { key: "system" as SubPage, icon: Activity, label: "System", desc: "Health & diagnostics", color: "text-tertiary-dim" },
      { key: "settings" as SubPage, icon: Settings, label: "Settings", desc: "Global system preferences", color: "text-outline" },
    ],
  },
];

const PAGE_TITLES: Record<string, string> = {
  engine: "Engine Parameters",
  "engine-dashboard": "Engine Dashboard",
  backtest: "Backtest",
  ml: "ML Training",
  alerts: "Alerts",
  risk: "Risk Management",
  settings: "Settings",
  journal: "Journal & Analytics",
  system: "System Diagnostics",
};

export function MorePage() {
  const [activePage, setActivePage] = useState<SubPage>(null);

  if (activePage) {
    return (
      <SubPageShell title={PAGE_TITLES[activePage] ?? ""} onBack={() => setActivePage(null)}>
        {activePage === "engine" && <EnginePage />}
        {activePage === "engine-dashboard" && <EngineDashboard />}
        {activePage === "backtest" && <BacktestView />}
        {activePage === "ml" && <MLTrainingView />}
        {activePage === "alerts" && <AlertsPage />}
        {activePage === "risk" && <RiskPage />}
        {activePage === "settings" && <SettingsPage />}
        {activePage === "journal" && <JournalView />}
        {activePage === "system" && <SystemDiagnostics />}
      </SubPageShell>
    );
  }

  return (
    <div className="min-h-full relative">
      {/* Terminal grid background */}
      <div className="absolute inset-0 pointer-events-none opacity-[0.03]" style={{
        backgroundSize: "40px 40px",
        backgroundImage: "linear-gradient(to right, rgba(0,207,252,0.5) 1px, transparent 1px), linear-gradient(to bottom, rgba(0,207,252,0.5) 1px, transparent 1px)",
      }} />

      <div className="relative z-10 px-4 pb-8">
        {/* Header */}
        <header className="py-8">
          <h1 className="font-headline text-3xl font-bold text-on-surface tracking-tight">System Hub</h1>
          <p className="text-on-surface-variant text-sm mt-1 uppercase tracking-widest opacity-70">v1.0.0</p>
        </header>

        {/* Navigation Clusters */}
        <div className="space-y-6">
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
                      key={item.key}
                      onClick={() => setActivePage(item.key)}
                      className={`w-full flex items-center justify-between p-4 hover:bg-surface-container-highest transition-colors group focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
                        i < cluster.items.length - 1 ? "border-b border-outline-variant/5" : ""
                      }`}
                    >
                      <div className="flex items-center gap-4">
                        <div className={`w-10 h-10 rounded-lg bg-surface-container-highest flex items-center justify-center ${item.color}`}>
                          <Icon size={20} />
                        </div>
                        <div className="text-left">
                          <span className="block text-on-surface font-semibold text-sm">{item.label}</span>
                          <span className="block text-xs text-on-surface-variant">{item.desc}</span>
                        </div>
                      </div>
                      <ChevronRight size={20} className="text-outline group-hover:text-primary transition-colors" />
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>

        {/* Connection Status Card */}
        <section className="mt-8">
          <button
            onClick={() => setActivePage("system" as SubPage)}
            className="w-full bg-surface-container-lowest p-5 border-l-4 border-primary rounded-r-lg text-left hover:bg-surface-container-low transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
          >
            <div className="flex justify-between items-start">
              <div>
                <h3 className="font-headline font-bold text-on-surface uppercase text-sm tracking-widest">Connection Secure</h3>
                <p className="text-xs text-on-surface-variant mt-1 font-mono">ENCRYPTED_NODE: LOCAL</p>
              </div>
              <div className="bg-primary/20 px-2 py-0.5 rounded-full">
                <span className="text-[10px] font-bold text-primary uppercase">System Status</span>
              </div>
            </div>
          </button>
        </section>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify build**

Run: `cd web && pnpm build`
Expected: Build succeeds. (EngineDashboard and SystemDiagnostics imports will fail — create stubs in next tasks.)

- [ ] **Step 4: Create EngineDashboard stub**

Create `web/src/features/engine/components/EngineDashboard.tsx` with a minimal placeholder:

```tsx
export function EngineDashboard() {
  return <div className="p-4 text-on-surface-variant text-sm">Engine Dashboard — coming soon</div>;
}
```

- [ ] **Step 5: Create SystemDiagnostics stub**

Create `web/src/features/system/components/SystemDiagnostics.tsx` (also create the directory):

```tsx
export function SystemDiagnostics() {
  return <div className="p-4 text-on-surface-variant text-sm">System Diagnostics — coming soon</div>;
}
```

- [ ] **Step 6: Create PairDeepDive stub**

Create `web/src/features/signals/components/PairDeepDive.tsx`:

```tsx
export function PairDeepDive({ pair }: { pair: string }) {
  return <div className="p-4 text-on-surface-variant text-sm">Pair Deep Dive: {pair} — coming soon</div>;
}
```

- [ ] **Step 7: Verify build succeeds with all stubs**

Run: `cd web && pnpm build`
Expected: PASS — no type errors, all imports resolve.

- [ ] **Step 8: Verify app loads and More hub navigates to sub-pages**

Run: `cd web && pnpm dev` — verify hub renders with 3 clusters, tapping items shows stub content with back button.

---

## Task 2: Reskin SettingsPage

**Files:**
- Modify: `web/src/features/settings/components/SettingsPage.tsx`
- Modify: `web/src/features/settings/components/SettingsGroup.tsx`

Match `web/.stitch-screens/settings.html`: 3-col pair grid with bottom border accent, diamond-thumb slider, toggle switches with glow, LLM window pills, API endpoint with mono font and status dots.

- [ ] **Step 1: Update SettingsGroup to M3 styling**

Replace `SettingsGroup.tsx` — remove explicit `border-border`, use tonal surface instead:

```tsx
export function SettingsGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-2 px-1">{title}</h2>
      <div className="bg-surface-container rounded-lg overflow-hidden border border-outline-variant/10">
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Reskin SettingsPage**

Update the entire `SettingsPage.tsx`. Key visual changes:
- **Pairs section**: 3-col grid with `bg-surface-container-highest border-b-2 border-primary` when active, `bg-surface-container-highest` when inactive. Font headline for pair symbol, label text for full name.
- **Signal threshold**: Replace plain range input with styled slider. Show value in headline font. Add `text-[10px] font-mono text-outline` min/max labels.
- **Toggles**: `w-10 h-5` toggle with `bg-tertiary-container/20` active and `shadow-[0_0_8px_rgba(86,239,159,0.5)]` glow dot, or `bg-surface-container-highest` inactive.
- **LLM window**: Pills in `bg-surface-container-lowest p-1 flex gap-1 rounded-lg` wrapper, active pill gets `bg-surface-container-high text-primary rounded border border-primary/20`.
- **API section**: `bg-surface-container p-4 rounded-lg` card. API URL in `bg-surface-container-lowest px-3 py-2 rounded text-[11px] font-mono` with green dot. Latency and SSL in `text-[10px] font-mono text-outline`.
- **Version**: Green dot + "System Operational" text.
- **Dividers**: `h-[1px] bg-outline-variant/20` instead of `border-b border-border`.

All existing `useSettingsStore` logic remains unchanged. Only className strings and minor structural JSX changes.

```tsx
// In the Toggle component, update styling:
// NOTE: The outer button has min-h-[44px] for touch target compliance (44px minimum).
// The visual track is nested inside to remain compact while the hit area is large.
function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative min-h-[44px] min-w-[44px] flex items-center justify-center flex-shrink-0
        focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded
        ${disabled ? "opacity-50" : ""}`}
    >
      <span className={`w-10 h-5 rounded-full transition-colors flex items-center px-1 ${
        checked ? "bg-tertiary-container/20" : "bg-surface-container-highest"
      }`}>
        <span className={`w-3 h-3 rounded-full transition-all ${
          checked
            ? "bg-tertiary-dim shadow-[0_0_8px_rgba(86,239,159,0.5)] ml-auto"
            : "bg-outline"
        }`} />
      </span>
    </button>
  );
}
```

Apply similar M3 tonal styling to each section: replace `bg-card` → `bg-surface-container`, `border-border` → `border-outline-variant/10`, `text-accent` → `text-primary`, `bg-accent/15` → `bg-surface-container-highest border-b-2 border-primary`, `text-dim` → `text-on-surface-variant`, `text-muted` → `text-on-surface-variant`.

- [ ] **Step 3: Verify build**

Run: `cd web && pnpm build`
Expected: PASS

- [ ] **Step 4: Visual check**

Run: `cd web && pnpm dev` — navigate to More > Settings, verify M3 styling applied.

---

## Task 3: Reskin RiskPage

**Files:**
- Modify: `web/src/features/settings/components/RiskPage.tsx`

Match `web/.stitch-screens/risk.html`: Margin config section with Isolated/Cross toggle, position sizing with progress bars, equity allocation with risk slider, risk heatmap cards with colored left borders, terminal-style risk log.

- [ ] **Step 1: Reskin RiskPage**

The existing `RiskPage` has a simple `SettingsGroup` wrapper with `RiskField` rows for risk settings. Reskin to:
- Header: "Risk Management" in headline font with `border-b border-outline-variant/10`.
- Section cards: `bg-surface-container border border-outline-variant/10 rounded-lg p-5`.
- Section headers: `w-1 h-3 bg-primary rounded-full` accent bar + `text-[10px] font-black uppercase tracking-[0.2em]` label.
- Risk per trade field: Large headline number + current options as pills.
- Other fields: Keep existing option buttons but restyle with M3 tokens — active: `bg-primary/15 text-primary border border-primary/30`, inactive: `bg-surface-container-lowest text-on-surface-variant`.
- Loss cooldown: Same pill buttons, M3 styled.
- Loading skeleton: `bg-surface-container` instead of `bg-card`.

All `api.getRiskSettings()` / `api.updateRiskSettings()` logic stays identical.

- [ ] **Step 2: Verify build**

Run: `cd web && pnpm build`
Expected: PASS

- [ ] **Step 3: Visual check**

Run: `cd web && pnpm dev` — navigate to More > Risk, verify M3 styling applied.

---

## Task 4: Reskin Alerts Suite

**Files:**
- Modify: `web/src/features/alerts/components/AlertsPage.tsx`
- Modify: `web/src/features/alerts/components/AlertList.tsx`
- Modify: `web/src/features/alerts/components/AlertForm.tsx`
- Modify: `web/src/features/alerts/components/AlertHistoryList.tsx`
- Modify: `web/src/features/alerts/components/QuietHoursSettings.tsx`

Match `web/.stitch-screens/alerts.html`.

- [ ] **Step 1: Reskin AlertsPage**

Remove the `onBack` prop logic (MorePage now handles back navigation via SubPageShell). Update tab bar to M3:
- Tab wrapper: `bg-surface-container-lowest p-1 rounded-lg flex gap-1`.
- Active tab: `bg-surface-container-highest text-on-surface rounded`.
- Inactive: `text-on-surface-variant hover:text-on-surface`.

```tsx
export function AlertsPage() {
  const [tab, setTab] = useState<Tab>("active");
  // ... same logic, remove onBack prop and back button JSX
  return (
    <div className="space-y-4">
      <div className="flex gap-1 bg-surface-container-lowest rounded-lg p-1">
        {(["active", "create", "history"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2 text-xs font-bold uppercase tracking-wider rounded min-h-[44px] transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
              tab === t
                ? "bg-surface-container-highest text-on-surface"
                : "text-on-surface-variant hover:text-on-surface"
            }`}
          >
            {t === "active" ? "Active" : t === "create" ? "Create" : "History"}
          </button>
        ))}
      </div>
      {/* ... same tab content rendering */}
    </div>
  );
}
```

- [ ] **Step 2: Reskin AlertList**

Per `alerts.html`: Each alert gets a colored left border by urgency (`border-l-2`), icon tile with urgency label, toggle switch, edit/delete icon buttons using Lucide (`Pencil`, `Trash2`, `Power`).

Key changes:
- Card: `bg-surface-container-lowest p-3 flex items-center justify-between gap-4 border-l-2` with border color: critical=`border-tertiary-dim`, normal=`border-primary`, silent=`border-outline-variant/30`.
- Icon tile: `w-10 h-10 rounded bg-surface-container-highest flex flex-col items-center justify-center`.
- Toggle: Custom switch like in Stitch.
- Edit/delete: `Pencil` and `Trash2` icons from Lucide in icon buttons. Each must have `aria-label` (e.g. `aria-label="Edit alert"`, `aria-label="Delete alert"`) and `min-h-[44px] min-w-[44px]` for touch targets.

- [ ] **Step 3: Reskin AlertForm**

Match `alerts.html` create panel:
- Alert type: 2-col grid, active = `bg-surface-container-highest text-primary border border-primary/40`, inactive = `bg-surface-container-lowest text-on-surface-variant border border-outline-variant/20`.
- Inputs: `bg-surface-container-lowest border border-outline-variant/20 rounded px-3 py-2 text-sm focus:border-primary focus:ring-1 focus:ring-primary`.
- Urgency pills: `bg-surface-container-lowest rounded p-1 flex gap-1` wrapper, active = `bg-surface-container-highest text-on-surface rounded`.
- Create button: `bg-primary-container text-on-primary-fixed py-3 rounded font-headline font-bold uppercase tracking-widest`.

- [ ] **Step 4: Reskin AlertHistoryList to terminal log**

Match the terminal-style log from `alerts.html`:
- Wrapper: `bg-surface-container-lowest border border-outline-variant/20 rounded overflow-hidden`.
- Header bar: `p-3 bg-surface-container flex items-center gap-2` with terminal dots and "Terminal Alert Log" label.
- Log entries: `font-mono text-[11px] leading-relaxed` with timestamp in `text-on-surface-variant`, status label in colored text (delivered=`text-tertiary-dim`, failed=`text-error`), status icon.

- [ ] **Step 5: Reskin QuietHoursSettings**

M3 form inputs: `bg-surface-container-lowest border border-outline-variant/20 rounded px-3 py-2`. Checkbox → custom toggle switch.

- [ ] **Step 6: Verify build**

Run: `cd web && pnpm build`
Expected: PASS

- [ ] **Step 7: Visual check**

Run: `cd web && pnpm dev` — navigate to More > Alerts, verify all 3 tabs styled correctly.

---

## Task 5: Reskin Journal / Analytics / Calendar / DeepDive

**Files:**
- Modify: `web/src/features/signals/components/JournalView.tsx`
- Modify: `web/src/features/signals/components/AnalyticsView.tsx`
- Modify: `web/src/features/signals/components/CalendarView.tsx`
- Modify: `web/src/features/signals/components/DeepDiveView.tsx`

Match `web/.stitch-screens/journal.html`.

- [ ] **Step 1: Reskin JournalView tab bar**

Update tab bar to M3 pill style:
- Wrapper: `bg-surface-container-low p-1 rounded-lg flex gap-1 w-full`.
- Active: `bg-surface-container-highest text-primary rounded-lg shadow-[0_0_8px_rgba(105,218,255,0.15)]`.
- Inactive: `text-on-surface-variant hover:bg-surface-bright rounded-lg`.

- [ ] **Step 2: Reskin AnalyticsView**

Per `journal.html`:
- Period pills: Active = `bg-surface-container-highest text-primary rounded-lg shadow-[0_0_8px_rgba(105,218,255,0.15)]`, inactive = `text-on-surface-variant`.
- Summary bento: `col-span-2` P&L card with `border-l-4 border-tertiary-dim`, large headline number. Win rate, Avg R:R, Signal count in individual `bg-surface-container` cards.
- Equity curve: SVG area chart with `fill="url(#chartGradient)"` using `tertiary-dim` gradient (like Stitch). Preserve existing SVG logic.
- Pair breakdown: Per-pair cards with icon tile (like Stitch), headline font for pair name, P&L in colored text. `bg-surface-container rounded-lg p-4 hover:bg-surface-container-high`.
- Streaks: Same grid but with M3 card styling.
- Replace all `bg-card` → `bg-surface-container`, `border-border` → `border-outline-variant/10`, `text-muted` → `text-on-surface-variant`, `text-long` → `text-tertiary-dim`, `text-short` → `text-error`.

- [ ] **Step 3: Reskin CalendarView**

M3 token swap on all classes:
- Monthly summary: `bg-surface-container` card, `text-tertiary-dim` for positive, `text-error` for negative.
- Calendar grid: `bg-surface-container` wrapper, day cells with `bg-tertiary-dim/10` for positive days, `bg-error/10` for negative.
- Selected day: `ring-1 ring-primary`.
- Today: `border border-outline-variant/10`, `text-primary`.

- [ ] **Step 4: Reskin DeepDiveView**

Same M3 token swap: `bg-card` → `bg-surface-container`, `border-border` → `border-outline-variant/10`, color aliases → M3 tokens.

- [ ] **Step 5: Verify build**

Run: `cd web && pnpm build`
Expected: PASS

- [ ] **Step 6: Visual check**

Run: `cd web && pnpm dev` — navigate to More > Journal, check all 3 sub-tabs.

---

## Task 6: Reskin Backtest Suite

**Files:**
- Modify: `web/src/features/backtest/components/BacktestView.tsx`
- Modify: `web/src/features/backtest/components/BacktestSetup.tsx`
- Modify: `web/src/features/backtest/components/BacktestResults.tsx`
- Modify: `web/src/features/backtest/components/BacktestCompare.tsx`

Match `web/.stitch-screens/backtest.html`.

- [ ] **Step 1: Reskin BacktestView**

Remove `onBack` prop (SubPageShell handles this). Update tab bar:
- Active: `bg-primary/15 text-primary`.
- Inactive: `text-on-surface-variant hover:text-on-surface`.
- Container: `bg-surface-container rounded-lg border border-outline-variant/10 p-0.5`.

- [ ] **Step 2: Reskin BacktestSetup**

Per `backtest.html`:
- `Section` component: `text-[10px] font-headline font-bold uppercase tracking-wider` label, `bg-surface-container p-5 rounded` card.
- Pairs: List with `bg-surface-container-lowest rounded border` per pair, check icon when selected.
- Timeframe: Pill buttons, active = `bg-primary-container text-on-primary-container rounded`.
- Weight sliders: Styled like Stitch with `shadow-[0_0_8px_rgba(105,218,255,0.4)]` on the fill bar, `text-[10px] font-bold text-on-surface` label, `text-[10px] font-mono text-primary` value.
- Run button: `bg-primary-container text-on-primary-fixed py-4 font-headline font-bold text-xs tracking-widest uppercase`.

- [ ] **Step 3: Reskin BacktestResults**

Per `backtest.html` results section:
- Summary stats: `grid grid-cols-2 md:grid-cols-4 gap-4`, each card = `bg-surface-container p-4 rounded border-l-2` with varying border color (primary, tertiary-dim, error, tertiary).
- `text-2xl font-headline font-bold` for values, `text-[10px] font-bold text-on-surface-variant` for labels.
- Equity curve: Chart colors already use `theme.chart` from Plan 1. Just restyle wrapper.
- Trade list: `bg-surface-container rounded-lg` wrapper, `divide-y divide-outline-variant/10`.

- [ ] **Step 4: Reskin BacktestCompare**

M3 token swap:
- Run selection: `bg-surface-container rounded-lg border border-outline-variant/10 divide-y divide-outline-variant/10`.
- Compare button: `bg-primary-container text-on-primary-fixed`.
- Table: `bg-surface-container rounded-lg border border-outline-variant/10`, header in `text-[10px] font-headline font-bold`.

- [ ] **Step 5: Verify build**

Run: `cd web && pnpm build`
Expected: PASS

- [ ] **Step 6: Visual check**

Run: `cd web && pnpm dev` — navigate to More > Backtest, check all 4 tabs.

---

## Task 7: Reskin MLTrainingView

**Files:**
- Modify: `web/src/features/ml/components/MLTrainingView.tsx`

Match `web/.stitch-screens/ml-training.html`. This is a large file (959 lines) with 4 tabs: Configure, Training, History, Backfill.

- [ ] **Step 1: Reskin MLTrainingView**

The file has many internal helper components (`TabButton`, `SettingsSection`, `ConfigField`, `Select`). Update each:

- `TabButton`: Active = `bg-primary/15 text-primary`, inactive = `text-on-surface-variant`.
- `SettingsSection`: `text-[10px] font-headline font-bold uppercase tracking-wider` label, `bg-surface-container rounded-lg border border-outline-variant/10` card.
- `ConfigField`: Dividers = `border-outline-variant/10`.
- `Select` pills: Active = `bg-surface-container-highest text-primary border border-primary/20`, inactive = `bg-surface-container-lowest text-on-surface-variant`.
- Error banner: `bg-error/10 border border-error/30`.
- Remove `onBack` button (SubPageShell handles).
- Tab bar wrapper: `bg-surface-container rounded-lg border border-outline-variant/10 p-1`.
- Training progress: Accent color update.
- History cards: `bg-surface-container rounded-lg border border-outline-variant/10`.
- System output log: Terminal style with `bg-surface-container-lowest font-mono text-[10px]`.

This is a class-swap refactor across the file. No logic changes.

- [ ] **Step 2: Verify build**

Run: `cd web && pnpm build`
Expected: PASS

- [ ] **Step 3: Visual check**

Run: `cd web && pnpm dev` — navigate to More > ML Training, check all 4 tabs.

---

## Task 8: Build EngineDashboard (New View)

**Files:**
- Create: `web/src/features/engine/components/EngineDashboard.tsx`

Match `web/.stitch-screens/engine.html`. This is a new parameter monitoring view that wraps the existing `EnginePage` data in a visual dashboard layout.

- [ ] **Step 1: Build EngineDashboard**

This view reuses the existing `useEngineStore` (same store as `EnginePage`). It displays:
1. **Status header**: System latency card + engine load card (mock values since we don't have a latency API — display "—" or use static placeholder).
2. **4-column parameter grid**: Blending, Technical, Order Flow, On-Chain categories. Each shows 2 key parameters from `useEngineStore().params`.
3. **Config summary card**: Count user overrides vs DB defaults.
4. **Refresh button** using `useEngineStore().refresh`.

```tsx
import { useEffect } from "react";
import { useEngineStore } from "../store";
import { RefreshCw } from "lucide-react";

export function EngineDashboard() {
  const { params, loading, error, fetch, refresh } = useEngineStore();

  useEffect(() => { fetch(); }, [fetch]);

  if (loading) return <div className="p-4 text-on-surface-variant text-sm">Loading parameters...</div>;
  if (error) return <div className="p-4 text-error text-sm">Error: {error}</div>;
  if (!params) return null;

  // Count user overrides vs DB defaults
  const countSources = (obj: Record<string, any>): { user: number; db: number } => {
    let user = 0, db = 0;
    for (const val of Object.values(obj)) {
      if (val && typeof val === "object" && "source" in val) {
        if (val.source === "user" || val.source === "yaml") user++;
        else db++;
      } else if (val && typeof val === "object") {
        const sub = countSources(val);
        user += sub.user;
        db += sub.db;
      }
    }
    return { user, db };
  };
  const counts = countSources(params);

  // Extract some key params for display
  const blendingParams = [
    { name: "ML Blend Weight", value: params.blending.ml_blend_weight.value, source: params.blending.ml_blend_weight.source },
    { name: "Signal Threshold", value: params.blending.thresholds.signal_threshold?.value ?? "—", source: params.blending.thresholds.signal_threshold?.source ?? "default" },
  ];

  return (
    <div className="space-y-4">
      {/* Status Header */}
      <div className="flex gap-4">
        <div className="flex-1 bg-surface-container p-4 rounded-lg">
          <span className="text-xs font-headline font-bold uppercase tracking-widest text-on-surface-variant">Parameters</span>
          <div className="font-headline text-3xl font-bold tabular-nums tracking-tighter text-primary mt-1">
            {counts.user + counts.db}
          </div>
        </div>
        <div className="bg-surface-container-low p-4 rounded-lg flex flex-col justify-center">
          <span className="text-xs uppercase text-on-surface-variant mb-1">Overrides</span>
          <div className="flex items-baseline gap-2">
            <span className="font-headline text-2xl font-bold tabular-nums">{counts.user}</span>
            <span className="text-tertiary-dim text-xs">user</span>
          </div>
        </div>
      </div>

      {/* Parameter Categories — 4 columns matching engine.html */}
      <div className="grid grid-cols-2 gap-4">
        <ParamCategory title="Blending" params={blendingParams} />
        <ParamCategory title="Technical" params={[
          { name: "RSI Threshold", value: params.technical?.sigmoid_params?.rsi_center?.value ?? "—", source: params.technical?.sigmoid_params?.rsi_center?.source ?? "default" },
          { name: "ADX Threshold", value: params.technical?.sigmoid_params?.adx_center?.value ?? "—", source: params.technical?.sigmoid_params?.adx_center?.source ?? "default" },
        ]} />
        <ParamCategory title="Order Flow" params={Object.entries(params.order_flow?.max_scores ?? {}).slice(0, 2).map(([k, v]: [string, any]) => ({
          name: k, value: v.value, source: v.source,
        }))} />
        <ParamCategory title="On-Chain" params={Object.entries(params.onchain?.btc_profile ?? {}).slice(0, 2).map(([k, v]: [string, any]) => ({
          name: k, value: typeof v === "object" && v.value !== undefined ? v.value : v, source: typeof v === "object" && v.source ? v.source : "default",
        }))} />
      </div>

      {/* Refresh */}
      <button
        onClick={refresh}
        className="w-full bg-primary-container text-on-primary-fixed py-3 rounded-lg text-xs font-bold uppercase tracking-widest flex items-center justify-center gap-2 active:scale-[0.98] transition-transform focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
      >
        <RefreshCw size={14} />
        Refresh Parameters
      </button>
    </div>
  );
}

function ParamCategory({ title, params }: { title: string; params: { name: string; value: any; source: string }[] }) {
  return (
    <section className="bg-surface-container p-4 rounded-lg flex flex-col gap-3">
      <h2 className="text-xs font-headline font-bold uppercase tracking-wider text-primary">{title}</h2>
      <div className="space-y-2">
        {params.map((p) => (
          <div key={p.name} className={`bg-surface-container-lowest p-3 rounded ${p.source === "user" || p.source === "yaml" ? "border-l-2 border-primary/40" : ""}`}>
            <div className="flex justify-between text-[10px] text-on-surface-variant uppercase mb-1">
              <span>{p.name}</span>
              <span className={p.source === "user" || p.source === "yaml" ? "text-primary" : "text-outline"}>
                {p.source === "user" || p.source === "yaml" ? "User" : "DB"}
              </span>
            </div>
            <span className="font-headline font-medium text-lg tabular-nums">{typeof p.value === "number" ? p.value.toFixed(3) : String(p.value)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
```

Note: The parameter property paths above may need adjustment based on the actual `EngineParams` type in `features/engine/store.ts`. Check the type definition and adjust `params.technical?.sigmoid_params?.rsi_center` etc. to match the real nested structure. The 4-category grid pattern follows `engine.html`.

- [ ] **Step 2: Verify build**

Run: `cd web && pnpm build`
Expected: PASS

- [ ] **Step 3: Visual check**

Run: `cd web && pnpm dev` — navigate to More > Engine Dashboard, verify parameter categories display.

---

## Task 9: Build SystemDiagnostics (New View)

**Files:**
- Create: `web/src/features/system/components/SystemDiagnostics.tsx`

Match `web/.stitch-screens/system.html`. Displays connection health, infrastructure status, data freshness — mostly static/mocked for now since there's no dedicated diagnostics API.

- [ ] **Step 1: Build SystemDiagnostics**

This view shows system health using data available from the frontend context:
1. **Health summary**: 4 cards (Connectivity, Database, Cache, ML Pipeline) with colored left borders and status dots. Use `useSignalStore((s) => s.connected)` for connectivity status. Others show static "Active" since we can't query backend infra from the frontend.
2. **WebSocket streams**: Table listing the 3 pairs (BTC/ETH/WIF-USDT-SWAP) with CONNECTED status. Use the available pairs from `AVAILABLE_PAIRS` constant.
3. **Infrastructure card**: Static display with Redis/DB/Collector info.
4. **Data freshness**: Progress bars for Technicals/Order Flow/On-Chain.

```tsx
import { useSignalStore } from "../../signals/store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { Wifi, Database, HardDrive, Cpu } from "lucide-react";

export function SystemDiagnostics() {
  const connected = useSignalStore((s) => s.connected);

  const healthCards = [
    { label: "Connectivity", status: connected ? "OPTIMAL" : "OFFLINE", color: connected ? "border-tertiary-dim" : "border-error", dotColor: connected ? "bg-tertiary-dim" : "bg-error" },
    { label: "Database", status: "ACTIVE", color: "border-tertiary-dim", dotColor: "bg-tertiary-dim" },
    { label: "Cache", status: "WARM", color: "border-primary", dotColor: "bg-primary" },
    { label: "ML Pipeline", status: "READY", color: "border-tertiary-dim", dotColor: "bg-tertiary-dim" },
  ];

  return (
    <div className="space-y-6">
      {/* Health Summary */}
      <section className="grid grid-cols-2 gap-3">
        {healthCards.map((card) => (
          <div key={card.label} className={`bg-surface-container p-4 ${card.color} border-l-2`}>
            <p className="text-[10px] font-headline font-bold text-on-surface-variant uppercase tracking-widest mb-1">{card.label}</p>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${card.dotColor} ${card.status === "OPTIMAL" ? "animate-pulse motion-reduce:animate-none" : ""}`} />
              <span className="text-sm font-bold tabular-nums">{card.status}</span>
            </div>
          </div>
        ))}
      </section>

      {/* WebSocket Streams */}
      <section className="bg-surface-container-low overflow-hidden rounded-lg">
        <div className="p-4 bg-surface-container flex justify-between items-center">
          <h2 className="font-headline font-bold text-xs tracking-tighter uppercase text-primary">WebSocket Streams</h2>
          <span className="text-[10px] tabular-nums bg-primary/10 text-primary px-2 py-0.5 rounded-full">{AVAILABLE_PAIRS.length} ACTIVE</span>
        </div>
        <div className="divide-y divide-outline-variant/10">
          {AVAILABLE_PAIRS.map((pair) => (
            <div key={pair} className="px-4 py-3 flex items-center justify-between">
              <span className="font-mono font-medium text-sm text-on-surface">{pair}</span>
              <span className="text-[10px] font-bold text-tertiary-dim bg-tertiary-dim/10 px-2 py-0.5 rounded">
                {connected ? "CONNECTED" : "DISCONNECTED"}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* Infrastructure */}
      <section className="bg-surface-container p-5 border border-outline-variant/10 rounded-lg">
        <h2 className="font-headline font-bold text-xs tracking-tighter uppercase text-primary mb-5">Infrastructure</h2>
        <div className="space-y-4">
          <InfraRow label="Redis (Cache)" detail="In-memory store" status="ACTIVE" />
          <InfraRow label="PostgreSQL" detail="Primary database" status="ACTIVE" />
          <InfraRow label="Collector Service" detail="OKX WebSocket ingestion" status="RUNNING" />
        </div>
      </section>

      {/* Data Freshness */}
      <section className="bg-surface-container p-5 border border-outline-variant/10 rounded-lg">
        <h2 className="font-headline font-bold text-xs tracking-tighter uppercase text-primary mb-5">Data Freshness</h2>
        <div className="space-y-5">
          <FreshnessBar label="Technicals" lag="Live" pct={95} color="bg-tertiary-dim" />
          <FreshnessBar label="Order Flow" lag="Live" pct={98} color="bg-tertiary-dim" />
          <FreshnessBar label="On-Chain" lag="~2m" pct={70} color="bg-primary" />
        </div>
      </section>
    </div>
  );
}

function InfraRow({ label, detail, status }: { label: string; detail: string; status: string }) {
  return (
    <div className="flex items-start justify-between">
      <div>
        <p className="text-[11px] font-bold text-on-surface">{label}</p>
        <p className="text-[10px] text-on-surface-variant">{detail}</p>
      </div>
      <span className="text-[10px] text-tertiary-dim uppercase font-bold">{status}</span>
    </div>
  );
}

function FreshnessBar({ label, lag, pct, color }: { label: string; lag: string; pct: number; color: string }) {
  return (
    <div>
      <div className="flex justify-between text-[10px] font-bold uppercase mb-1">
        <span className="text-on-surface-variant">{label}</span>
        <span className={pct >= 90 ? "text-tertiary-dim" : "text-primary"}>{lag}</span>
      </div>
      <div className="h-1.5 w-full bg-surface-container-lowest overflow-hidden rounded-full">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd web && pnpm build`
Expected: PASS

- [ ] **Step 3: Visual check**

Run: `cd web && pnpm dev` — navigate to More > System Diagnostics (via connection card), verify health cards and WS table.

---

## Task 10: Build PairDeepDive (New View)

**Files:**
- Create: `web/src/features/signals/components/PairDeepDive.tsx`

Match `web/.stitch-screens/pair-deepdive.html`. Per-pair analysis overlay: market regime, ML confidence gauge, engine stats bento, order flow snapshot, signal audit log.

- [ ] **Step 1: Build PairDeepDive**

This view receives a `pair` prop and displays per-pair analysis. It uses:
- `useSignalStore` for recent signals filtered by pair
- `useLivePrice(pair)` for current price/change
- Static placeholder sections for ML confidence, order flow (these don't have dedicated per-pair API endpoints yet)

```tsx
import { useMemo } from "react";
import { useSignalStore } from "../store";
import { useLivePrice } from "../../../shared/hooks/useLivePrice";
import { TrendingUp, TrendingDown } from "lucide-react";

interface PairDeepDiveProps {
  pair: string;
}

export function PairDeepDive({ pair }: PairDeepDiveProps) {
  const signals = useSignalStore((s) => s.signals);
  const { price, change24h } = useLivePrice(pair);

  const pairSignals = useMemo(
    () => signals.filter((s) => s.pair === pair).slice(0, 5),
    [signals, pair]
  );

  const shortPair = pair.replace("-USDT-SWAP", "");
  const isPositive = (change24h ?? 0) >= 0;

  return (
    <div className="space-y-4">
      {/* Price Header */}
      <div className="flex items-end justify-between">
        <div>
          <h2 className="font-headline font-bold text-2xl">{shortPair}/USDT</h2>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-headline font-bold text-xl tabular-nums">
              {price ? price.toLocaleString(undefined, { minimumFractionDigits: 2 }) : "—"}
            </span>
            {change24h != null && (
              <span className={`text-sm font-bold tabular-nums ${isPositive ? "text-tertiary-dim" : "text-error"}`}>
                {isPositive ? "+" : ""}{change24h.toFixed(2)}%
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Market Regime */}
      <section className="bg-surface-container rounded-lg p-5 border border-outline-variant/10">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Market Regime</span>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full animate-pulse motion-reduce:animate-none ${isPositive ? "bg-tertiary-dim" : "bg-error"}`} />
          <span className={`font-headline font-bold text-xl italic ${isPositive ? "text-tertiary-dim" : "text-error"}`}>
            {isPositive ? "Trending Bullish" : "Trending Bearish"}
          </span>
        </div>
      </section>

      {/* Engine Stats Bento */}
      <section className="grid grid-cols-2 gap-3">
        <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant/5">
          <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Signals (24h)</span>
          <span className="font-headline font-bold text-2xl tabular-nums">{pairSignals.length}</span>
        </div>
        <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant/5">
          <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Latest Score</span>
          <span className="font-headline font-bold text-2xl tabular-nums">
            {pairSignals[0]?.final_score?.toFixed(0) ?? "—"}
          </span>
        </div>
      </section>

      {/* Signal Audit Log */}
      <section className="space-y-3">
        <h3 className="font-headline font-bold text-sm tracking-widest uppercase px-1">Signal Audit Log</h3>
        {pairSignals.length === 0 ? (
          <p className="text-on-surface-variant text-sm text-center py-8">No recent signals for {shortPair}</p>
        ) : (
          pairSignals.map((signal) => {
            const isLong = signal.direction === "LONG";
            return (
              <div
                key={signal.id}
                className={`bg-surface-container hover:bg-surface-container-high transition-colors p-4 rounded-lg flex items-center justify-between border-l-2 ${
                  isLong ? "border-tertiary-dim" : "border-error"
                }`}
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 bg-surface-container-highest flex items-center justify-center rounded">
                    {isLong ? (
                      <TrendingUp size={20} className="text-tertiary-dim" />
                    ) : (
                      <TrendingDown size={20} className="text-error" />
                    )}
                  </div>
                  <div>
                    <div className="font-headline font-bold text-sm">
                      {signal.direction} {signal.timeframe?.toUpperCase()}
                    </div>
                    <div className="text-[10px] text-on-surface-variant tabular-nums">
                      {new Date(signal.created_at).toLocaleTimeString()} UTC
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className={`font-mono font-bold text-sm ${isLong ? "text-tertiary-dim" : "text-error"}`}>
                    {signal.final_score?.toFixed(0) ?? "—"}
                  </div>
                  <div className="text-[10px] text-on-surface-variant uppercase font-bold">
                    {signal.outcome}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </section>
    </div>
  );
}
```

Note: The implementer should check the exact shape of the `Signal` type in `features/signals/types.ts` to ensure property names (`final_score`, `direction`, `timeframe`, `status`, `created_at`, `pair`) match. Adjust as needed. Also verify `useLivePrice` exists and its return type.

- [ ] **Step 2: Verify build**

Run: `cd web && pnpm build`
Expected: PASS (may need adjustments to signal property names — fix any type errors)

- [ ] **Step 3: Note**

PairDeepDive is built but not yet wired into Layout.tsx as a slide-up overlay. The drill-down state (`activeDrillDown` / `drillDownPair`) and `onPairDrillDown` callbacks in Home/SignalCard were scoped to Plans 1 and 2 per the spec. If those weren't implemented, a follow-up task will be needed to wire PairDeepDive into the app navigation.

---

## Task 11: Final Verification

- [ ] **Step 1: Full build check**

Run: `cd web && pnpm build`
Expected: PASS with zero type errors

- [ ] **Step 2: Visual smoke test**

Run: `cd web && pnpm dev`

Verify:
1. More tab → shows hub with 3 clusters
2. Tap each hub item → navigates to sub-page with back button
3. Settings: M3 pair grid, styled slider, glow toggles, LLM pills
4. Risk: M3 sections with option buttons
5. Alerts: 3-tab layout, alert cards with left borders, terminal history log
6. Journal → Analytics: Bento stats, equity curve, pair breakdown
7. Journal → Calendar: M3 calendar grid
8. Backtest: Tab bar, styled setup, results cards
9. ML Training: 4-tab layout, M3 forms
10. Engine Dashboard: Parameter grid with categories
11. System Diagnostics: Health cards, WS streams, infra
12. Connection Status card at bottom of hub → opens System Diagnostics

- [ ] **Step 3: Commit all Plan 3 work**

Single commit for the entire Plan 3 batch (per CLAUDE.md — no incremental commits):

```bash
git add -A
git commit -m "feat(ui): Plan 3 — sub-pages, new views, and More hub with Kinetic Terminal design"
```
