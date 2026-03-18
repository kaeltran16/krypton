# Structured LLM Factors

Replace the fixed opinion/confidence bucket system (+20/-15/-30) with structured, typed factors that capture the LLM's reasoning as discrete, scorable observations.

## Context

Currently, the LLM returns an `opinion` (confirm/caution/contradict) and `confidence` (HIGH/MEDIUM/LOW). The score adjustment is a fixed bucket scaled by confidence. The LLM's explanation text — containing specific observations like divergences, key levels, or volume exhaustion — is stored but never used programmatically. All nuance is discarded.

This is the last item in the signal algorithm improvements tracker (`docs/signal-algorithm-improvements.md`).

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Replace vs augment opinion system | Replace entirely | Eliminates blunt buckets; factors are the sole LLM score mechanism |
| Factor type definition | Fixed enum (12 types) | Tractable for backtesting; sufficient coverage; expandable |
| Category metadata | Included but not used in scoring | Prepares for future category-pooled scoring (Approach 3) without adding complexity now |
| Pipeline direction | Unidirectional (LLM factors affect LLM contribution only) | Avoids double-counting, keeps pipeline single-pass, simpler to debug |
| Factor validation | Required (1-5 factors, must parse) | Clean break; parse failure = no LLM contribution, same as current timeout behavior |
| Caution SL tightening | Removed | Score-based ATR scaling already handles weaker signals; extra tightening double-dips |
| Levels priority cascade | ML first, LLM second, ATR fallback | Trained ML has better calibration for price levels; LLM is better at qualitative reasoning |
| Weight optimization | Offline replay of resolved production signals | LLM is not called during backtests; replay stored factors against outcomes instead |

## Factor Type Enum

12 factor types across 4 categories:

| Category | Factor Type | Description |
|----------|------------|-------------|
| structure | `support_proximity` | Price near key support level |
| structure | `resistance_proximity` | Price near key resistance level |
| structure | `level_breakout` | Breaking through key level |
| structure | `htf_alignment` | Higher-timeframe trend confirms/conflicts |
| momentum | `rsi_divergence` | RSI diverging from price |
| momentum | `volume_divergence` | Volume diverging from price |
| momentum | `macd_divergence` | MACD diverging from price |
| exhaustion | `volume_exhaustion` | Volume drying up, move losing steam |
| exhaustion | `funding_extreme` | Funding rate at extreme levels |
| exhaustion | `crowded_positioning` | L/S ratio heavily skewed |
| event | `pattern_confirmation` | Candlestick pattern supports direction |
| event | `news_catalyst` | News event supports or undermines thesis |

Categories are metadata on the enum — stored for future use but not part of the scoring formula.

## Data Model

### New Pydantic Models

```python
class FactorCategory(str, Enum):
    STRUCTURE = "structure"
    MOMENTUM = "momentum"
    EXHAUSTION = "exhaustion"
    EVENT = "event"

class FactorType(str, Enum):
    SUPPORT_PROXIMITY = "support_proximity"
    RESISTANCE_PROXIMITY = "resistance_proximity"
    LEVEL_BREAKOUT = "level_breakout"
    HTF_ALIGNMENT = "htf_alignment"
    RSI_DIVERGENCE = "rsi_divergence"
    VOLUME_DIVERGENCE = "volume_divergence"
    MACD_DIVERGENCE = "macd_divergence"
    VOLUME_EXHAUSTION = "volume_exhaustion"
    FUNDING_EXTREME = "funding_extreme"
    CROWDED_POSITIONING = "crowded_positioning"
    PATTERN_CONFIRMATION = "pattern_confirmation"
    NEWS_CATALYST = "news_catalyst"

FACTOR_CATEGORIES: dict[FactorType, FactorCategory] = {
    FactorType.SUPPORT_PROXIMITY: FactorCategory.STRUCTURE,
    FactorType.RESISTANCE_PROXIMITY: FactorCategory.STRUCTURE,
    FactorType.LEVEL_BREAKOUT: FactorCategory.STRUCTURE,
    FactorType.HTF_ALIGNMENT: FactorCategory.STRUCTURE,
    FactorType.RSI_DIVERGENCE: FactorCategory.MOMENTUM,
    FactorType.VOLUME_DIVERGENCE: FactorCategory.MOMENTUM,
    FactorType.MACD_DIVERGENCE: FactorCategory.MOMENTUM,
    FactorType.VOLUME_EXHAUSTION: FactorCategory.EXHAUSTION,
    FactorType.FUNDING_EXTREME: FactorCategory.EXHAUSTION,
    FactorType.CROWDED_POSITIONING: FactorCategory.EXHAUSTION,
    FactorType.PATTERN_CONFIRMATION: FactorCategory.EVENT,
    FactorType.NEWS_CATALYST: FactorCategory.EVENT,
}

class LLMFactor(BaseModel):
    type: FactorType
    direction: Literal["bullish", "bearish"]
    strength: Literal[1, 2, 3]  # 1=mild, 2=moderate, 3=strong
    reason: str                 # one-sentence explanation

class LLMResponse(BaseModel):
    factors: list[LLMFactor]    # 1-5 factors
    explanation: str            # overall summary for UI/debugging
    levels: LLMLevels | None = None  # entry/SL/TP (unchanged)
```

