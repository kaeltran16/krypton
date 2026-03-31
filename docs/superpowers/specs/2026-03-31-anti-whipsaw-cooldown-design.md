# Anti-Whipsaw Signal Cooldown

## Problem

The pipeline runs on every confirmed candle. In choppy/ranging markets, it can emit signals for the same pair that repeatedly hit SL. This whipsaw pattern is the largest source of unnecessary losses in ranging regimes.

## Success Criteria

- Consecutive SL-hit sequences of length >= 3 decrease by > 50% in backtested ranging periods (ADX < 25)
- Suppresses < 15% of signals that would have been profitable (false negative rate)
- Measurable via PipelineEvaluation records with `suppressed_reason IS NOT NULL` cross-referenced against hypothetical outcome

## Solution

Graduated per-pair+timeframe+direction cooldown that suppresses signal emission after consecutive SL hits. No suppression after a single SL (normal trading). Cooldown escalates only when consecutive stops indicate the market is chopping.

### Definition: Consecutive SL Streak

A streak is the count of SL_HIT outcomes for a given (pair, timeframe, direction) since the last non-SL terminal outcome. Any win (TP1_HIT, TP2_HIT, TP1_TRAIL, TP1_TP2) or EXPIRED outcome resets the streak to 0. The streak is purely sequential — no time window; any SL_HIT increments regardless of how much time has passed since the prior SL.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Cooldown trigger | 2nd consecutive SL_HIT (not 1st) | Single SL is normal; preserve signal volume |
| Scope | Same pair + timeframe + direction | Whipsaw is a per-timeframe phenomenon; cross-TF suppression blocks valid higher-TF signals |
| Direction | Same-direction only | Allows genuine reversals through; alternating whipsaw is rarer given multi-source scoring |
| State store | Redis | Already in pipeline for candle cache; survives API restarts; fast reads; fails safe on Redis restart (streak resets to 0) |
| Check location | `run_pipeline` step 7, after LLM gate, before emission | Full scoring data available for monitoring; LLM calls only happen when blended >= threshold anyway. Keeping cooldown after LLM gate preserves complete evaluation data for suppressed signals in the monitor, at the cost of occasional wasted LLM calls during extended chop. |
| Monitoring | `suppressed_reason` field on `PipelineEvaluation` | Evaluations are already persisted for all pipeline runs; zero extra DB writes. Only populated when score >= threshold but emission was blocked by cooldown — not on normal non-emissions. |
| Streak reset | On win (TP1_HIT, TP2_HIT, TP1_TRAIL, TP1_TP2) or expiry | Expiry means chop has stopped (market went sideways); wins indicate directionally correct scoring |
| Regime interaction | Stacks with regime dampening (defense-in-depth) | Regime system (`engine/regime.py`) already dampens trend/pattern scores in ranging markets (trend_cap: 18 vs 38-40). Cooldown is a separate layer — regime reduces score magnitude, cooldown blocks repeated directional failures. Both can activate simultaneously; this is intentional. If future data shows over-suppression in ranging, reduce `cooldown_max_candles` rather than adding regime-conditional logic. |
| RiskSettings coexistence | Independent of `cooldown_after_loss_minutes` | `RiskSettings.cooldown_after_loss_minutes` operates at the position entry layer (post-signal, blocking trade execution). This feature operates at the signal emission layer (pre-trade, blocking signal broadcast). Both may activate simultaneously; this is intentional defense-in-depth. |

## Escalation Table

| Consecutive SLs (same direction) | Cooldown candles |
|----------------------------------|-----------------|
| 0-1 | 0 (no suppression) |
| 2 | 1 |
| 3 | 2 |
| 4+ | 3 (cap) |

Formula: `cooldown_candles = min(streak - 1, cooldown_max_candles)`, only when `streak >= 2`.

Cooldown duration in wall-clock time per timeframe:

| Timeframe | 1 candle | 2 candles | 3 candles (cap) |
|-----------|----------|-----------|-----------------|
| 15m | 15 min | 30 min | 45 min |
| 1H | 1 hour | 2 hours | 3 hours |
| 4H | 4 hours | 8 hours | 12 hours |

## Redis State

Two keys per (pair, timeframe, direction):

**Streak counter:**
```
cooldown:streak:{pair}:{timeframe}:{direction}
```
Example: `cooldown:streak:BTC-USDT-SWAP:1h:LONG` -> `"2"`

**Last SL timestamp:**
```
cooldown:last_sl:{pair}:{timeframe}:{direction}
```
Example: `cooldown:last_sl:BTC-USDT-SWAP:1h:LONG` -> `"2026-03-31T14:00:00Z"`

Both keys:
- Set atomically via Redis pipeline by outcome resolver on SL_HIT (INCR streak, SET timestamp)
- Deleted atomically via Redis pipeline on win or expiry (reset)
- 7-day safety TTL to prevent orphaned keys if a pair is removed from config
- If a pair is removed and re-added within 7 days, old streak data persists (conservative — suppresses until natural expiry)

## Streak Management (Outcome Resolver)

On each signal resolution in the outcome resolution loop. Direction is read from the resolved signal's `direction` field (set at emission, immutable after).

All Redis operations use `redis.pipeline()` to guarantee atomicity:

```python
# SL_HIT
async def _update_cooldown_streak_sl(redis, pair, tf, direction, outcome_at):
    streak_key = f"cooldown:streak:{pair}:{tf}:{direction}"
    last_sl_key = f"cooldown:last_sl:{pair}:{tf}:{direction}"
    # only update timestamp if newer than existing
    existing = await redis.get(last_sl_key)
    if existing and parse(existing) >= outcome_at:
        # out-of-order resolution; still increment streak but keep newer timestamp
        await redis.incr(streak_key)
        await redis.expire(streak_key, 7 * 86400)
        return
    pipe = redis.pipeline()
    pipe.incr(streak_key)
    pipe.set(last_sl_key, outcome_at.isoformat())
    pipe.expire(streak_key, 7 * 86400)
    pipe.expire(last_sl_key, 7 * 86400)
    await pipe.execute()

# Win or Expiry
async def _reset_cooldown_streak(redis, pair, tf, direction):
    pipe = redis.pipeline()
    pipe.delete(f"cooldown:streak:{pair}:{tf}:{direction}")
    pipe.delete(f"cooldown:last_sl:{pair}:{tf}:{direction}")
    await pipe.execute()
```

- **SL_HIT**: Call `_update_cooldown_streak_sl`. Timestamp only updates if newer than existing (handles out-of-order resolution).
- **Win (TP1_HIT, TP2_HIT, TP1_TRAIL, TP1_TP2)**: Call `_reset_cooldown_streak`.
- **Expiry**: Call `_reset_cooldown_streak`.

## Cooldown Check (run_pipeline)

In `run_pipeline`, after computing `direction` and `effective_threshold`, before the `emitted = abs(final) >= effective_threshold` decision:

```python
suppressed_reason = None
if abs(final) >= effective_threshold:
    streak_key = f"cooldown:streak:{pair}:{timeframe}:{direction}"
    streak = int(await redis.get(streak_key) or 0)
    if streak >= 2:
        cooldown = min(streak - 1, settings.cooldown_max_candles)
        last_sl_raw = await redis.get(f"cooldown:last_sl:{pair}:{timeframe}:{direction}")
        if last_sl_raw:
            candle_seconds = {"15m": 900, "1h": 3600, "4h": 14400}[timeframe]
            elapsed = (now - parse(last_sl_raw)).total_seconds()
            remaining_seconds = cooldown * candle_seconds - elapsed
            if remaining_seconds > 0:
                suppressed_reason = (
                    f"cooldown: streak={streak}, "
                    f"{remaining_seconds:.0f}s remaining ({direction} SL_HIT)"
                )

emitted = abs(final) >= effective_threshold and suppressed_reason is None
```

