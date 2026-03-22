# Engine Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge EngineDashboard and EnginePage into a single unified engine page with a summary strip, visual category hierarchy (hero/standard/sub variants), and a per-pair zone.

**Architecture:** Modify 4 existing components (SourceBadge, WeightBar, ParameterCategory, EnginePage), delete 1 (EngineDashboard), and clean up 1 navigation file (MorePage). No new files, no store/type/API changes. Pure presentational refactor.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v3, Zustand, lucide-react

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `web/src/features/engine/components/SourceBadge.tsx` | Modify | Return null for hardcoded, show "c" for configurable, bump font |
| `web/src/features/engine/components/WeightBar.tsx` | Modify | Add aria-label, move % to label row, remove title attr |
| `web/src/features/engine/components/ParameterCategory.tsx` | Modify | Add variant prop (hero/standard/sub), aria-expanded, py-3, accordion animation |
| `web/src/features/engine/components/EnginePage.tsx` | Rewrite | Summary strip + hero blending + standard/sub categories + per-pair zone |
| `web/src/features/engine/components/EngineDashboard.tsx` | Delete | Absorbed into EnginePage summary strip |
| `web/src/features/more/components/MorePage.tsx` | Modify | Remove engine-dashboard entry from SubPage type, CLUSTERS, PAGE_TITLES, rendering |

---

### Task 1: SourceBadge — show only for configurable params

**Files:**
- Modify: `web/src/features/engine/components/SourceBadge.tsx` (all 17 lines)

- [ ] **Step 1: Rewrite SourceBadge**

Replace the full contents of `SourceBadge.tsx`:

```tsx
interface Props {
  source: "hardcoded" | "configurable";
}

export default function SourceBadge({ source }: Props) {
  if (source !== "configurable") return null;

  return (
    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-500/15 text-green-400">
      c
    </span>
  );
}
```

Changes from current:
- Return `null` when `source !== "configurable"` (was rendering a badge for both)
- Display `"c"` instead of the full `source` string
- Remove the hardcoded style branch (no longer reachable)
- Font size stays `text-[10px]` (already correct — spec bumps from 9px but current code is already 10px)

- [ ] **Step 2: Verify build**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors (Props interface unchanged, consumers pass same values)

- [ ] **Step 3: Visual check**

Run: `cd web && pnpm dev`
Navigate to More > Engine. Verify:
- Configurable params show a small green "c" pill
- Hardcoded params show no badge (clean row)

---

### Task 2: WeightBar — accessibility and mobile label fix

**Files:**
- Modify: `web/src/features/engine/components/WeightBar.tsx` (all 35 lines)

- [ ] **Step 1: Rewrite WeightBar**

Replace the full contents of `WeightBar.tsx`:

```tsx
const COLORS = ["#F0B90B", "#0ECB81", "#3B82F6", "#A855F7"];

interface Props {
  weights: Record<string, { value: unknown; source: string }>;
}

export default function WeightBar({ weights }: Props) {
  const entries = Object.entries(weights);

  const ariaLabel = "Source weights: " +
    entries.map(([name, w]) => `${name} ${(Number(w.value) * 100).toFixed(0)}%`).join(", ");

  return (
    <div className="px-3 py-2">
      <div className="flex h-5 rounded overflow-hidden" role="img" aria-label={ariaLabel}>
        {entries.map(([name, w], i) => {
          const pct = Number(w.value) * 100;
          return (
            <div
              key={name}
              style={{ width: `${pct}%`, backgroundColor: COLORS[i % COLORS.length] }}
              className="h-full"
            />
          );
        })}
      </div>
      <div className="flex justify-between mt-1">
        {entries.map(([name, w], i) => (
          <span key={name} className="text-[10px] text-muted" style={{ color: COLORS[i % COLORS.length] }}>
            {name} ({(Number(w.value) * 100).toFixed(0)}%)
          </span>
        ))}
      </div>
    </div>
  );
}
```

