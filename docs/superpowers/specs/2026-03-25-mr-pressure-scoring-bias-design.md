# Design: Mean-Reversion Pressure — Fixing Structural LONG Bias

**Date:** 2026-03-25
**Status:** Draft
**Scope:** Backend signal engine scoring pipeline

---

## Problem Statement

The signal engine produces significantly more LONG signals than SHORT signals. This is not solely due to bullish market conditions — the scoring architecture has structural biases that suppress SHORT signals even when exhaustion/reversal evidence is strong.

### Root Cause Analysis

Six bias points compound through the pipeline. All share the same blind spot: **they assume trending = trend-follow, with zero sensitivity to exhaustion evidence.**

| # | Bias Point | Location | Mechanism |
|---|---|---|---|
| 1 | Static regime caps | `traditional.py` | trend_cap=38 vs mean_rev_cap=22 in trending regime. Mean-reversion can never arithmetically outweigh trend: max MR+squeeze=-34 vs trend+volume=+66. The caps predetermine the winner. |
| 2 | Additive volume with own direction | `traditional.py` | OBV slopes upward in bull markets (cumulative). Adds ~12 LONG points that any SHORT signal must overcome. |
| 3 | Trend-only confidence | `traditional.py` | `confidence = trend_strength*0.4 + conviction*0.4 + agreement*0.2`. 80% depends on trend clarity. SHORT signals get ~0.30 confidence vs LONG's ~0.65, reducing their weight in the combiner. |
| 4 | Unconditional confluence | `main.py` | HTF DI direction adds +/-15 with no awareness of exhaustion. Creates a 30-point directional swing. |
| 5 | Triple order flow suppression | `traditional.py` | Contrarian signals (the primary SHORT source in trends) are dampened by regime (0.3x), trend conviction, and rate-of-change logic. |
| 6 | Score-magnitude LLM gate | `main.py` | LLM triggers at \|blended\|>=40 (the `engine_llm_threshold` setting). The combiner's weighted average structurally compresses SHORT scores well below this threshold. SHORT signals never get LLM evaluation. |

### Pipeline Trace: RSI=80, BB_pos=0.93, ADX=30 (bull market)

```
Current pipeline (SHORT candidate suppressed at every stage):

Tech:        trend(+38) + mean_rev(-22) + squeeze(-8) + volume(+12) = +20 LONG
Confluence:  +13 (HTF bullish)
Tech total:  +33 LONG
Confidence:  0.65 (trend-biased)
Order flow:  -10 (contrarian suppressed from -33)
Combiner:    ~+20 LONG
LLM gate:    called (20 < 25? borderline, often yes for LONG)
Final:       ~+35 to +45 LONG signal emitted

The same market conditions should produce a SHORT candidate, but every stage
pushes toward LONG or suppresses the SHORT thesis.
```

---

## Solution: `mr_pressure` — Exhaustion-Aware Scoring

### Core Concept

Introduce a single signal — `mr_pressure` (0.0 to 1.0) — that measures how extreme mean-reversion indicators are. This signal propagates to every bias point, making the pipeline responsive to exhaustion evidence without changing the scoring architecture.

When `mr_pressure = 0` (neutral indicators), behavior is identical to current. Changes are proportional to exhaustion evidence.

### mr_pressure Computation

```python
def compute_mr_pressure(rsi: float, bb_pos: float) -> float:
    """Measure mean-reversion indicator extremity. 0.0-1.0.

    Multiplicative gate: BOTH RSI and BB position must be extreme.
    Prevents firing on RSI alone (can stay >70 for weeks in crypto).
    Symmetric: works for both overbought and oversold.
    """
    rsi_extremity = max(0, abs(rsi - 50) - 10) / 30    # 0 when 40-60, 1.0 at 10/90
    bb_extremity = max(0, abs(bb_pos - 0.5) - 0.2) / 0.3  # 0 when 0.3-0.7, 1.0 at edges
    return rsi_extremity * bb_extremity
```

