# Regime Optimizer Expansion — Design Spec

**Date:** 2026-03-27
**Status:** Draft
**Goal:** Expand regime weight optimization to cover all 5 scoring sources (tech, flow, onchain, pattern, liquidation) through two parallel workstreams.

---

## Problem

The current regime weight optimizer (DE-based) only tunes outer weights for tech + pattern because order flow, on-chain, and liquidation data aren't available during backtesting. This means 3 of 5 source weights are handcrafted defaults that have never been validated against outcomes.

The 5 scoring sources (`OUTER_KEYS` in `regime.py`): **tech**, **flow**, **onchain**, **pattern**, **liquidation**. On-chain and liquidation are separate scoring tracks — on-chain scores via `compute_onchain_score()` (Coinglass data), liquidation scores via `compute_liquidation_score()` (liquidation event clusters).

## Solution

Two parallel workstreams that are independently shippable:

- **Workstream B**: Wire `OrderFlowSnapshot` data into the backtester so the existing DE optimizer can tune flow outer weights on real historical data.
- **Workstream C**: Persist per-source scores on emitted signals, then run a new DE optimizer mode against resolved signal outcomes to tune all 5 outer weight categories.

## Guiding Principle

Backtest-driven validation — improvements are only worth keeping if the optimizer can measure the difference. No synthetic proxies. No changes without measurable fitness impact.

---

## Workstream B: OrderFlowSnapshot in Backtester

### B1. Pure Flow Scoring Function

**File:** `engine/traditional.py`

Extract the scoring logic from `compute_order_flow_score()` into a pure function:

```python
def score_order_flow(
    flow_metrics: dict,
    flow_history: list[dict] | None,
    regime_mix: dict,
    trend_conviction: float,
    mr_pressure: float,
    asset_scale: dict,
) -> dict:
    """Pure scoring function — no app.state dependency."""
    ...
```

The existing `compute_order_flow_score()` becomes a thin wrapper that reads from `app.state.order_flow` and `app.state.order_flow_history`, then delegates to `score_order_flow()`.

No behavior change to the live pipeline.

### B2. Backtester Flow Data Loading

**File:** `engine/backtester.py`

`BacktestConfig` gets an optional field:

```python
flow_snapshots: dict[int, dict] | None = None
```

Keyed by candle timestamp (epoch ms), values are `{funding_rate, open_interest, oi_change_pct, long_short_ratio, cvd_delta}`.

The caller queries `OrderFlowSnapshot` for the pair's date range and builds this lookup. Timestamp matching: find the snapshot with the closest timestamp <= candle close time. If no snapshot exists at or before a candle's timestamp (e.g., first candles in range before collection started), the lookup returns `None` and B3's fallback applies.

### B3. Backtester Scoring Integration

At each candle in the backtest loop:

1. Look up flow snapshot by candle timestamp
2. If found, push onto a rolling deque (size 10 = `TOTAL_SNAPSHOTS` from `RECENT_WINDOW(3) + BASELINE_WINDOW(7)` in `constants.ORDER_FLOW`)
3. Call `score_order_flow()` with the snapshot and rolling history
4. Pass the resulting `flow_score` and `flow_confidence` to `compute_preliminary_score()` (instead of hardcoded 0)
5. If no snapshot exists for that candle, fall back to current behavior (`flow_score=0, flow_weight=0.0`). The combiner's weight renormalization redistributes flow's weight to available sources automatically.

Graceful degradation: candles before snapshot collection started use tech+pattern only. Later candles with snapshots get full tech+pattern+flow scoring.

### B4. Optimizer Parameter Expansion

**File:** `engine/regime_optimizer.py`

When flow snapshots are provided:

- `_BACKTEST_OUTER_KEYS` expands from `["tech", "pattern"]` to `["tech", "pattern", "flow"]`
- `N_PARAMS` increases by 4 (one flow weight per regime)
- `PARAM_BOUNDS` gets 4 additional `_WEIGHT_BOUNDS` entries
- `_MockRegimeWeights` already handles arbitrary outer keys via its constructor loop

When no flow snapshots are provided, parameter space stays the same as today (backward compatible).

---

## Workstream C: Live Signal Optimizer

### C1. Per-Source Score Persistence

**File:** `main.py` (~line 1004, `raw_indicators` dict)

Add these keys to the `raw_indicators` JSONB on every emitted signal:

