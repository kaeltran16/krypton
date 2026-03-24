# Settings Page Redesign

## Overview

Full visual redesign of the Settings page to match the quality bar of other redesigned pages (Engine, Risk, ML Training, System Diagnostics). The current page has inconsistent button styles, flat section layout, missing headline fonts, and a redundant System section.

## Current State

- **SettingsPage.tsx**: 3 groups (Trading, Notifications, System) using `SettingsGroup` wrapper
- **SettingsGroup.tsx**: Generic container with `border-b` dividers between items
- **3 different button selection styles**: pairs (border-b-2), timeframes (border + primary/20), news window (bg + border)
- **Native `<input type="range">`** for threshold slider
- **System section** duplicates SystemDiagnostics with hardcoded fake data ("Latency: —", "SSL: Active", version "1.0.0")

## Design

### Layout

Single scrollable page with two section groups separated by colored section labels. No tabs, no SegmentedControl. Each setting is a self-contained card.

### Structure

```
Settings Page
├── Section Label: "Trading" (text-primary, uppercase, tracking-widest)
│   ├── Card: Pairs (pill multi-select: BTC / ETH / WIF)
│   ├── Card: Timeframes (pill multi-select: 15m / 1h / 4h)
│   ├── Card: Signal Threshold (styled range slider + large value display)
│   ├── Card: On-Chain Scoring (toggle + description)
│   ├── Card: News Alerts (toggle + description)
│   └── Card: LLM News Window (pill select: 15m / 30m / 60m)
├── Section Label: "Notifications"
│   ├── Card: Push Notifications (toggle + error state)
│   └── Card: Quiet Hours (toggle + expandable start/end/timezone)
```

### Cards

Each card uses the same container styling as RiskPage's `RiskSection` (without the status icon):
- `bg-surface-container border border-outline-variant/10 rounded-lg p-4`
- Card title: `font-headline text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant`
- `space-y-3` between cards, `mb-2` for section labels

### Section Labels

Styled as colored headers above card groups:
- `text-[10px] font-bold text-primary uppercase tracking-widest opacity-80 px-1 mb-2`

### Pill Buttons (Unified)

All multi-select buttons (pairs, timeframes, news window) use the same style:

**Active state:**
- `bg-primary/15 text-primary border border-primary/30 rounded-lg font-bold`

**Inactive state:**
- `bg-surface-container-lowest text-on-surface-variant rounded-lg`

**Layout:**
- `flex gap-3`, each button `flex-1` for equal width (applies to all: pairs, timeframes, news window)
- `min-h-[44px] py-2 text-sm font-medium` — 44px minimum height for touch target compliance (Apple HIG)

### Signal Threshold Slider

Replace native `<input type="range">` with a styled version:
- Keep the native `<input type="range">` for accessibility and functionality
- Add `aria-label="Signal threshold"` and ensure `aria-valuemin`, `aria-valuemax`, `aria-valuenow` are set
- Style with CSS: custom track (`bg-surface-container-lowest`, 6px height, rounded) and thumb (`bg-primary`, 18px, rounded-full with glow shadow)
- Large value display: `font-headline text-2xl font-bold tabular-nums text-primary` (right-aligned in header row)
- Endpoint labels: `text-[10px] font-mono text-outline`

### Toggle Cards

For On-Chain Scoring, News Alerts, Push Notifications:
- Row layout: `flex items-center justify-between`
- Label + optional description on left
- `Toggle` component on right
- Description text: `text-[11px] text-on-surface-variant mt-0.5`

### Quiet Hours Card

The `QuietHoursSettings` component renders its own "Quiet Hours" label, toggle, and expand/collapse logic internally. To avoid duplicating the label, the Quiet Hours card does NOT add its own card title — it wraps `QuietHoursSettings` in a card container only. The component's internal label styling is updated to match the card title pattern (`font-headline text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant`) for visual consistency.

## Changes

### Files Modified

- **`web/src/features/settings/components/SettingsPage.tsx`** — full rewrite
  - Remove System section (API endpoint, version, connection status)
  - Remove `SettingsGroup` usage
  - Replace pair buttons with unified pill style (drops full coin names — `PAIR_NAMES` map removed, shows only ticker: BTC / ETH / WIF)
  - Replace timeframe buttons with unified pill style
  - Replace news window buttons with unified pill style
  - Add styled slider for threshold
  - Wrap each setting in its own card
  - Add section labels
  - Remove imports: `useSignalStore` (no longer needed for connection status)

### Files Deleted

- **`web/src/features/settings/components/SettingsGroup.tsx`** — no longer used

### Files Minimally Modified

- **`web/src/features/alerts/components/QuietHoursSettings.tsx`** — update "Quiet Hours" label styling to match card title pattern (`font-headline text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant`). No structural changes.

### Files Unchanged

- `store.ts` — no state changes needed
- `types.ts` — no type changes needed
- `store.test.ts` — store behavior unchanged

### Store Changes

- `apiBaseUrl` field remains in the store/types but is no longer exposed in the UI. It stays in localStorage persistence for programmatic use.

## No New Dependencies

All components used already exist in the codebase:
- `Toggle` from `shared/components/Toggle`
- `QuietHoursSettings` from `alerts/components/QuietHoursSettings`
- CSS custom properties from `shared/theme.ts`

### Preserved Behaviors

The following existing behaviors carry over from the current implementation unchanged:
- **Sync error banner** — `bg-error/10 border border-error/30` message at top when sync fails, with `role="alert"` for screen reader announcement
- **Loading skeleton** — pulse-animated placeholder cards while initial fetch is in-flight
- **Push notification error state** — "Permission denied" text on toggle failure

## Testing

- Existing `store.test.ts` continues to pass unchanged
- Manual verification: all 8 settings cards render, toggles work, pill buttons toggle correctly, slider updates threshold, quiet hours expand/collapse
- `pnpm build` passes (TypeScript check)