Reference values:

| RSI | BB pos | mr_pressure | Interpretation |
|-----|--------|-------------|----------------|
| 55 | 0.55 | 0.00 | Neutral — no effect |
| 65 | 0.70 | 0.00 | Mild — no effect |
| 72 | 0.82 | 0.16 | Moderate — small adjustments |
| 78 | 0.90 | 0.40 | Strong — meaningful shifts |
| 85 | 0.95 | 0.69 | Very strong — large shifts |
| 25 | 0.08 | 0.37 | Oversold — symmetric application |

---

## Fix Details

### Fix 1: Dynamic Caps — Shift Budget Based on Evidence

**File:** `engine/traditional.py`, inside `compute_technical_score`
**Trigger:** mr_pressure > 0

After computing regime-blended caps, shift budget from trend to mean-reversion proportional to mr_pressure.

```python
caps = blend_caps(regime, regime_weights)
shift = mr_pressure * MAX_CAP_SHIFT  # constant, default 18
caps["mean_rev_cap"] += shift
caps["trend_cap"] -= shift
```

The total cap budget stays balanced (what trend loses, mean_rev gains). When mr_pressure=0, caps are unchanged.

| mr_pressure | trend_cap | mean_rev_cap | Can MR outweigh trend? |
|---|---|---|---|
| 0.00 | 38.0 | 22.0 | No (gap = 16) |
| 0.16 | 35.1 | 24.9 | No (gap = 10) |
| 0.40 | 30.8 | 29.2 | Borderline |
| 0.69 | 25.6 | 34.4 | Yes (MR leads by 9) |

**New constant:** `MAX_CAP_SHIFT` in `engine/constants.py`, default 18. Tunable — start conservative at 12 if concerned about weakening trend-following.

### Fix 2: Volume as Confirmation Multiplier

**File:** `engine/traditional.py`, inside `compute_technical_score`
**Trigger:** Always active (structural change)

Currently volume is additive with its own direction. OBV trends upward in bull markets, injecting persistent LONG bias. Change volume to a multiplier that confirms the directional score (trend + mean_rev + squeeze) rather than competing with it.

**Before:**
```python
total = trend_score + mean_rev_score + squeeze_score + obv_score + vol_score
```

**After:**
```python
directional = trend_score + mean_rev_score + squeeze_score

if directional == 0:
    total = 0
else:
    score_sign = 1 if directional > 0 else -1

    # Does volume flow confirm the score's thesis?
    # Note: uses sigmoid_scale (unipolar, 0-1) not sigmoid_score (bipolar, -1 to +1)
    # because we need a 0-1 strength measure, not a signed score
    obv_dir = 1 if obv_slope_norm > 0 else -1
    obv_confirms = (obv_dir == score_sign)
    obv_strength = sigmoid_scale(abs(obv_slope_norm), center=0, steepness=4)

    candle_confirms = (candle_direction == score_sign)
    vol_strength = sigmoid_scale(vol_ratio - 1, center=0, steepness=3)

    confirmation = (
        0.6 * (obv_strength if obv_confirms else 1 - obv_strength)
        + 0.4 * (vol_strength if candle_confirms else 1 - vol_strength)
    )
    # confirmation: 0.0 (contradicts) to 1.0 (confirms)

    vol_mult = VOL_MULT_FLOOR + (VOL_MULT_CEIL - VOL_MULT_FLOOR) * confirmation
    total = directional * vol_mult
```

The `volume_cap` regime value is repurposed to define the multiplier range:
```python
VOL_MULT_CEIL = 1.0 + caps["volume_cap"] / 100   # e.g., 1.28
VOL_MULT_FLOOR = 2.0 - VOL_MULT_CEIL              # e.g., 0.72 (symmetric)
```

**Impact comparison for SHORT directional score of -22:**

| | Additive (current) | Multiplicative (proposed) |
|---|---|---|
| Volume in bull market | -22 + 12 = **-10** | -22 * 0.82 = **-18** |
| Volume confirms SHORT | -22 + (-12) = **-34** | -22 * 1.28 = **-28** |