| Key | Source variable (main.py) | Notes |
|---|---|---|
| `tech_score` | `tech_result["score"]` | Currently stored as `traditional_score` on the signal row but NOT in `raw_indicators` |
| `tech_confidence` | `tech_conf` (from `tech_result.get("confidence", 0.5)`) | Not currently stored anywhere in raw_indicators |
| `flow_score` | `flow_result["score"]` | Aggregated score from `compute_order_flow_score()` |
| `flow_confidence` | `flow_conf` (from `flow_result.get("confidence", 0.5)`) | Not currently stored; individual flow details like `flow_contrarian_mult` are already stored but not the aggregated confidence |
| `onchain_score` | `onchain_score` (from `onchain_result["score"]`) | Separate source from liquidation — scores via `compute_onchain_score()` |
| `onchain_confidence` | `onchain_conf` (from `onchain_result.get("confidence", 0.0)`) | |
| `pattern_score` | `pat_score` | |
| `pattern_confidence` | `pattern_conf` (from `pat_result.get("confidence", 0.0)`) | |

`liquidation_score` and `liquidation_confidence` are already stored in `raw_indicators` (lines 1036-1037).

No database migration — JSONB keys only.

### C2. Shared DE Runner

**File:** `engine/regime_optimizer.py`

Extract common DE boilerplate into a shared function:

```python
def _run_de_optimization(
    objective_fn: Callable,
    param_bounds: list[tuple],
    max_iterations: int = 300,
    cancel_flag: dict | None = None,
    on_progress: Callable | None = None,
) -> dict:
    """Shared differential evolution runner."""
    ...
```

Both `optimize_regime_weights()` (backtest mode) and `optimize_from_signals()` (live mode) call this with their own objective functions and parameter bounds.

### C3. Live Signal Optimizer

**File:** `engine/regime_optimizer.py`

New entry point:

```python
def optimize_from_signals(
    signals: list[dict],
    pair: str,
    signal_threshold: int = 40,
    max_iterations: int = 300,
    cancel_flag: dict | None = None,
    on_progress: Callable | None = None,
) -> dict:
```

**Input:** List of resolved signal dicts, each containing:
- Per-source scores and confidences (from `raw_indicators`)
- Regime mix at emission time (from `raw_indicators`)
- Outcome (TP1_HIT, TP2_HIT, SL_HIT, EXPIRED)
- Entry, SL, TP levels for P&L calculation

**Parameter space:** Outer weights only — 5 sources x 4 regimes = 20 params. Inner caps are excluded because they affect how source scores are computed, and those scores are already baked into the stored values.

**Weight application chain per candidate weight vector:**

The live pipeline applies weights through this chain (main.py lines 613-668):
1. `blend_outer_weights(regime, regime_weights)` → raw outer weights per source
2. Zero unavailable sources, then renormalize remaining weights to sum to 1.0
3. Pass normalized weights + per-source confidences to `compute_preliminary_score()`
4. Inside the combiner, effective weights = `base_weight * confidence`, then re-normalized again

The objective function must replicate steps 1-4 using candidate outer weights:
1. For each signal, reconstruct `regime_mix` from stored `raw_indicators` keys (`regime_trending`, `regime_ranging`, `regime_volatile`, `regime_steady`)
2. Apply candidate outer weights for the dominant regime (same blending as `blend_outer_weights()`)
3. Zero any source whose stored score is 0 AND confidence is 0 (source was unavailable at emission), renormalize
4. Call `compute_preliminary_score()` with the renormalized weights and stored scores/confidences
5. Determine if the signal would still be emitted (`|re-scored| >= threshold`)
6. For emitted signals: compute win/loss from stored outcome (TP1_HIT/TP2_HIT = win, SL_HIT = loss, EXPIRED = loss with P&L from `outcome_pnl_pct`)
7. For suppressed signals: if the original outcome was a loss, count as a "filtered loss" (improves effective win rate). If the original outcome was a win, count as a "missed win" (penalizes fitness via lower trade count, which naturally hurts if it drops below 20).
8. Compute fitness: `win_rate*0.4 + profit_factor*0.3 + avg_rr*0.2 - max_dd*0.1` (same weights as backtest optimizer, `regime_optimizer.py` lines 29-45)

**Partial per-source scores:** Signals are included if they have at minimum `tech_score` and the `regime_*` keys present in `raw_indicators`. Missing source scores (e.g., `flow_score` absent because flow data was unavailable) are treated as score=0, confidence=0 — matching the live pipeline's degradation behavior where unavailable sources get zeroed weight.

**Concurrency:** Only one optimization task (backtest or live-signal) may run at a time per pair. If an optimization is already running, the endpoint returns HTTP 409 with the active task's status. Both modes share the existing `cancel_flag` mechanism in `app.state`.

Minimum 20 resolved signals required (same as backtest optimizer). If count < 20, endpoint returns HTTP 400 with the available count.

**Performance:** No candle replay or indicator computation — just combiner math on pre-computed scores. Full DE run should complete in seconds, not minutes.

### C4. API Endpoint

**File:** `api/optimizer.py` (alongside existing optimizer endpoints)

New endpoint: `POST /api/optimizer/optimize-from-signals`

Request body:
```python
class OptimizeFromSignalsRequest(BaseModel):
    pair: str
    timeframe: str | None = None  # None = all timeframes
    lookback_days: int = 90       # query window to bound signal count
    max_signals: int = 500        # hard cap on signals processed
    min_signals: int = 20
    max_iterations: int = 300
```

