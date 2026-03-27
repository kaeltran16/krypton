# Regime Optimizer Expansion — Design Spec

**Date:** 2026-03-27
**Status:** Draft
**Goal:** Expand regime weight optimization to cover all 6 scoring sources (tech, flow, onchain, pattern, liquidation, confluence) through two parallel workstreams.

---

## Problem

The current regime weight optimizer (DE-based) only tunes outer weights for tech + pattern because order flow, on-chain, liquidation, and confluence data aren't available during backtesting. This means 4 of 6 source weights are handcrafted defaults that have never been validated against outcomes.

The 6 scoring sources (`OUTER_KEYS` in `regime.py`): **tech**, **flow**, **onchain**, **pattern**, **liquidation**, **confluence**. On-chain and liquidation are separate scoring tracks — on-chain scores via `compute_onchain_score()` (Coinglass data), liquidation scores via `compute_liquidation_score()` (liquidation event clusters). Confluence scores via `compute_confluence_score()` measure multi-timeframe agreement from parent candle data.

## Solution

Two parallel workstreams that are independently shippable:

- **Workstream B**: Wire `OrderFlowSnapshot` data into the backtester so the existing DE optimizer can tune flow outer weights on real historical data.
- **Workstream C**: Persist per-source scores on emitted signals, then run a new DE optimizer mode against resolved signal outcomes to tune all 6 outer weight categories.

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
    flow_age_seconds: float | None = None,
    asset_scale: float = 1.0,
) -> dict:
    """Pure scoring function — no app.state dependency."""
    ...
```

Parameters match the current `compute_order_flow_score()` signature exactly. `flow_age_seconds` drives freshness decay on confidence (live pipeline computes this from snapshot timestamp vs. current time; backtester computes it from `candle_close_time - snapshot_timestamp`). `asset_scale` is a per-pair float looked up from `ORDER_FLOW_ASSET_SCALES[pair]` by the caller — the pure function receives the resolved scalar, not the lookup dict.

The existing `compute_order_flow_score()` becomes a thin wrapper that reads from `app.state.order_flow` and `app.state.order_flow_history`, then delegates to `score_order_flow()`.

No behavior change to the live pipeline.

### B2. Backtester Flow Data Loading

**File:** `engine/backtester.py`

`BacktestConfig` gets an optional field:

```python
flow_snapshots: list[dict] | None = None
```

A pre-sorted list (ascending by timestamp) of snapshot dicts, each with `{timestamp: datetime, funding_rate, open_interest, oi_change_pct, long_short_ratio, cvd_delta}`. Timestamps are `datetime` objects matching the `OrderFlowSnapshot.timestamp` DB column type.

The caller queries `OrderFlowSnapshot` for the pair's date range and builds this list. At backtest init, an index is built for O(1) lookup: `bisect_right` on snapshot timestamps to find the most recent snapshot with `timestamp <= candle_close_time`. Maximum drift tolerance: `2 * candle_interval` — if the closest snapshot is older than 2 candle intervals, treat as missing (no snapshot for that candle). If multiple snapshots fall within one candle window, the most recent one (closest to candle close) is used. If no snapshot exists at or before a candle's timestamp (e.g., first candles in range before collection started), the lookup returns `None` and B3's fallback applies.

### B3. Backtester Scoring Integration

At each candle in the backtest loop:

1. Look up flow snapshot by candle timestamp (using bisect index from B2)
2. If found, push onto a rolling deque (size 10 = `TOTAL_SNAPSHOTS` from `RECENT_WINDOW(3) + BASELINE_WINDOW(7)` in `constants.ORDER_FLOW`). Do not advance the deque when no snapshot is found — maintain position so RoC baselines stay consistent.
3. Call `score_order_flow()` with the snapshot as `flow_metrics`, deque contents as `flow_history`, and `flow_age_seconds` computed as `(candle_close_time - snapshot_timestamp).total_seconds()`
4. Pass the resulting `flow_score` and `flow_confidence` to `compute_preliminary_score()` (instead of hardcoded 0)
5. If no snapshot exists for that candle, fall back to current behavior (`flow_score=0, flow_weight=0.0`). The combiner's weight renormalization redistributes flow's weight to available sources automatically.

**RoC ramp-up:** The flow scoring function's RoC override requires `len(flow_history) >= TOTAL_SNAPSHOTS` (10 snapshots). During the first 9 candles with snapshots, RoC boost is naturally disabled (`roc_boost=0.0`), matching live pipeline behavior. This is expected — no special handling needed.

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
| `regime_steady` | `tech_result["indicators"].get("regime_steady")` | Currently missing — `regime_trending/ranging/volatile` are stored but `regime_steady` is not. Required by C3 for regime mix reconstruction. |

`liquidation_score`, `liquidation_confidence`, `confluence_score`, and `confluence_confidence` are already stored in `raw_indicators`.

These keys align with `_IC_SOURCE_KEYS` in `engine/optimizer.py` (which maps `OUTER_KEYS` → `{key}_score`), enabling IC pruning to automatically cover all 6 sources once the data is present.

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

**Parameter space:** Outer weights only — 6 sources × 4 regimes = 24 params. All 6 `OUTER_KEYS` (tech, flow, onchain, pattern, liquidation, confluence) are tuned. Inner caps are excluded because they affect how source scores are computed, and those scores are already baked into the stored values.

**Weight application chain per candidate weight vector:**

The live pipeline applies weights through this chain (main.py lines 613-668):
1. `blend_outer_weights(regime, regime_weights)` → raw outer weights per source (all 6 keys)
2. Zero unavailable sources, then renormalize remaining weights to sum to 1.0
3. Pass normalized weights + per-source confidences to `compute_preliminary_score()`
4. Inside the combiner, effective weights = `base_weight * confidence`, then re-normalized again

The objective function must replicate steps 1-4 using candidate outer weights:
1. For each signal, reconstruct `regime_mix` from stored `raw_indicators` keys (`regime_trending`, `regime_ranging`, `regime_volatile`, `regime_steady`)
2. Apply candidate outer weights for the dominant regime (same blending as `blend_outer_weights()`)
3. Zero any source whose stored score is 0 AND confidence is 0 (source was unavailable at emission), renormalize
4. Call `compute_preliminary_score()` with the renormalized weights and stored scores/confidences
5. Determine if the signal would still be emitted (`|re-scored| >= threshold`)
6. Build trade list and compute fitness (see pseudocode below)

**Trade list construction pseudocode:**

```python
kept_trades = []     # signals that pass re-scoring threshold
filtered_wins = 0    # original wins suppressed by new weights (penalty via lower trade count)