The SHORT signal is stronger in the common case (volume disagrees but doesn't fully cancel), and volume can never flip the score's direction.

### Fix 3: Directional Confidence

**File:** `engine/traditional.py`, inside `compute_technical_score`
**Trigger:** Always active (structural change)

Confidence should measure "how strong is the evidence for the direction the score points" — not "how clear is the trend." Either a strong trend OR extreme mean-reversion indicators can produce high confidence.

**Before:**
```python
confidence = trend_strength * 0.4 + trend_conviction * 0.4 + (1 - indicator_conflict) * 0.2
```

**After:**
```python
score_sign = 1 if total > 0 else -1

# Trend thesis confidence (high when trend supports score direction)
trend_conf = trend_strength * 0.5 + trend_conviction * 0.5
if di_sign != score_sign:
    trend_conf *= 0.2  # trend opposes score — weak support

# Mean-reversion thesis confidence (high when MR indicators are extreme)
mr_conf = mr_pressure  # already 0-1, requires both RSI+BB extreme

# Either thesis can produce confidence
thesis_conf = max(trend_conf, mr_conf)
confidence = thesis_conf * 0.8 + (1 - indicator_conflict) * 0.2
```

The `max()` is the key operation: if either trend or mean-reversion evidence strongly supports the score's direction, confidence is high.

| Score direction | Current confidence | Directional confidence |
|---|---|---|
| LONG in uptrend | 0.65 | ~0.67 (similar) |
| SHORT with RSI=80, BB=0.93 | 0.30 | ~0.55 |
| LONG with RSI=25, oversold | 0.30 | ~0.50 |

### Fix 4: Confluence Dampening

**File:** `main.py`, in `run_pipeline` after confluence computation
**Trigger:** mr_pressure > 0

Reduce the HTF alignment bonus/penalty when exhaustion evidence is present. The HTF trend direction is less relevant when the current timeframe shows exhaustion.

```python
mr_pressure = tech_result.get("mr_pressure", 0.0)
confluence_score = compute_confluence_score(child_direction, parent_indicators, ...)
confluence_score = round(confluence_score * (1 - mr_pressure * CONFLUENCE_DAMPENING))
```

| mr_pressure | Multiplier (at 0.7 dampening) | Old confluence | New confluence |
|---|---|---|---|
| 0.00 | 1.00 | -13 | -13 |
| 0.40 | 0.72 | -13 | -9 |
| 0.69 | 0.52 | -13 | -7 |

**New constant:** `CONFLUENCE_DAMPENING` in `engine/constants.py`, default 0.7. At 0.7, full exhaustion (mr_pressure=1.0) reduces confluence by 70%.

### Fix 5: Order Flow Contrarian Relaxation

**File:** `engine/traditional.py`, in `compute_order_flow_score`
**Trigger:** mr_pressure > 0
**Interface change:** New optional parameter `mr_pressure: float = 0.0`

When exhaustion evidence is present, raise the floor on the contrarian multiplier AND relax the conviction dampening ceiling. Both must be relaxed — the existing code applies `final_mult = min(final_mult, 1.0 - trend_conviction)` which hard-caps `final_mult` regardless of the contrarian floor. In a strong trend (conviction=0.7), this ceiling is 0.3, nullifying any raised floor.

```python
def compute_order_flow_score(metrics, regime=None, ..., mr_pressure=0.0):
    # ... existing contrarian_mult computation ...

    # Raise the contrarian floor when exhaustion evidence is present
    if mr_pressure > 0:
        relaxed_floor = TRENDING_FLOOR + mr_pressure * (1.0 - TRENDING_FLOOR)
        contrarian_mult = max(contrarian_mult, relaxed_floor)

    final_mult = contrarian_mult + roc_boost * (1.0 - contrarian_mult)

    # Relax conviction dampening proportional to mr_pressure
    # Without this, min(final_mult, 1 - trend_conviction) caps final_mult
    # at ~0.3 in strong trends, nullifying the raised floor above
    effective_conviction = trend_conviction * (1.0 - mr_pressure)
    conviction_dampening = 1.0 - effective_conviction
    final_mult = min(final_mult, conviction_dampening)
```

At mr_pressure=0, `effective_conviction = trend_conviction` — identical to current behavior.
At mr_pressure=0.69, conviction=0.7: `effective_conviction = 0.7 * 0.31 = 0.22`, ceiling = 0.78 — the raised floor survives.

| mr_pressure | contrarian_mult | conviction ceiling | effective final_mult | Funding+LS contribution |
|---|---|---|---|---|
| 0.00 | 0.30 | 0.30 | 0.30 | -18 |
| 0.40 | 0.58 | 0.58 | 0.58 | -28 |
| 0.69 | 0.78 | 0.78 | 0.78 | -35 |

The caller in `main.py` passes `mr_pressure` from the tech result:
```python
flow_result = compute_order_flow_score(
    flow_metrics,
    regime=tech_result["regime"],
    flow_history=flow_history,
    trend_conviction=tech_result["indicators"].get("trend_conviction", 0.0),
    mr_pressure=tech_result.get("mr_pressure", 0.0),
)
```

### Fix 6: LLM Gate — Dual Trigger (Score OR Exhaustion)

**File:** `main.py`, in `run_pipeline` at the LLM gate check
**Trigger:** mr_pressure >= `engine_mr_llm_trigger`

The LLM gate currently triggers on blended score magnitude (`|blended| >= engine_llm_threshold`, default 40). The combiner's weighted average structurally compresses SHORT scores well below this threshold. This means SHORT signals never get LLM evaluation — the one stage where qualitative exhaustion assessment (RSI divergence, volume exhaustion, funding extreme) could push the score past the signal threshold.

Fix: add a second trigger path based on exhaustion evidence.

**Before:**
```python
if abs(blended) >= settings.engine_llm_threshold and prompt_template:
```

**After:**
```python
mr_pressure = tech_result.get("mr_pressure", 0.0)
should_call_llm = (
    abs(blended) >= settings.engine_llm_threshold
    or mr_pressure >= settings.engine_mr_llm_trigger
)
if should_call_llm and prompt_template:
```

| Scenario | blended | mr_pressure | Old gate (threshold=40) | New gate |
|---|---|---|---|---|
| Strong LONG trend | +45 | 0.0 | Called | Called (score path) |
| Moderate LONG | +25 | 0.0 | Not called | Not called |
| Moderate exhaustion | -17 | 0.40 | Not called | Called (mr_pressure path) |
| Strong exhaustion | -28 | 0.69 | Not called | Called (mr_pressure path) |
| Mild overbought | -5 | 0.16 | Not called | Not called |

**New setting:** `engine_mr_llm_trigger` in config, default 0.30. This means both RSI and BB position must be meaningfully extreme before triggering an extra LLM call. Cost impact: ~5-10% of candles in trending markets trigger the exhaustion path, roughly doubling LLM call volume. Acceptable given these are the highest-value calls.

**Signal threshold (40) remains fixed.** It is a quality gate for risk control. With the scoring fixes, genuine SHORT setups produce strong enough blended scores that, with LLM contribution, can cross 40.

---

## End-to-End Comparison

Same scenario: ADX=30, DI+>DI-, bull market. Traces are **illustrative** (sigmoid outputs rounded for readability). The qualitative direction — current produces LONG, proposed can produce SHORT — is the key takeaway. Exact magnitudes depend on specific indicator values and should be validated via backtesting.

Note: `sigmoid_scale(30, 15, 0.30) = 0.989` — the trend score saturates near the cap at ADX=30.

### mr_pressure = 0.40 (RSI=78, BB_pos=0.90)

| Stage | Current | Proposed | Notes |
|---|---|---|---|
| Caps | trend=38, mr=22 | trend=30.8, mr=29.2 | shift=7.2 |
| Trend score | ~+37.6 | ~+30.5 | ADX=30 saturates sigmoid, scaled by cap |
| Mean-rev score | ~-21.5 | ~-28.5 | RSI=78 saturates MR sigmoid, scaled by cap |
| Squeeze score | ~-8 | ~-8 | Follows MR sign |
| **Directional** | **+8** | **-6** | Caps determine winner |
| Volume | +10 additive | *0.83 = -5 | Multiplicative, OBV partially disagrees |
| Confluence | +12 | +9 | Dampened by 0.72x |
| **Tech score** | **+30** | **-2** | |
| Confidence | ~0.60 | ~0.50 | Directional, mr_pressure provides floor |
| Order flow | -10 | -25 | Conviction ceiling relaxed |
| Combiner blended | ~+15 | ~-10 | |
| LLM called? | Borderline | Yes (mr_pressure path) | Dual trigger |
| LLM contribution | +10 to +15 | -10 to -20 | Direction-dependent |
| **Final score** | **~+25 to +30** | **~-20 to -30** | **Moderate: no signal either way** |

At moderate exhaustion, the system correctly suppresses the false LONG and moves toward SHORT. A signal is unlikely from either side — the evidence isn't strong enough. This is correct behavior.

### mr_pressure = 0.69 (RSI=85, BB_pos=0.95)

| Stage | Current | Proposed |
|---|---|---|
| Caps | trend=38, mr=22 | trend=25.6, mr=34.4 |
| Trend score | ~+37.6 | ~+25.3 |
| Mean-rev score | ~-22.0 | ~-34.0 |
| Squeeze score | ~-10 | ~-10 |
| **Directional** | **+6** | **-19** |
| Volume | +10 | *0.82 = -16 |
| Confluence | +12 | +5 |
| **Tech score** | **+28** | **-30** |
| Order flow | -10 | -35 |
| Combiner blended | ~+15 | ~-28 |
| LLM called? | Borderline | Yes (both paths) |
| LLM contribution | +10 | -15 to -20 |
| **Final score** | **~+25 (no signal)** | **~-43 to -48 SHORT** |

---

## Data Flow

```
compute_technical_score()
  |
  +-- compute_mr_pressure(rsi, bb_pos)  -->  mr_pressure (0.0-1.0)
  |
  +-- Dynamic caps: shift = mr_pressure * MAX_CAP_SHIFT
  |     trend_cap -= shift, mean_rev_cap += shift
  |
  +-- Multiplicative volume: directional * vol_mult
  |
  +-- Directional confidence: max(trend_conf, mr_conf)
  |
  +-- Include mr_pressure in indicators dict for observability
  |     (serialized to LLM prompt, stored in Signal.raw_indicators JSONB)
  |
  +-- Returns: {score, indicators, regime, caps, confidence, mr_pressure}
         |
         +--> main.py: confluence dampening (mr_pressure)
         |
         +--> compute_order_flow_score(mr_pressure=...)
         |
         +--> combiner: uses directional confidence
         |
         +--> LLM gate: should_call_llm = |blended|>=25 OR mr_pressure>=0.30
```

---

## New Constants

Added to `engine/constants.py`:

```python
MR_PRESSURE = {
    "rsi_offset": 10,          # RSI deviation from 50 before activation
    "rsi_range": 30,           # RSI range for 0-1 scaling
    "bb_offset": 0.2,          # BB position deviation from 0.5 before activation
    "bb_range": 0.3,           # BB position range for 0-1 scaling
    "max_cap_shift": 18,       # max points to transfer between trend/MR caps
    "confluence_dampening": 0.7,  # max confluence reduction at full pressure
    "mr_llm_trigger": 0.30,    # mr_pressure threshold for LLM exhaustion path
}

VOL_MULTIPLIER = {
    "obv_weight": 0.6,         # OBV confirmation weight
    "vol_ratio_weight": 0.4,   # volume ratio confirmation weight
}
```

New config setting:
- `engine_mr_llm_trigger`: float, default 0.30 (config-only for initial implementation; can be promoted to `PipelineSettings` DB column for runtime override in a follow-up if needed)

### Optimizer Integration

Added to `engine/param_groups.py` as a **grid** group (DE sweep is not yet wired in `optimizer.py`). This lets the optimizer tune mr_pressure behavior via counterfactual backtesting + shadow validation on real signals.

**Tunable parameters** (the 4 highest-impact knobs):

| Param | Dot-path | Range | Step | Default | What it controls |
|-------|----------|-------|------|---------|------------------|
| `max_cap_shift` | `technical.mr_pressure.max_cap_shift` | 8–24 | 4 | 18 | How aggressively trend/MR caps shift |
| `confluence_dampening` | `technical.mr_pressure.confluence_dampening` | 0.30–0.90 | 0.15 | 0.70 | Max HTF confluence reduction at full pressure |
| `obv_weight` | `technical.vol_multiplier.obv_weight` | 0.30–0.80 | 0.10 | 0.60 | OBV vs volume-ratio confirmation balance |
| `mr_llm_trigger` | `technical.mr_pressure.mr_llm_trigger` | 0.20–0.45 | 0.05 | 0.30 | mr_pressure threshold for LLM exhaustion path |

**Not tuned** (activation zone): `rsi_offset`, `rsi_range`, `bb_offset`, `bb_range`. These define the mathematical mapping from RSI/BB to a 0–1 scale — stable by design. Can be added later if needed.

**Grid size:** 5 × 5 × 6 × 6 = 900 candidates (before constraint filtering). Comparable to existing `mean_reversion` group.

```python
def _mr_pressure_ok(c: dict[str, Any]) -> bool:
    return (
        c["max_cap_shift"] > 0
        and 0 < c["confluence_dampening"] < 1
        and 0 < c["obv_weight"] < 1
        and 0 < c["mr_llm_trigger"] < 1
    )

PARAM_GROUPS["mr_pressure"] = {
    "params": {
        "max_cap_shift": "technical.mr_pressure.max_cap_shift",
        "confluence_dampening": "technical.mr_pressure.confluence_dampening",
        "obv_weight": "technical.vol_multiplier.obv_weight",
        "mr_llm_trigger": "technical.mr_pressure.mr_llm_trigger",
    },
    "sweep_method": "grid",
    "sweep_ranges": {
        "max_cap_shift": (8, 24, 4),
        "confluence_dampening": (0.30, 0.90, 0.15),
        "obv_weight": (0.30, 0.80, 0.10),
        "mr_llm_trigger": (0.20, 0.45, 0.05),
    },
    "constraints": _mr_pressure_ok,
    "priority": _priority_for("mr_pressure"),
}
```

**Priority layer:** Add `"mr_pressure"` to layer 2 (alongside `mean_reversion`, `order_flow`):
```python
PRIORITY_LAYERS[2].add("mr_pressure")
```

**Backtester param override plumbing (gap 1 — in scope):**

The backtester calls `compute_technical_score(df, regime_weights=...)` at `backtester.py:155` but has no way to pass alternative constant values. The scoring functions import `MR_PRESSURE` and `VOL_MULTIPLIER` dicts directly from `engine/constants.py`. To make these tunable via the optimizer:

1. `BacktestConfig` gains an optional field:
   ```python
   param_overrides: dict[str, Any] = field(default_factory=dict)
   ```

2. `compute_technical_score` gains an optional `overrides: dict | None = None` parameter. When present, values are merged over the constant defaults:
   ```python
   mr = {**MR_PRESSURE, **(overrides.get("mr_pressure") or {})}
   vol = {**VOL_MULTIPLIER, **(overrides.get("vol_multiplier") or {})}
   ```

3. The backtester passes overrides through:
   ```python
   tech_result = compute_technical_score(df, regime_weights=regime_weights, overrides=config.param_overrides)
   ```

4. `run_counterfactual_eval` in `optimizer.py` maps candidate params to override dicts:
   ```python
   param_overrides = {
       "mr_pressure": {k: candidate[k] for k in ("max_cap_shift", "confluence_dampening", "mr_llm_trigger") if k in candidate},
       "vol_multiplier": {k: candidate[k] for k in ("obv_weight",) if k in candidate},
   }
   config = BacktestConfig(
       signal_threshold=candidate.get("signal", settings.engine_signal_threshold),
       param_overrides=param_overrides,
   )
   ```

This same plumbing unblocks DE groups in a follow-up (see `2026-03-25-optimizer-de-sweep-spec.md`).

---

## Implementation Scope

| Fix | File | Change | Lines |
|---|---|---|---|
| `compute_mr_pressure()` | `engine/traditional.py` | New function | ~8 |
| Dynamic caps | `engine/traditional.py` | After `blend_caps()` in `compute_technical_score` | ~4 |
| Multiplicative volume | `engine/traditional.py` | Replace additive volume block in `compute_technical_score` | ~15 (replaces ~6) |
| Directional confidence | `engine/traditional.py` | Replace confidence computation in `compute_technical_score` | ~12 (replaces ~3) |
| Confluence dampening | `main.py` | After `compute_confluence_score` call | ~2 |
| Order flow relaxation | `engine/traditional.py` | New param + 3 lines in `compute_order_flow_score` | ~5 |
| LLM dual trigger | `main.py` | Replace single threshold check | ~5 |
| Constants | `engine/constants.py` | New constant dicts | ~12 |
| Config setting | `config.py` | New `engine_mr_llm_trigger` field | ~2 |
| Optimizer group | `engine/param_groups.py` | New `mr_pressure` group + constraint + priority layer | ~25 |
| Backtester override | `engine/backtester.py` | `param_overrides` support in `BacktestConfig` + scoring calls | ~15 |

**Total:** ~105 lines changed/added across 6 files.

---

## Backward Compatibility

When `mr_pressure = 0` (RSI between 40-60 or BB_pos between 0.3-0.7):
- Cap shift = 0 (caps unchanged)
- Volume multiplier uses same OBV/vol_ratio logic, just applied multiplicatively
- Directional confidence: if score is trend-aligned, `trend_conf > mr_conf`, so `max()` picks trend_conf — similar to current
- Confluence dampening = 0 (unchanged)
- Order flow relaxation = 0 (unchanged)
- LLM gate: falls back to score-magnitude trigger (unchanged)

The two always-active changes (fix 2 and 3) have the following impact at mr_pressure=0:

**Volume (fix 2):** The max theoretical score changes from 100 (additive: 38+22+12+28) to ~92 (multiplicative: 72 * 1.28). This ~8% reduction affects both LONG and SHORT symmetrically. Signals near the threshold (40-44) could drop below it. Mitigation: monitor signal emission rate post-deployment. If needed, reduce `signal_threshold` by 2-3 points to compensate. A regression test should verify that a strong-trend-no-exhaustion scenario (ADX=30, RSI=55, BB_pos=0.5) produces LONG signals of similar strength to current.

**Confidence (fix 3):** In a trend-aligned LONG scenario, `trend_conf` is high and `mr_conf` is 0 (neutral RSI/BB). `max(trend_conf, 0) = trend_conf` — same as current. No regression.

**Volume cap semantic shift:** The `volume_cap` regime value now defines the multiplier amplitude instead of a score contribution ceiling. `PARAMETER_DESCRIPTIONS["volume_cap"]` in `constants.py` must be updated to reflect this. Operators tuning `volume_cap` via `RegimeWeights` should understand that large values (e.g., 50) create an aggressive multiplier range (0.50x to 1.50x).

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| False exhaustion in strong trends (RSI stays >70 for weeks) | Medium | Multiplicative gate requires BOTH RSI extreme AND BB extreme. BB_pos normalizes within a few candles even if RSI stays elevated. |
| Weakening valid trend-following signals | Low | At mr_pressure=0.40, trend_cap drops from 38 to 30.8 — still the dominant dimension. Only at extreme exhaustion (0.69+) does MR overtake trend. Start with MAX_CAP_SHIFT=12 if conservative. |
| Increased LLM cost | Low | mr_pressure >= 0.30 occurs on ~5-10% of candles in trending markets. ~1 extra LLM call per candle period across all pairs/timeframes. |
| Volume multiplier edge cases | Low | When directional=0, total=0 (no multiplication). The `vol_mult` range is bounded by `volume_cap` regime value, so no unbounded scaling. |
| Score distribution shift affecting existing thresholds | Medium | Signal threshold (40) tested in end-to-end trace — genuine SHORT signals reach -43 to -48 at strong exhaustion. Monitor signal counts post-deployment. |
| Multiplicative volume reduces max score by ~8% | Medium | Symmetric — affects LONG and SHORT equally. Regression test for LONG signal strength required. May need 2-3 point signal_threshold reduction if emission rate drops. |
| volume_cap semantic shift confuses operators | Low | Update `PARAMETER_DESCRIPTIONS["volume_cap"]` to reflect new meaning. Document that large values create aggressive multiplier ranges. |

---

## Testing Strategy

### Unit Tests

1. **`compute_mr_pressure`**: Verify symmetry (overbought vs oversold), multiplicative gate (RSI extreme alone = 0), boundary values.

2. **Dynamic caps**: Verify shift is applied correctly, caps stay balanced (sum doesn't change), no shift at mr_pressure=0.

3. **Multiplicative volume**: Verify volume can't flip score direction, multiplier range matches volume_cap, confirms/contradicts scenarios.

4. **Directional confidence**: Verify SHORT signals with extreme RSI/BB get higher confidence than current formula, LONG signals in trends are similar to current.

5. **Confluence dampening**: Verify dampening factor, no dampening at mr_pressure=0.

6. **Order flow relaxation**: Verify contrarian_mult floor rises with mr_pressure, no change at mr_pressure=0.

7. **LLM dual trigger**: Verify both paths trigger independently, floor on mr_pressure trigger.

### Integration Tests

8. **Full pipeline trace**: Feed candles with RSI=85, BB_pos=0.95 through `compute_technical_score` + `compute_order_flow_score` + `compute_preliminary_score` and verify a negative (SHORT) blended score is achievable.

9. **Neutral regression**: Feed candles with RSI=50, BB_pos=0.5 and verify output matches current behavior (mr_pressure=0 path).

10. **LONG signal regression**: Feed candles with ADX=30, RSI=55, BB_pos=0.5 (strong trend, no exhaustion) and verify LONG signal strength is not significantly degraded by the volume multiplier change. The score should remain within ~10% of current output.

### Optimizer Tests

11. **Param group registration**: Verify `mr_pressure` group exists in `PARAM_GROUPS`, has correct sweep ranges, and constraint function accepts valid candidates / rejects invalid ones.

12. **Backtester param overrides**: Verify `BacktestConfig(param_overrides={"max_cap_shift": 12})` produces different scores than default, confirming overrides propagate to scoring functions.

13. **Counterfactual eval**: Verify `run_counterfactual_eval(app, "mr_pressure")` generates candidates within sweep ranges and returns best candidate + metrics (or None if insufficient data).

---

## ALGORITHM.md Updates

Update Section 3 (Technical Scoring) to document:
- `mr_pressure` computation and its role
- Dynamic cap shifting
- Volume as confirmation multiplier
- Directional confidence formula

Update Section 4 (Order Flow) to document mr_pressure relaxation.

Update Section 9 (Multi-Timeframe Confluence) to document mr_pressure dampening.

Update Section 12 (LLM Gate) to document dual trigger.

Add mr_pressure constants to Section 21 (Key Thresholds & Constants).
