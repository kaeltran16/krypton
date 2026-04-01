# Adaptive Regime Weight Online Update

## Problem

`RegimeWeights` stores per-pair outer weights, but those weights only change when a baseline row is materially updated and reloaded into runtime state. Between baseline refreshes, the live source mix can become stale after regime transitions, especially when the best blend of `tech`, `flow`, `onchain`, `pattern`, `liquidation`, `confluence`, and `news` changes faster than the baseline update cadence.

The pipeline already persists the data needed for a lighter adaptive layer:
- per-source scores and confidences in `Signal.raw_indicators`
- the regime snapshot in `Signal.engine_snapshot`
- terminal outcomes in `Signal.outcome`

This feature adds a bounded online adaptation layer that reacts to recent resolved signals without replacing the durable Postgres-owned baseline.

## Success Criteria

- Live outer weights adapt between baseline refreshes using only recent durable signal history
- Restarts rebuild the same adaptive state from persisted signals; no Redis dependency
- The durable `RegimeWeights` row remains the source of truth for baseline weights
- Online updates only affect outer weights; they do not change regime detection or inner caps
- Insufficient or incomplete recent data falls back cleanly to baseline weights
- A materialized baseline refresh clears the adaptive overlay for that pair/timeframe

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Durable authority | `RegimeWeights` row in Postgres | Baseline remains durable and inspectable |
| Adaptive state | Replay-derived in-memory overlay | Single-instance friendly; restart rebuilds from durable facts |
| History scope | Last 14 days, minimum 20 eligible signals, maximum 100 replayed signals per `(pair, timeframe)` | Prioritizes latest data while bounding replay cost |
| Retention semantics | Runtime retained-signal window must match restart replay window exactly | Long-lived processes and restarts must converge to the same overlay |
| Regime attribution | Full stored regime mix, not dominant bucket only | Matches the engine's soft regime model |
| Outcome symmetry | Symmetric for wins and losses | User preference; same base step size in both directions |
| `EXPIRED` treatment | Weak negative evidence only for sources aligned with the emitted trade | Treats lack of follow-through as mild blame without rewarding dissenters |
| Baseline refresh behavior | Clear overlay on any materialized `RegimeWeights` refresh | Safer and easier to verify than rebasing in v1 |
| Persistence of overlay | None | Rebuilt from signals on startup; no second source of truth |

## State Model

For each `(pair, timeframe)` the runtime keeps three layers:

1. `baseline`: the `RegimeWeights` DB row loaded at startup or refreshed by an explicit runtime reload path
2. `overlay`: an in-memory per-regime, per-source delta table
3. `effective_outer_weights`: `baseline + overlay`, then clamped and renormalized before blending

The overlay only applies to outer weights. `blend_caps()` and regime detection stay unchanged.

The overlay is not free-running state. It is always derived from a bounded eligible-signal window for the same `(pair, timeframe)`:

- retain only signals with `outcome_at >= now - 14 days`
- retain at most the newest 100 eligible signals by `outcome_at`
- replay retained signals in ascending `(outcome_at, id)` order
- deactivate the overlay whenever the retained eligible count drops below 20

Runtime structure:

```python
app.state.regime_weight_overlays[(pair, timeframe)] = {
    "trending": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
    "ranging": {...},
    "volatile": {...},
    "steady": {...},
    "eligible_count": 37,
    "window_oldest_outcome_at": "2026-03-24T12:00:00Z",
    "window_newest_outcome_at": "2026-04-01T10:14:00Z",
    "rebuilt_at": "2026-04-01T10:15:00Z",
}
```

## Eligibility Rules

A resolved signal is eligible for online learning when all of the following are true:

- `Signal.outcome` is terminal
- `Signal.raw_indicators` contains per-source scores
- `Signal.engine_snapshot` contains the emitted regime mix
- the signal belongs to the target `(pair, timeframe)`

Signals with missing snapshots or missing per-source scores are ignored. This keeps the adaptive layer derived from complete evidence only.

