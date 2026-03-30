# Pipeline Monitor — Design Spec

## Overview

A new "Pipeline Monitor" page that shows every pipeline evaluation (emitted and rejected), with summary stats and expandable detail rows. Answers the question: "why aren't signals being emitted?" by making all scoring data visible, not just emitted signals.

Currently, non-emitted evaluations are logged to stdout but not persisted. This feature adds DB persistence for all evaluations with 7-day retention, a REST API for querying them, and a frontend page under the "More" menu.

## Backend

### New Model: `PipelineEvaluation`

Table: `pipeline_evaluations`

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger, PK | auto-increment |
| `pair` | String(32), not null | e.g. "BTC-USDT-SWAP" |
| `timeframe` | String(8), not null | e.g. "5m" |
| `evaluated_at` | DateTime(timezone=True), not null | candle close timestamp |
| `emitted` | Boolean, not null | whether a signal was created |
| `signal_id` | Integer, FK → signals.id (ON DELETE SET NULL), nullable | links to Signal row if emitted |
| `final_score` | Integer, not null | -100 to +100 |
| `effective_threshold` | Integer, not null | adaptive threshold used |
| `tech_score` | Integer, not null | technical indicator score |
| `flow_score` | Integer, not null | order flow score |
| `onchain_score` | Integer, nullable | on-chain score (if available) |
| `pattern_score` | Integer, nullable | candlestick pattern score |
| `liquidation_score` | Integer, nullable | liquidation cluster score |
| `confluence_score` | Integer, nullable | multi-timeframe confluence score |
| `indicator_preliminary` | Integer, not null | pre-ML weighted blend |
| `blended_score` | Integer, not null | post-ML blend |
| `ml_score` | Float, nullable | ML model raw prediction |
| `ml_confidence` | Float, nullable | ML model confidence |
| `llm_contribution` | Integer, not null, default 0 | LLM adjustment (0 if gate not triggered) |
| `ml_agreement` | String(16), not null | "agree" / "disagree" / "neutral" — ML-indicator alignment from `compute_agreement(indicator_preliminary, ml_score)`. "neutral" when ML is unavailable (`ml_score` is None). |
| `indicators` | JSONB, not null | see JSONB Schemas section below |
| `regime` | JSONB, not null | see JSONB Schemas section below |
| `availabilities` | JSONB, not null | see JSONB Schemas section below |

**Indexes:**
- `ix_pipeline_eval_pair_time` on `(pair, evaluated_at)` — main query path
- `ix_pipeline_eval_time` on `(evaluated_at)` — for pruning and time-range queries

**Default ordering:** `evaluated_at DESC` (most recent first) for all queries.

**Location:** Add to `backend/app/db/models.py` alongside existing models.

### JSONB Schemas

**`indicators`** — flat dict of all raw indicator values available at evaluation time:
```json
{
  "adx": 28.5, "rsi": 55.2, "bb_upper": 68500, "bb_lower": 67200, "bb_width": 0.019,
  "obv_slope": 0.003, "vol_ratio": 1.2, "atr": 350.5,
  "funding_rate": 0.0001, "long_short_ratio": 1.05, "oi_change_pct": 0.02,
  "cvd_delta": 15000, "regime_trending": 0.4, "regime_ranging": 0.35,
  "regime_volatile": 0.25
}
```
Superset of what's available — keys absent when source unavailable. Built from `tech_result["indicators"]` merged with flow/on-chain data already computed at evaluation time (see Pipeline Integration below).

**`regime`** — continuous regime mix floats (sum to ~1.0):
```json
{ "trending": 0.4, "ranging": 0.35, "volatile": 0.25 }
```
Sourced from `tech_result["regime"]`. Three keys only (no `steady` — steady state is implied by low values across all three).

