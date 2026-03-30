# Signal Quality Improvements Design

Three targeted improvements to signal scoring quality: joint ATR optimization, LLM contribution hardening, and faster IC pruning.

---

## 1. Joint Bayesian ATR Optimization

### Problem

`performance_tracker.py` optimizes SL, TP1, and TP2 ATR multipliers independently via sequential 1D sweeps. These dimensions are coupled — a wider SL changes the probability of reaching TP targets. Sequential optimization finds a locally suboptimal solution.

### Design

Replace the three `_sweep_dimension()` calls in `optimize()` with a single `gp_minimize()` call from `scikit-optimize` over the full 3D search space.

**Search space:**
- SL: `Real(0.8, 2.5)`
- TP1: `Real(1.0, 4.0)`
- TP2: `Real(2.0, 6.0)`

**GP parameters:** `n_calls=40`, `n_initial_points=8`, `acq_func='EI'`.

**Objective function:**

```python
def _gp_objective(self, params, signals, candles_map):
    sl_atr, tp1_atr, tp2_atr = params

    # Constraint enforcement via penalty
    if tp1_atr < sl_atr or tp2_atr < tp1_atr * 1.2:
        return 999.0  # penalty (GP minimizes)

    pnls = []
    for idx, sig in enumerate(signals):
        candles = candles_map.get(idx, [])
        if not candles:
            continue
        result = self.replay_signal(
            direction=sig["direction"],
            entry=sig["entry"],
            atr=sig["atr"],
            sl_atr=sl_atr,
            tp1_atr=tp1_atr,
            tp2_atr=tp2_atr,
            candles=candles,
            created_at=sig["created_at"],
        )
        if result is not None:
            pnls.append(result["outcome_pnl_pct"])

    sortino = self.compute_sortino(pnls)
    if sortino is None or sortino == float("inf"):
        return 0.0  # no data or all winners — neutral, not penalty
    return -sortino  # negate because gp_minimize minimizes
```

Note: `replay_signal()` is a static method with signature `(direction, entry, atr, sl_atr, tp1_atr, tp2_atr, candles, created_at)` — the GP wrapper unpacks signal fields before calling it. `candles_map` uses integer indices matching the signal list order (same convention as `_sweep_dimension`). `compute_sortino` is a static method on `PerformanceTracker`. The replay result uses key `outcome_pnl_pct` (from `resolve_signal_outcome`).

**Post-GP guardrails:** The best point from `result.x` goes through existing `_apply_guardrails()` — delta from current values clamped to `MAX_SL_ADJ=0.3` / `MAX_TP_ADJ=0.5`. R:R floor enforcement (`tp1 >= sl`) also unchanged.

**Error handling:** Wrap `gp_minimize()` in try/except. On any runtime error (NaN, convergence failure, unexpected exception), log the error and fall back to the existing sequential sweep.

**Fallback:** If `scikit-optimize` import fails, fall back to the existing sequential sweep. `_sweep_dimension()` stays as a private method.

**Rollback config:** Add `atr_optimizer_mode: str = "gp"` to settings. Values: `"gp"` (default) or `"sweep"`. This allows reverting to sweep via config without a code change.

**Logging:** Log GP result after completion: best Sortino, best parameters, number of evaluations, and whether fallback was used.

### Files Changed

| File | Change |
|------|--------|
| `backend/requirements.txt` | Add `scikit-optimize>=0.10` |
| `backend/app/config.py` | Add `atr_optimizer_mode: str = "gp"` setting |
| `backend/app/engine/performance_tracker.py` | Add `_gp_objective()`, replace sweep calls in `optimize()` with `gp_minimize()` + fallback, add logging |
| `backend/tests/engine/test_performance_tracker.py` | Add test for joint optimization, constraint penalty, fallback path, error handling |

---

## 2. LLM Contribution Cap + Dual-Pass Consistency

### Problem

The LLM can contribute up to +/-35 points. With a signal threshold of 40, a single LLM call can push a borderline blended score of 15 (40-25) to a signal. There is no consistency check — one LLM call is trusted entirely.

### Design

#### 2a. Reduce cap

Change default `llm_factor_total_cap` from `35.0` to `25.0` in `config.py`. Still overridable via `PipelineSettings`.

**DB migration:** Add Alembic migration to update existing PipelineSettings values:
```sql
UPDATE pipeline_settings
SET llm_factor_total_cap = 25.0
WHERE llm_factor_total_cap = 35.0 OR llm_factor_total_cap IS NULL;
```
This ensures the new default takes effect even when a DB override row exists.

