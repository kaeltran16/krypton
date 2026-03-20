# Plan 1: Foundation + Layout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the OKX-style design system with the "Kinetic Terminal" M3 design tokens, update Layout/navigation chrome, and install new dependencies — so all subsequent view-level reskinning (Plans 2 & 3) can proceed.

**Architecture:** Design tokens live in `theme.ts` and flow into Tailwind via `tailwind.config.ts`. Global CSS in `index.css` handles scrollbar, utilities, and glass effects. `Layout.tsx` owns tab state, context-aware header switching, and bottom nav. Drill-down overlay state for Pair Deep Dive is deferred to Plan 3 (when the PairDeepDive component is built). Two new shared components (`EngineHeader`, `SubPageShell`) provide the More-tab header and sub-page wrapper.

**Tech Stack:** React 19, Tailwind CSS 3, Lucide React (icons), Motion (animations), Space Grotesk (Google Font)

**Spec:** `docs/superpowers/specs/2026-03-20-kinetic-terminal-redesign-design.md`

**Stitch reference HTML:** `web/.stitch-screens/dashboard.html` (header + nav patterns)

---

### Task 1: Install Dependencies

**Files:**
- Modify: `web/package.json`

- [ ] **Step 1: Install lucide-react and motion**

```bash
cd web && pnpm add lucide-react motion
```

- [ ] **Step 2: Verify install**

```bash
cd web && pnpm ls lucide-react motion
```

Expected: Both packages listed with versions.

---

### Task 2: Rewrite theme.ts

**Files:**
- Modify: `web/src/shared/theme.ts`

This is the single source of truth. Every color, font, and chart config flows from here.

- [ ] **Step 1: Replace theme.ts with full M3 token set**

Write the complete new file. Key changes:
- 40+ M3 color tokens (surface hierarchy, primary, tertiary, error, on-* variants)
- Legacy aliases (`long`, `short`, `accent`, `card`, `card-hover`, `border`, `foreground`, `muted`, `dim`)
- Extended palette unchanged (`blue`, `purple`, `pink`, `orange`, `teal`, `indigo`, `neutral`)
- New `fontFamily`: add `headline` (Space Grotesk)
- New `borderRadius` object with `pill` token
- Updated `glass` values for new surface colors
- Updated `chart` colors to match new palette
- Updated `indicators` colors (gold → cyan, green/red to new values)