## Configuration

Add `cooldown_max_candles: int = 3` to:
- `Settings` class in `config.py` (default 3, field name `engine_cooldown_max_candles`)
- `PipelineSettings` DB model (nullable, for runtime override)
- `_OVERRIDE_MAP` in `main.py`: `"cooldown_max_candles": "engine_cooldown_max_candles"`
- `PipelineSettingsUpdate` pydantic model in `api/pipeline_settings.py`
- `_row_to_dict()` serialization in `api/pipeline_settings.py`

Setting to 0 disables cooldown entirely.

## Database Changes

One Alembic migration:
- Add `suppressed_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)` to `PipelineEvaluation`
- Add `cooldown_max_candles: Mapped[int | None] = mapped_column(Integer, nullable=True)` to `PipelineSettings`

## Frontend / API Changes

### TypeScript Types
- Add `suppressed_reason?: string | null` to `PipelineEvaluation` interface in `features/monitor/types.ts`
- Add `cooldown_max_candles?: number | null` to pipeline settings type in `features/settings/`

### Monitor API
- Update `_eval_to_dict()` in `api/monitor.py` to include `suppressed_reason` in serialized response

### Monitor Page

**EvaluationTable:**
- Show orange "COOLDOWN" pill badge on rows where `suppressed_reason IS NOT NULL`
- These rows have `emitted=False` but scored above threshold — visually distinct from normal non-emissions (which show grey "REJ" badge)

**EvaluationDetail:**
- Display `suppressed_reason` as plain text in the detail panel

**Filters:**
- Change emitted filter to three-state dropdown: Emitted / Not Emitted / Suppressed
- "Suppressed" filters to `emitted=false AND suppressed_reason IS NOT NULL`

**WebSocket broadcast:**
- Add `suppressed: bool` and `suppressed_reason: str | null` to the `broadcast_scores` payload

## Concurrency & Ordering

**Pipeline concurrency**: `run_pipeline` is called once per confirmed candle per (pair, timeframe). Candles for the same pair+tf do not overlap — the next candle only confirms after the prior one closes. No concurrent cooldown reads for the same (pair, tf, direction) are possible within `run_pipeline`.

**Outcome resolution ordering**: The outcome resolver loop processes PENDING signals in `created_at` ascending order. Out-of-order resolution is unlikely but handled: `_update_cooldown_streak_sl` only updates `last_sl` timestamp if the new timestamp is strictly newer than the existing one, preventing an earlier-resolved signal from backdating the cooldown window.

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Redis restart | Streaks reset to 0. No suppression until new SLs accumulate. Fails safe (more signals, not fewer). This is acceptable — a restart during active chop means at most 1 extra signal leaks through before the streak rebuilds. |
| Redis GET/SET partial failure | Mitigated by atomic pipeline operations. If the entire pipeline call fails, the streak is unchanged (no partial state). |
| Candle gap (exchange downtime) | Wall-clock elapsed time; cooldown expires naturally during gap. |
| Multiple directions | Independent streaks. LONG cooldown does not affect SHORT. |
| Fresh pair/timeframe | Redis GET returns None, streak=0. No suppression. |
| Pair removed from config | 7-day TTL on Redis keys auto-cleans. If pair re-added within 7 days, old streak persists (conservative). |
| `cooldown_max_candles = 0` | Cooldown disabled entirely; `min(streak-1, 0) = 0`, no suppression ever triggers. |
| LLM cost during cooldown | LLM gate runs before cooldown check; some LLM calls may be "wasted" on suppressed signals. Acceptable trade-off for complete evaluation data in monitor. |
| Corrupted `last_sl` value | If `datetime.fromisoformat()` fails on a corrupted timestamp, catch the exception, log a warning, delete both keys (reset streak), and allow the signal through. Fail safe. |