#### 2b. Dual-pass consistency

**New in `llm.py`:** `call_openrouter_dual_pass()` wraps the existing `call_openrouter()` with two concurrent calls:

1. **Standard call** — existing prompt, unchanged.
2. **Devil's advocate call** — same context, but the system instruction is modified.

**Concurrency:** Both calls execute concurrently via `asyncio.gather()`. Total latency equals one LLM call (up to 30s), not two sequential calls.

```python
async def call_openrouter_dual_pass(prompt_standard, prompt_devils, ...):
    results = await asyncio.gather(
        call_openrouter(prompt_standard, ...),
        call_openrouter(prompt_devils, ...),
        return_exceptions=True,
    )
    standard_result = results[0] if not isinstance(results[0], Exception) else None
    devils_result = results[1] if not isinstance(results[1], Exception) else None
    return standard_result, devils_result
```

**Partial failure handling:**
- Both succeed: aggregate contributions (see below).
- Standard succeeds, devil's advocate fails: use standard call result alone (single-pass fallback). No penalty applied.
- Standard fails, devil's advocate succeeds: skip LLM entirely (existing behavior when LLM fails). The devil's advocate call alone is not reliable as a primary signal.
- Both fail: skip LLM entirely (existing behavior).

**Devil's advocate prompt:** A second prompt template file (`signal_analysis_devils_advocate.txt`) in `backend/app/prompts/`. Same structure and output schema as the standard template. Key system instruction change:

> "You are a critical analyst. Your task is to identify the strongest case AGAINST the prevailing signal direction. Score the top 3-5 factors that support the opposing view. Use the same factor types and scoring schema. Be genuinely contrarian — do not simply invert the standard analysis."

Same temperature, same max_tokens, same output schema (list of `LLMFactor`).

**Aggregation in `combiner.py`:** New `aggregate_dual_pass()`:

```python
def aggregate_dual_pass(contrib_a: int, contrib_b: int, cap: float) -> tuple[int, bool]:
    agreed = (contrib_a >= 0) == (contrib_b >= 0) or contrib_a == 0 or contrib_b == 0

    if agreed:
        merged = round((contrib_a + contrib_b) / 2)
    else:
        # Disagreement: 50% of smaller magnitude, direction of standard call
        magnitude = min(abs(contrib_a), abs(contrib_b)) / 2
        sign = 1 if contrib_a >= 0 else -1
        merged = round(sign * magnitude)

    return clamp(merged, -cap, cap), agreed
```

The standard call's direction is preferred on disagreement because it uses the primary analysis prompt, which is calibrated to the signal context. The devil's advocate is a consistency check, not a co-equal vote.

**LLM levels:** Use levels from the standard call only. The devil's advocate call is for factor consistency checking and does not contribute levels (entry/SL/TP). If the standard call fails, no levels are available (existing fallback to ML or ATR defaults applies).

**Observability:** Store `llm_dual_pass_agreed: bool` in `Signal.risk_metrics` JSONB (not `raw_indicators`, since `raw_indicators` is consumed by IC pruning which expects numeric scores). Note: `risk_metrics` is built inside `_emit_signal()` (not `run_pipeline()`), so `dual_pass_agreed` must be passed through `signal_data` and merged into `risk_metrics` after position sizing completes.

**Cost:** Both calls execute concurrently, so latency is unchanged. Token cost doubles per LLM-gated signal. Acceptable because LLM is only invoked when `|blended| >= 40`, which is infrequent.

### Files Changed

| File | Change |
|------|--------|
| `backend/app/config.py` | `llm_factor_total_cap` default 35.0 -> 25.0 |
| `backend/app/engine/llm.py` | Add `call_openrouter_dual_pass()` |
| `backend/app/engine/combiner.py` | Add `aggregate_dual_pass()` |
| `backend/app/main.py` | Call `call_openrouter_dual_pass()` instead of `call_openrouter()`, use standard-call levels only |
| `backend/app/prompts/signal_analysis_devils_advocate.txt` | Devil's advocate prompt template |
| `backend/alembic/versions/` | Migration to update llm_factor_total_cap in PipelineSettings |
| `backend/tests/engine/test_combiner.py` | Tests for `aggregate_dual_pass()` (agree, disagree, edge cases) |
| `backend/tests/engine/test_llm.py` | Test dual-pass orchestration: both succeed, partial failure, both fail |

---

## 3. Exponentially Weighted IC Pruning

### Problem

IC pruning requires 30 consecutive days below -0.05 before a source is pruned. A source that becomes harmful after a regime change damages signals for nearly a month before removal.

