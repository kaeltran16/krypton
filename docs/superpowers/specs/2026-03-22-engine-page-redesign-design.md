# Engine Page Redesign — Design Spec

**Date:** 2026-03-22
**Status:** Approved

## Problem

The engine feature has two separate pages accessible from the More menu:

1. **EnginePage** — a long accordion list of every pipeline parameter, visually monotonous
2. **EngineDashboard** — a summary view with vanity metrics (parameter count) and a 2x2 grid showing 2 params per category

They feel redundant. The dashboard wastes space on low-value info, while the parameter list lacks visual hierarchy — every section looks identical.

## Solution

Merge into a single unified engine page with a hybrid layout: a compact summary strip at the top (source weights + key thresholds), then parameter categories with visual differentiation based on importance.

## Layout (top to bottom)

### 1. Summary Strip

- Title "Engine Parameters" with a Refresh icon button (right-aligned, `RefreshCw` icon, accent color, min 44×44px tap area via `p-2`, shows spinning animation during refresh via `animate-spin` while store `loading` is true)
- Source weight bar — horizontal stacked bar showing tech/order_flow/onchain/pattern weights with percentage labels and color-coded source names below
  - Accessibility: `aria-label` on the bar container summarizing all weights (e.g. "Source weights: tech 40%, order_flow 25%, onchain 20%, pattern 15%"), built dynamically from data
  - Always show percentage labels below the bar alongside source names (not inside segments via `title` tooltip, which doesn't work on mobile)
- Key thresholds row — uses `<dl>` with `<dt>`/`<dd>` pairs for semantic label-value association, wrapped in `flex flex-wrap gap-2`:
  - Signal threshold (e.g. `45.0`)
  - LLM threshold (e.g. `30.0`)
  - ML Blend weight (e.g. `0.30`)
  - Each card: `min-w-[5.5rem] flex-1` so they display 3-across on wider screens and wrap to 2+1 on narrow (≤375px). Uppercase accent-colored `<dt>` label on top, monospace `<dd>` value below, `surface-container` background, `rounded-lg`

### 2. Blending (Hero Category)

- Visual treatment: `border-l-2 border-primary`, `bg-surface-container` background — stands out from other categories
- Default open
- Contains: source weight detail rows, ml_blend_weight, thresholds (signal, LLM, confluence)
- **LLM Factor Weights** renders as a `sub` variant nested inside this hero section (not as a sibling category). It contains the individual factor weight rows plus `factor_cap` as the last row.
- The weight bar in the summary strip provides the at-a-glance view; this section has the full detail

### 3. Top-Level Categories (Standard)

Closed by default. Categories:
- Technical — Indicators
- Order Flow
- On-Chain — BTC
- On-Chain — ETH
- Levels & ATR
- ATR Guardrails
- Phase 1 Scaling
- Pattern Strengths
- Performance Tracker
- Optimization Guardrails

Visual treatment: `border border-border/50`, `bg-surface-container-low` header (not `bg-surface/50` — at 50% opacity on the `#080c12` background, surface is nearly invisible; use the opaque `surface-container-low` token instead for reliable contrast). Standard font weight. Slightly more prominent than sub-categories.

### 4. Sub-Categories

These are detail sections under a parent concept:
- **Sigmoid Params** and **Mean Reversion** (under Technical — rendered as siblings directly after "Technical — Indicators")
- **LLM Factor Weights** (under Blending — rendered as a nested child inside the hero section's expanded content)

Visual treatment: dimmer text color (`text-muted`), left indent (`ml-2`), thinner/lighter borders (`border-border/30`), smaller border-radius. They read as "detail" without needing explicit group wrappers.

### 5. Per-Pair Zone

Visually separated from global params above via extra spacing.

- Container: subtle accent-tinted border (`border-primary/20`), `rounded-xl`, inner padding, `bg-surface-container-low` background
- Label: "Per-Pair Parameters" in primary color, uppercase, tracked
- Pair/timeframe dropdowns: row below the label (not inline — on narrow screens inline placement causes crowding), using existing `Dropdown` component with `size="sm"`, `flex gap-2`
- Empty state: if the selected pair/timeframe combo has no regime or ATR data, show `text-muted text-xs text-center py-4` message: "No data for this pair/timeframe"
- Inside the zone:
  - **Regime Weights** — existing `RegimeGrid` component (inner caps + outer weights tables)
  - **Learned ATR** — sl_atr, tp1_atr, tp2_atr, last_optimized, signal_count rows

## Component Changes

### `SourceBadge`

- Only renders when `source === "configurable"` (return `null` for hardcoded — clean rows)
- Displays a single character "c" instead of the full word
- Styling: small pill, green-tinted background (`bg-green-500/15 text-green-400`), `text-[10px]` (bumped from 9px — 9px is below the 12px body minimum; 10px is acceptable for a badge)

### `ParameterCategory`

Add a `variant` prop: `"hero" | "standard" | "sub"`

| Variant    | Border                          | Background               | Header text                    | Indent |
|------------|---------------------------------|--------------------------|--------------------------------|--------|
| `hero`     | `border-l-2 border-primary`     | `bg-surface-container`   | `text-foreground font-semibold` | none   |
| `standard` | `border border-border/50`       | `bg-surface-container-low` | `text-foreground font-medium`  | none   |
| `sub`      | `border border-border/30`       | `bg-surface/30`          | `text-muted text-sm`           | `ml-2` |

Default: `"standard"` (backward compatible).

Accessibility & interaction:
- Add `aria-expanded={open}` to the accordion button element
- Bump header padding to `py-3` (from `py-2.5`) to ensure 44px minimum touch target height
- Add expand/collapse transition: wrap content in a container with `transition-all duration-200` and `overflow-hidden`, toggling `max-height` (or use `grid-rows` animation pattern: `grid grid-rows-[0fr]` → `grid-rows-[1fr]`)

### `ParameterRow`

No changes needed — already displays name, value, and source badge.

### `WeightBar`

Changes needed:
- Add `aria-label` to the bar container, dynamically built from weights (e.g. "Source weights: tech 40%, order_flow 25%, onchain 20%, pattern 15%")
- Move percentage labels from inside the colored segments to the label row below the bar — show `name (pct%)` per source. This avoids reliance on `title` tooltips (which don't work on mobile) and fixes contrast issues (black text on dark-colored segments)
- Remove `title` attribute from segments
- Used both in summary strip (standalone) and inside Blending category detail

### `RegimeGrid`

No changes needed.

### `EnginePage`

- Restructure JSX to implement the layout above
- Move weight bar + key threshold extraction to summary strip
- Apply `variant` props to categories
- Wrap pair/timeframe section in the per-pair zone container

### `EngineDashboard`

**Delete entirely.** Its useful parts (weight bar, threshold display) are absorbed into the summary strip.

### `MorePage`

- Remove `"engine-dashboard"` from `SubPage` type, `CLUSTERS`, `PAGE_TITLES`, and the rendering switch
- Remove `EngineDashboard` import
- Single "Engine" entry remains

### `EngineHeader`

Already exists as a shared component. No changes needed — it's used by the SubPageShell.

## Files Affected

| File | Action |
|------|--------|
| `web/src/features/engine/components/EnginePage.tsx` | Rewrite layout |
| `web/src/features/engine/components/ParameterCategory.tsx` | Add `variant` prop, `aria-expanded`, `py-3`, accordion animation |
| `web/src/features/engine/components/SourceBadge.tsx` | Show only for configurable, display "c", bump to `text-[10px]` |
| `web/src/features/engine/components/WeightBar.tsx` | Add `aria-label`, move percentages to label row, remove `title` |
| `web/src/features/engine/components/EngineDashboard.tsx` | Delete |
| `web/src/features/more/components/MorePage.tsx` | Remove engine-dashboard entry |

## What Stays the Same

- Store (`engine/store.ts`) — no changes, same fetch/refresh pattern
- Types (`engine/types.ts`) — no changes
- API endpoint (`/api/engine/parameters`) — no changes
- `RegimeGrid`, `ParameterRow` — no changes
- Backend — no changes

## Design Decisions

1. **Hybrid summary over pure dashboard** — vanity metrics like "87 parameters" don't help. The weight bar and 3 key thresholds are the numbers you'd actually glance at.
2. **Visual hierarchy over grouping** — 12 categories is scannable as a flat list when visual weight guides the eye. Adding group headers creates organizational overhead without helping you find things faster.
3. **Per-pair zone separation** — global vs contextual params is a real conceptual boundary worth showing visually, not hiding in the same flat list.
4. **Badge minimalism** — "c" instead of "configurable" on only tunable params. Hardcoded is the default assumption; only call out what's tunable.