Eligible outcomes:
- Wins: `TP1_HIT`, `TP2_HIT`, `TP1_TRAIL`, `TP1_TP2`
- Losses: `SL_HIT`
- Weak-negative: `EXPIRED`

## Learning Rule

### Source Inputs

The updater reads these source families from `raw_indicators`:
- `tech_score`, `tech_confidence`
- `flow_score`, `flow_confidence`
- `onchain_score`, `onchain_confidence`
- `pattern_score`, `pattern_confidence`
- `liquidation_score`, `liquidation_confidence`
- `confluence_score`, `confluence_confidence`
- `news_score`, `news_confidence`

Scores already live on the pipeline's shared `-100..100` scale, so magnitude normalization uses `abs(score) / 100`.

### Per-Source Influence

For each source:

```python
confidence_factor = 0.5 + 0.5 * clamp(confidence, 0.0, 1.0)
magnitude_factor = 0.5 + 0.5 * clamp(abs(score) / 100.0, 0.0, 1.0)
influence = confidence_factor * magnitude_factor
```

This keeps the multiplier bounded in `[0.25, 1.0]`. Tiny or low-confidence sources still count a little; dominant sources move more.

### Outcome Credit / Blame

Let `aligned` mean the source score pointed in the same direction as the emitted trade:
- LONG signal: source score `> 0`
- SHORT signal: source score `< 0`

Let `opposed` mean the source score pointed against the emitted trade.

Outcome effect:
- Win: `aligned = +1`, `opposed = -1`
- `SL_HIT`: `aligned = -1`, `opposed = +1`
- `EXPIRED`: `aligned = -0.5`, `opposed = 0`

Zero scores do not update anything.

### Regime-Distributed Update

The emitted regime snapshot is taken from `engine_snapshot.regime_mix`. For each regime `r` and source `s`:

```python
BASE_LR = 0.01

delta[r][s] += BASE_LR * regime_mix[r] * outcome_effect * influence
```

This distributes one signal's learning across the full stored regime mix rather than collapsing to a single bucket.

### Bounds

Overlay deltas are bounded per regime/source cell:

```python
OVERLAY_DELTA_MIN = -0.12
OVERLAY_DELTA_MAX = 0.12
```

After adding the overlay to the baseline, effective weights are clamped and renormalized:

```python
EFFECTIVE_WEIGHT_FLOOR = 0.02
EFFECTIVE_WEIGHT_CEILING = 0.50
```

Each regime row is then renormalized to sum to `1.0`.

The online updater never mutates the baseline row in place.

## Effective Weight Resolution

Add a helper in the regime-weight path that:

1. extracts baseline outer weights from the `RegimeWeights` row
2. applies the overlay for the `(pair, timeframe)` if one exists
3. clamps each source weight to `[0.02, 0.50]`
4. renormalizes each regime row to sum to `1.0`
5. feeds the resulting per-regime table into the existing `blend_outer_weights()` logic

If no overlay exists for a pair/timeframe, the behavior is identical to today.

## Startup Rebuild

On startup:

1. load baseline `RegimeWeights` rows as usual
2. query resolved signals for each `(pair, timeframe)` where `outcome_at >= now - 14 days`
3. keep at most the newest 100 eligible signals per `(pair, timeframe)` by `outcome_at`
4. replay those retained signals in ascending `(outcome_at, id)` order to rebuild the overlay
5. only activate the overlay when at least 20 eligible signals remain after filtering

If a pair/timeframe has fewer than 20 eligible recent signals, it runs baseline-only.

`created_at` is not used for recency or replay order. A signal qualifies for the window based on resolution time (`outcome_at`) because that is when the learning event becomes durable.

Implementation note for planning: the replay query should be profiled against current signal volume. v1 does not require a schema change up front, but adding a composite `(pair, timeframe, outcome_at)` index is allowed if startup or rebuild latency is not acceptable.

This makes the adaptive state depend on the latest durable signal outcomes, not on cache survival.

## Runtime Update Flow

