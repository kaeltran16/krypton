# V2 Component Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cherry-pick 4 component improvements from the v2 Stitch design into the current Kinetic Terminal UI — per-indicator score bars, engine reasoning chain, richer Pair Deep Dive, and dashboard sparkline.

**Architecture:** All 4 features are frontend-only except one backend change: exposing `raw_indicators` and `engine_snapshot` in the signal API response (data already stored in DB, just not serialized). Order flow fields are also added to `raw_indicators` at signal creation time. New components are self-contained files. Existing components get minimal modifications to import and render them. Commit once at the end per CLAUDE.md policy.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Zustand, Vitest

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/api/routes.py` | Add `raw_indicators` + `engine_snapshot` to `_signal_to_dict()` |
| Modify | `backend/app/main.py` | Add order flow fields to `raw_indicators` dict at signal creation |
| Modify | `web/src/features/signals/types.ts` | Add `RawIndicators` type + field on `Signal` |
| Modify | `web/src/features/signals/store.test.ts` | Add `raw_indicators: null` to test factory |
| Create | `web/src/features/signals/components/IndicatorAudit.tsx` | Per-indicator score bars (RSI, ADX, BB, Volume, Regime) |
| Create | `web/src/features/signals/components/ReasoningChain.tsx` | Synthesized engine reasoning chain from signal data |
| Modify | `web/src/features/signals/components/SignalDetail.tsx` | Import and render IndicatorAudit + ReasoningChain |
| Modify | `web/src/features/signals/components/PairDeepDive.tsx` | Add momentum profile, confidence bar, stats |
| Create | `web/src/features/home/components/MiniSparkline.tsx` | Tiny SVG sparkline component |
| Modify | `web/src/features/home/components/HomeView.tsx` | Add sparkline to AccountHeader |

---

## Task 1: Expose raw_indicators + engine_snapshot in API Response

**Files:**
- Modify: `backend/app/api/routes.py:24-51` (the `_signal_to_dict()` function)
- Modify: `backend/app/main.py` (~line 722, where `raw_indicators` dict is built)

- [ ] **Step 1: Add raw_indicators and engine_snapshot to _signal_to_dict**

In `backend/app/api/routes.py`, find the `_signal_to_dict()` function. Add both fields to the returned dict. Both are already stored as JSONB on the Signal model but excluded from serialization.

```python
# In _signal_to_dict(), add these keys to the returned dict:
"raw_indicators": signal.raw_indicators,
"engine_snapshot": signal.engine_snapshot,
```

Note: `engine_snapshot` is a pre-existing bug fix — the frontend `SignalDetail.tsx` already reads `signal.engine_snapshot` but REST responses never included it (only WebSocket broadcasts did).

- [ ] **Step 2: Add order flow fields to raw_indicators in main.py**

In `backend/app/main.py`, find where `raw_indicators` dict is constructed (around line 699-733). After the existing fields, add the raw order flow values from `flow_result["details"]`:

```python
# After existing raw_indicators fields, add:
"funding_rate": flow_result["details"].get("funding_rate") if flow_result else None,
"open_interest_change_pct": flow_result["details"].get("open_interest_change_pct") if flow_result else None,
"long_short_ratio": flow_result["details"].get("long_short_ratio") if flow_result else None,
```

These fields are computed in `compute_order_flow_score()` but were never persisted on the signal. The ReasoningChain component needs them to render the Order Flow step.

- [ ] **Step 3: Verify backend tests pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v -x`
Expected: All existing tests pass (both changes are additive).

---

## Task 2: Add RawIndicators Type to Frontend

**Files:**
- Modify: `web/src/features/signals/types.ts`
- Modify: `web/src/features/signals/store.test.ts`

- [ ] **Step 1: Add RawIndicators interface**

Add this interface to `types.ts`:

```typescript
export interface RawIndicators {
  // Technical indicators
  rsi?: number;
  adx?: number;
  di_plus?: number;
  di_minus?: number;
  bb_pos?: number;
  bb_width_pct?: number;
  obv_slope?: number;
  vol_ratio?: number;
  atr?: number;
  ema_9?: number;
  ema_21?: number;
  ema_50?: number;

  // Component scores
  mean_rev_score?: number;
  squeeze_score?: number;

  // Market regime
  regime_trending?: number;
  regime_ranging?: number;
  regime_volatile?: number;

  // Order flow (present when flow data available)
  funding_rate?: number;
  open_interest_change_pct?: number;
  long_short_ratio?: number;

  // Catch-all for additional engine fields
  [key: string]: number | string | boolean | null | undefined;
}
```

