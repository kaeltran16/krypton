# Kinetic Terminal Redesign — Design Spec

**Date**: 2026-03-20
**Status**: Draft
**Scope**: Full frontend reskin from OKX-style to "Kinetic Terminal" M3 design system, based on 15 Stitch screens.

---

## 1. Overview

Reskin the Krypton PWA frontend to match the "Kinetic Terminal" design system created in Google Stitch. This is primarily a visual change — all business logic, hooks, stores, API client, and backend remain untouched. The one exception is a small navigation state addition for Pair Deep Dive (see §3.4).

### Key Design Shifts
- **Color**: OKX gold/green/red → M3 cyan/green/red tonal surface hierarchy
- **Typography**: Inter-only → Space Grotesk headlines + Inter body (dual-font)
- **Icons**: Custom SVGs → Lucide React (tree-shakeable)
- **Borders**: Explicit borders → tonal layering (surface hierarchy defines depth)
- **Radius**: Default Tailwind rounding → tighter precision (keep `rounded-full` at 9999px for circles)
- **Animation**: CSS-only → Motion (motion.dev) for transitions and micro-interactions
- **Header**: Static TickerBar → context-aware (market header vs Engine Control)

### Out of Scope
- Login/auth pages (none exist currently, skip)
- Backend changes
- Business logic changes (hooks, stores, API client, types)
- Chart rendering internals (lightweight-charts — only theme colors change)

---

## 2. Design System Foundation

### 2.1 Color Palette (M3 Tonal Surfaces)

| Token | Hex | Usage |
|---|---|---|
| `surface` | `#0a0f14` | Base background |
| `surface-container-lowest` | `#000000` | Recessed inputs |
| `surface-container-low` | `#0e141a` | Subtle sections |
| `surface-container` | `#141a21` | Default cards |
| `surface-container-high` | `#1a2028` | Elevated cards |
| `surface-container-highest` | `#1f262f` | Active/selected states |
| `surface-bright` | `#252d36` | Hover states |
| `surface-variant` | `#1f262f` | Glass overlays (intentionally same hex as `surface-container-highest` — semantic alias for future divergence) |
| `primary` | `#69daff` | Primary actions, links |
| `primary-container` | `#00cffc` | Primary buttons, strong accent |
| `primary-dim` | `#00c0ea` | Subtle primary |
| `tertiary-dim` | `#56ef9f` | Bullish/long, success |
| `tertiary-container` | `#66fdac` | Strong bullish |
| `error` | `#ff716c` | Bearish/short, errors |
| `error-container` | `#9f0519` | Error backgrounds |
| `error-dim` | `#d7383b` | Subtle error |
| `on-surface` | `#e7ebf3` | Primary text |
| `on-surface-variant` | `#a7abb3` | Secondary text, labels |
| `on-primary-fixed` | `#002a35` | Text on primary buttons |
| `on-tertiary-fixed` | `#004a2a` | Text on tertiary containers |
| `on-error` | `#490006` | Text on error containers |
| `outline-variant` | `#43484f` | Ghost borders (10-15% opacity only) |
| `outline` | `#71767d` | Disabled states |

Full M3 token set (secondary, inverse, tertiary-fixed, etc.) included in `theme.ts` for completeness per Stitch export.

**Legacy aliases** preserved in `theme.ts` for backward compatibility:
- `long` → `#56ef9f`, `short` → `#ff716c`, `accent` → `#00cffc`
- `foreground` → `#e7ebf3`, `muted` → `#a7abb3`, `dim` → `#71767d`
- `card` → `#141a21`, `card-hover` → `#1a2028`, `border` → `#43484f`

**Extended palette** (unchanged from current, used by indicators/badges):
- `blue` → `#3B82F6`, `purple` → `#8B5CF6`, `pink` → `#EC4899`
- `orange` → `#F97316`, `teal` → `#14B8A6`, `indigo` → `#6366F1`, `neutral` → `#6B7280`

### 2.2 Typography

| Role | Font | Weight | Usage |
|---|---|---|---|
| `font-headline` | Space Grotesk | 500, 700 | Tailwind `fontFamily` entry. Headlines, scores, balances, section titles |
| `font-body` / `font-sans` | Inter | 400, 500, 600 | Tailwind `fontFamily` entry. Body text, descriptions |
| `font-mono` | JetBrains Mono | 400, 500 | Tailwind `fontFamily` entry. Code, API endpoints, logs |