### Removed Fields

- `opinion: Opinion` — removed from `LLMResponse`
- `confidence: Confidence` — removed from `LLMResponse`
- `Opinion` and `Confidence` type aliases — removed

### LLM Call Return Model

```python
class LLMResult(BaseModel):
    response: LLMResponse
    prompt_tokens: int
    completion_tokens: int
    model: str  # actual model used
```

`call_openrouter()` returns `LLMResult | None` instead of `LLMResponse | None`.

## Scoring Logic

### Default Factor Weights

| Factor Type | Default Weight |
|-------------|---------------|
| `support_proximity` | 6 |
| `resistance_proximity` | 6 |
| `level_breakout` | 8 |
| `htf_alignment` | 7 |
| `rsi_divergence` | 7 |
| `volume_divergence` | 6 |
| `macd_divergence` | 6 |
| `volume_exhaustion` | 5 |
| `funding_extreme` | 5 |
| `crowded_positioning` | 5 |
| `pattern_confirmation` | 5 |
| `news_catalyst` | 7 |

### Formula

```
for each factor:
    sign = +1 if factor.direction aligns with signal direction, else -1
    contribution = sign * factor_weight[factor.type] * factor.strength

llm_contribution = sum(contributions)
llm_contribution = clamp(llm_contribution, -35, +35)
final_score = clamp(blended_score + llm_contribution, -100, +100)
```

- "Aligns with signal direction" = bullish factor on LONG signal, or bearish factor on SHORT signal
- Max single factor contribution: 8 * 3 = 24 (level_breakout at strength 3)
- Total cap: ±35 (comparable to current ±30 range)
- Typical 2-4 factor signals will produce ±10 to ±25 contribution

### Config

```python
llm_factor_weights: dict[str, float]  # factor_type -> weight, defaults above
llm_factor_total_cap: float = 35.0
```

Stored in engine settings, overridable via `PipelineSettings` DB table.

### Function Signatures

Split the current `compute_final_score()` into two functions for clarity:

```python
def compute_llm_contribution(factors: list[LLMFactor], direction: str, factor_weights: dict[str, float], total_cap: float) -> int:
    """Compute the LLM score contribution from structured factors."""

def compute_final_score(blended_score: int, llm_contribution: int) -> int:
    """Apply LLM contribution to blended score. Returns clamped [-100, +100]."""
```

`main.py` calls both separately so `llm_contribution` is available for the levels cascade.

### Replaces

- `compute_final_score(preliminary_score, llm_response)` — split into `compute_llm_contribution()` + `compute_final_score()`
- `CONFIDENCE_MULTIPLIER` dict — removed
- Caution SL tightening (`caution_sl_factor`) — removed; score-based ATR scaling handles it
- `llm_opinion` and `caution_sl_factor` parameters removed from `calculate_levels()` signature

## Levels Priority Cascade

Updated order (ML promoted above LLM):

1. **ML regression** — if available and confidence >= threshold (unchanged logic)
2. **LLM levels** — if provided, `llm_contribution >= 0`, and passes `_validate_llm_levels()`
3. **ATR defaults** — fallback (unchanged)

Same guardrails applied to all paths (SL/TP bounds, R:R floor).

## Prompt Changes

Update `prompts/signal_analysis.txt`:

- Remove instructions to return `opinion` and `confidence`
- List the 12 factor types with brief descriptions
- Request 1-5 factors as JSON array with `type`, `direction`, `strength`, `reason`
- Keep `explanation` field (overall 2-3 sentence summary)
- Keep `levels` field (entry/SL/TP)
- Add strength calibration: 1 = weak/suggestive, 2 = clear evidence, 3 = strong/multiple confirming signals

### Expected Response Format