```typescript
// ─── Design Tokens ─────────────────────────────────────────────
// "The Kinetic Terminal" — M3 tonal surface hierarchy.
// Single source of truth. Tailwind config consumes colors + fontFamily + borderRadius.
// Chart components import chart + indicators.

export const theme = {
  colors: {
    // ── M3 Surface Hierarchy ──
    surface: "#0a0f14",
    "surface-dim": "#0a0f14",
    "surface-container-lowest": "#000000",
    "surface-container-low": "#0e141a",
    "surface-container": "#141a21",
    "surface-container-high": "#1a2028",
    "surface-container-highest": "#1f262f",
    "surface-bright": "#252d36",
    "surface-variant": "#1f262f",
    "surface-tint": "#69daff",
    background: "#0a0f14",

    // ── Primary (cyan) ──
    primary: "#69daff",
    "primary-container": "#00cffc",
    "primary-dim": "#00c0ea",
    "primary-fixed": "#00cffc",
    "primary-fixed-dim": "#00c0ea",
    "on-primary": "#004a5d",
    "on-primary-container": "#004050",
    "on-primary-fixed": "#002a35",
    "on-primary-fixed-variant": "#004a5c",
    "inverse-primary": "#006880",

    // ── Secondary (neutral) ──
    secondary: "#e1e2e7",
    "secondary-container": "#44474b",
    "secondary-dim": "#d3d4d9",
    "secondary-fixed": "#e1e2e7",
    "secondary-fixed-dim": "#d3d4d9",
    "on-secondary": "#4f5256",
    "on-secondary-container": "#cfd0d4",
    "on-secondary-fixed": "#3d4043",
    "on-secondary-fixed-variant": "#595c5f",

    // ── Tertiary (green/bullish) ──
    tertiary: "#c1ffd4",
    "tertiary-container": "#66fdac",
    "tertiary-dim": "#56ef9f",
    "tertiary-fixed": "#66fdac",
    "tertiary-fixed-dim": "#56ef9f",
    "on-tertiary": "#00683d",
    "on-tertiary-container": "#005e37",
    "on-tertiary-fixed": "#004a2a",
    "on-tertiary-fixed-variant": "#00693e",

    // ── Error (red/bearish) ──
    error: "#ff716c",
    "error-container": "#9f0519",
    "error-dim": "#d7383b",
    "on-error": "#490006",
    "on-error-container": "#ffa8a3",

    // ── On-surface / text ──
    "on-surface": "#e7ebf3",
    "on-surface-variant": "#a7abb3",
    "on-background": "#e7ebf3",

    // ── Outline ──
    outline: "#71767d",
    "outline-variant": "#43484f",

    // ── Inverse ──
    "inverse-surface": "#f7f9ff",
    "inverse-on-surface": "#50555c",

    // ── Legacy aliases (backward compat for existing components) ──
    long: "#56ef9f",
    short: "#ff716c",
    accent: "#00cffc",
    foreground: "#e7ebf3",
    muted: "#a7abb3",
    dim: "#71767d",
    card: "#141a21",
    "card-hover": "#1a2028",
    border: "#43484f",

    // ── Extended palette (indicators, tool icons, badges — unchanged) ──
    blue: "#3B82F6",
    purple: "#8B5CF6",
    pink: "#EC4899",
    orange: "#F97316",
    teal: "#14B8A6",
    indigo: "#6366F1",
    neutral: "#6B7280",
  },

  fontFamily: {
    sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
    headline: ["Space Grotesk", "system-ui", "sans-serif"],
    mono: ["JetBrains Mono", "Fira Code", "monospace"],
  },

  borderRadius: {
    DEFAULT: "0.125rem",
    lg: "0.25rem",
    xl: "0.5rem",
    pill: "0.75rem",
  },

  glass: {
    nav: "rgba(31, 38, 47, 0.60)",
    card: "rgba(20, 26, 33, 0.65)",
    dialog: "rgba(10, 15, 20, 0.9)",
    border: "rgba(67, 72, 79, 0.15)",
    backdrop: "rgba(0, 0, 0, 0.7)",
    blur: { nav: "24px", dialog: "20px", card: "12px" },
  },

  chart: {
    background: "#0a0f14",
    text: "#a7abb3",
    grid: "rgba(31, 38, 47, 0.3)",
    scaleBorder: "#43484f",
    candleUp: "#56ef9f",
    candleDown: "#ff716c",
    volumeUp: "rgba(86, 239, 159, 0.3)",
    volumeDown: "rgba(255, 113, 108, 0.3)",
    macdHistUp: "rgba(86, 239, 159, 0.6)",
    macdHistDown: "rgba(255, 113, 108, 0.6)",
  },

  indicators: {
    ema21: "#00cffc",
    ema50: "#69daff",
    ema200: "#A855F7",
    sma21: "#F59E0B",
    sma50: "#6366F1",
    sma200: "#EC4899",
    rsi: "#00cffc",
    macd: "#69daff",
    macdSignal: "#F97316",
    stochK: "#56ef9f",
    stochD: "#ff716c",
    bb: "#6B7280",
    vwap: "#F97316",
    ichTenkan: "#69daff",
    ichKijun: "#ff716c",
    ichSenkouA: "#56ef9f",
    ichSenkouB: "#ff716c",
    supertrend: "#56ef9f",
    psar: "#8B5CF6",
    pivots: "#14B8A6",
    cci: "#F97316",
    atr: "#EC4899",
    adx: "#8B5CF6",
    willr: "#14B8A6",
    mfi: "#ff716c",
    obv: "#6366F1",
    curveColors: ["#00cffc", "#56ef9f", "#ff716c", "#69daff"],
  },
} as const;
```

- [ ] **Step 2: Verify no TypeScript errors**

```bash
cd web && npx tsc --noEmit
```

Expected: No errors (Tailwind config and all `theme.*` imports still resolve).