**Note on `font-label`**: This is a *design role*, not a Tailwind `fontFamily` token (it uses the same Inter font as body). Implemented as a utility pattern: `text-[10px] uppercase tracking-widest font-medium font-body`. No separate `fontFamily` entry needed.

Tabular numbers (`font-feature-settings: "tnum"`) on all price/metric displays via a `.tabular` CSS utility class.

### 2.3 Border Radius

| Token | Value | Usage |
|---|---|---|
| `DEFAULT` | 2px (0.125rem) | Subtle rounding |
| `lg` | 4px (0.25rem) | Cards, buttons |
| `xl` | 8px (0.5rem) | Panels, modals |
| `pill` | 12px (0.75rem) | Custom token for pill badges |
| `full` | 9999px (unchanged) | Circles, dots — **not overridden** |

**Important**: `rounded-full` stays at Tailwind default `9999px` to preserve circular elements (connection dots, avatars). A new `rounded-pill` token is added for pill-shaped badges.

The `.glass-card` class in `index.css` must also update its `border-radius` from `0.5rem` to `0.25rem` (4px).

### 2.4 Icons — Lucide React

~30 icons needed. Key mappings from Stitch Material Symbols:
- `home` → `Home`, `show_chart` → `BarChart3`, `sensors` → `Zap`
- `newspaper` → `Newspaper`, `more_horiz` → `MoreHorizontal`
- `trending_up` → `TrendingUp`, `trending_down` → `TrendingDown`
- `search` → `Search`, `settings` → `Settings`, `shield` → `Shield`
- `memory` → `Cpu`, `monitoring` → `LineChart`, `model_training` → `Brain`
- `notifications_active` → `BellRing`, `terminal` → `Terminal`
- `chevron_right` → `ChevronRight`, `arrow_back` → `ArrowLeft`
- `circle` → `Circle`, `edit` → `Pencil`, `delete` → `Trash2`

### 2.5 Animation — Motion (motion.dev)

| Pattern | Implementation | Usage |
|---|---|---|
| Tab visibility | `motion.div` with `animate={{ opacity, y }}` on the *visible* panel | Tab switches — **tabs remain mounted** (no `AnimatePresence` mount/unmount, to preserve scroll/chart/WS state). Hidden tabs get `opacity: 0, pointerEvents: none`. |
| Staggered card entry | `staggerChildren` on parent, `cardEnter` variants on children | Signal feed, news feed, position list |
| Scale on tap | `whileTap={{ scale: 0.95 }}` | Buttons, nav items |
| Slide-up sheet | `AnimatePresence` + `motion.div` sliding from bottom | Pair Deep Dive drill-down, indicator panel |
| Glow pulse | CSS `@keyframes` (not motion) | Live indicators, active connection dots |

**Key decision**: Tabs stay mounted with CSS-hidden architecture. Motion only animates opacity/transform on the active panel. This preserves chart state, scroll position, and WebSocket subscriptions.

### 2.6 Glass Effects

- Bottom nav: `bg-[rgba(31,38,47,0.60)] backdrop-blur-xl`
- Ghost borders: `border-outline-variant/10` or `/15` only
- Active tab glow: `shadow-[0_0_8px_rgba(105,218,255,0.15)]`
- Floating panels: `bg-surface-container-high/80 backdrop-blur-xl`

### 2.7 Global CSS Patterns

- Scrollbar: 4px width, `#0a0f14` track, `#1f262f` thumb
- Selection: `selection:bg-primary/30`
- No-border philosophy: depth via surface color tiers, not `border-*`
- Labels: `text-[10px] uppercase tracking-widest text-on-surface-variant`
- `.tabular` utility: `font-feature-settings: "tnum"; font-variant-numeric: tabular-nums;`
- `.glass-card` update: `border-radius: 0.25rem` (was `0.5rem`)
- `pulseGlow` keyframe updated to cyan `rgba(0, 207, 252, ...)` (was gold)

### 2.8 Safelist Updates

New dynamic token/opacity combos to add to Tailwind safelist:
- `text-tertiary-dim`, `text-error`, `text-primary`
- `bg-tertiary-dim/10`, `bg-tertiary-dim/20`, `bg-error/10`, `bg-error/20`
- `border-tertiary-dim/30`, `border-error/30`, `border-outline-variant/10`, `border-outline-variant/15`

Existing `text-long`, `text-short`, `bg-long/*`, `bg-short/*` safelist entries remain valid via legacy aliases.

---