Behavior:
1. Check no optimization task is already running for this pair (return 409 if busy)
2. Query resolved signals from DB matching pair (and optionally timeframe), filtered to last `lookback_days` days, capped at `max_signals` (most recent first)
3. Filter to signals that have `tech_score` and `regime_trending` keys in `raw_indicators` (skip legacy signals without per-source scores)
4. If count < `min_signals`, return HTTP 400 with `{"error": "insufficient_signals", "available": count, "required": min_signals}`
5. Spawn async task calling `optimize_from_signals()`
6. Produce a `ParameterProposal` with `backtest_metrics` JSONB containing `"optimization_mode": "live_signals"` to distinguish from backtest-originated proposals (which use `"optimization_mode": "backtest"` or omit the key). No schema migration needed — `backtest_metrics` is already JSONB.
7. Broadcast `optimizer_update` WebSocket event (type: `"optimization_started"`, same schema as existing events)

### C5. Frontend Trigger

**File:** `features/optimizer/OptimizerPage.tsx` (or a sub-component)

Add a trigger mechanism on the existing OptimizerPage:
- Button labeled "Optimize from Live Signals" (or a toggle/tab between Backtest vs. Live mode)
- Pair selector (reuse existing)
- Shows resolved signal count for selected pair (query existing signals endpoint with outcome filter)
- Resulting proposals appear in the same proposal list. Distinguish source by reading `backtest_metrics.optimization_mode` — render a badge ("Backtest" / "Live Signals") on each proposal card.
- Disable button while any optimization is running (existing `isOptimizing` state covers this)

No new page or feature module — plugs into existing optimizer UI.

---

## What's Out of Scope

- Additional regime inputs (ADX + BB width only; deferred until this measurement infrastructure is in place)
- Inner cap optimization from live signals (caps affect source scores which are baked in stored signals)
- On-chain or liquidation snapshot persistence for backtester (low-weight sources, insufficient ROI)
- Changes to the proposal/shadow/promote workflow (reused as-is)
- Database schema migrations — no new columns or tables. Per-source scores use existing `raw_indicators` JSONB. Proposal source tagging uses existing `backtest_metrics` JSONB with an `optimization_mode` key convention.

---

## Files Affected

| File | Change | Workstream |
|---|---|---|
| `engine/traditional.py` | Extract `score_order_flow()` pure function | B |
| `engine/backtester.py` | Load flow snapshots, maintain rolling window, call `score_order_flow()` | B |
| `engine/regime_optimizer.py` | Extract shared DE runner, add `optimize_from_signals()`, expand `_BACKTEST_OUTER_KEYS` conditionally | B + C |
| `engine/constants.py` | `ORDER_FLOW_ASSET_SCALES` used by extracted pure function — may need to be passed as param or imported | B |
| `main.py` | Add per-source scores to `raw_indicators` dict (~line 1004) | C |
| `api/optimizer.py` | New `POST /api/optimizer/optimize-from-signals` endpoint, concurrency guard | C |
| `features/optimizer/OptimizerPage.tsx` | Add live optimization trigger button, proposal source badge | C |
| `features/optimizer/types.ts` | Add `optimization_mode` to proposal type (read from `backtest_metrics` JSONB) | C |
| `shared/lib/api.ts` | Add `optimizeFromSignals()` API method | C |

---

## Validation

### Workstream B
- Existing backtester tests must pass unchanged (no flow snapshots = same behavior as today)
- New tests for `score_order_flow()` pure function: given identical inputs, output matches `compute_order_flow_score()`
- Backtest with `flow_snapshots=None` produces identical results to current behavior
- Backtest with flow snapshots: flow_score > 0 for candles with matching snapshots, flow_score = 0 for candles without
- Integration test: backtest with flow snapshots produces different (better or equal) fitness than without
- Optimizer with flow snapshots has `N_PARAMS` = original + 4 and `_BACKTEST_OUTER_KEYS` includes `"flow"`

### Workstream C
- Every emitted signal has `tech_score`, `tech_confidence`, `flow_score`, `flow_confidence`, `onchain_score`, `onchain_confidence`, `pattern_score`, `pattern_confidence` in `raw_indicators`
- `optimize_from_signals()` with 20 mock resolved signals produces a valid weight vector (all weights > 0, per-regime sums normalized)
- `optimize_from_signals()` with < 20 signals raises/returns appropriate error
- Endpoint returns 409 when optimization already running for the pair
- Endpoint returns 400 with `available` count when insufficient signals
- Live optimizer correctly filters signals missing `tech_score` key in `raw_indicators`
- Signals with partial source scores (e.g., flow unavailable) included with score=0, confidence=0 for that source
- Produced `ParameterProposal` has `backtest_metrics.optimization_mode == "live_signals"`