**`availabilities`** — per scoring source, availability weight and conviction:
```json
{
  "tech": { "availability": 1.0, "conviction": 0.85 },
  "flow": { "availability": 1.0, "conviction": 0.6 },
  "onchain": { "availability": 0.0, "conviction": 0.0 },
  "pattern": { "availability": 1.0, "conviction": 0.3 },
  "liquidation": { "availability": 0.0, "conviction": 0.0 },
  "confluence": { "availability": 1.0, "conviction": 0.5 }
}
```
Sources with `availability: 0.0` were unavailable for this evaluation.

### Pipeline Integration

In `main.py:run_pipeline`, after the threshold check at ~line 1000 and before the early return for non-emitted evals, insert a `PipelineEvaluation` row. This captures both emitted and rejected evaluations.

Data needed is already computed at this point in the pipeline:
- `final`, `effective_threshold`, `emitted` — from threshold check
- `tech_result`, `flow_result`, `onchain_result`, etc. — from scoring phase
- `indicator_preliminary`, `blended`, `ml_score`, `ml_confidence` — from combination phase
- `llm_contribution`, `ml_agreement` — from LLM gate
- `regime` — from `tech_result["regime"]`

**Building `indicators` for all evaluations:** The `_build_raw_indicators()` helper is currently called only for emitted signals (after the early return). For the evaluation row, build a lightweight indicators dict directly from data already available at the insertion point: `tech_result["indicators"]` (contains ADX, RSI, BB, OBV, etc.) merged with flow data from `app.state.order_flow[pair]` (funding rate, L/S ratio, OI, CVD) and regime floats from `tech_result["regime"]`. Do not call `_build_raw_indicators()` for rejected evals — avoid adding latency to the hot path.

**Failure handling:** The evaluation INSERT is observability data and must not block signal emission. Wrap in try/except — log the error and continue. For emitted signals, persist the evaluation row first, then proceed to `_emit_signal()` independently.

For emitted signals, set `signal_id` to the newly created Signal's id. This requires inserting the eval row with `signal_id=None` initially, then updating it after `_emit_signal()` returns the signal id. Alternatively, insert the eval row after `_emit_signal()` for emitted evals only (with `signal_id` set), and before the early return for rejected evals (with `signal_id=None`).

### Pruning

Add a daily background task (similar to existing signal resolution loop) that runs:
```sql
DELETE FROM pipeline_evaluations WHERE evaluated_at < now() - interval '7 days'
```

Register in `main.py` lifespan alongside other background tasks.

### Alembic Migration

New migration to create the `pipeline_evaluations` table with columns and indexes as specified above.

### New API: `backend/app/api/monitor.py`

**`GET /api/monitor/evaluations`**

Query params:
- `pair` (optional): filter by pair
- `emitted` (optional): boolean filter
- `after` (optional): ISO datetime, evaluations after this time
- `before` (optional): ISO datetime, evaluations before this time
- `limit` (optional): default 50, max 200
- `offset` (optional): default 0

Response: `{ items: PipelineEvaluation[], total: int }`

Each item includes all columns. `indicators`, `regime`, `availabilities` are returned as JSON objects. Results ordered by `evaluated_at DESC`. `total` reflects the filtered count (not all-time total).

**`GET /api/monitor/summary`**

Query params:
- `period` (optional): "1h", "6h", "24h" (default), or "7d"

Response:
```json
{
  "period": "24h",
  "total_evaluations": 847,
  "emitted_count": 12,
  "emission_rate": 0.014,
  "avg_abs_score": 24.3,
  "per_pair": [
    {
      "pair": "BTC-USDT-SWAP",
      "total": 283,
      "emitted": 5,
      "emission_rate": 0.018,
      "avg_abs_score": 26.1
    }
  ]
}
```

`per_pair` always includes all configured pairs (BTC/ETH/WIF), even if a pair has zero evaluations in the period (returns zero counts).

Both endpoints require `X-API-Key` auth (same as all other endpoints).

Register the router in `main.py` app factory alongside existing routers.

## Frontend

### New Feature: `web/src/features/monitor/`