## 3. Navigation Architecture

### 3.1 Bottom Nav (5 tabs, unchanged)

| Tab | Lucide Icon | Active Color |
|---|---|---|
| Home | `Home` | `#00cffc` |
| Chart | `BarChart3` | `#00cffc` |
| Signals | `Zap` | `#00cffc` |
| News | `Newspaper` | `#00cffc` |
| More | `MoreHorizontal` | `#00cffc` |

Active tab: cyan color, glow shadow, `strokeWidth={2.5}`.
Inactive: outline icon, `#a7abb3`, `strokeWidth={1.5}`.
Labels: Inter 10px uppercase tracking-wider.

### 3.2 Context-Aware Header

**Market tabs** (Home, Chart, Signals, News):
- Left: "KRYPTON" branding (Space Grotesk bold) + divider + selected pair name (cyan)
- Right: 24h change badge (green/red) + search icon
- Fixed position, `h-14`, `bg-surface`

**More tab + sub-pages**:
- Left: Terminal icon + "Engine Control" (Space Grotesk bold, cyan)
- Right: Settings gear icon
- Fixed position, `h-14`, `bg-surface`

### 3.3 More Hub Navigation

3 clusters with chevron navigation:

**Execution Layer**: Engine Dashboard, Backtest
**Intelligence Hub**: ML Training, Alerts
**Safety & Security**: Risk, Settings

Plus System/Diagnostics accessible from the connection status card at bottom.

Sub-pages render inline (replace hub content), with back button in header. Settings and Risk are currently embedded as inline sections in `MorePage.tsx` — they will be **extracted into separate component files** (`SettingsView.tsx`, `RiskView.tsx`) to become navigable sub-pages matching the Stitch design.

### 3.4 Pair Deep Dive

Drill-down view, not a tab. Accessible from:
- Home: tap an open position
- Signals: tap a signal card

Slides up as a sheet/overlay via `AnimatePresence`. Back button returns to previous view.

**State management**: A small `drillDown` state is needed in `Layout.tsx` (or a new Zustand `navigation` store) to track:
- `activeDrillDown: 'pair-deep-dive' | null`
- `drillDownPair: string | null` (e.g., "BTC-USDT-SWAP")

This is the one non-visual change in this spec. HomeView and SignalCard will need an `onPairDrillDown(pair)` callback prop threaded from Layout.

---

## 4. Screen Designs

### 4.1 Home (Dashboard)

- **Account bento**: Balance card (2-col span) with equity, unrealized P&L, deposit/withdraw buttons. Quick stats grid: available balance, margin use %, exposure, win rate.
- **Open positions**: Cards with direction badge (LONG/SHORT + leverage), pair name, P&L %, entry/mark/liq prices in sub-row. **Tappable → opens Pair Deep Dive.**
- **High-conviction signals**: List with score, pattern context, timestamp. Performance bar (win/loss ratio).
- **Market intelligence**: 3 news cards with impact dots (high=error, mid=primary, neutral=outline).

### 4.2 Chart

- **Timeframe bar**: 15M/1H/4H/1D/1W pill buttons below header. Active = `bg-surface-container-highest text-primary`.
- **Chart area**: Lightweight-charts rendering unchanged. Theme colors updated. OHLC overlay top-left.
- **Floating indicator panel**: Bottom center, glass panel with 3 groups (Moving Averages, Overlays, Oscillators). Active indicators get `border-primary/20 bg-primary/10`.
- **BUY/SELL FABs**: Fixed bottom-right, stacked. BUY = `bg-tertiary-container`, SELL = `bg-error`.

### 4.3 Signals Feed

- **Filter tabs**: All/Active/Traded/Skipped in pill group with `bg-surface-container-lowest` wrapper.
- **Signal cards**: Border `border-outline-variant/15`. Header: pair + direction badge + score with progress bar. Pattern badges row. Price grid (2x2): entry, SL, TP1, TP2. Footer: risk %, R:R, status indicator, Execute button. **Tappable → opens Pair Deep Dive.**
- **Connection status**: Green dot + "Connected (Live OKX Feed)" in header.

### 4.4 Signal Deep-Dive

- **Hero score**: Large score number with circular SVG gauge, sentiment label.
- **Bento**: Timeframe + trend strength.
- **Execution matrix**: 2x2 grid of entry/SL/TP1/TP2 with colored left borders (primary/error/tertiary).
- **Intelligence components**: Progress bars for Tech Analysis, Order Flow, On-Chain, LLM scores.
- **Pattern badges**: Pill badges with check icons.
- **AI synthesis**: Text block with highlighted spans.
- **Journal actions**: 3-button row — Traded (primary), Skipped, Add Note.

