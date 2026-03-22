# Backtest Page Improvements — Design Spec

## Overview

Improve the backtesting page across four areas: visual consistency (M3 token migration), setup UX (collapsible sections), results enrichment (per-pair breakdown + trade filtering/sorting), and compare tab upgrades (config summary labels + config diff table).

All changes are frontend-only — no backend modifications required.

## Phase 1: Visual Consistency — M3 Token Migration

### Problem

Three components (`ParameterOverridePanel`, `OptimizeTab`, `ApplyModal`) use legacy theme classes (`text-muted`, `bg-card`, `text-accent`, etc.) instead of the M3 design tokens used everywhere else. Additionally, `BacktestResults` and `BacktestCompare` use `text-tertiary-dim` for positive values instead of `text-long`/`text-short` used throughout the rest of the app.

### Token Mapping

| Old class | New M3 class |
|---|---|
| `text-muted` | `text-on-surface-variant` |
| `text-foreground` | `text-on-surface` |
| `hover:text-foreground` | `hover:text-on-surface` |
| `bg-surface` | `bg-surface-container` |
| `bg-surface/50` | `bg-surface-container/50` |
| `bg-card` | `bg-surface-container` |
| `border-border` | `border-outline-variant` |
| `border-border/50` | `border-outline-variant/30` |
| `border-border/30` | `border-outline-variant/10` |
| `text-accent` | `text-primary` |
| `border-accent` | `border-primary` |
| `bg-accent/20` | `bg-primary/15` |
| `hover:bg-accent/30` | `hover:bg-primary/30` |
| `hover:text-accent/80` | `hover:text-primary/80` |
| `text-red-400` | `text-error` |

### Chart Color Alignment

`BacktestResults.tsx:EquityCurve` uses `theme.colors.accent` as the JS line color. Migrate this to `theme.colors.primary` to match the M3 token system. This is a JS value, not a CSS class — update the `color` option passed to `chart.addSeries()`.

### Color Alignment

Replace all `tertiary-dim` color references with `long` equivalents for positive values:
- `text-tertiary-dim` → `text-long`
- `bg-tertiary-dim/` → `bg-long/`
- `border-tertiary-dim` → `border-long`

Files:
- `BacktestResults.tsx` (StatsStrip, TradeList, TradeDetail, OutcomeBadge, MonthlyPnl)
- `BacktestCompare.tsx` (run selection list on line 78 uses `text-tertiary-dim` for positive P&L — align to `text-long`/`text-short`)

### Files

- `web/src/features/backtest/components/ParameterOverridePanel.tsx`
- `web/src/features/backtest/components/OptimizeTab.tsx`
- `web/src/features/backtest/components/ApplyModal.tsx`
- `web/src/features/backtest/components/BacktestResults.tsx`
- `web/src/features/backtest/components/BacktestCompare.tsx`

## Phase 2: Setup UX — Collapsible Sections

### Problem

`BacktestSetup` has 8+ sections in a long vertical scroll. On mobile, users must scroll past rarely-changed settings to reach the Run button.

### Design

Modify the existing `Section` component to support collapsible behavior:

- **Always visible** (not collapsible): Pairs, Timeframe, Date Range
- **Collapsible, default collapsed**: Scoring Weights, Thresholds, ML Blending, Indicators, Risk & Levels, Historical Data
- **Self-collapsing (unchanged)**: Parameter Overrides — `ParameterOverridePanel` already has its own built-in collapse toggle and is not wrapped in a `Section` component, so it keeps its existing behavior. Only migrate its theme tokens (Phase 1).

#### Section Component Changes

Add props to `Section`:
- `collapsible?: boolean` — enables collapse behavior
- `defaultOpen?: boolean` — initial state (defaults to `false` for collapsible sections)
- `summary?: string` — one-line summary shown when collapsed

When collapsed, display the section header with a chevron and the summary text. When expanded, show full content.

#### Chevron Icon