Structure:
```
features/monitor/
├── components/
│   ├── MonitorPage.tsx       # Main page component
│   ├── SummaryCards.tsx       # Top summary metrics
│   ├── PairBreakdown.tsx      # Per-pair emission rate cards
│   ├── EvaluationTable.tsx    # Filterable evaluation list
│   └── EvaluationDetail.tsx   # Expanded row detail view
├── hooks/
│   └── useMonitorData.ts     # Data fetching hook
└── types.ts                  # TypeScript types
```

### Navigation

Add "Pipeline Monitor" as a sub-page entry in the More page. Add `"monitor"` to the `SubPage` type union in `MorePage.tsx`. Render `MonitorPage` when selected.

### Page Layout

Top to bottom, single scrollable column (mobile-first):

1. **SubPageShell** header with "Pipeline Monitor" title and back button
2. **Filter bar**: Pair dropdown (All / BTC / ETH / WIF), Status dropdown (All / Emitted / Rejected), Time range dropdown (1h / 6h / 24h / 7d), Refresh button. Time range selection applies to both the evaluations list and the summary cards (summary endpoint accepts all four periods).
3. **Summary cards** (3-column grid): Total evaluations, Emitted count + rate, Average |score|
4. **Per-pair breakdown** (3-column grid): Each pair shows eval count, emitted count, emission rate progress bar
5. **Evaluation table**: Rows showing time, pair, final score, tech score, flow score, threshold, status badge. Tap to expand.
6. **Expanded detail** (inline below tapped row): Two-column grid showing the scoring pipeline stages: sub-scores (tech, flow, onchain, pattern, liquidation, confluence) → `indicator_preliminary` (weighted blend) → `blended_score` (post-ML) → `final_score` (post-LLM). Show ML agreement badge and LLM contribution. Collapsible "Technical Indicators" and "Order Flow" sections with full indicator values from the `indicators` JSONB.
7. **Load more** button at bottom for pagination

### Styling

Follow existing patterns:
- Use `Card` component for summary and breakdown cards
- Use `MetricCard` for summary stats
- Use `Badge` for emitted/rejected status
- Use `CollapsibleSection` for expanded detail sections
- Score colors: positive → `long` (#0ECB81), negative → `short` (#F6465D), neutral/low → `text-zinc-500`
- Near-threshold rejected rows get subtle amber tint: rejected rows where `|final_score| >= effective_threshold * 0.85`
- Use `Skeleton` components for loading states

### Data Fetching

`useMonitorData` hook:
- Holds filter state (pair, emitted, time range)
- Calls `api.getMonitorEvaluations(filters)` and `api.getMonitorSummary(period)`
- Manual refresh via callback (no auto-polling)
- Loading state: show `Skeleton` placeholders matching the summary cards and table row layout
- Error state: inline error message with retry button (no toast — page-level errors stay on-page)
- Empty state: when filters match nothing, show `EmptyState` component with "No evaluations match your filters" message. On fresh install (no evaluations at all), show "Pipeline evaluations will appear here after the first candle closes."
- Pagination: tracks offset, appends on "load more"

### API Client

Add to `web/src/shared/lib/api.ts`:
- `getMonitorEvaluations(params)` → `GET /api/monitor/evaluations`
- `getMonitorSummary(params)` → `GET /api/monitor/summary`

### Types

Add to `web/src/features/monitor/types.ts`:
- `PipelineEvaluation` — mirrors DB model, with `indicators` typed as `Record<string, number>`, `regime` as `{ trending: number; ranging: number; volatile: number }`, `availabilities` as `Record<string, { availability: number; conviction: number }>`, and `ml_agreement` as `"agree" | "disagree" | "neutral"`
- `MonitorSummary` — mirrors summary response
- `PairSummary` — per-pair stats within summary
- `MonitorFilters` — filter state shape (`pair`, `emitted`, `period`)

## Out of Scope

- Real-time WebSocket push of evaluations (manual refresh only)
- Score distribution histograms or charts
- Alerting on low emission rates
- Comparison between time periods
- Export/download of evaluation data

These can be added later if needed.