for signal in signals:
    re_scored = abs(compute_preliminary_score(...))  # steps 1-4 above
    is_win = signal["outcome"] in ("TP1_HIT", "TP2_HIT")
    pnl_pct = signal["outcome_pnl_pct"] or 0.0  # nullable; default 0 if missing

    if re_scored >= threshold:
        # Signal would still be emitted — include in trade list
        kept_trades.append({
            "win": is_win,
            "pnl_pct": pnl_pct,
            "rr": abs(pnl_pct / sl_pct) if sl_pct else 0,  # sl_pct from signal entry/SL
        })
    else:
        # Signal suppressed by candidate weights
        # Filtered losses are simply excluded (good — improves win rate).
        # Filtered wins are also excluded (bad — tracked for awareness but
        # penalized implicitly: fewer trades → lower fitness if count < MIN_TRADES).
        if is_win:
            filtered_wins += 1

# Compute stats from kept_trades only
total_trades = len(kept_trades)
wins = sum(1 for t in kept_trades if t["win"])
losses = total_trades - wins
win_rate = (wins / total_trades * 100) if total_trades else 0
gross_profit = sum(t["pnl_pct"] for t in kept_trades if t["pnl_pct"] > 0)
gross_loss = abs(sum(t["pnl_pct"] for t in kept_trades if t["pnl_pct"] < 0))
profit_factor = (gross_profit / gross_loss) if gross_loss else gross_profit
avg_rr = mean(t["rr"] for t in kept_trades) if kept_trades else 0
max_dd = max_drawdown_from_cumulative_pnl(kept_trades)

# compute_fitness() returns 0.0 if total_trades < MIN_TRADES (20)
fitness = compute_fitness({"total_trades": total_trades, "win_rate": win_rate,
                           "profit_factor": profit_factor, "avg_rr": avg_rr,
                           "max_drawdown": max_dd})