### 4.5 News Feed

- **Filters**: Category pills (All/Crypto/Macro) + impact level toggles (High/Medium/Low with colored dots).
- **Articles**: Left border colored by impact (error=high, primary=mid, outline=low). Headline (Space Grotesk), sentiment badge, affected pair chips with % change.
- **AI summary**: Expandable on high-impact articles. Bullet points with primary-colored dots.
- **FAB**: Notification bell, bottom-right.

### 4.6 More (System Hub)

- Terminal grid background effect (CSS gradient).
- Header: "System Hub" title + version label.
- 3 navigation clusters, each with icon tiles, labels, descriptions, chevrons.
- Connection status card at bottom with uptime badge and encrypted node info.

### 4.7 Settings (extracted to separate component)

- **Active pairs**: 3-col button grid with active `border-primary` bottom border.
- **Signal threshold**: Slider with diamond thumb, min/max labels.
- **Toggles**: On-chain scoring, news alerts, push notifications. Custom toggle with glow on active.
- **LLM window**: 15m/30m/60m pill selector.
- **API endpoint**: Mono font display with copy icon, connection latency, SSL status.
- **Version**: System operational indicator.

### 4.8 Alerts Dashboard

- **Create form**: Alert type (Signal/Price), label input, condition builder (pair + operator + value), urgency pills (Low/Med/High), notification channels (checkboxes).
- **Active alerts**: List with colored left borders by urgency, toggle/edit/delete actions.
- **History**: Terminal-style log with timestamps, TRIGGER/ERROR/SYSTEM labels, status indicators.

### 4.9 Risk Management (extracted to separate component)

- **Margin config**: Isolated/Cross toggle, max position size with progress bar, leverage cap dropdown, equity buffer.
- **Equity allocation**: Risk per trade slider with Conservative/Aggressive labels, capital utilization donut chart.
- **Risk heatmap**: Per-pair cards with alert level badges and colored left borders.
- **Risk log**: Terminal-style log with monospace font.

### 4.10 Journal & Analytics

- **Period selector**: 7D/30D/All pill group.
- **Summary bento**: Net P&L (large, with border-left accent), win rate, avg R:R, signal count with pair avatars.
- **Equity curve**: SVG area chart with gradient fill.
- **Pair performance**: Cards per pair with icon, win rate, P&L %, signal count.

### 4.11 Backtest Dashboard

- Reskin existing `BacktestSetup.tsx`, `BacktestResults.tsx`, `BacktestCompare.tsx` to match Stitch Backtest Dashboard screen. Same component structure, new visual treatment.

### 4.12 ML Training Dashboard

- Reskin existing `MLTrainingView.tsx` to match Stitch ML Training Dashboard screen.

### 4.13 Engine Dashboard (NEW)

- Pipeline status cards: active instances, latency, scoring weights.
- Per-pair engine state visualization.
- Located under More > Execution Layer > Engine.

### 4.14 System / Diagnostics (NEW)

- Connection health: WebSocket status, Redis, DB.
- Uptime logs, terminal-style.
- Located under More (accessible from connection status card).

### 4.15 Pair Deep Dive (NEW)

- Per-pair analysis: score breakdown, order flow snapshot, on-chain data, recent signals.
- Drill-down from Home (position tap) or Signals (signal card tap).
- Slides up as overlay with `AnimatePresence`.

---

## 5. New Dependencies

| Package | Purpose | Size (gzip) |
|---|---|---|
| `lucide-react` | Icon library | ~5KB (tree-shaken) |
| `motion` | Animation library | ~18KB |
| Space Grotesk | Headline font (Google Fonts CSS import) | ~15KB woff2 |

---

## 6. File Change Summary

### Modified (~40 files)

**Foundation (4)**:
- `src/shared/theme.ts` — New M3 color palette, fonts, radii, chart/indicator colors, legacy aliases, extended palette
- `tailwind.config.ts` — Wire new theme tokens, add `rounded-pill`, update `pulseGlow` keyframe to cyan, update safelist
- `src/index.css` — New base styles, scrollbar, `.tabular` utility, `.glass-card` radius, remove gradient body, update CSS vars
- `index.html` — Add Space Grotesk font link, update `theme-color` meta to `#0a0f14`