- [ ] **Step 2: Add raw_indicators field to Signal interface**

In the `Signal` interface, add:

```typescript
raw_indicators: RawIndicators | null;
```

Place it after `traditional_score` and before `llm_factors`.

- [ ] **Step 3: Fix test factory**

In `web/src/features/signals/store.test.ts`, find the `createSignal` factory function. Add `raw_indicators: null,` to the default signal object (alongside the other null fields like `llm_factors`, `risk_metrics`, etc.).

- [ ] **Step 4: Verify build + tests**

Run: `cd web && pnpm build && pnpm test`
Expected: Build succeeds, tests pass.

---

## Task 3: Per-Indicator Score Audit Component

**Files:**
- Create: `web/src/features/signals/components/IndicatorAudit.tsx`

- [ ] **Step 1: Create IndicatorAudit component**

This component takes `raw_indicators` and renders per-indicator score bars. Each indicator maps to a visual bar with contextual labels.

```tsx
import type { RawIndicators } from "../types";

interface IndicatorAuditProps {
  indicators: RawIndicators;
}

interface IndicatorRow {
  label: string;
  value: number;
  max: number;
  format: (v: number) => string;
  color?: string;
}

function getRows(ind: RawIndicators): IndicatorRow[] {
  const rows: IndicatorRow[] = [];

  if (ind.rsi != null) {
    rows.push({
      label: "RSI (14)",
      value: ind.rsi,
      max: 100,
      format: (v) => v.toFixed(1),
      color: ind.rsi > 70 ? "bg-error" : ind.rsi < 30 ? "bg-long" : "bg-primary",
    });
  }

  if (ind.adx != null) {
    rows.push({
      label: "ADX",
      value: ind.adx,
      max: 60,
      format: (v) => v.toFixed(1),
    });
  }

  if (ind.bb_pos != null) {
    rows.push({
      label: "BB Position",
      value: ind.bb_pos * 100,
      max: 100,
      format: (v) => `${v.toFixed(0)}%`,
    });
  }

  if (ind.vol_ratio != null) {
    rows.push({
      label: "Volume",
      value: Math.min(ind.vol_ratio * 50, 100),
      max: 100,
      format: () => `${ind.vol_ratio!.toFixed(2)}x avg`,
    });
  }

  if (ind.obv_slope != null) {
    rows.push({
      label: "OBV Flow",
      value: Math.min(Math.abs(ind.obv_slope) * 5000, 100),
      max: 100,
      format: () => (ind.obv_slope! >= 0 ? "Accumulation" : "Distribution"),
      color: ind.obv_slope >= 0 ? "bg-long" : "bg-short",
    });
  }

  return rows;
}

export function IndicatorAudit({ indicators }: IndicatorAuditProps) {
  const rows = getRows(indicators);
  if (rows.length === 0) return null;

  const regime = indicators.regime_trending != null ? {
    trending: indicators.regime_trending ?? 0,
    ranging: indicators.regime_ranging ?? 0,
    volatile: indicators.regime_volatile ?? 0,
  } : null;

  return (
    <div className="p-5 border-b border-outline-variant/10 space-y-4">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant">
        Indicator Breakdown
      </h3>

      {rows.map((row) => (
        <div key={row.label} className="space-y-1.5">
          <div className="flex justify-between text-xs">
            <span className="text-on-surface-variant">{row.label}</span>
            <span className="font-mono tabular-nums text-on-surface">
              {row.format(row.value)}
            </span>
          </div>
          <div className="h-1.5 w-full bg-surface-container-highest rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${row.color ?? "bg-primary"}`}
              style={{ width: `${Math.min((row.value / row.max) * 100, 100)}%` }}
            />
          </div>
        </div>
      ))}

      {regime && <RegimeBar regime={regime} />}
    </div>
  );
}