```

The `MIN_TRADES = 20` gate from `compute_fitness()` applies to the live signal optimizer identically to the backtest optimizer. If candidate weights suppress enough signals to drop below 20 kept trades, fitness returns 0.0, naturally steering DE away from overly aggressive filtering.

**Partial per-source scores:** Signals are included if they have at minimum `tech_score` and the `regime_*` keys present in `raw_indicators`. Missing source scores (e.g., `flow_score` absent because flow data was unavailable) are treated as score=0, confidence=0 — matching the live pipeline's degradation behavior where unavailable sources get zeroed weight.

**Concurrency:** Only one optimization task (backtest or live-signal) may run at a time globally (matching the existing single-shadow constraint in `optimizer.active_shadow_proposal_id`). If an optimization is already running, the endpoint returns HTTP 409 with the active task's status.

Tracking: add `app.state.active_signal_optimization: dict | None` — set to `{"pair": pair, "cancel_flag": {"cancelled": False}}` when started, cleared to `None` on completion. The 409 guard checks both `active_signal_optimization` and any running backtest optimization. Cancel endpoint sets `cancel_flag["cancelled"] = True` (same pattern as backtest cancel in `api/backtest.py`).

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
1. Check no optimization task is already running (check both `app.state.active_signal_optimization` and any active backtest optimization; return 409 if busy)
2. Query resolved signals from DB matching pair (and optionally timeframe), filtered to `outcome NOT IN ('PENDING')` and `created_at >= now - lookback_days`, ordered by `created_at DESC`, capped at `max_signals`
3. Filter to signals that have `tech_score` and `regime_trending` keys in `raw_indicators` (skip legacy signals without per-source scores)
4. If count < `min_signals`, return HTTP 400 with `{"error": "insufficient_signals", "available": count, "required": min_signals}`
5. Set `app.state.active_signal_optimization = {"pair": pair, "cancel_flag": {"cancelled": False}}`
6. Spawn async task calling `optimize_from_signals()`, passing the cancel_flag
7. On completion, produce a `ParameterProposal` with `backtest_metrics` JSONB containing `"optimization_mode": "live_signals"` to distinguish from backtest-originated proposals (which use `"optimization_mode": "backtest"` or omit the key). No schema migration needed — `backtest_metrics` is already JSONB.
8. Clear `app.state.active_signal_optimization = None`
9. Broadcast `optimizer_update` WebSocket event:
   ```python
   {"type": "optimizer_update", "event": "optimization_started", "pair": pair, "mode": "live_signals"}
   # on completion:
   {"type": "optimizer_update", "event": "optimization_completed", "proposal_id": proposal_id, "mode": "live_signals"}
   ```
   Same payload structure as existing optimizer events (`type` + `event` + `proposal_id`), with added `mode` field.

### C5. Frontend Trigger

**File:** `features/optimizer/OptimizerPage.tsx` (or a sub-component)

Add a trigger mechanism on the existing OptimizerPage:
- Button labeled "Optimize from Live Signals" (or a toggle/tab between Backtest vs. Live mode)
- Pair selector (reuse existing)
- Shows resolved signal count for selected pair (query `GET /signals` with new `outcome` filter param — see files affected)
- Resulting proposals appear in the same proposal list. Distinguish source by reading `backtest_metrics.optimization_mode` — render a badge ("Backtest" / "Live Signals") on each proposal card.
- Disable button while any optimization is running (existing `isOptimizing` state covers this)

No new page or feature module — plugs into existing optimizer UI.

---

## What's Out of Scope

- Additional regime inputs (ADX + BB width only; deferred until this measurement infrastructure is in place)
- Inner cap optimization from live signals (caps affect source scores which are baked in stored signals)
- On-chain, liquidation, or confluence snapshot persistence for backtester (these sources are tuned via Workstream C's live signal optimizer instead; insufficient historical data ROI for backtester integration)
- Changes to the proposal/shadow/promote workflow (reused as-is)
- Database schema migrations — no new columns or tables. Per-source scores use existing `raw_indicators` JSONB. Proposal source tagging uses existing `backtest_metrics` JSONB with an `optimization_mode` key convention.

---

## Files Affected

| File | Change | Workstream |
|---|---|---|
| `engine/traditional.py` | Extract `score_order_flow()` pure function | B |
| `engine/backtester.py` | Load flow snapshots, maintain rolling window, call `score_order_flow()` | B |
| `engine/regime_optimizer.py` | Extract shared DE runner, add `optimize_from_signals()`, expand `_BACKTEST_OUTER_KEYS` conditionally | B + C |
| `engine/constants.py` | `ORDER_FLOW_ASSET_SCALES` used by extracted pure function — passed as resolved float by caller, imported directly in backtester | B |
| `main.py` | Add per-source scores + `regime_steady` to `raw_indicators` dict (~line 1004), add `active_signal_optimization` to `app.state` | C |
| `api/optimizer.py` | New `POST /api/optimizer/optimize-from-signals` endpoint, concurrency guard against both backtest and live-signal optimizations | C |
| `api/routes.py` | Add optional `outcome: str \| None` query param to `GET /signals` (filter by outcome status, e.g., `"resolved"` to exclude PENDING) | C |
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
- Every emitted signal has `tech_score`, `tech_confidence`, `flow_score`, `flow_confidence`, `onchain_score`, `onchain_confidence`, `pattern_score`, `pattern_confidence`, and `regime_steady` in `raw_indicators` (`liquidation_*` and `confluence_*` already present)
- `optimize_from_signals()` with 20 mock resolved signals produces a valid weight vector (24 params: 6 sources × 4 regimes, all weights > 0, per-regime sums normalized)
- `optimize_from_signals()` with < 20 signals raises/returns appropriate error
- `optimize_from_signals()` where candidate weights suppress all signals → `compute_fitness()` returns 0.0 (MIN_TRADES gate)
- Endpoint returns 409 when any optimization (backtest or live-signal) is already running
- Endpoint returns 400 with `available` count when insufficient signals
- Live optimizer correctly filters signals missing `tech_score` key in `raw_indicators`
- Signals with partial source scores (e.g., flow unavailable) included with score=0, confidence=0 for that source
- Signals with `outcome_pnl_pct = NULL` treated as 0.0 P&L
- Produced `ParameterProposal` has `backtest_metrics.optimization_mode == "live_signals"`
- `app.state.active_signal_optimization` is set during run and cleared on completion/cancellation