**Shared components (2)**:
- `src/shared/components/Layout.tsx` — Context-aware header, glass nav, Lucide icons, motion tab transitions (opacity/transform, not mount/unmount), Pair Deep Dive overlay state
- `src/shared/components/TickerBar.tsx` — Restyle to KRYPTON branding + pair + change badge

**Feature components (~34)**:
- `features/home/components/HomeView.tsx` — Add `onPairDrillDown` callback prop
- `features/home/components/RecentSignals.tsx`
- `features/chart/components/ChartView.tsx`
- `features/chart/components/IndicatorSheet.tsx`
- `features/signals/components/SignalsView.tsx`
- `features/signals/components/SignalFeed.tsx`
- `features/signals/components/SignalCard.tsx` — Add `onPairDrillDown` callback prop
- `features/signals/components/SignalDetail.tsx`
- `features/signals/components/DeepDiveView.tsx`
- `features/signals/components/ConnectionStatus.tsx`
- `features/signals/components/PatternBadges.tsx`
- `features/signals/components/JournalView.tsx`
- `features/signals/components/AnalyticsView.tsx`
- `features/signals/components/CalendarView.tsx`
- `features/news/components/NewsView.tsx`
- `features/news/components/NewsFeed.tsx`
- `features/news/components/NewsCard.tsx`
- `features/more/components/MorePage.tsx` — Refactored: hub only, sub-pages extracted
- `features/alerts/components/AlertsPage.tsx`
- `features/alerts/components/AlertList.tsx`
- `features/alerts/components/AlertForm.tsx`
- `features/alerts/components/AlertHistoryList.tsx`
- `features/alerts/components/QuietHoursSettings.tsx`
- `features/backtest/components/BacktestView.tsx`
- `features/backtest/components/BacktestSetup.tsx`
- `features/backtest/components/BacktestResults.tsx`
- `features/backtest/components/BacktestCompare.tsx`
- `features/ml/components/MLTrainingView.tsx`
- `features/trading/components/OrderDialog.tsx`

### New files (~9)

- `src/shared/components/EngineHeader.tsx` — Engine Control header for More tab
- `src/shared/components/SubPageShell.tsx` — Shared wrapper for More sub-pages (back button + title)
- `features/more/components/SettingsView.tsx` — Extracted from MorePage inline settings
- `features/more/components/RiskView.tsx` — Extracted from MorePage inline risk section
- `features/engine/components/EngineDashboard.tsx` — Engine Dashboard view
- `features/system/components/SystemDiagnostics.tsx` — System/Diagnostics view
- `features/signals/components/PairDeepDive.tsx` — Pair Deep Dive drill-down view

### Untouched (explicitly verified)

- All hooks: `useSignalWebSocket`, `useChartData`, `useLivePrice`, `useAccount`, `useNews`, `useServiceWorker`, `useSignalStats`
- All stores: `signals/store.ts`, `settings/store.ts`, `news/store.ts`, `alerts/store.ts`, `backtest/store.ts`
- All type definitions
- `shared/lib/api.ts`, `shared/lib/constants.ts`, `shared/lib/format.ts`
- `shared/lib/haptics.ts`, `shared/lib/push.ts`, `shared/lib/websocket.ts`
- `features/chart/components/CandlestickChart.tsx` (internals unchanged, receives new theme colors via `theme.chart`)
- `features/chart/lib/indicators.ts`
- `features/dashboard/hooks/useAccount.ts`
- Backend (zero changes)
- All test files (visual changes only)

**Components covered by legacy aliases** (will render with new colors, no structural changes needed):
- `src/shared/components/UpdateModal.tsx` — uses `text-accent`, `bg-card` → covered by aliases
- `features/news/components/NewsAlertToast.tsx` — uses `text-long`, `bg-long/10` → covered
- `features/alerts/components/AlertToast.tsx` — uses `text-long`, `text-short` → covered

---

## 7. Implementation Plans

Work is split into 3 sequential plans, each with its own implement → verify cycle.

### Plan 1: Foundation + Layout (~10 files)

Must complete first — all other plans depend on this.

