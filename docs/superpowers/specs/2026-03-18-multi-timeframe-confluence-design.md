# Multi-Timeframe Confluence Design

## Problem

Each timeframe (15m, 1h, 4h) runs the signal pipeline independently. A 15m long signal carries the same conviction whether it aligns with the 1h/4h uptrend or fights against higher-timeframe structure. Signals opposing the higher-TF trend get stopped out more frequently, while aligned signals deserve higher conviction but receive no boost.

## Approach

Add a confluence scoring component (±15 points) to the technical score. Each timeframe references its parent timeframe's cached trend indicators (ADX, +DI, -DI) to determine alignment. Aligned signals are boosted, conflicting signals are penalized, scaled by parent trend strength.

## Timeframe Hierarchy

```
15m  →  1h (parent)
1h   →  4h (parent)
4h   →  1D (parent)
1D   →  none (top-level, no confluence component)
```

This requires adding 1D candle ingestion via the OKX WebSocket `candle1Dutc` channel.

## Indicator Caching

### Live Pipeline

When `run_pipeline()` computes `compute_technical_score()` for any timeframe, it writes the trend indicators to Redis:

- **Key:** `htf_indicators:{pair}:{timeframe}`
- **Value:** JSON blob `{"adx": float, "di_plus": float, "di_minus": float, "timestamp": str}`
- **TTL:** 2× the timeframe period (e.g., 1h cache TTL = 2h) as a safety net against stale data if ingestion stops

The Redis write must be wrapped in try/except — if Redis is unavailable, log a warning and continue. A failed write simply means child timeframes read a miss and fall back to confluence = 0 via the existing cold-start path.

When a child timeframe's pipeline runs, it reads its parent's cached indicators from Redis. If the cache doesn't exist (cold start, no confirmed parent candle since boot), the confluence component returns 0 — neutral, no boost or penalty.

### Why Cache Instead of Compute On-Demand

The parent timeframe's most recent confirmed candle can be up to one period old (e.g., 45 minutes for 1h when processing 15m). Computing from confirmed candles is accurate and avoids synthesizing candles from lower-TF data. Caching the result avoids re-running `compute_technical_score()` on the parent's 200-candle window for every child candle.

## Confluence Scoring

### Function: `compute_confluence_score(child_direction, parent_indicators) → int`

**Inputs:**
- `child_direction`: trend direction from the child's own ADX/DI analysis (+1 if DI+ > DI-, -1 otherwise)
- `parent_indicators`: cached `{adx, di_plus, di_minus}` from the parent timeframe, or None

**Algorithm:**
1. If `parent_indicators` is None, return 0
2. If `di_plus == di_minus`, return 0 (no clear parent direction)
3. Determine parent direction: +1 if `di_plus > di_minus`, -1 if `di_minus > di_plus`
4. Compute parent strength: `sigmoid_scale(adx, center=15, steepness=0.30)` → 0.0 to 1.0 (reuses existing sigmoid from `scoring.py`)
5. Check alignment:
   - **Aligned** (same direction): `+max_score × parent_strength`
   - **Conflicting** (opposite): `-max_score × parent_strength`
6. Clamp to `[-max_score, +max_score]`

**Default max_score:** 15

### Score Examples

| Parent ADX | Alignment | Approximate Score |
|------------|-----------|-------------------|
| 40 (strong trend) | Aligned | +14 |
| 40 (strong trend) | Conflicting | -14 |
| 25 (moderate) | Aligned | +11 |
| 15 (threshold) | Either | ±7.5 |
| 10 (weak/no trend) | Either | ±3 |

Strength scaling ensures that only clear higher-TF trends meaningfully shift the score. A weak or ambiguous parent trend produces near-zero confluence, avoiding noise.

## Pipeline Integration

### `run_pipeline()` Changes

After computing `compute_technical_score()`:

1. Look up parent timeframe from mapping: `TIMEFRAME_PARENT = {"15m": "1h", "1h": "4h", "4h": "1D"}`
2. If current timeframe has a parent, fetch `htf_indicators:{pair}:{parent_tf}` from Redis
3. Determine child direction from own indicators (`di_plus`, `di_minus`)
4. Call `compute_confluence_score(child_direction, parent_indicators)`
5. Add confluence score to `tech_result["score"]` (the technical component), then clamp to [-100, +100]. This means confluence modifies the technical score *before* it enters the weighted blend via `compute_preliminary_score()`. At the default 40% tech weight, a ±15 confluence adjustment contributes approximately ±6 points to the preliminary score — proportional influence, not an outsized additive bump.
6. After computing own indicators, write `htf_indicators:{pair}:{timeframe}` to Redis for child timeframes to use