Changes from current:
- Added `role="img"` and dynamic `aria-label` to bar container (accessibility)
- Removed `title` attribute from segments (doesn't work on mobile)
- Removed percentage text and centering from inside colored segments (contrast issue with black text on dark segments)
- Label row below now shows `name (pct%)` format instead of just `name`
- Segments are plain colored divs (`h-full`, no text)

- [ ] **Step 2: Verify build**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors (Props interface unchanged)

---

### Task 3: ParameterCategory — variant prop, aria-expanded, animation

**Files:**
- Modify: `web/src/features/engine/components/ParameterCategory.tsx` (all 43 lines)

- [ ] **Step 1: Rewrite ParameterCategory**

Replace the full contents of `ParameterCategory.tsx`:

```tsx
import { useState } from "react";
import ParameterRow from "./ParameterRow";

type Variant = "hero" | "standard" | "sub";

const VARIANT_STYLES: Record<Variant, { container: string; header: string; indent: string }> = {
  hero: {
    container: "border-l-2 border-primary bg-surface-container",
    header: "text-foreground font-semibold",
    indent: "",
  },
  standard: {
    container: "border border-border/50 bg-surface-container-low",
    header: "text-foreground font-medium",
    indent: "",
  },
  sub: {
    container: "border border-border/30 bg-surface/30",
    header: "text-muted text-sm",
    indent: "ml-2",
  },
};

interface Props {
  title: string;
  variant?: Variant;
  defaultOpen?: boolean;
  children?: React.ReactNode;
  params?: Record<string, { value: unknown; source: "hardcoded" | "configurable" }>;
}

export default function ParameterCategory({
  title,
  variant = "standard",
  defaultOpen = false,
  children,
  params,
}: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const styles = VARIANT_STYLES[variant];
  const entries = params ? Object.entries(params) : [];

  return (
    <div className={`rounded-lg overflow-hidden ${styles.indent} ${styles.container}`}>
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className={`w-full flex items-center justify-between px-3 py-3 hover:bg-surface-container-high/30 transition-colors text-sm ${styles.header}`}
      >
        <span>{title}</span>
        <span className="text-muted text-xs">{open ? "\u2212" : "+"}</span>
      </button>
      <div
        className="grid transition-all duration-200"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden">
          {params &&
            entries.map(([key, param], i) => (
              <ParameterRow
                key={key}
                name={key}
                value={param.value}
                source={param.source}
                last={i === entries.length - 1 && !children}
              />
            ))}
          {children}
        </div>
      </div>
    </div>
  );
}
```

Changes from current:
- Added `variant` prop (`"hero" | "standard" | "sub"`) with `VARIANT_STYLES` lookup — each variant has distinct container border/bg, header text style, and indent
- Default variant is `"standard"` (backward compatible — existing callers don't pass it)
- Added `aria-expanded={open}` to the accordion button
- Bumped header padding from `py-2.5` to `py-3` for 44px min touch target
- Replaced conditional render (`{open && ...}`) with CSS grid-rows animation (`grid-rows-[0fr]` → `grid-rows-[1fr]`) for smooth expand/collapse
- Content wrapped in `overflow-hidden` div inside the grid container
- Removed `mb-2` from container (spacing now handled by parent `space-y-2`)
- Removed `bg-surface/50` from header (spec says this is nearly invisible on `#080c12` background) — hover state uses `bg-surface-container-high/30` instead
- `last` prop on ParameterRow accounts for whether children follow

- [ ] **Step 2: Safelist dynamic Tailwind classes**

The `VARIANT_STYLES` object uses Tailwind classes in string values resolved at runtime. Tailwind's JIT scanner finds them in source, but to guarantee they survive purging, add them to the safelist in `web/tailwind.config.ts`:

```diff
  safelist: [
    "text-long", "text-short",
    ...
    "border-outline-variant/10", "border-outline-variant/15",
+   // ParameterCategory variant styles
+   "border-l-2", "border-primary", "bg-surface-container",
+   "bg-surface-container-low", "border-border/50", "border-border/30",
+   "bg-surface/30", "text-muted", "text-foreground",
+   "font-semibold", "font-medium", "text-sm",
  ],
```

- [ ] **Step 3: Verify build**

Run: `cd web && npx tsc --noEmit && pnpm build`
Expected: No type errors, production build succeeds, and variant styles are present in the CSS output.

---

### Task 4: EnginePage — unified layout rewrite

**Files:**
- Rewrite: `web/src/features/engine/components/EnginePage.tsx` (all 134 lines)

- [ ] **Step 1: Rewrite EnginePage**

Replace the full contents of `EnginePage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useEngineStore } from "../store";
import ParameterCategory from "./ParameterCategory";
import ParameterRow from "./ParameterRow";
import WeightBar from "./WeightBar";
import RegimeGrid from "./RegimeGrid";
import { Dropdown } from "../../../shared/components/Dropdown";

export default function EnginePage() {
  const { params, loading, error, fetch, refresh } = useEngineStore();
  const [selectedPair, setSelectedPair] = useState("");
  const [selectedTf, setSelectedTf] = useState("");

  useEffect(() => { fetch(); }, [fetch]);

  useEffect(() => {
    if (!params) return;
    const pairs = Object.keys(params.regime_weights || {});
    if (pairs.length > 0 && !selectedPair) {
      setSelectedPair(pairs[0]);
      const tfs = Object.keys(params.regime_weights[pairs[0]] || {});
      if (tfs.length > 0) setSelectedTf(tfs[0]);
    }
  }, [params, selectedPair]);

  if (loading && !params) return <div className="p-4 text-muted text-sm">Loading parameters...</div>;
  if (error) return <div className="p-4 text-red-400 text-sm">Error: {error}</div>;
  if (!params) return null;

  const regimeData = selectedPair && selectedTf
    ? params.regime_weights?.[selectedPair]?.[selectedTf]
    : null;
  const learnedAtr = selectedPair && selectedTf
    ? params.learned_atr?.[selectedPair]?.[selectedTf]
    : null;

  const allPairs = [
    ...new Set([
      ...Object.keys(params.regime_weights || {}),
      ...Object.keys(params.learned_atr || {}),
    ]),
  ];
  const allTfs = selectedPair
    ? [
        ...new Set([
          ...Object.keys(params.regime_weights?.[selectedPair] || {}),
          ...Object.keys(params.learned_atr?.[selectedPair] || {}),
        ]),
      ]
    : [];

  const hasPerPairData = regimeData || learnedAtr;

  return (
    <div className="p-3 space-y-2">
      {/* ── Summary Strip ── */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-foreground">Engine Parameters</h3>
          <button
            onClick={refresh}
            className="p-2 text-accent hover:text-accent/80 transition-colors"
            aria-label="Refresh parameters"
          >
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        <WeightBar weights={params.blending.source_weights} />

        <dl className="flex flex-wrap gap-2 mt-2">
          {[
            { label: "Signal", value: params.blending.thresholds.signal_threshold },
            { label: "LLM", value: params.blending.thresholds.llm_threshold },
            { label: "ML Blend", value: params.blending.ml_blend_weight },
          ].map(({ label, value }) => (
            <div key={label} className="min-w-[5.5rem] flex-1 bg-surface-container rounded-lg px-3 py-2">
              <dt className="text-[10px] uppercase tracking-wider text-accent">{label}</dt>
              <dd className="font-mono text-sm text-foreground">{formatThreshold(value?.value)}</dd>
            </div>
          ))}
        </dl>
      </div>

      {/* ── Blending (Hero Category) ── */}
      <ParameterCategory title="Blending" variant="hero" defaultOpen>
        <ParameterRow name="ml_blend_weight" value={params.blending.ml_blend_weight.value} source={params.blending.ml_blend_weight.source} />
        {Object.entries(params.blending.thresholds).map(([k, v], i, arr) => (
          <ParameterRow key={k} name={k} value={v.value} source={v.source} last={i === arr.length - 1} />
        ))}

        {/* LLM Factor Weights — sub variant nested inside hero */}
        <ParameterCategory title="LLM Factor Weights" variant="sub">
          {Object.entries(params.blending.llm_factor_weights).map(([k, v]) => (
            <ParameterRow key={k} name={k} value={v.value} source={v.source} />
          ))}
          <ParameterRow name="factor_cap" value={params.blending.llm_factor_cap.value} source={params.blending.llm_factor_cap.source} last />
        </ParameterCategory>
      </ParameterCategory>

      {/* ── Standard Categories ── */}
      <ParameterCategory title="Technical — Indicators" params={params.technical.indicator_periods} />

      {/* Sub-categories of Technical */}
      <ParameterCategory title="Sigmoid Params" variant="sub" params={params.technical.sigmoid_params} />
      <ParameterCategory title="Mean Reversion" variant="sub" params={params.technical.mean_reversion} />

      <ParameterCategory title="Order Flow" params={params.order_flow.regime_params}>
        {Object.entries(params.order_flow.max_scores).map(([k, v]) => (
          <ParameterRow key={k} name={`max_${k}`} value={v.value} source={v.source} />
        ))}
      </ParameterCategory>

      <ParameterCategory title="On-Chain — BTC" params={params.onchain.btc_profile as Record<string, any>} />
      <ParameterCategory title="On-Chain — ETH" params={params.onchain.eth_profile as Record<string, any>} />
      <ParameterCategory title="Levels & ATR" params={params.levels.atr_defaults} />
      <ParameterCategory title="ATR Guardrails" params={params.levels.atr_guardrails} />
      <ParameterCategory title="Phase 1 Scaling" params={params.levels.phase1_scaling} />
      <ParameterCategory title="Pattern Strengths" params={params.patterns.strengths} />
      <ParameterCategory title="Performance Tracker" params={params.performance_tracker.optimization_params} />
      <ParameterCategory title="Optimization Guardrails" params={params.performance_tracker.guardrails} />

      {/* ── Per-Pair Zone ── */}
      {allPairs.length > 0 && (
        <div className="mt-4 border border-primary/20 rounded-xl bg-surface-container-low p-3">
          <div className="text-[10px] font-bold uppercase tracking-widest text-primary mb-2">
            Per-Pair Parameters
          </div>

          <div className="flex gap-2 mb-3">
            <Dropdown
              value={selectedPair}
              onChange={(v) => {
                setSelectedPair(v);
                const tfs = Object.keys(params.regime_weights?.[v] || {});
                if (tfs.length > 0) setSelectedTf(tfs[0]);
              }}
              options={allPairs.map((p) => ({ value: p, label: p }))}
              size="sm"
              fullWidth={false}
              ariaLabel="Select pair"
            />
            <Dropdown
              value={selectedTf}
              onChange={setSelectedTf}
              options={allTfs.map((tf) => ({ value: tf, label: tf }))}
              size="sm"
              fullWidth={false}
              ariaLabel="Select timeframe"
            />
          </div>

          {!hasPerPairData && (
            <p className="text-muted text-xs text-center py-4">No data for this pair/timeframe</p>
          )}

          {regimeData && (
            <ParameterCategory title={`Regime Weights — ${selectedPair} ${selectedTf}`}>
              <RegimeGrid regimes={regimeData} />
            </ParameterCategory>
          )}

          {learnedAtr && (
            <ParameterCategory title={`Learned ATR — ${selectedPair} ${selectedTf}`}>
              <ParameterRow name="sl_atr" value={learnedAtr.sl_atr.value} source={learnedAtr.sl_atr.source} />
              <ParameterRow name="tp1_atr" value={learnedAtr.tp1_atr.value} source={learnedAtr.tp1_atr.source} />
              <ParameterRow name="tp2_atr" value={learnedAtr.tp2_atr.value} source={learnedAtr.tp2_atr.source} />
              <ParameterRow name="last_optimized" value={learnedAtr.last_optimized_at || "never"} source="configurable" />
              <ParameterRow name="signal_count" value={learnedAtr.signal_count} source="configurable" last />
            </ParameterCategory>
          )}
        </div>
      )}
    </div>
  );
}

function formatThreshold(v: unknown): string {
  if (typeof v === "number") return v.toFixed(2);
  if (typeof v === "string") return v;
  return "--";
}
```

Changes from current EnginePage:
- **Summary strip** at top: title with RefreshCw icon button (spinning when loading, p-2 for 44px tap area), WeightBar, and 3 key threshold cards using `<dl>`/`<dt>`/`<dd>` with `min-w-[5.5rem] flex-1` (3-across on wider, wraps to 2+1 on <=375px)
- **Blending** section: `variant="hero"`, `defaultOpen`, without duplicate WeightBar (summary strip already shows it), with LLM Factor Weights nested inside as `variant="sub"` (was a separate sibling category)
- **Technical sub-categories**: Sigmoid Params and Mean Reversion rendered as `variant="sub"` siblings after Technical — Indicators (was "Technical — Sigmoid Params" and "Technical — Mean Reversion")
- **All other categories**: standard variant (default), closed by default
- **Per-pair zone**: visually separated with `mt-4`, accent-tinted border (`border-primary/20`), `rounded-xl`, `bg-surface-container-low`, with label "Per-Pair Parameters" in primary color, uppercase, tracked. Dropdowns on own row below label. Empty state message when no data.
- **Loading guard** changed from `if (loading)` to `if (loading && !params)` — during a refresh, `params` is still set so the page stays rendered with the spinning RefreshCw icon visible. Only the initial load (when params is null) shows the loading placeholder.
- **Removed** old text "Refresh" button, replaced with RefreshCw icon
- Added `formatThreshold` helper for threshold card values

- [ ] **Step 2: Verify build**

Run: `cd web && npx tsc --noEmit && pnpm build`
Expected: No type errors, production build succeeds

- [ ] **Step 3: Visual check**

Run: `cd web && pnpm dev`
Navigate to More > Engine. Verify:
- Summary strip shows weight bar + 3 threshold cards
- Blending section has hero treatment (left primary border, surface-container bg)
- LLM Factor Weights appears nested inside Blending when expanded
- Sigmoid Params and Mean Reversion appear indented after Technical — Indicators
- Standard categories have border/50 + surface-container-low header
- Per-pair zone has accent-tinted border and is visually separated
- Accordion animations are smooth
- All categories except Blending start collapsed

---

### Task 5: Delete EngineDashboard and clean up MorePage

**Files:**
- Delete: `web/src/features/engine/components/EngineDashboard.tsx`
- Modify: `web/src/features/more/components/MorePage.tsx`

- [ ] **Step 1: Delete EngineDashboard.tsx**

```bash
rm web/src/features/engine/components/EngineDashboard.tsx
```

- [ ] **Step 2: Update MorePage.tsx**

In `web/src/features/more/components/MorePage.tsx`, make these changes:

**Line 11** — Remove the import:
```diff
-import { EngineDashboard } from "../../engine/components/EngineDashboard";
```

**Line 2** — Remove `Activity` from lucide import (no longer needed after removing Engine Dashboard entry — check if Activity is used by System entry first):

Activity IS still used by the System entry (line 38: `icon: Activity`), so keep the import as-is.

**Line 15** — Remove `"engine-dashboard"` from SubPage type:
```diff
-type SubPage = "engine" | "engine-dashboard" | "backtest" | "ml" | "alerts" | "risk" | "settings" | "journal" | "system" | null;
+type SubPage = "engine" | "backtest" | "ml" | "alerts" | "risk" | "settings" | "journal" | "system" | null;
```

**Lines 22-23** — Remove the engine-dashboard item from CLUSTERS[0].items:
```diff
      { key: "engine" as SubPage, icon: Cpu, label: "Engine", desc: "Pipeline parameters & weights", color: "text-primary" },
-     { key: "engine-dashboard" as SubPage, icon: Activity, label: "Engine Dashboard", desc: "Live parameter monitoring", color: "text-primary" },
      { key: "backtest" as SubPage, icon: LineChart, label: "Backtest", desc: "Historical simulation hub", color: "text-tertiary-dim" },
```

**Lines 45-46** — Remove the engine-dashboard entry from PAGE_TITLES:
```diff
  engine: "Engine Parameters",
- "engine-dashboard": "Engine Dashboard",
  backtest: "Backtest",
```

**Line 63** — Remove the rendering case:
```diff
        {activePage === "engine" && <EnginePage />}
-       {activePage === "engine-dashboard" && <EngineDashboard />}
        {activePage === "backtest" && <BacktestView />}
```

- [ ] **Step 3: Verify build**

Run: `cd web && npx tsc --noEmit`
Expected: No type errors, no unused import warnings

- [ ] **Step 4: Verify no other imports of EngineDashboard**

Run: `grep -r "EngineDashboard" web/src/`
Expected: No results

- [ ] **Step 5: Visual check**

Run: `cd web && pnpm dev`
Navigate to More tab. Verify:
- "Engine Dashboard" entry is gone from the Execution Layer cluster
- Only "Engine" and "Backtest" remain
- Clicking "Engine" still opens the unified engine page

- [ ] **Step 6: Final commit (all tasks)**

```bash
git add -A
git commit -m "feat(engine): unified engine page — summary strip, visual hierarchy, per-pair zone"
```