Use an inline SVG chevron (matching the app's existing icon stroke width). Points **right** when collapsed, rotates **90° clockwise** (pointing down) when expanded. Apply `transition-transform duration-200` to the chevron. Size: 16×16px, `text-on-surface-variant`.

#### Accessibility

The section header must be a `<button>` (or have `role="button"` + `tabIndex={0}`). Required attributes:
- `aria-expanded={isOpen}` — reflects current collapse state
- `aria-controls={contentId}` — references the collapsible content `id`
- Keyboard support: Enter and Space toggle the section (native with `<button>`)

The collapsible content wrapper should have `id={contentId}` and `role="region"`.

#### Collapse Animation

Use the `grid-rows-[0fr]` / `grid-rows-[1fr]` pattern already established in `HomeView.tsx:OpenPositions` for smooth height transitions. Apply `transition-[grid-template-rows] duration-200 ease-out`.

Add `motion-reduce:transition-none` to the grid container so the collapse is instant when the user has `prefers-reduced-motion` enabled — consistent with the `motion-reduce:animate-none` pattern used elsewhere (e.g., `BacktestResults.tsx:21`).

#### Summary Strings

Each collapsible section shows a condensed summary of current values when collapsed:
- **Scoring Weights**: `"Tech 75% / Pattern 25%"`
- **Thresholds**: `"Signal ≥ 40"`
- **ML Blending**: `"Off"` or `"On · ≥ 65%"`
- **Indicators**: `"ADX RSI BB OBV + Patterns"` or `"ADX RSI BB OBV"`
- **Risk & Levels**: `"SL 1.5x · TP1 2.0x · TP2 3.0x · Max 3"`
- **Historical Data**: `"90d imported"` (if `importStatus` has data) or `"No data imported"` (default)

Note: Parameter Overrides is excluded — it has its own collapse behavior via `ParameterOverridePanel`.

### Files

- `web/src/features/backtest/components/BacktestSetup.tsx`

## Phase 3: Results Enrichment

### Problem

The results view lacks per-pair granularity and trade list navigation. With 40+ trades across multiple pairs, users can't quickly assess which pairs performed well or find specific trades.

### A) Per-Pair Breakdown

A new `PairBreakdown` component inserted between `StatsStrip` and `EquityCurve` in `ResultsContent`.

#### Layout

Cards use `grid grid-cols-1 sm:grid-cols-3 gap-2`. With 3 available pairs this fills one row on desktop and stacks vertically on mobile. Each card uses `bg-surface-container rounded-lg border border-outline-variant/10 p-3`.

#### Card Content

Each pair card shows:
- Pair name (abbreviated, e.g. "BTC/USDT")
- Trade count
- Win rate (colored `text-long` if ≥ 50%, `text-short` if < 50%)
- Net P&L (colored by sign)
- Avg R:R

#### Data Source

Computed client-side via `useMemo` from the existing `trades[]` array. Group by `trade.pair`, aggregate:
- `total`: count
- `wins`: count where outcome includes "TP" or equals "WIN"
- `win_rate`: wins / total * 100
- `net_pnl`: sum of `pnl_pct`
- `avg_rr`: for each trade with a non-null `exit_price`, compute `|exit_price - entry_price| / |entry_price - sl|`. Average across qualifying trades. Trades with `exit_price === null` are excluded from the average.

### B) Trade Filter Bar

Replace the plain `Trades ({count})` header with a filter/sort bar.

#### Filter Dimensions

- **Pair**: "All Pairs" (default) + one pill per pair present in trades
- **Direction**: "Both" (default), "Long", "Short"
- **Outcome**: "All" (default), "Wins", "Losses"

Active filter pills use `bg-primary/15 text-primary border-primary/30`. Inactive pills use `bg-transparent text-on-surface-variant border-outline-variant/30`.

Filter pills must use `min-h-[44px] px-3 py-2` to meet the 44px minimum touch target size.

#### Filter Bar Layout

Wrap all pills and the sort dropdown in a `flex flex-wrap gap-2` container. This allows pills to flow onto a second row on narrow screens instead of overflowing. Each filter group (Pair, Direction, Outcome) is separated by a thin `border-r border-outline-variant/20` divider, with the sort dropdown at the end.

#### Sort Options

Dropdown with options (add `aria-label="Sort trades"`):
- Date (newest) — default
- Date (oldest)
- P&L (high → low)
- P&L (low → high)
- Duration
- Score

#### Empty Filtered State

When filters match zero trades, display in place of the trade list:
```
<div className="py-12 text-center text-on-surface-variant">
  <p className="text-sm">No trades match filters</p>
  <button onClick={clearFilters} className="mt-2 text-xs text-primary">Clear filters</button>
</div>
```

The `clearFilters` handler resets all filter state to defaults (All Pairs, Both, All).

#### Filter Animation

When filters change and the trade list updates, apply `transition-opacity duration-150` to the trade list container for a subtle crossfade rather than an instant snap.

#### State Management

Filter and sort state lives in local `useState` within the `TradeList` component — ephemeral UI state, not persisted to Zustand.

The filtered/sorted trade list is computed via `useMemo` from trades + filter/sort state.

### Files

- `web/src/features/backtest/components/BacktestResults.tsx`

## Phase 4: Compare Tab Upgrades

### Problem

Compared runs are labeled "Run 1", "Run 2" with no config context. Users must remember which run used which parameters. There's also no way to see what actually changed between runs.

### A) Config Summary Labels

Replace bare "Run N" labels with config summary cards. Each card shows:
- Color dot + "Run N" label
- Condensed config: pairs (abbreviated) · timeframe · signal threshold · SL multiplier
- Run date

Format: `"BTC, ETH · 15m · Thresh 40 · SL 1.5x"` — always shows the same four fields for consistency. The `ConfigDiff` table (Phase 4B) handles detailed parameter comparison separately.

These labels appear in:
1. The run selection list (replacing the current simple text)
2. Column headers in the comparison metric table
3. Legend items under the equity curve chart

#### Config Fingerprint Logic

Static label — always includes the same fields regardless of which runs are selected:

```
function configLabel(config: BacktestConfig): string {
  const pairs = config.pairs.map(p => p.replace("-USDT-SWAP", "")).join(", ");
  return `${pairs} · ${config.timeframe} · Thresh ${config.signal_threshold} · SL ${config.sl_atr_multiplier}x`;
}
```

### B) Config Diff Table

A new `ConfigDiff` component inserted between `CompareEquityCurves` and `CompareTable`.

#### Behavior

- Compare `config` objects across all selected runs
- Show only parameters where values differ between any two runs
- All differing values are highlighted equally — each run's column uses its assigned curve color (`CURVE_COLORS[i]`) as the text color with `font-bold`, so no single run is treated as the "baseline"
- Footer text: `"N of M parameters differ — identical parameters hidden"`
- If all parameters are identical, show: `"All parameters identical across runs"`

#### Config Keys to Compare

```
signal_threshold, tech_weight, pattern_weight, enable_patterns,
sl_atr_multiplier, tp1_atr_multiplier, tp2_atr_multiplier,
max_concurrent_positions, ml_enabled, ml_confidence_threshold
```

Display labels map these to human-readable names (e.g. `signal_threshold` → "Signal Threshold").

**Excluded from diff:** `pairs`, `timeframe`, `date_from`, `date_to` — these are already visible in the config summary labels (Phase 4A) and would add noise to the diff table since they almost always differ.

### Files

- `web/src/features/backtest/components/BacktestCompare.tsx`

## Render Order (ResultsContent)

After all changes, the results view renders:
1. `StatsStrip` — summary metrics
2. `PairBreakdown` — per-pair stats (new)
3. `EquityCurve` — equity chart
4. `MonthlyPnl` — monthly grid
5. `TradeList` — with filter bar (enhanced)

## Render Order (Compare Tab)

After all changes, the compare results render:
1. `CompareEquityCurves` — overlaid equity curves
2. `ConfigDiff` — parameter differences (new)
3. `CompareTable` — side-by-side metrics

## Non-Goals

- No backend changes
- No new API endpoints
- No new Zustand store fields (all new state is local component state)
- No new dependencies
- No changes to the backtest types or data model