```json
{
  "factors": [
    {
      "type": "rsi_divergence",
      "direction": "bullish",
      "strength": 2,
      "reason": "RSI making higher lows while price makes lower lows on last 5 candles"
    },
    {
      "type": "funding_extreme",
      "direction": "bearish",
      "strength": 1,
      "reason": "Funding slightly elevated but not extreme"
    }
  ],
  "explanation": "Bullish divergence forming but funding headwind limits conviction.",
  "levels": {
    "entry": 67000,
    "stop_loss": 66200,
    "take_profit_1": 67800,
    "take_profit_2": 68600
  }
}
```

## Validation

In `parse_llm_response()`:

- Reject if `factors` is empty or missing → return `None`
- Reject if any factor has unknown `type` (not in `FactorType` enum) → return `None`
- Reject if any factor has `strength` outside [1, 2, 3] → return `None` (Pydantic `Literal` enforces this)
- Cap at 5 factors — truncate beyond that
- Parse failure → return `None` (no LLM contribution, same as current timeout behavior)

## Storage

### Signal DB Model Changes

- **Remove columns:** `llm_opinion`, `llm_confidence`
- **Keep column:** `explanation`
- **Add column:** `llm_factors` (JSONB) — stores raw factor list

Stored value:
```json
[
  {"type": "rsi_divergence", "direction": "bullish", "strength": 2, "reason": "RSI higher lows vs price lower lows"},
  {"type": "funding_extreme", "direction": "bearish", "strength": 1, "reason": "Funding slightly elevated"}
]
```

### Token Usage Tracking

Stored in `raw_indicators` JSONB (no new columns):

```json
{
  "llm_prompt_tokens": 1250,
  "llm_completion_tokens": 180,
  "llm_model": "anthropic/claude-3.5-sonnet",
  "llm_contribution": 14
}
```

### Alembic Migration

- Add `llm_factors` JSONB column (nullable)
- Remove `llm_opinion` and `llm_confidence` columns
- No backfill needed for `raw_indicators` — historical rows will have `None` for the new LLM token keys, which callers must handle

## Weight Optimization

LLM is not called during backtesting. Factor weight optimization uses resolved production signals instead:

1. Accumulate resolved signals (TP hit / SL hit / expired) with stored `llm_factors`
2. Offline replay: re-score the LLM contribution with candidate weights against known outcomes
3. Use `differential_evolution` — objective function replays stored factor data, not full candle history
4. Parameter vector: 12 factor weights (bounded [0, 15]) + 1 total cap (bounded [15, 50])
5. Minimum data: ~200 resolved signals with factor data before optimization is meaningful

## Files Changed

| File | Change |
|------|--------|
| `engine/models.py` | New `FactorType`, `FactorCategory`, `LLMFactor`, `LLMResult` models; update `LLMResponse`; remove `Opinion`, `Confidence` |
| `engine/llm.py` | Update `call_openrouter()` to return `LLMResult`; extract token usage from response; update `SYSTEM_PROMPT` to match factor-based schema (remove opinion/confidence language) |
| `engine/combiner.py` | Split `compute_final_score()` into `compute_llm_contribution()` + `compute_final_score()`; update `calculate_levels()` cascade (reorder to ML-first, remove `llm_opinion` and `caution_sl_factor` params from signature); remove `CONFIDENCE_MULTIPLIER` |
| `prompts/signal_analysis.txt` | Restructure to request factors instead of opinion/confidence |
| `db/models.py` | Add `llm_factors` column; remove `llm_opinion`, `llm_confidence` |
| `main.py` | Update `run_pipeline()` to use `LLMResult`; store factors + token usage |
| `config.py` | Add `llm_factor_weights`, `llm_factor_total_cap`; remove `llm_caution_sl_factor` |
| `api/` endpoints | Update signal serializers — remove `llm_opinion`/`llm_confidence` fields; remove synthetic `confidence` field (was derived from `llm_confidence`); add `llm_factors` and `llm_contribution` to response |
| Alembic migration | Add `llm_factors`, drop `llm_opinion`/`llm_confidence` |
| `web/src/features/signals/types.ts` | Remove `confidence` and `llm_opinion` fields from `Signal` type; add `llm_factors` and `llm_contribution` |
| `web/src/features/signals/components/SignalDetail.tsx` | Update to display `llm_factors` instead of opinion/confidence |
| Tests | Update tests for new models, scoring logic, and prompt format; delete caution SL tests (`test_calculate_levels_caution_tightens_sl_ml`, `test_calculate_levels_caution_tightens_sl_atr_defaults`, `test_calculate_levels_caution_no_effect_with_llm_levels`) |