1. Install dependencies (`lucide-react`, `motion`)
2. `src/shared/theme.ts` — Full M3 palette, fonts, radii, chart/indicator colors, legacy aliases, extended palette
3. `tailwind.config.ts` — Wire new theme, add `rounded-pill`, update `pulseGlow`, update safelist
4. `src/index.css` — Base styles, scrollbar, `.tabular`, `.glass-card` radius, remove gradient, update CSS vars
5. `index.html` — Space Grotesk font link, `theme-color` meta
6. `src/shared/components/Layout.tsx` — Context-aware header, glass nav, Lucide icons, motion tab transitions, drill-down state
7. `src/shared/components/TickerBar.tsx` — KRYPTON branding + pair + change badge
8. `src/shared/components/EngineHeader.tsx` (new) — Engine Control header
9. `src/shared/components/SubPageShell.tsx` (new) — Back button + title wrapper
10. Verify: `pnpm build` passes, app loads, nav works

### Plan 2: Core Views (~25 files)

The 5 main tabs and their direct sub-components. Can proceed in any order once Plan 1 is done.

**Home**:
- `features/home/components/HomeView.tsx`
- `features/home/components/RecentSignals.tsx`

**Chart**:
- `features/chart/components/ChartView.tsx`
- `features/chart/components/IndicatorSheet.tsx`

**Signals** (feed + detail):
- `features/signals/components/SignalsView.tsx`
- `features/signals/components/SignalFeed.tsx`
- `features/signals/components/SignalCard.tsx`
- `features/signals/components/SignalDetail.tsx`
- `features/signals/components/DeepDiveView.tsx`
- `features/signals/components/ConnectionStatus.tsx`
- `features/signals/components/PatternBadges.tsx`

**News**:
- `features/news/components/NewsView.tsx`
- `features/news/components/NewsFeed.tsx`
- `features/news/components/NewsCard.tsx`

**More** (hub only):
- `features/more/components/MorePage.tsx` — Refactored to hub, sub-pages extracted

**Trading**:
- `features/trading/components/OrderDialog.tsx`

Verify: `pnpm build` passes, all 5 tabs render correctly with new design

### Plan 3: Sub-pages + New Views (~12 files)

More sub-pages (extracted/reskinned) and net-new views. Lowest priority.

**Extracted sub-pages**:
- `features/more/components/SettingsView.tsx` (new, extracted from MorePage)
- `features/more/components/RiskView.tsx` (new, extracted from MorePage)
- `features/alerts/components/AlertsPage.tsx`
- `features/alerts/components/AlertList.tsx`
- `features/alerts/components/AlertForm.tsx`
- `features/alerts/components/AlertHistoryList.tsx`
- `features/alerts/components/QuietHoursSettings.tsx`
- `features/signals/components/JournalView.tsx`
- `features/signals/components/AnalyticsView.tsx`
- `features/signals/components/CalendarView.tsx`
- `features/backtest/components/BacktestView.tsx`
- `features/backtest/components/BacktestSetup.tsx`
- `features/backtest/components/BacktestResults.tsx`
- `features/backtest/components/BacktestCompare.tsx`
- `features/ml/components/MLTrainingView.tsx`

**New views**:
- `features/engine/components/EngineDashboard.tsx` (new)
- `features/system/components/SystemDiagnostics.tsx` (new)
- `features/signals/components/PairDeepDive.tsx` (new)

Verify: `pnpm build` passes, all sub-pages and new views render correctly

---

## 8. Indicator Colors

`theme.indicators` updated to match new palette:
- `ema21`: `#00cffc` (was `#F0B90B` gold → now primary cyan)
- `ema50`: `#69daff` (was `#3B82F6`)
- `rsi`: `#00cffc` (was `#F0B90B`)
- `macd`: `#69daff` (was `#3B82F6`)
- `stochK`: `#56ef9f` (was `#10B981`)
- `stochD`: `#ff716c` (was `#EF4444`)
- `ichSenkouA`: `#56ef9f` (was `#0ECB81`)
- `ichSenkouB`: `#ff716c` (was `#F6465D`)
- `curveColors`: `["#00cffc", "#56ef9f", "#ff716c", "#69daff"]`

Other indicator colors (`ema200`, `sma*`, `psar`, `pivots`, `cci`, `atr`, `adx`, etc.) remain unchanged — they use the extended palette which carries over.

---

## 9. Reference

Stitch screen HTML files stored at `web/.stitch-screens/` for reference during implementation:
- `dashboard.html`, `chart.html`, `signals.html`, `news.html`, `more.html`
- `settings.html`, `alerts.html`, `risk.html`, `signal-deepdive.html`
- `journal.html`, `backtest.html`, `ml-training.html`
- `engine.html`, `system.html`, `pair-deepdive.html`
