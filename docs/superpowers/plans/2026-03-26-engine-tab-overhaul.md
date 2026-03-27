# Engine Tab Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all functional, UX, and UI gaps in the Engine tab — wire up parameter descriptions, broadcast live pipeline scores, add inline parameter editing, and migrate to shared components for visual consistency.

**Architecture:** The Engine tab becomes a live monitoring + configuration dashboard. The backend adds a `pipeline_scores` WebSocket broadcast after every pipeline evaluation (not just emitted signals). The frontend migrates from custom one-off components to shared `Card`, `CollapsibleSection`, `MetricCard`, `SectionLabel`, and `Skeleton` components. Inline editing reuses the existing `previewEngineApply`/`confirmEngineApply` API methods and follows the pattern established by the backtest `ApplyModal`.

**Tech Stack:** React 19, TypeScript, Zustand, Tailwind CSS, FastAPI WebSocket

---

### Task 1: Wire up parameter descriptions to ParameterRow

The `descriptions` dict is already returned by the API and stored in `params.descriptions`, but `EnginePage` never passes it down through `ParameterCategory`. `ParameterRow` already accepts a `descriptions` prop and forwards it to `ParamInfoPopup` — the only gap is threading it from EnginePage through ParameterCategory.

**Files:**
- Modify: `web/src/features/engine/components/EnginePage.tsx`
- Modify: `web/src/features/engine/components/ParameterCategory.tsx`
- Modify: `web/src/features/engine/components/ParameterRow.tsx`

- [ ] **Step 1: Thread `descriptions` through ParameterCategory**

In `ParameterCategory.tsx`, add a `descriptions` prop and forward it to each `ParameterRow`:

```tsx
// ParameterCategory.tsx
interface Props {
  title: string;
  variant?: Variant;
  defaultOpen?: boolean;
  children?: React.ReactNode;
  params?: Record<string, { value: unknown; source: "hardcoded" | "configurable" }>;
  descriptions?: Record<string, { description: string; pipeline_stage: string; range: string }>;
}

export default function ParameterCategory({
  title,
  variant = "standard",
  defaultOpen = false,
  children,
  params,
  descriptions,
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
        <span className="text-on-surface-variant text-xs">{open ? "\u2212" : "+"}</span>
      </button>
      <div
        className={`grid transition-all duration-200 ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}
      >
        <div className="overflow-hidden">
          {params &&
            entries.map(([key, param], i) => (
              <ParameterRow
                key={key}
                name={key}
                value={param.value}
                source={param.source}
                descriptions={descriptions}
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

- [ ] **Step 2: Pass `descriptions` from EnginePage to every ParameterCategory and ParameterRow**

In `EnginePage.tsx`, extract descriptions and pass them through. Add this line after the existing destructuring:

```tsx
const descriptions = params.descriptions;
```

Then add `descriptions={descriptions}` to every `<ParameterCategory>` and standalone `<ParameterRow>` in the JSX. For example:

```tsx
<ParameterCategory title="Blending" variant="hero" defaultOpen descriptions={descriptions}>
  <ParameterRow name="ml_blend_weight" value={params.blending.ml_blend_weight.value} source={params.blending.ml_blend_weight.source} descriptions={descriptions} />
  {Object.entries(params.blending.thresholds).map(([k, v], i, arr) => (
    <ParameterRow key={k} name={k} value={v.value} source={v.source} descriptions={descriptions} last={i === arr.length - 1} />
  ))}
  {/* ... same for LLM Factor Weights sub-category and its rows */}
</ParameterCategory>

<ParameterCategory title="Technical — Indicators" params={params.technical.indicator_periods} descriptions={descriptions} />
<ParameterCategory title="Sigmoid Params" variant="sub" params={params.technical.sigmoid_params} descriptions={descriptions} />
<ParameterCategory title="Mean Reversion" variant="sub" params={params.technical.mean_reversion} descriptions={descriptions} />
<ParameterCategory title="Order Flow" params={params.order_flow.regime_params} descriptions={descriptions}>
  {Object.entries(params.order_flow.max_scores).map(([k, v]) => (
    <ParameterRow key={k} name={`max_${k}`} value={v.value} source={v.source} descriptions={descriptions} />
  ))}
</ParameterCategory>
{/* Repeat for all remaining ParameterCategory instances */}
```

Apply the same `descriptions={descriptions}` prop to every `<ParameterCategory>` and every standalone `<ParameterRow>` in the file — there are ~15 ParameterCategory instances and ~8 standalone ParameterRow instances.

- [ ] **Step 3: Verify info icons appear**

Run: `cd web && pnpm build`
Expected: No TypeScript errors. Open the app, navigate to Engine tab, expand a category — info icons should appear next to parameters that have entries in `PARAMETER_DESCRIPTIONS`.

---

### Task 2: Broadcast live pipeline scores via WebSocket

Currently, intermediate scores (technical, order flow, on-chain, pattern, ML, LLM, final) are computed every pipeline run but only logged. The `PipelineFlow` component already accepts score data — it just never receives any. Add a `pipeline_scores` WebSocket broadcast after every evaluation.

**Files:**
- Modify: `backend/app/main.py` (after `_log_pipeline_evaluation` call, ~line 851)
- Modify: `backend/app/api/connections.py` (add `broadcast_scores` method)

- [ ] **Step 1: Add `broadcast_scores` to ConnectionManager**

In `connections.py`, add a new method that broadcasts to all clients (scores aren't pair-filtered — the Engine tab wants all of them):

```python
async def broadcast_scores(self, scores: dict):
    """Broadcast pipeline score breakdown to all connected clients."""
    await self._broadcast_to_all({"type": "pipeline_scores", "scores": scores})
```

- [ ] **Step 2: Broadcast scores after every pipeline evaluation**

In `main.py`, right after the `_log_pipeline_evaluation(...)` call (line 851) and before `app.state.last_pipeline_cycle = time.time()` (line 853), add:

```python
    manager: ConnectionManager = app.state.manager
    await manager.broadcast_scores({
        "pair": pair,
        "timeframe": timeframe,
        "technical": round(tech_result["score"], 1),
        "order_flow": round(flow_result["score"], 1),
        "onchain": round(onchain_score, 1) if onchain_available else None,
        "patterns": round(pat_score, 1) if pat_score else None,
        "regime_blend": round(indicator_preliminary, 1),
        "ml_gate": round(ml_score, 1) if ml_score is not None else None,
        "llm_gate": round(llm_contribution, 2) if llm_contribution else None,
        "signal": round(final, 1),
        "emitted": emitted,
    })
```

- [ ] **Step 3: Run backend tests to verify no breakage**

Run: `docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All tests pass. The broadcast call uses `_broadcast_to_all` which handles empty connection lists gracefully.

---

### Task 3: Consume pipeline scores in the frontend store

Add a WebSocket listener that captures `pipeline_scores` events and stores the latest scores per pair in the engine Zustand store.

**Files:**
- Modify: `web/src/features/engine/store.ts`
- Modify: `web/src/features/engine/types.ts`

- [ ] **Step 1: Add PipelineScores type**

In `types.ts`, add at the end:

```typescript
export interface PipelineScores {
  pair: string;
  timeframe: string;
  technical: number | null;
  order_flow: number | null;
  onchain: number | null;
  patterns: number | null;
  regime_blend: number | null;
  ml_gate: number | null;
  llm_gate: number | null;
  signal: number | null;
  emitted: boolean;
}
```

- [ ] **Step 2: Extend the engine store with live scores**

In `store.ts`, add a `liveScores` map and a `pushScores` action:

```typescript
import { create } from "zustand";
import { api } from "../../shared/lib/api";
import type { EngineParameters, PipelineScores } from "./types";

interface EngineStore {
  params: EngineParameters | null;
  loading: boolean;
  error: string | null;
  liveScores: Record<string, PipelineScores>; // keyed by "pair:timeframe"
  fetch: () => Promise<void>;
  refresh: () => Promise<void>;
  pushScores: (scores: PipelineScores) => void;
}

async function _load(set: (s: Partial<EngineStore>) => void) {
  set({ loading: true, error: null });
  try {
    const data = await api.getEngineParameters();
    set({ params: data, loading: false });
  } catch (e) {
    set({ error: (e as Error).message, loading: false });
  }
}

export const useEngineStore = create<EngineStore>((set, get) => ({
  params: null,
  loading: false,
  error: null,
  liveScores: {},

  fetch: async () => {
    if (get().params) return;
    await _load(set);
  },

  refresh: () => _load(set),

  pushScores: (scores) =>
    set((s) => ({
      liveScores: {
        ...s.liveScores,
        [`${scores.pair}:${scores.timeframe}`]: scores,
      },
    })),
}));
```

- [ ] **Step 3: Hook up WebSocket listener in useSignalWebSocket**

In `web/src/features/signals/hooks/useSignalWebSocket.ts`, add a handler for the `pipeline_scores` message type inside the existing `ws.onMessage` callback, after the existing handlers:

```typescript
else if (data.type === "pipeline_scores" && data.scores) {
  useEngineStore.getState().pushScores(data.scores);
}
```

Add the import at the top:
```typescript
import { useEngineStore } from "../../engine/store";
```

- [ ] **Step 4: Verify build**

Run: `cd web && pnpm build`
Expected: No TypeScript errors.

---

### Task 4: Wire live scores into PipelineFlow

Connect the stored `liveScores` to the `PipelineFlow` component so nodes show actual scores.

**Files:**
- Modify: `web/src/features/engine/components/EnginePage.tsx`
- Modify: `web/src/features/engine/components/PipelineFlow.tsx`

- [ ] **Step 1: Build nodes from liveScores in EnginePage**

In `EnginePage.tsx`, add a pair/timeframe selector for the pipeline view and map `liveScores` into the `PipelineFlow` `nodes` prop:

```tsx
const liveScores = useEngineStore((s) => s.liveScores);
const scoreKeys = Object.keys(liveScores);
const [scorePair, setScorePair] = useState("");
const hasScores = scoreKeys.length > 0;

// Auto-select first available score key
useEffect(() => {
  if (scoreKeys.length > 0 && !scorePair) setScorePair(scoreKeys[0]);
}, [scoreKeys.length, scorePair]);

const activeScores = scorePair ? liveScores[scorePair] : null;

const pipelineNodes = activeScores
  ? {
      technical: { label: "Technical", score: activeScores.technical },
      order_flow: { label: "Order Flow", score: activeScores.order_flow },
      onchain: { label: "On-Chain", score: activeScores.onchain },
      patterns: { label: "Patterns", score: activeScores.patterns },
      regime_blend: { label: "Regime Blend", score: activeScores.regime_blend },
      ml_gate: { label: "ML Gate", score: activeScores.ml_gate },
      llm_gate: { label: "LLM Gate", score: activeScores.llm_gate },
      signal: { label: "Signal", score: activeScores.signal },
    }
  : undefined;
```

- [ ] **Step 2: Add score pair selector and pass nodes to PipelineFlow**

Replace the current `<PipelineFlow />` call in EnginePage's JSX with:

```tsx
<div className="space-y-2">
  {scoreKeys.length > 1 ? (
    <Dropdown
      value={scorePair}
      onChange={setScorePair}
      options={scoreKeys.map((k) => ({ value: k, label: k.replace(":", " · ") }))}
      size="sm"
      fullWidth={false}
      ariaLabel="Pipeline score pair"
    />
  ) : scorePair ? (
    <span className="text-[10px] text-muted">{scorePair.replace(":", " · ")}</span>
  ) : null}
  <PipelineFlow nodes={pipelineNodes} />
  {!hasScores && (
    <p className="text-[10px] text-muted text-center">Waiting for pipeline scores…</p>
  )}
</div>
```

- [ ] **Step 3: Add emitted indicator to PipelineFlow signal node**

Implementation order: modify `PipelineFlow.tsx` first (NodeData type + ScoreNode render), then update the `pipelineNodes` mapping in `EnginePage.tsx`.

In `PipelineFlow.tsx`, update the `ScoreNode` to show an emitted indicator when the signal node's score is present. Modify `NodeData` to accept an optional `emitted` flag:

```tsx
interface NodeData {
  label: string;
  score?: number | null;
  details?: Record<string, number>;
  emitted?: boolean;
}
```

In `ScoreNode`, after the score display, add:

```tsx
{data.emitted && (
  <div className="text-[10px] text-long font-medium mt-0.5">EMITTED</div>
)}
```

Then in `EnginePage.tsx`, add `emitted` to the signal node:

```tsx
signal: { label: "Signal", score: activeScores.signal, emitted: activeScores.emitted },
```

- [ ] **Step 4: Verify build**

Run: `cd web && pnpm build`
Expected: No TypeScript errors.

---

### Task 5: Add inline parameter editing

Add edit capability for `configurable` parameters. Tapping a configurable parameter's value enters edit mode with a number input. Changes go through the existing preview → confirm flow from `api.previewEngineApply` / `api.confirmEngineApply`.

**Files:**
- Modify: `web/src/features/engine/components/ParameterRow.tsx`
- Modify: `web/src/features/engine/components/ParameterCategory.tsx`
- Modify: `web/src/features/engine/components/EnginePage.tsx`

- [ ] **Step 1: Add edit mode to ParameterRow**

Replace the full content of `ParameterRow.tsx`:

```tsx
import { useState, useRef, useEffect } from "react";
import { Pencil } from "lucide-react";
import SourceBadge from "./SourceBadge";
import ParamInfoPopup from "./ParamInfoPopup";
import { ParamRow } from "../../../shared/components/ParamRow";

interface Props {
  name: string;
  value: unknown;
  source: "hardcoded" | "configurable";
  last?: boolean;
  descriptions?: Record<string, { description: string; pipeline_stage: string; range: string }>;
  dotPath?: string;
  onEdit?: (dotPath: string, value: number) => void;
}

export default function ParameterRow({ name, value, source, last, descriptions, dotPath, onEdit }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const submittedRef = useRef(false);
  const editable = source === "configurable" && !!dotPath && !!onEdit && typeof value === "number";

  useEffect(() => {
    if (editing) {
      submittedRef.current = false;
      inputRef.current?.focus();
    }
  }, [editing]);

  const display = Array.isArray(value)
    ? value.join(", ")
    : typeof value === "object" && value !== null
      ? JSON.stringify(value)
      : String(value);

  const handleSubmit = () => {
    if (submittedRef.current) return;
    submittedRef.current = true;
    const num = parseFloat(draft);
    if (!isNaN(num) && num !== value && dotPath && onEdit) {
      onEdit(dotPath, num);
    }
    setEditing(false);
  };

  return (
    <ParamRow
      label={
        <span className="flex items-center gap-1">
          <span>{name}</span>
          <ParamInfoPopup name={name} descriptions={descriptions} />
        </span>
      }
      value={
        editing ? (
          <input
            ref={inputRef}
            type="number"
            step="any"
            aria-label={`Edit ${name}`}
            className="w-24 bg-surface-container-high border border-primary/40 rounded px-1.5 py-0.5 text-xs font-mono text-on-surface text-right outline-none focus:border-primary"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={handleSubmit}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubmit();
              if (e.key === "Escape") { submittedRef.current = true; setEditing(false); }
            }}
          />
        ) : (
          <span
            className={`flex items-center gap-2 ${editable ? "cursor-pointer hover:text-primary transition-colors" : ""}`}
            onClick={editable ? () => { setDraft(String(value)); setEditing(true); } : undefined}
          >
            <span>{display}</span>
            <SourceBadge source={source} />
            {editable && <Pencil size={10} className="text-muted" />}
          </span>
        )
      }
      last={last}
    />
  );
}
```

- [ ] **Step 2: Thread `onEdit` and `dotPath` through ParameterCategory**

In `ParameterCategory.tsx`, add `onEdit` and `dotPathPrefix` props:

```tsx
interface Props {
  title: string;
  variant?: Variant;
  defaultOpen?: boolean;
  children?: React.ReactNode;
  params?: Record<string, { value: unknown; source: "hardcoded" | "configurable" }>;
  descriptions?: Record<string, { description: string; pipeline_stage: string; range: string }>;
  onEdit?: (dotPath: string, value: number) => void;
  dotPathPrefix?: string;
}
```

Pass them through when rendering from `params`:

```tsx
<ParameterRow
  key={key}
  name={key}
  value={param.value}
  source={param.source}
  descriptions={descriptions}
  dotPath={dotPathPrefix ? `${dotPathPrefix}.${key}` : undefined}
  onEdit={onEdit}
  last={i === entries.length - 1 && !children}
/>
```

- [ ] **Step 3: Add apply flow to EnginePage**

In `EnginePage.tsx`, add state and handlers for the preview → confirm flow. Add this after the existing state declarations:

```tsx
const [pendingEdit, setPendingEdit] = useState<{ path: string; value: number } | null>(null);
const [applyDiff, setApplyDiff] = useState<ParameterDiff[] | null>(null);
const [applyLoading, setApplyLoading] = useState(false);
const [applyError, setApplyError] = useState<string | null>(null);

const handleEdit = async (dotPath: string, value: number) => {
  setPendingEdit({ path: dotPath, value });
  setApplyLoading(true);
  setApplyError(null);
  try {
    const result = await api.previewEngineApply({ [dotPath]: value });
    setApplyDiff(result.diff);
  } catch (e) {
    // Keep applyError visible even though we clear pendingEdit — the error
    // banner renders independently so the user sees what went wrong.
    setApplyError((e as Error).message);
    setPendingEdit(null);
    setApplyDiff(null);
  } finally {
    setApplyLoading(false);
  }
};

const handleConfirm = async () => {
  if (!pendingEdit) return;
  setApplyLoading(true);
  try {
    await api.confirmEngineApply({ [pendingEdit.path]: pendingEdit.value });
    await refresh();
    setPendingEdit(null);
    setApplyDiff(null);
  } catch (e) {
    setApplyError((e as Error).message);
  } finally {
    setApplyLoading(false);
  }
};

const handleCancelApply = () => {
  setPendingEdit(null);
  setApplyDiff(null);
  setApplyError(null);
};
```

Add the `ParameterDiff` import at the top:
```tsx
import type { ParameterDiff } from "../types";
```

- [ ] **Step 4: Add inline confirmation banner**

In `EnginePage.tsx`, add a confirmation banner at the top of the JSX (inside the root `<div>`, before `<PipelineFlow />`):

```tsx
{/* Preview error toast (visible when preview fails and there's no diff to show) */}
{applyError && !applyDiff && (
  <div className="flex items-center justify-between px-3 py-2 bg-error/10 border border-error/20 rounded-lg">
    <span className="text-xs text-error">{applyError}</span>
    <button onClick={() => setApplyError(null)} className="text-error text-xs ml-2">{"\u2715"}</button>
  </div>
)}

{/* Confirm banner */}
{applyDiff && pendingEdit && (
  <Card variant="high" padding="sm" border>
    <div className="flex items-center justify-between mb-2">
      <span className="text-xs font-medium text-on-surface">Confirm Change</span>
      {applyError && <span className="text-[10px] text-error">{applyError}</span>}
    </div>
    {applyDiff.map((d) => (
      <div key={d.path} className="flex justify-between text-xs font-mono py-0.5">
        <span className="text-on-surface-variant">{d.path.split(".").pop()}</span>
        <span>
          <span className="text-on-surface-variant">{d.current ?? "\u2014"}</span>
          <span className="text-on-surface-variant mx-1">{"\u2192"}</span>
          <span className="text-primary">{d.proposed}</span>
        </span>
      </div>
    ))}
    <p className="text-[10px] text-muted mt-1">This changes live engine behavior.</p>
    <div className="flex gap-2 justify-end mt-2">
      <Button variant="ghost" size="sm" onClick={handleCancelApply}>Cancel</Button>
      <Button variant="primary" size="sm" onClick={handleConfirm} loading={applyLoading}>Apply</Button>
    </div>
  </Card>
)}
```

- [ ] **Step 5: Pass `onEdit` and `dotPathPrefix` to all configurable ParameterCategory instances**

For each `<ParameterCategory>` that contains configurable parameters, add the two props. Examples:

```tsx
<ParameterCategory title="Blending" variant="hero" defaultOpen descriptions={descriptions} onEdit={handleEdit}>
  <ParameterRow name="ml_blend_weight" value={params.blending.ml_blend_weight.value} source={params.blending.ml_blend_weight.source} descriptions={descriptions} dotPath="blending.ml_blend_weight" onEdit={handleEdit} />
  {Object.entries(params.blending.thresholds).map(([k, v], i, arr) => (
    <ParameterRow key={k} name={k} value={v.value} source={v.source} descriptions={descriptions} dotPath={`blending.thresholds.${k}`} onEdit={handleEdit} last={i === arr.length - 1} />
  ))}

  <ParameterCategory title="LLM Factor Weights" variant="sub" descriptions={descriptions} onEdit={handleEdit}>
    {Object.entries(params.blending.llm_factor_weights).map(([k, v]) => (
      <ParameterRow key={k} name={k} value={v.value} source={v.source} descriptions={descriptions} dotPath={`blending.llm_factor_weights.${k}`} onEdit={handleEdit} />
    ))}
    <ParameterRow name="factor_cap" value={params.blending.llm_factor_cap.value} source={params.blending.llm_factor_cap.source} descriptions={descriptions} dotPath="blending.llm_factor_cap" onEdit={handleEdit} last />
  </ParameterCategory>
</ParameterCategory>

<ParameterCategory title="Mean Reversion" variant="sub" params={params.technical.mean_reversion} descriptions={descriptions} onEdit={handleEdit} dotPathPrefix="mean_reversion" />
```

Note: Only blending and mean_reversion params have backend apply support (see `_PIPELINE_SETTINGS_MAP` and `_SCORING_PARAMS_MAP`). Technical indicator_periods, order_flow, onchain, patterns, levels, and performance_tracker categories do NOT have `dotPath`/`onEdit` — they remain read-only. Regime weights and learned ATR in the per-pair section also support editing via `regime_weights.*` and `learned_atr.*` dot paths.

For per-pair learned ATR rows, pass the dynamic dot paths:

```tsx
<ParameterRow name="sl_atr" value={learnedAtr.sl_atr.value} source={learnedAtr.sl_atr.source} descriptions={descriptions} dotPath={`learned_atr.${selectedPair}.${selectedTf}.current_sl_atr`} onEdit={handleEdit} />
<ParameterRow name="tp1_atr" value={learnedAtr.tp1_atr.value} source={learnedAtr.tp1_atr.source} descriptions={descriptions} dotPath={`learned_atr.${selectedPair}.${selectedTf}.current_tp1_atr`} onEdit={handleEdit} />
<ParameterRow name="tp2_atr" value={learnedAtr.tp2_atr.value} source={learnedAtr.tp2_atr.source} descriptions={descriptions} dotPath={`learned_atr.${selectedPair}.${selectedTf}.current_tp2_atr`} onEdit={handleEdit} />
```

- [ ] **Step 6: Verify build + manual test**

Run: `cd web && pnpm build`
Expected: No TypeScript errors. Tapping a configurable value opens an input. Submitting shows the confirm banner. Confirming applies and refreshes.

---

### Task 6: Migrate to shared UI components

Replace all hand-rolled containers, headers, loading states, and metric chips with shared components (`Card`, `SectionLabel`, `MetricCard`, `Skeleton`). This brings the Engine tab in line with the visual language of Settings, Optimizer, and ML pages.

**Files:**
- Modify: `web/src/features/engine/components/EnginePage.tsx`
- Modify: `web/src/features/engine/components/SourceBadge.tsx`

- [ ] **Step 1: Add shared component imports to EnginePage**

Replace the existing imports in `EnginePage.tsx` to include all needed shared components:

```tsx
import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useEngineStore } from "../store";
import ParameterCategory from "./ParameterCategory";
import ParameterRow from "./ParameterRow";
import WeightBar from "./WeightBar";
import RegimeGrid from "./RegimeGrid";
import { Dropdown } from "../../../shared/components/Dropdown";
import { Button } from "../../../shared/components/Button";
import PipelineFlow from "./PipelineFlow";
import { api } from "../../../shared/lib/api";
import { Card } from "../../../shared/components/Card";
import { SectionLabel } from "../../../shared/components/SectionLabel";
import { MetricCard } from "../../../shared/components/MetricCard";
import { Skeleton } from "../../../shared/components/Skeleton";
import type { ParameterDiff } from "../types";
```

Note: Preserve the existing `formatThreshold` helper function (currently at the bottom of EnginePage.tsx) — it's used in the MetricCard grid below.

- [ ] **Step 2: Replace loading state with Skeleton**

Replace the loading check:

```tsx
// Before
if (loading && !params) return <div className="p-4 text-on-surface-variant text-sm">Loading parameters...</div>;

// After — skeleton shapes match the actual page layout (pipeline grid, metric row, categories)
if (loading && !params) {
  return (
    <div className="p-3 space-y-3">
      {/* Pipeline flow placeholder (2-row grid) */}
      <Skeleton height="h-28" />
      {/* MetricCard row */}
      <div className="grid grid-cols-3 gap-2">
        <Skeleton height="h-14" />
        <Skeleton height="h-14" />
        <Skeleton height="h-14" />
      </div>
      {/* WeightBar + category list */}
      <Skeleton height="h-8" />
      <Skeleton height="h-10" count={4} />
    </div>
  );
}
```

- [ ] **Step 3: Add page header and use SectionLabel for groups**

Replace the current "Engine Parameters" heading block with a proper page header at the top of the root div, and use `SectionLabel` to group sections:

```tsx
<div className="p-3 space-y-3">
  {/* Page header */}
  <div className="flex items-center justify-between">
    <h2 className="text-sm font-medium text-on-surface">Engine</h2>
    <Button
      variant="ghost"
      icon={<RefreshCw size={16} className={loading ? "animate-spin" : ""} />}
      onClick={refresh}
      aria-label="Refresh parameters"
    />
  </div>

  {/* Confirm banner (from Task 5) */}

  {/* Pipeline flow section */}
  <PipelineFlow nodes={pipelineNodes} />

  {/* Threshold metrics — SectionLabel has mb-2 baked in; use className="-mb-1"
     inside space-y-3 to avoid double spacing (12px gap + 8px margin) */}
  <SectionLabel as="h3" color="primary" className="-mb-1">Scoring Thresholds</SectionLabel>
  <div className="grid grid-cols-3 gap-2">
    <MetricCard label="Signal" value={formatThreshold(params.blending.thresholds.signal_threshold?.value)} />
    <MetricCard label="LLM" value={formatThreshold(params.blending.thresholds.llm_threshold?.value)} />
    <MetricCard label="ML Blend" value={formatThreshold(params.blending.ml_blend_weight?.value)} />
  </div>

  {/* Source weights */}
  <SectionLabel as="h3" color="primary" className="-mb-1">Source Weights</SectionLabel>
  <Card padding="sm">
    <WeightBar weights={params.blending.source_weights} />
  </Card>

  {/* Parameter categories */}
  <SectionLabel as="h3" color="primary" className="-mb-1">Parameters</SectionLabel>
  {/* ... ParameterCategory instances ... */}

  {/* Per-pair section */}
  <SectionLabel as="h3" color="primary" className="-mb-1">Per-Pair Parameters</SectionLabel>
  <Card variant="low" padding="sm" border>
    {/* ... pair/tf dropdowns + regime grid + learned ATR ... */}
  </Card>

  {/* Adaptive thresholds */}
  <SectionLabel as="h3" color="primary" className="-mb-1">Adaptive Thresholds</SectionLabel>
  <Card variant="low" padding="sm" border>
    {/* ... default threshold + overrides table ... */}
  </Card>
</div>
```

Remove the old `<div>` wrapper that contained the "Engine Parameters" heading and the threshold `<dl>` chips — they're replaced by the header and `MetricCard` grid above.

- [ ] **Step 4: Update spacing from space-y-2 to space-y-3**

The root `<div>` should use `space-y-3` (already done in step 3's template). Also update the inner `<PipelineFlow>` wrapper spacing to `space-y-2`.

- [ ] **Step 5: Improve SourceBadge**

Replace `SourceBadge.tsx` to show a clearer label:

```tsx
interface Props {
  source: "hardcoded" | "configurable";
}

export default function SourceBadge({ source }: Props) {
  if (source === "configurable") {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-500/15 text-green-400 uppercase tracking-wider">
        tunable
      </span>
    );
  }
  return null;
}
```

- [ ] **Step 6: Verify build and visual consistency**

Run: `cd web && pnpm build`
Expected: No TypeScript errors. The Engine tab now uses the same Card, SectionLabel, MetricCard, and Skeleton patterns as Settings, Optimizer, and ML pages. Spacing is `space-y-3`. Headers are consistent `text-[10px] font-headline font-bold uppercase` via SectionLabel.

---

### Task 7: Update engine store tests

Update the existing engine store test to cover the new `liveScores` state and `pushScores` action.

**Files:**
- Modify: `web/src/features/engine/__tests__/store.test.ts`

- [ ] **Step 1: Read existing test file**

Read `web/src/features/engine/__tests__/store.test.ts` to understand current test structure and patterns.

- [ ] **Step 2: Add pushScores test**

Add a test for the `pushScores` action:

```typescript
import { useEngineStore } from "../store";
import type { PipelineScores } from "../types";