---

### Task 3: Update tailwind.config.ts

**Files:**
- Modify: `web/tailwind.config.ts`

- [ ] **Step 1: Wire new theme tokens, add pill radius, update keyframes + safelist**

```typescript
import type { Config } from "tailwindcss";
import { theme } from "./src/shared/theme";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: theme.colors,
      fontFamily: theme.fontFamily,
      borderRadius: theme.borderRadius,
      animation: {
        'slide-down': 'slideDown 0.3s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'fade-in': 'fadeIn 0.15s ease-in-out',
        'card-enter': 'cardEnter 0.35s cubic-bezier(0.16, 1, 0.3, 1) backwards',
        'pulse-glow': 'pulseGlow 2s ease-in-out 3',
      },
      keyframes: {
        slideDown: { '0%': { transform: 'translateY(-100%)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
        slideUp: { '0%': { transform: 'translateY(20px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
        fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        cardEnter: { '0%': { transform: 'translateY(12px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
        pulseGlow: { '0%, 100%': { boxShadow: '0 0 0 0 rgba(0, 207, 252, 0)' }, '50%': { boxShadow: '0 0 8px 2px rgba(0, 207, 252, 0.15)' } },
      },
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
    "text-tertiary-dim", "text-error", "text-primary",
    "bg-tertiary-dim/10", "bg-tertiary-dim/20",
    "bg-error/10", "bg-error/20",
    "border-tertiary-dim/30", "border-error/30",
    "border-outline-variant/10", "border-outline-variant/15",
  ],
  plugins: [],
} satisfies Config;
```

Key changes from current:
- Added `borderRadius: theme.borderRadius` (new `pill` token, tighter `lg`/`xl`). **Note:** This overrides Tailwind's default `rounded-lg` (`0.5rem` → `0.25rem`), `rounded-xl` (`0.75rem` → `0.5rem`), and `rounded` (`0.25rem` → `0.125rem`). This is intentional for the tighter terminal aesthetic and affects ~136 usages across 28 files — all existing components will get sharper corners. Visual QA across all views is needed after this plan to verify nothing looks wrong at the tighter radii.
- Updated `pulseGlow` from gold `rgba(240, 185, 11, ...)` to cyan `rgba(0, 207, 252, ...)`
- Added new safelist entries for M3 tokens

- [ ] **Step 2: Verify**

```bash
cd web && npx tsc --noEmit
```

---

### Task 4: Rewrite index.css

**Files:**
- Modify: `web/src/index.css`

- [ ] **Step 1: Replace index.css with new base styles**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --safe-top: env(safe-area-inset-top, 0px);
  --safe-bottom: env(safe-area-inset-bottom, 0px);

  /* Theme tokens — keep in sync with shared/theme.ts */
  --color-foreground: #e7ebf3;
  --color-primary: #69daff;
  --color-primary-container: #00cffc;
  --glass-nav: rgba(31, 38, 47, 0.60);
  --glass-card: rgba(20, 26, 33, 0.65);
  --glass-dialog: rgba(10, 15, 20, 0.9);
  --glass-border: rgba(67, 72, 79, 0.15);
  --glass-backdrop: rgba(0, 0, 0, 0.7);
  --glass-blur-card: 12px;
  --glass-blur-dialog: 20px;
}

body {
  background-color: #0a0f14;
  color: var(--color-foreground);
  font-family: Inter, system-ui, -apple-system, sans-serif;
  margin: 0;
  min-height: 100vh;
  min-height: 100dvh;
  -webkit-font-smoothing: antialiased;
  -webkit-tap-highlight-color: transparent;
  overscroll-behavior: none;
}

/* Eliminate 300ms tap delay on mobile Safari */
button, a, [role="button"], [role="switch"] {
  touch-action: manipulation;
}

/* Global focus-visible ring for keyboard navigation */
:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--color-primary) 60%, transparent);
  outline-offset: 2px;
  border-radius: 4px;
}

:focus:not(:focus-visible) {
  outline: none;
}

input, select, textarea {
  font-size: 16px; /* Prevent iOS zoom on focus */
}