**1D pipeline runs:** 1D is confluence-only — it does not emit signals. The pipeline runs `compute_technical_score()` and writes the indicator cache to Redis, then returns early before the LLM gate and signal emission steps. This avoids unnecessary LLM API calls for a timeframe whose sole purpose is providing parent data for 4h confluence.

**Concurrent timing:** When a parent candle confirms, a child candle often confirms simultaneously (e.g., every 1h boundary is also a 15m boundary). If both pipeline runs execute concurrently, the child may read the parent's *previous* cached indicators rather than the just-confirmed ones. This is expected and benign — the previous period's trend indicators are still representative, and the next child candle will pick up the fresh cache.

**Confluence at score extremes:** Adding ±15 confluence to a tech score already near ±100 will be partially lost to clamping (e.g., tech 95 + confluence 15 = 110, clamped to 100). This is acceptable — signals near the extremes are already high-conviction and don't need the full confluence bump.

### Signal Storage

Store in the signal's `raw_indicators` JSONB:
- `confluence_score`: the computed ±15 value
- `parent_tf`: which timeframe was referenced
- `parent_adx`, `parent_di_plus`, `parent_di_minus`: the parent indicators used

This enables debugging and analysis of confluence impact on signal quality.

## 1D Candle Ingestion

### WebSocket Subscription

Add to `TIMEFRAME_CHANNEL_MAP` in `ws_client.py`:
```
"1D": "candle1Dutc"
```

OKX uses UTC-based daily candles for this channel.

### Storage

No schema changes needed — the existing `Candle` model and Redis cache handle arbitrary timeframes. 1D candles use the same `candles:{pair}:1D` key pattern with a 200-candle rolling window.

### Config

Add `"1D"` to the default `timeframes` list in `config.py`. 1D candles confirm once per day — minimal overhead on ingestion and storage. After deployment, the first confirmed 1D candle arrives at UTC midnight — until then (up to 24h), 4h confluence will be 0 via the cold-start path.

## Backtester Changes

### Pre-Computation

New helper function:

```
precompute_parent_indicators(parent_candles: list[dict]) → tuple[list[str], list[dict]]
```

1. Takes chronologically sorted parent-TF candles
2. Iterates with a rolling 200-candle window (matching the minimum 70-candle requirement for `compute_technical_score()`)
3. Calls `compute_technical_score()` at each step
4. Returns `(sorted_timestamps, indicators_list)` — two parallel lists for O(log n) bisect lookup by child timestamp

### `run_backtest()` Integration

- Accept optional `parent_candles: list[dict]` parameter
- If provided, call `precompute_parent_indicators()` at startup
- During iteration, for each child candle, look up the most recent parent snapshot where `parent_timestamp <= child_timestamp` (sorted timestamps + bisect)
- Feed snapshot into `compute_confluence_score()` — same logic as live pipeline
- If `parent_candles` is None, confluence score = 0 (matches live cold-start behavior)

### API Changes

The backtest API endpoint (`POST /api/backtest/run`) uses the `TIMEFRAME_PARENT` mapping to determine the parent timeframe from the requested timeframe, queries Postgres for parent-TF candles over the same date range, and passes both to `run_backtest()`. If no parent-TF candles exist (e.g., historical import hasn't been run for that timeframe), `parent_candles` is None and confluence = 0. No frontend UI changes needed — confluence scoring applies automatically when parent data is available.

## Configuration

New config parameters in `config.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `engine_confluence_max_score` | 15 | Maximum ±points for confluence component |

Add `"1D"` to the default `timeframes` list.

The `TIMEFRAME_PARENT` mapping is a code constant, not a config parameter, since the hierarchy is structural.

## Testing

### Unit Tests: `compute_confluence_score()`

- Aligned + strong parent ADX (40) → score near +15
- Conflicting + strong parent ADX (40) → score near -15
- Weak parent ADX (10) → score near 0 regardless of alignment
- Parent indicators is None → returns 0
- Edge case: parent DI+ == DI- → returns 0 (no clear direction)
- Score clamped to [-max_score, +max_score]

### Integration Tests: Caching

- After 1h pipeline run, `htf_indicators:{pair}:1h` exists in Redis with correct ADX/DI values
- 15m pipeline run reads cached 1h indicators and produces non-zero confluence score
- Cold start (no cache) → confluence score is 0, pipeline completes normally
- TTL expiry → stale cache cleared, subsequent reads return None, confluence = 0

### Backtester Tests

- `precompute_parent_indicators()` produces correct number of snapshots (one per parent candle after minimum candle requirement)
- Backtest with parent candles produces different scores than without
- Timestamp lookup returns most recent parent snapshot — never future data
- Backtest without parent candles runs normally with confluence = 0