describe("useEngineStore", () => {
  beforeEach(() => {
    useEngineStore.setState({
      params: null,
      loading: false,
      error: null,
      liveScores: {},
    });
  });

  // ... existing tests ...

  it("pushScores stores scores keyed by pair:timeframe", () => {
    const scores: PipelineScores = {
      pair: "BTC-USDT-SWAP",
      timeframe: "1H",
      technical: 42.5,
      order_flow: -10.3,
      onchain: null,
      patterns: 5.0,
      regime_blend: 30.1,
      ml_gate: 15.0,
      llm_gate: 0.8,
      signal: 35.2,
      emitted: false,
    };

    useEngineStore.getState().pushScores(scores);

    const stored = useEngineStore.getState().liveScores["BTC-USDT-SWAP:1H"];
    expect(stored).toEqual(scores);
  });

  it("pushScores overwrites previous scores for same key", () => {
    const first: PipelineScores = {
      pair: "BTC-USDT-SWAP",
      timeframe: "1H",
      technical: 42.5,
      order_flow: -10.3,
      onchain: null,
      patterns: 5.0,
      regime_blend: 30.1,
      ml_gate: 15.0,
      llm_gate: 0.8,
      signal: 35.2,
      emitted: false,
    };
    const second: PipelineScores = {
      ...first,
      technical: 50.0,
      signal: 45.0,
      emitted: true,
    };

    useEngineStore.getState().pushScores(first);
    useEngineStore.getState().pushScores(second);

    const stored = useEngineStore.getState().liveScores["BTC-USDT-SWAP:1H"];
    expect(stored.technical).toBe(50.0);
    expect(stored.signal).toBe(45.0);
    expect(stored.emitted).toBe(true);
  });
});
```

- [ ] **Step 3: Run tests**

Run: `cd web && npx vitest run src/features/engine/__tests__/store.test.ts`
Expected: All tests pass.

---

### Task 8: Final integration verification

- [ ] **Step 1: Run full frontend build**

Run: `cd web && pnpm build`
Expected: Clean build, no TypeScript errors.

- [ ] **Step 2: Run full frontend test suite**

Run: `cd web && npx vitest run`
Expected: All tests pass.

- [ ] **Step 3: Run backend tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 4: Commit all changes**

Single commit for the entire overhaul:

```bash
git add web/src/features/engine/ web/src/features/signals/hooks/useSignalWebSocket.ts backend/app/main.py backend/app/api/connections.py
git commit -m "feat(engine): descriptions, live scores, inline editing, shared UI migration"
```
