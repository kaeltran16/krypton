# Engine Parameter Optimizer — Design Spec

## Overview

A self-tuning system that monitors parameter fitness, proposes changes backed by backtests, validates them in shadow mode, and promotes improvements — all managed through a dashboard with an approval gate. Extends the existing Engine page and PerformanceTracker infrastructure.

## Goals

1. **Observability**: Pipeline flow diagram showing how scores traverse the system, per-signal traceability
2. **Understanding**: Each node in the pipeline is tappable, revealing sub-scores and the parameters that produced them
3. **Auto-tuning**: All ~200 engine parameters are organized into groups, continuously monitored, and optimized via a hybrid live-tracking + backtest approach with human approval

## Architecture

### Data Flow (User-Facing Pipeline Diagram)

```
Candles --> [Technical] --+
                          |
Order Flow ---------------+-- Regime Blend -- ML Gate -- LLM Gate -- Signal
                          |      ^
On-Chain -----------------+   (inner caps +
                          |    outer weights)
Patterns -----------------+
```

Each node displays its output from the most recent signal. Tapping a node expands to show sub-scores and contributing parameters. Read-only — no controls on this diagram.

### Parameter Descriptions (Info Popups)

Every parameter displayed in the Engine page and Optimizer proposal diffs includes an info icon that opens a tooltip/popup explaining:
- **What it does**: Plain-language description of the parameter's role (e.g., "Controls how aggressively RSI extremes contribute to mean-reversion scores")
- **Where it acts**: Which stage of the pipeline it affects (e.g., "Technical scoring -> Mean Reversion")
- **Range/constraints**: Valid values and what happens at the extremes (e.g., "0.1-1.0 — higher = sharper sigmoid curve, more binary scoring")

Descriptions are defined in a shared constant map (`PARAMETER_DESCRIPTIONS`) in `engine/constants.py` on the backend (~200 entries), served via the `/api/engine/parameters` endpoint alongside values. Authoring all ~200 descriptions is an explicit work item in this feature — each entry is a short dict with `description`, `pipeline_stage`, and `range` fields. Rendered as info popups on both the Engine page's `ParameterRow` component and the Optimizer's proposal diff tables.

### Frontend Layout

**Engine page** (existing, enhanced):
- New pipeline flow diagram at the top
- Existing parameter browser unchanged below
- Small badge/indicator when a pending proposal exists (links to Optimizer)

**Optimizer page** (new, under "More" menu alongside Engine):
- Group health table: each parameter group's rolling profit factor, colored status (green/yellow/red), last optimized metadata
- Proposal cards: diff table (param name, current -> proposed), backtest metrics, Approve/Reject buttons
- Shadow progress: live two-column comparison (current vs proposed), progress bar (e.g., "12/20 signals"), real-time updates via WebSocket
- History log: expandable list of past promotions/rejections with dates and metrics

### Backend — Generalized PerformanceTracker

The existing `PerformanceTracker` expands from ATR-only to managing all parameter groups.

**Fitness Tracking**: Fitness is tracked at the whole-signal level, not decomposed per parameter group. On each signal resolution, the optimizer updates a global rolling profit factor. To determine which group to investigate, it uses **counterfactual backtesting**: periodically re-run recent signals with one group's parameters perturbed while others stay fixed. If a group's perturbation consistently improves profit factor, that group is flagged as the optimization target. This avoids the impossible problem of attributing a single signal's P&L to individual parameter groups.

**Backtest Dispatch**: When a group is flagged, run a targeted backtest — sweep candidates for that group only, holding all other params fixed. Rank candidates by profit factor. If the best candidate beats current by >5%, create a proposal.

**Background Loop**: New `run_optimizer_loop()` task alongside the existing pipeline. Checks group fitness every N signal resolutions, dispatches backtests when needed, manages shadow scoring, handles auto-promote/reject/rollback.

### New DB Model — `ParameterProposal`

```
id: int (PK)
status: enum (pending, shadow, approved, rejected, promoted, rolled_back)
parameter_group: str
changes: JSONB  -- {path: {current: value, proposed: value}}
backtest_metrics: JSONB  -- {profit_factor, win_rate, avg_rr, drawdown, signals_tested}
shadow_metrics: JSONB (nullable)  -- filled during shadow mode
created_at: datetime
shadow_started_at: datetime (nullable)
promoted_at: datetime (nullable)
rejected_reason: str (nullable)
```

### Shadow Mode

When a proposal is approved:

1. Engine scores each signal twice — once with current params, once with proposed params for the affected group
2. Shadow results stored in a separate `ShadowResult` table (FK to Signal): `{proposal_id, signal_id, shadow_score, shadow_entry, shadow_sl, shadow_tp1, shadow_tp2, shadow_outcome}` — keeps the Signal model lean since shadow mode is intermittent
3. Shadow scores are never acted upon (no trades, no notifications)
4. After N signals resolve (default 20) with shadow data:
   - Shadow profit factor > current profit factor --> auto-promote
   - Shadow profit factor < current by >10% --> auto-reject
   - Within 10% --> surface as "inconclusive" for manual decision
5. Only one shadow proposal active at a time. Additional proposals queue as pending.

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/optimizer/status` | Group health scores, active proposal, shadow progress |
| GET | `/api/optimizer/proposals` | Paginated proposal history |
| POST | `/api/optimizer/proposals/{id}/approve` | Start shadow mode |
| POST | `/api/optimizer/proposals/{id}/reject` | Reject with optional reason |
| POST | `/api/optimizer/proposals/{id}/promote` | Early manual promote during shadow |
| POST | `/api/optimizer/proposals/{id}/rollback` | Revert a promoted change |

**WebSocket**: Extend existing `/ws/signals` with `optimizer_update` event type for live shadow progress and proposal state changes.

### Parameter Groups

| Group | Parameters | Sweep Method | Constraints |
|-------|-----------|--------------|-------------|
| `source_weights` | traditional, flow, onchain, pattern | Grid, step 0.05 | Must sum to 1.0 |
| `thresholds` | signal, llm, ml_confidence | Grid, step 5/5/0.05 | signal > llm |
| `regime_caps` | 12 inner caps (4 per regime) | Differential evolution | Caps sum to 100 per regime |
| `regime_outer` | 12 outer weights (4 per regime) | Differential evolution | Sum to 1.0 per regime |
| `atr_levels` | sl, tp1, tp2 defaults | Grid (existing tracker) | tp2 > tp1 > sl, R:R floor |
| `sigmoid_curves` | ~7 steepness/center params | Differential evolution | Positive values |
| `order_flow` | max scores, steepnesses | Differential evolution | Max scores sum <= 100 |
| `pattern_strengths` | 15 pattern strengths | Differential evolution | Range 3-25 |
| `indicator_periods` | ADX, RSI, SMA, EMA, OBV | Grid, standard periods | Integers only |
| `mean_reversion` | rsi/bb steepness, blend ratio | Grid | blend_ratio in [0,1] |
| `llm_factors` | 12 factor weights + cap | Differential evolution | Cap <= 50 |
| `onchain` | per-asset profiles | Differential evolution, per asset | Max scores <= 100 |

**Priority layering**: Groups optimize in order — `thresholds` and `source_weights` first (biggest impact, fewest params), then `regime_*` and `atr_levels`, then everything else. A group won't optimize if a higher-priority group has an active proposal.

### Guardrails

- No group optimizes more than once per 50 resolved signals
- Maximum 1 shadow proposal active at a time (isolate changes)
- Auto-rollback if live profit factor drops >15% within 10 signals of promotion
- Priority layering prevents cascading changes
- All changes persisted to DB with full audit trail

### Primary Metric

**Profit factor** (total gains / total losses) is the primary optimization metric. Used for:
- Global health scoring and counterfactual group evaluation
- Backtest candidate ranking
- Shadow mode promotion/rejection decisions

The existing regime optimizer's composite fitness formula (win_rate * 0.4 + profit_factor * 0.3 + avg_rr * 0.2 - max_dd * 0.1) is used as a secondary ranking when profit factor alone produces ties or near-ties between candidates.

## Files Affected

### New Files
- `backend/app/engine/optimizer.py` — optimizer loop, group definitions, backtest dispatch, shadow management
- `backend/app/api/optimizer.py` — REST endpoints for optimizer status/proposals
- `backend/app/db/migrations/` — new migration for `ParameterProposal` and `ShadowResult` models
- `web/src/features/optimizer/` — new feature slice (components, store, types)

### Modified Files
- `backend/app/engine/performance_tracker.py` — generalize to support parameter groups
- `backend/app/db/models.py` — add `ParameterProposal` and `ShadowResult` models
- `backend/app/main.py` — start optimizer loop in lifespan
- `backend/app/api/routes.py` — register optimizer router
- `web/src/features/engine/components/EnginePage.tsx` — add pipeline flow diagram, proposal badge
- `web/src/shared/lib/api.ts` — add optimizer API methods
- `web/src/features/more/components/MorePage.tsx` — add Optimizer entry (Optimizer lives under "More" alongside Engine, not as a new bottom tab)