function RegimeBar({ regime }: { regime: { trending: number; ranging: number; volatile: number } }) {
  const total = regime.trending + regime.ranging + regime.volatile || 1;
  const pcts = {
    trending: (regime.trending / total) * 100,
    ranging: (regime.ranging / total) * 100,
    volatile: (regime.volatile / total) * 100,
  };
  const dominant = pcts.trending >= pcts.ranging && pcts.trending >= pcts.volatile
    ? "Trending"
    : pcts.volatile >= pcts.ranging
      ? "Volatile"
      : "Ranging";

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-on-surface-variant">Market Regime</span>
        <span className="font-mono tabular-nums text-on-surface">{dominant}</span>
      </div>
      <div className="h-1.5 w-full bg-surface-container-highest rounded-full overflow-hidden flex">
        {pcts.trending > 0 && (
          <div className="h-full bg-primary" style={{ width: `${pcts.trending}%` }} />
        )}
        {pcts.ranging > 0 && (
          <div className="h-full bg-outline" style={{ width: `${pcts.ranging}%` }} />
        )}
        {pcts.volatile > 0 && (
          <div className="h-full bg-error" style={{ width: `${pcts.volatile}%` }} />
        )}
      </div>
      <div className="flex gap-3 text-[10px] text-on-surface-variant">
        <span>Trend {pcts.trending.toFixed(0)}%</span>
        <span>Range {pcts.ranging.toFixed(0)}%</span>
        <span>Vol {pcts.volatile.toFixed(0)}%</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd web && pnpm build`
Expected: Build succeeds.

---

## Task 4: Engine Reasoning Chain Component

**Files:**
- Create: `web/src/features/signals/components/ReasoningChain.tsx`

- [ ] **Step 1: Create ReasoningChain component**

This component synthesizes a logical reasoning chain from existing signal data. No fake timestamps — shows the engine's analysis pipeline as sequential steps with extracted data.

```tsx
import type { Signal, DetectedPattern } from "../types";

interface ReasoningChainProps {
  signal: Signal;
}

interface Step {
  phase: string;
  detail: string;
  value?: string;
  sentiment?: "bullish" | "bearish" | "neutral";
}

function buildChain(signal: Signal): Step[] {
  const steps: Step[] = [];
  const ind = signal.raw_indicators;

  // Step 1: Market regime
  if (ind?.regime_trending != null) {
    const dominant =
      (ind.regime_trending ?? 0) >= (ind.regime_ranging ?? 0) &&
      (ind.regime_trending ?? 0) >= (ind.regime_volatile ?? 0)
        ? "trending"
        : (ind.regime_volatile ?? 0) >= (ind.regime_ranging ?? 0)
          ? "volatile"
          : "ranging";
    const total = (ind.regime_trending ?? 0) + (ind.regime_ranging ?? 0) + (ind.regime_volatile ?? 0) || 1;
    const pct = Math.round(((ind[`regime_${dominant}`] as number) / total) * 100);
    steps.push({
      phase: "Regime Detection",
      detail: `Market classified as ${dominant}`,
      value: `${pct}% confidence`,
      sentiment: dominant === "trending" ? "bullish" : "neutral",
    });
  }

  // Step 2: Technical scan — sentiment follows signal direction
  if (ind?.rsi != null) {
    const rsiLabel =
      ind.rsi > 70 ? "overbought" : ind.rsi < 30 ? "oversold" : "neutral";
    steps.push({
      phase: "Technical Scan",
      detail: `RSI ${ind.rsi.toFixed(1)} (${rsiLabel}), ADX ${ind.adx?.toFixed(1) ?? "N/A"}`,
      value: `Score: ${Math.abs(signal.traditional_score).toFixed(0)}`,
      sentiment: signal.direction === "LONG" ? "bullish" : "bearish",
    });
  }

  // Step 3: Pattern recognition
  if (signal.detected_patterns && signal.detected_patterns.length > 0) {
    const names = signal.detected_patterns
      .slice(0, 3)
      .map((p: DetectedPattern) => p.name)
      .join(", ");
    const bias = signal.detected_patterns[0]?.bias ?? "neutral";
    steps.push({
      phase: "Pattern Recognition",
      detail: names,
      value: `${signal.detected_patterns.length} pattern${signal.detected_patterns.length > 1 ? "s" : ""}`,
      sentiment: bias === "bullish" ? "bullish" : bias === "bearish" ? "bearish" : "neutral",
    });
  }

  // Step 4: Order flow
  if (ind?.funding_rate != null) {
    steps.push({
      phase: "Order Flow",
      detail: `Funding ${(ind.funding_rate * 100).toFixed(4)}%, OI ${ind.open_interest_change_pct != null ? `${ind.open_interest_change_pct > 0 ? "+" : ""}${ind.open_interest_change_pct.toFixed(1)}%` : "N/A"}`,
      value: ind.long_short_ratio != null ? `L/S ${ind.long_short_ratio.toFixed(2)}` : undefined,
      sentiment: "neutral",
    });
  }

  // Step 5: LLM consensus
  if (signal.llm_factors && signal.llm_factors.length > 0) {
    const bullCount = signal.llm_factors.filter((f) => f.direction === "bullish").length;
    const bearCount = signal.llm_factors.filter((f) => f.direction === "bearish").length;
    steps.push({
      phase: "LLM Consensus",
      detail: `${bullCount} bullish, ${bearCount} bearish factor${bullCount + bearCount > 1 ? "s" : ""}`,
      value: signal.llm_contribution != null ? `${signal.llm_contribution > 0 ? "+" : ""}${signal.llm_contribution.toFixed(1)}` : undefined,
      sentiment: bullCount > bearCount ? "bullish" : bearCount > bullCount ? "bearish" : "neutral",
    });
  }

  // Step 6: Final score
  steps.push({
    phase: "Signal Emission",
    detail: `${signal.direction} ${signal.pair} ${signal.timeframe}`,
    value: `Score: ${Math.abs(signal.final_score).toFixed(0)}/100`,
    sentiment: signal.direction === "LONG" ? "bullish" : "bearish",
  });

  return steps;
}

const SENTIMENT_DOT: Record<string, string> = {
  bullish: "bg-long",
  bearish: "bg-short",
  neutral: "bg-outline",
};

export function ReasoningChain({ signal }: ReasoningChainProps) {
  const steps = buildChain(signal);
  if (steps.length <= 1) return null;

  return (
    <div className="p-5 border-b border-outline-variant/10">
      <h3 className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-4">
        Engine Reasoning Chain
      </h3>
      <div className="space-y-0">
        {steps.map((step, i) => (
          <div key={step.phase} className="flex gap-3">
            {/* Timeline */}
            <div className="flex flex-col items-center w-3 flex-shrink-0">
              <div className={`w-2 h-2 rounded-full mt-1.5 ${SENTIMENT_DOT[step.sentiment ?? "neutral"]}`} />
              {i < steps.length - 1 && (
                <div className="w-px flex-1 bg-outline-variant/20 my-1" />
              )}
            </div>
            {/* Content */}
            <div className="pb-4 min-w-0">
              <div className="flex items-baseline gap-2">
                <span className="text-xs font-bold text-on-surface uppercase tracking-wider">
                  {step.phase}
                </span>
                {step.value && (
                  <span className="text-[10px] font-mono tabular-nums text-primary">
                    {step.value}
                  </span>
                )}
              </div>
              <p className="text-xs text-on-surface-variant mt-0.5 leading-relaxed">
                {step.detail}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd web && pnpm build`
Expected: Build succeeds.

---

## Task 5: Integrate IndicatorAudit + ReasoningChain into SignalDetail

**Files:**
- Modify: `web/src/features/signals/components/SignalDetail.tsx`

- [ ] **Step 1: Add imports**

At the top of `SignalDetail.tsx`, add:

```typescript
import { IndicatorAudit } from "./IndicatorAudit";
import { ReasoningChain } from "./ReasoningChain";
```

- [ ] **Step 2: Add IndicatorAudit after the Score Breakdown section**

Find the section ending with `</div>` after the `ScoreBar` components (around line 86, after the `llm_factors` block). Add right after that closing `</div>`:

```tsx
{signal.raw_indicators && (
  <IndicatorAudit indicators={signal.raw_indicators} />
)}
```

- [ ] **Step 3: Add ReasoningChain after IndicatorAudit (before detected_patterns)**

Right after the IndicatorAudit block, before the `detected_patterns` check:

```tsx
<ReasoningChain signal={signal} />
```

- [ ] **Step 4: Verify build**

Run: `cd web && pnpm build`
Expected: Build succeeds with no type errors.

---

## Task 6: Enrich PairDeepDive

**Files:**
- Modify: `web/src/features/signals/components/PairDeepDive.tsx`

The current PairDeepDive shows: price, regime text, 2 stats, signal audit log.
Enhancements: confidence progress bar, 4 stats (with win rate + avg P&L from `by_pair` data already returned by stats endpoint), momentum profile (live indicator values from latest signal).

- [ ] **Step 1: Add useSignalStats import and data extraction**

Add import at top:

```typescript
import { useSignalStats } from "../../home/hooks/useSignalStats";
```

Inside the component, after the existing hooks:

```typescript
const { stats } = useSignalStats(30);
const pairStats = stats?.by_pair[pair];
```

Note: This creates a separate API call from HomeView's `useSignalStats()` (which uses 7 days). This is intentional — PairDeepDive wants 30-day pair performance data.

- [ ] **Step 2: Replace the Market Regime section with confidence bar**

Replace the existing Market Regime `<section>` with a version that includes a confidence progress bar using regime data from the latest signal's `raw_indicators`:

```tsx
{/* Market Regime with Confidence */}
<section className="bg-surface-container rounded-lg p-5 border border-outline-variant/10">
  <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Market Regime</span>
  <div className="flex items-center gap-2 mb-3">
    <span className={`w-2 h-2 rounded-full animate-pulse motion-reduce:animate-none ${isPositive ? "bg-tertiary-dim" : "bg-error"}`} />
    <span className={`font-headline font-bold text-xl italic ${isPositive ? "text-tertiary-dim" : "text-error"}`}>
      {isPositive ? "Trending Bullish" : "Trending Bearish"}
    </span>
  </div>
  {(() => {
    const latest = pairSignals[0]?.raw_indicators;
    if (!latest?.regime_trending) return null;
    const total = (latest.regime_trending ?? 0) + (latest.regime_ranging ?? 0) + (latest.regime_volatile ?? 0) || 1;
    const confidence = Math.round((Math.max(latest.regime_trending ?? 0, latest.regime_ranging ?? 0, latest.regime_volatile ?? 0) / total) * 100);
    return (
      <div className="space-y-1">
        <div className="flex justify-between text-[10px] text-on-surface-variant">
          <span>CONFIDENCE</span>
          <span className="font-mono tabular-nums">{confidence}%</span>
        </div>
        <div className="h-1 bg-surface-container-highest rounded-full overflow-hidden">
          <div className="h-full bg-primary rounded-full" style={{ width: `${confidence}%` }} />
        </div>
      </div>
    );
  })()}
</section>
```

- [ ] **Step 3: Expand stats grid from 2 to 4 metrics**

Replace the existing 2-column stats grid with:

```tsx
<section className="grid grid-cols-2 gap-3">
  <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant/5">
    <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Signals (24h)</span>
    <span className="font-headline font-bold text-2xl tabular-nums">{pairSignals.length}</span>
  </div>
  <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant/5">
    <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Latest Score</span>
    <span className="font-headline font-bold text-2xl tabular-nums">
      {pairSignals[0]?.final_score?.toFixed(0) ?? "\u2014"}<span className="text-sm text-on-surface-variant">/100</span>
    </span>
  </div>
  <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant/5">
    <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Win Rate</span>
    <span className={`font-headline font-bold text-2xl tabular-nums ${(pairStats?.win_rate ?? 0) >= 50 ? "text-tertiary-dim" : "text-error"}`}>
      {pairStats ? `${pairStats.win_rate}%` : "\u2014"}
    </span>
  </div>
  <div className="bg-surface-container-low p-4 rounded-lg border border-outline-variant/5">
    <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] block mb-2">Avg P&L</span>
    <span className={`font-headline font-bold text-2xl tabular-nums ${(pairStats?.avg_pnl ?? 0) >= 0 ? "text-tertiary-dim" : "text-error"}`}>
      {pairStats ? `${pairStats.avg_pnl >= 0 ? "+" : ""}${pairStats.avg_pnl.toFixed(1)}%` : "\u2014"}
    </span>
  </div>
</section>
```

- [ ] **Step 4: Add Momentum Profile section**

After the stats grid and before the Signal Audit Log, add a momentum profile showing live indicator values from the latest signal's raw_indicators:

```tsx
{/* Momentum Profile */}
{(() => {
  const ind = pairSignals[0]?.raw_indicators;
  if (!ind) return null;
  const metrics = [
    { label: "RSI (14)", value: ind.rsi, format: (v: number) => v.toFixed(1) },
    { label: "ADX", value: ind.adx, format: (v: number) => v.toFixed(1) },
    { label: "Vol Ratio", value: ind.vol_ratio, format: (v: number) => `${v.toFixed(2)}x` },
  ].filter((m) => m.value != null);
  if (metrics.length === 0) return null;
  return (
    <section className="bg-surface-container rounded-lg p-5 border border-outline-variant/10">
      <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-3">Momentum Profile</h3>
      <div className="space-y-2">
        {metrics.map((m) => (
          <div key={m.label} className="flex items-center justify-between">
            <span className="text-xs text-on-surface-variant">{m.label}</span>
            <span className="font-mono font-bold text-sm tabular-nums text-on-surface">{m.format(m.value!)}</span>
          </div>
        ))}
      </div>
    </section>
  );
})()}
```

- [ ] **Step 5: Verify build**

Run: `cd web && pnpm build`
Expected: Build succeeds.

---

## Task 7: Dashboard Mini Sparkline

**Files:**
- Create: `web/src/features/home/components/MiniSparkline.tsx`
- Modify: `web/src/features/home/components/HomeView.tsx`

- [ ] **Step 1: Create MiniSparkline component**

A tiny, reusable SVG sparkline that renders inline. No axes, no labels — just a line with gradient fill. Uses `useId()` to avoid SVG gradient ID collisions if multiple instances render on the same page.

```tsx
import { useId } from "react";

interface MiniSparklineProps {
  data: number[];
  width?: number;
  height?: number;
  className?: string;
}

export function MiniSparkline({ data, width = 80, height = 24, className = "" }: MiniSparklineProps) {
  const gradId = useId();

  if (data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = 1;

  const points = data
    .map((v, i) => {
      const x = pad + (i / (data.length - 1)) * (width - pad * 2);
      const y = pad + (height - pad * 2) - ((v - min) / range) * (height - pad * 2);
      return `${x},${y}`;
    })
    .join(" ");

  const last = data[data.length - 1];
  const isPositive = last >= data[0];
  const color = isPositive ? "#56ef9f" : "#ff716c";

  const areaPoints = `${pad},${height - pad} ${points} ${width - pad},${height - pad}`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={className}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon fill={`url(#${gradId})`} points={areaPoints} />
      <polyline fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" points={points} />
    </svg>
  );
}
```

- [ ] **Step 2: Add sparkline to AccountHeader in HomeView**

In `HomeView.tsx`, add the import:

```typescript
import { MiniSparkline } from "./MiniSparkline";
```

The `AccountHeader` function currently receives `portfolio` and `loading`. Change its props to also accept equity curve data. In the parent `HomeView` return block, update:

```tsx
<AccountHeader
  portfolio={portfolio}
  loading={accountLoading}
  equityCurve={stats?.equity_curve.map((d) => d.cumulative_pnl) ?? []}
/>
```

Then update the `AccountHeader` function signature:

```typescript
function AccountHeader({ portfolio, loading, equityCurve }: {
  portfolio: Portfolio | null;
  loading: boolean;
  equityCurve: number[];
}) {
```

And inside AccountHeader, after the P&L percentage badge `<span>`, add the sparkline:

```tsx
{equityCurve.length >= 2 && (
  <MiniSparkline data={equityCurve} className="ml-auto opacity-80" />
)}
```

Place it inside the `flex items-center gap-2 mt-3` div, so the layout becomes: P&L amount + percentage badge + sparkline (right-aligned via ml-auto).

- [ ] **Step 3: Verify build**

Run: `cd web && pnpm build`
Expected: Build succeeds.

---

## Final Verification

- [ ] **Step 1: Full build check**

```bash
cd web && pnpm build
```

- [ ] **Step 2: Lint check**

```bash
cd web && pnpm lint
```

- [ ] **Step 3: Backend tests**

```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v
```

- [ ] **Step 4: Frontend tests**

```bash
cd web && pnpm test
```

- [ ] **Step 5: Visual verification**

Start dev server (`pnpm dev`), open a signal detail dialog, and verify:
1. Indicator Breakdown section appears with RSI/ADX/BB/Volume/Regime bars
2. Engine Reasoning Chain shows analysis steps with colored dots
3. Dashboard header shows mini sparkline next to P&L
4. PairDeepDive (if navigable) shows confidence bar, 4 stats, momentum profile

- [ ] **Step 6: Commit all changes**

Per CLAUDE.md policy, commit once at the end:

```bash
git add backend/app/api/routes.py backend/app/main.py \
  web/src/features/signals/types.ts \
  web/src/features/signals/store.test.ts \
  web/src/features/signals/components/IndicatorAudit.tsx \
  web/src/features/signals/components/ReasoningChain.tsx \
  web/src/features/signals/components/SignalDetail.tsx \
  web/src/features/signals/components/PairDeepDive.tsx \
  web/src/features/home/components/MiniSparkline.tsx \
  web/src/features/home/components/HomeView.tsx
git commit -m "feat(ui): add indicator audit, reasoning chain, enriched pair deep dive, dashboard sparkline"
```