/* Scrollbar — thin terminal style */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: #0a0f14; }
::-webkit-scrollbar-thumb { background: #1f262f; border-radius: 2px; }

/* Selection */
::selection {
  background: rgba(105, 218, 255, 0.3);
}

dialog::backdrop {
  background: var(--glass-backdrop);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

dialog {
  margin: 0;
  margin-top: auto;
  padding: 0;
  border: none;
  max-height: 85vh;
  width: 100%;
  max-width: 32rem;
  border-radius: 0.5rem 0.5rem 0 0;
  overflow-y: auto;
  background: var(--glass-dialog);
  backdrop-filter: blur(var(--glass-blur-dialog));
  -webkit-backdrop-filter: blur(var(--glass-blur-dialog));
  color: var(--color-foreground);
  border-top: 1px solid var(--glass-border);
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

/* Tabular numbers for prices and metrics */
.tabular {
  font-feature-settings: "tnum";
  font-variant-numeric: tabular-nums;
}

/* Typography utilities */
.text-display {
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.2;
}

.text-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

@keyframes slide-down {
  from { transform: translateY(-100%); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

.animate-slide-down {
  animation: slide-down 0.3s ease-out;
}

/* Stagger animation delays for card lists */
.stagger-1 { animation-delay: 0ms; }
.stagger-2 { animation-delay: 40ms; }
.stagger-3 { animation-delay: 80ms; }
.stagger-4 { animation-delay: 120ms; }
.stagger-5 { animation-delay: 160ms; }
.stagger-6 { animation-delay: 200ms; }
.stagger-7 { animation-delay: 240ms; }
.stagger-8 { animation-delay: 280ms; }
.stagger-9 { animation-delay: 320ms; }
.stagger-10 { animation-delay: 360ms; }

/* Glass card — updated for terminal aesthetic */
.glass-card {
  background: var(--glass-card);
  backdrop-filter: blur(var(--glass-blur-card));
  -webkit-backdrop-filter: blur(var(--glass-blur-card));
  border: 1px solid var(--glass-border);
  border-radius: 0.25rem;
}

/* Terminal grid background for More/Engine pages */
.terminal-grid {
  background-size: 40px 40px;
  background-image: linear-gradient(to right, rgba(0, 207, 252, 0.03) 1px, transparent 1px),
                    linear-gradient(to bottom, rgba(0, 207, 252, 0.03) 1px, transparent 1px);
}

/* Respect reduced-motion preferences (WCAG 2.1) */
@media (prefers-reduced-motion: reduce) {
  .animate-card-enter { animation: none !important; opacity: 1; transform: none; }
  .animate-pulse-glow { animation: none !important; }
}
```

Key changes:
- Fonts loaded via `<link>` in `index.html` (not CSS `@import`, which is render-blocking)
- Flat `background-color` replaces gradient
- Updated CSS vars to match new M3 palette
- Added scrollbar styles, `.tabular` utility, `.terminal-grid`
- Updated `.glass-card` radius from `0.5rem` to `0.25rem`
- Updated focus ring to cyan via `--color-primary`

---

### Task 5: Update index.html

**Files:**
- Modify: `web/index.html`

- [ ] **Step 1: Update theme-color meta tag**

Change line 6 from:
```html
<meta name="theme-color" content="#0B0E11" />
```
to:
```html
<meta name="theme-color" content="#0a0f14" />
```

- [ ] **Step 2: Add Google Fonts preconnect + stylesheet links**

Add before the closing `</head>` (alongside existing preloads):
```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet" />
```

Fonts are loaded via HTML `<link>` (non-render-blocking with `font-display: swap`) rather than CSS `@import` (which blocks rendering until all fonts download).

---

### Task 6: Rewrite Layout.tsx

**Files:**
- Modify: `web/src/shared/components/Layout.tsx`

This is the most complex change. The new Layout:
- Replaces custom SVG icons with Lucide
- Adds context-aware header (TickerBar for market tabs, EngineHeader for More)
- Replaces old nav styling with glass effect + glow
- Adds motion-based opacity transitions for tab panels (tabs stay mounted)
- Drill-down state for Pair Deep Dive deferred to Plan 3

- [ ] **Step 1: Rewrite Layout.tsx**

```tsx
import { useState, type ReactNode } from "react";
import { motion } from "motion/react";
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
  const views: Record<Tab, ReactNode> = { home, chart, signals, news, more };

  return (
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

      <nav className="fixed bottom-0 left-0 right-0 flex justify-around items-center pt-2 px-2 safe-bottom bg-[rgba(31,38,47,0.60)] backdrop-blur-xl z-30 border-t border-outline-variant/15 shadow-[0_-12px_32px_rgba(0,0,0,0.2)]">
        {TABS.map((t) => {
          const Icon = TAB_ICONS[t];
          const active = tab === t;
          return (
            <motion.button
              key={t}
              onClick={() => { hapticTap(); setTab(t); }}
              whileTap={{ scale: 0.95 }}
              aria-current={active ? "page" : undefined}
              className={`flex flex-col items-center justify-center min-h-[44px] py-2 px-3 transition-all duration-200 ${
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
            </motion.button>
          );
        })}
      </nav>
    </div>
  );
}
```

Key changes:
- Lucide icons replace custom SVGs (5 inline icon components deleted)
- `TabButton` and all `Icon*` functions removed — replaced by data-driven `TABS.map()`
- Glass nav: `bg-[rgba(31,38,47,0.60)] backdrop-blur-xl` with outline-variant border
- Active tab: `text-primary-container` + glow shadow, `strokeWidth={2.5}`
- Inactive: `text-on-surface-variant`, `strokeWidth={1.5}`
- Context header: `isMarketTab ? <TickerBar> : <EngineHeader>`
- Inactive tabs use `pointer-events-none absolute inset-0 overflow-hidden` (not `display: none`) so motion can animate opacity/y smoothly. `<main>` has `relative` for positioning context. **Note:** This means all 5 tab views are rendered simultaneously (previously `hidden` = `display: none` skipped paint). Verify that `lightweight-charts` canvas instances handle the invisible-but-rendered state correctly (sizing, resize observers). If perf issues arise, consider falling back to `visibility: hidden` for inactive tabs.
- Nav buttons use `motion.button` with `whileTap={{ scale: 0.95 }}` for tap feedback
- Nav buttons include `min-h-[44px]` for touch target compliance and `aria-current="page"` on active tab
- `pb-20` instead of `pb-16` (nav is slightly taller with padding)

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd web && npx tsc --noEmit
```

Expected: May fail on missing `EngineHeader` — that's Task 8. Continue to next task.

---

### Task 7: Rewrite TickerBar.tsx

**Files:**
- Modify: `web/src/shared/components/TickerBar.tsx`

The TickerBar becomes the KRYPTON branding header for market tabs.

- [ ] **Step 1: Rewrite TickerBar.tsx**

```tsx
import { ChevronDown } from "lucide-react";
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
    <header className="bg-surface flex justify-between items-center w-full px-4 h-14 z-40 sticky top-0 safe-top">
      <div className="flex items-center gap-3">
        <span className="text-on-surface font-headline font-bold text-lg tracking-tight">KRYPTON</span>
        <div className="h-4 w-px bg-outline-variant/30" />
        <div className="relative flex items-center">
          <select
            value={pair}
            onChange={(e) => onPairChange(e.target.value)}
            aria-label="Select trading pair"
            className="bg-transparent font-headline font-bold tracking-tight text-base text-primary-container border-none outline-none appearance-none cursor-pointer pr-5"
          >
            {AVAILABLE_PAIRS.map((p) => (
              <option key={p} value={p} className="bg-surface-container text-on-surface">
                {p.replace("-SWAP", "")}
              </option>
            ))}
          </select>
          <ChevronDown size={14} className="absolute right-0 pointer-events-none text-primary-container/60" />
        </div>
      </div>
      <div className="flex items-center gap-4">
        {change24h !== null && (
          <div className="flex items-center gap-1.5 px-2 py-1 bg-surface-container rounded-lg">
            <span className={`text-[10px] font-headline font-bold tracking-widest uppercase ${
              isPositive ? "text-tertiary-dim" : "text-error"
            }`}>
              {isPositive ? "+" : ""}{change24h.toFixed(2)}%
            </span>
          </div>
        )}
        {price !== null && (
          <span className="font-mono text-sm tabular text-on-surface">
            ${formatPrice(price)}
          </span>
        )}
      </div>
    </header>
  );
}
```

Key changes:
- "KRYPTON" branding left-aligned with Space Grotesk
- Pair selector next to branding (separated by divider) with ChevronDown affordance
- Pair display strips `-SWAP` suffix for cleaner mobile UI
- Change badge in `bg-surface-container` pill
- Price in mono tabular
- `bg-surface` flat background instead of glass
- `sticky top-0` positioning

---

### Task 8: Create EngineHeader.tsx

**Files:**
- Create: `web/src/shared/components/EngineHeader.tsx`

Header shown when the More tab (or its sub-pages) is active.

- [ ] **Step 1: Create EngineHeader.tsx**

```tsx
import { Terminal } from "lucide-react";

export function EngineHeader() {
  return (
    <header className="bg-surface flex items-center w-full px-4 h-14 z-40 sticky top-0 safe-top">
      <div className="flex items-center gap-3">
        <Terminal size={20} className="text-primary-container" />
        <span className="font-headline font-bold tracking-tight uppercase text-lg text-primary-container">
          Engine Control
        </span>
      </div>
    </header>
  );
}
```

---

### Task 9: Create SubPageShell.tsx

**Files:**
- Create: `web/src/shared/components/SubPageShell.tsx`

Shared wrapper for More sub-pages (Settings, Risk, Alerts, etc.) — provides back button + title.

- [ ] **Step 1: Create SubPageShell.tsx**

```tsx
import { type ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { hapticTap } from "../lib/haptics";

interface SubPageShellProps {
  title: string;
  onBack: () => void;
  children: ReactNode;
}

export function SubPageShell({ title, onBack, children }: SubPageShellProps) {
  return (
    <div className="min-h-full">
      <div className="flex items-center gap-3 px-4 py-4">
        <button
          onClick={() => { hapticTap(); onBack(); }}
          className="p-1.5 hover:bg-surface-variant rounded-lg transition-colors"
        >
          <ArrowLeft size={20} className="text-primary" />
        </button>
        <h1 className="font-headline font-bold text-lg tracking-tight uppercase text-on-surface">
          {title}
        </h1>
      </div>
      <div className="px-4 pb-8">
        {children}
      </div>
    </div>
  );
}
```

---

### Task 10: Verify Build

- [ ] **Step 1: Run TypeScript check**

```bash
cd web && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 2: Run production build**

```bash
cd web && pnpm build
```

Expected: Build succeeds. The app will look partially broken (old component styles against new tokens) — that's expected and will be fixed in Plan 2.

- [ ] **Step 3: Quick visual smoke test**

```bash
cd web && pnpm dev
```

Open in browser. Verify:
- Bottom nav renders with Lucide icons and glass effect
- "KRYPTON" header shows on Home/Chart/Signals/News tabs
- "Engine Control" header shows on More tab
- Tab switching works with opacity transition
- Colors are the new M3 palette (cyan primary, dark surfaces)

- [ ] **Step 4: Commit all remaining changes**

```bash
git add -A
git commit -m "feat(ui): Kinetic Terminal foundation — layout, nav, headers, design tokens"
```

---

## Summary

| Task | Files | What |
|---|---|---|
| 1 | `package.json` | Install lucide-react + motion |
| 2 | `theme.ts` | Full M3 color/font/radius/chart/indicator tokens |
| 3 | `tailwind.config.ts` | Wire new theme, update keyframes + safelist |
| 4 | `index.css` | New base styles, scrollbar, utilities |
| 5 | `index.html` | Update theme-color meta |
| 6 | `Layout.tsx` | Context header, glass nav, Lucide icons, motion |
| 7 | `TickerBar.tsx` | KRYPTON branding + pair + change badge |
| 8 | `EngineHeader.tsx` | New — Engine Control header |
| 9 | `SubPageShell.tsx` | New — back button + title wrapper |
| 10 | — | Build verification |