### Design

Replace the consecutive-day check with an exponentially weighted moving average of daily IC values.

**New function:**

```python
def compute_ew_ic(ic_history: list[float], alpha: float = 0.1) -> float:
    if not ic_history:
        return 0.0
    if len(ic_history) < 3:
        return sum(ic_history) / len(ic_history)  # simple mean for very short history
    # Initialize with mean of first 3 values to avoid first-value bias
    ew_ic = sum(ic_history[:3]) / 3
    for ic in ic_history[3:]:
        ew_ic = alpha * ic + (1 - alpha) * ew_ic
    return ew_ic
```

Alpha = 0.1 gives a ~10-day half-life. A source that turns harmful will trigger pruning in days rather than a month. Initializing with the mean of the first 3 values prevents a single outlier first day from having outsized influence.

**Updated pruning logic:**

```python
def should_prune_source(source_name: str, ic_history: list[float]) -> bool:
    if source_name in IC_PRUNE_EXCLUDED_SOURCES:
        return False
    if len(ic_history) < 5:  # need minimal data
        return False
    return compute_ew_ic(ic_history) < IC_PRUNE_THRESHOLD  # -0.05

def should_reenable_source(ic_history: list[float]) -> bool:
    if len(ic_history) < 5:  # same minimum as pruning to prevent thrashing
        return False
    return compute_ew_ic(ic_history) > IC_REENABLE_THRESHOLD  # 0.0
```

Re-enable requires 5 days of history (same as pruning) to prevent rapid thrashing between pruned and enabled states.

**Removed:** `IC_MIN_DAYS = 30` constant. The EW average handles cold-start naturally — few data points keep EW-IC near the simple mean, preventing premature pruning.

**IC_WINDOW_DAYS:** Remains at 7, unchanged. It controls the window for daily IC computation (fetching resolved signals from the last 7 days to compute one day's IC value). This is independent of the EW-IC lookback, which operates over all stored `SourceICHistory` entries.

**Transition from old rule:** On the first cycle after deploy, `compute_ew_ic()` runs over all available `SourceICHistory` entries. Sources currently pruned under the old rule remain pruned unless EW-IC > 0.0 (the re-enable threshold). This is the correct behavior — the EW-IC for a source that had 30 consecutive days below -0.05 will also be well below -0.05, so no incorrect un-pruning occurs.

**No schema change.** Daily IC values already stored in `SourceICHistory`. EW-IC computed on the fly each cycle.

**Excluded sources unchanged:** `tech` and `liquidation` still never pruned.

### Files Changed

| File | Change |
|------|--------|
| `backend/app/engine/optimizer.py` | Add `compute_ew_ic()`, update `should_prune_source()` and `should_reenable_source()`, remove `IC_MIN_DAYS` |
| `backend/app/engine/constants.py` | Remove `IC_MIN_DAYS` constant |
| `backend/tests/engine/test_optimizer.py` | Tests for EW-IC computation (hand-calculated values, initialization, short history), pruning/re-enable thresholds, cold-start behavior, transition scenario |

---

## Testing Strategy

All changes are unit-testable with existing test infrastructure (mocked app state, no real DB/Redis needed):

- **1.1:** Mock `replay_signal()` returns, verify GP finds better Sortino than fixed values, verify constraint penalty, verify guardrail clamping, verify fallback to sweep on import error, verify fallback on runtime error, verify `atr_optimizer_mode="sweep"` config bypasses GP.
- **1.2:** Mock `call_openrouter()` responses for both passes, verify aggregation logic for agree/disagree/edge cases, verify partial failure fallback (standard succeeds + devils fails, both fail), verify cap reduction applied, verify levels come from standard call only.
- **1.3:** Verify EW-IC math against hand-calculated values (including mean-of-3 initialization), verify prune/re-enable thresholds with symmetric 5-day minimum, verify cold-start safety, verify transition scenario (source with 30 days of negative IC stays pruned under new logic).

---

## Dependencies Between Changes

None. All three changes are independent and can be implemented/tested in any order. They touch different functions in different files (with minor overlap in `main.py` for the LLM call site).

Recommended implementation order: 1.3 (smallest), 1.2 (medium), 1.1 (largest).

---

## Migration Checklist

| Change | Migration Type | Notes |
|--------|---------------|-------|
| 1.1 GP optimizer | None | Code-only; config flag for rollback |
| 1.2 LLM cap 35->25 | Alembic data migration | UPDATE pipeline_settings to new default |
| 1.3 EW IC pruning | None | Uses existing SourceICHistory data; transition is seamless |