### On Outcome Resolution

After the transaction commits terminal outcomes:

1. inspect newly resolved signals
2. filter to eligible signals with complete snapshots
3. update the retained eligible-signal window for that `(pair, timeframe)`:
   - insert the newly resolved eligible signal using `(outcome_at, id)` ordering
   - evict any retained signals older than `now - 14 days`
   - trim the retained set to the newest 100 eligible signals
4. rebuild the overlay from the retained set rather than applying unbounded in-place drift
5. store the rebuilt overlay in `app.state.regime_weight_overlays`, or remove it if the retained eligible count is now below 20

This should happen alongside the existing post-resolution bookkeeping in `main.py`.

This keeps a long-running process behaviorally equivalent to a clean restart replay.

### On Materialized Baseline Refresh

When a baseline `RegimeWeights` row is materially changed and the app reloads it into runtime state:

1. replace the runtime baseline row
2. clear the in-memory overlay for that `(pair, timeframe)`
3. clear the retained eligible-signal window metadata for that `(pair, timeframe)`

Clearing is intentional in v1. It avoids mixing stale short-horizon adaptation with a freshly optimized baseline.

In the current app, baseline refresh events are:

- startup load of `app.state.regime_weights`
- manual `RegimeWeights` edits followed by the existing reload path
- any future optimizer flow that actually writes `RegimeWeights` and reloads runtime state

Proposal promotion by itself is not a baseline refresh. Today it changes proposal status only; it does not mutate `RegimeWeights` until some separate path writes those values.

## Failure and Fallback Behavior

- Missing or malformed snapshot data: skip the signal, log at warning level once per pair/timeframe batch
- No recent eligible sample set: baseline-only
- Overlay reconstruction error on startup: drop overlay for that pair/timeframe, keep baseline
- Overlay update error during runtime: keep the last valid overlay and continue scoring
- Retained window falls below 20 eligible signals after eviction: remove the overlay and return to baseline-only for that pair/timeframe

The scorer must never fail closed because the adaptive layer is unavailable.

## Observability

At minimum, log:
- overlay rebuild counts per `(pair, timeframe)`
- pairs/timeframes skipped for insufficient recent samples
- overlay clear events after baseline refresh
- overlay deactivation events caused by retained-window eviction below the minimum sample gate

Any future admin/API surface for this feature should expose:
- baseline outer weights
- effective outer weights
- overlay deltas
- eligible recent sample count
- retained window oldest/newest `outcome_at`

This observability surface is explicitly out of scope for v1.

## Testing

### Unit Tests

- full-regime-mix distribution of a single update
- symmetric win/loss behavior
- `EXPIRED` weak-negative behavior (`aligned = -0.5`, `opposed = 0`)
- bounded influence multiplier from score magnitude and confidence
- clamp and renormalization behavior
- effective weight fallback when no overlay exists

### Integration Tests

- startup rebuild from recent resolved signals
- minimum-sample gate disables overlay
- runtime incremental update after a terminal outcome
- clearing overlay when baseline changes
- runtime eviction of aged or overflow signals matches a fresh restart replay
- replay ordering uses ascending `(outcome_at, id)` rather than `created_at`

### Regression Tests

- baseline-only scoring remains unchanged when overlay is absent
- missing signal snapshots do not break scoring
- online updates do not alter regime caps or regime detection

## Files Affected

### New

- `backend/app/engine/regime_online.py` — overlay rebuild, incremental updates, effective outer-weight resolution
- `backend/tests/engine/test_regime_online.py` — online update and rebuild tests

### Modified

- `backend/app/engine/regime.py` — route outer-weight reads through effective baseline-plus-overlay resolution
- `backend/app/main.py` — startup rebuild hook, post-resolution incremental update hook, overlay clear on baseline refresh

## Non-Goals

- No changes to regime detection inputs or smoothing
- No changes to `blend_caps()`
- No Redis-backed adaptive state
- No direct DB writes for every online nudge
- No attempt to replace the batch optimizer
