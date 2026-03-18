# Structured LLM Factors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed opinion/confidence LLM scoring system with structured typed factors that capture discrete, scorable observations from the LLM.

**Architecture:** The LLM returns 1-5 typed factors (from a 12-type enum) instead of an opinion/confidence pair. Each factor has a direction, strength (1-3), and reason. Factor contributions are summed (with per-type weights) and capped at +-35 to produce the LLM score adjustment. The levels priority cascade is reordered to ML-first. Token usage is tracked per call.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Pydantic, Alembic, React 19, TypeScript

**Spec:** `docs/superpowers/specs/2026-03-18-structured-llm-factors-design.md`

---

## File Map

| File | Responsibility |
|------|---------------|
| `backend/app/engine/models.py` | Pydantic models: `FactorType`, `FactorCategory`, `LLMFactor`, `LLMResult`, updated `LLMResponse` |
| `backend/app/engine/llm.py` | OpenRouter API call, response parsing, system prompt, token extraction |
| `backend/app/engine/combiner.py` | `compute_llm_contribution()`, updated `compute_final_score()`, reordered `calculate_levels()` |
| `backend/app/config.py` | `llm_factor_weights`, `llm_factor_total_cap` settings; remove `llm_caution_sl_factor` |
| `backend/app/prompts/signal_analysis.txt` | Updated prompt requesting factors instead of opinion/confidence |
| `backend/app/db/models.py` | Signal model: add `llm_factors` JSONB, remove `llm_opinion`/`llm_confidence` |
| `backend/app/main.py` | Pipeline integration: use `LLMResult`, store factors + tokens |
| `backend/app/api/routes.py` | Signal serializer: remove `confidence`/`llm_opinion`, add `llm_factors`/`llm_contribution` |
| `web/src/features/signals/types.ts` | TypeScript types: add `LLMFactor`, update `Signal` interface |
| `web/src/features/signals/components/SignalDetail.tsx` | Display factors instead of opinion |
| `web/src/features/signals/store.test.ts` | Update test fixtures |
| Alembic migration | Add `llm_factors`, preserve old data in `raw_indicators`, drop `llm_opinion`/`llm_confidence` |
| `backend/tests/engine/test_combiner.py` | New factor scoring tests, delete caution SL tests |
| `backend/tests/engine/test_llm.py` | Updated parse/call tests for factor-based responses |
| `backend/tests/test_db_models.py` | Update Signal fixture: replace `llm_opinion`/`llm_confidence` with `llm_factors` |
| `backend/tests/test_pipeline.py` | Update integration tests: remove `parse_llm_response` usage, new `compute_final_score` signature |
| `backend/tests/api/test_journal.py` | Update `_make_signal` fixture: replace old LLM fields with `llm_factors` |
| `backend/tests/test_pipeline_ml.py` | Update LLM behavior tests: factor-based `LLMResult`, remove `llm_caution_sl_factor` |

---

### Task 1: Add Factor Enums and Pydantic Models

**Files:**
- Modify: `backend/app/engine/models.py`
- Test: `backend/tests/engine/test_models.py` (create)

- [ ] **Step 1: Write tests for new models**

Create `backend/tests/engine/test_models.py`:

```python
import pytest
from pydantic import ValidationError
from app.engine.models import (
    FactorType, FactorCategory, LLMFactor, LLMResponse, LLMResult,
    FACTOR_CATEGORIES, DEFAULT_FACTOR_WEIGHTS,
)


def test_factor_type_enum_has_12_members():
    assert len(FactorType) == 12


def test_factor_categories_maps_all_types():
    for ft in FactorType:
        assert ft in FACTOR_CATEGORIES


def test_llm_factor_valid():
    f = LLMFactor(type="rsi_divergence", direction="bullish", strength=2, reason="RSI higher lows")
    assert f.type == FactorType.RSI_DIVERGENCE
    assert f.strength == 2


def test_llm_factor_invalid_strength():
    with pytest.raises(ValidationError):
        LLMFactor(type="rsi_divergence", direction="bullish", strength=4, reason="bad")


def test_llm_factor_invalid_type():
    with pytest.raises(ValidationError):
        LLMFactor(type="made_up_factor", direction="bullish", strength=1, reason="bad")


def test_llm_factor_invalid_direction():
    with pytest.raises(ValidationError):
        LLMFactor(type="rsi_divergence", direction="neutral", strength=1, reason="bad")


def test_llm_response_valid():
    r = LLMResponse(
        factors=[LLMFactor(type="rsi_divergence", direction="bullish", strength=2, reason="test")],
        explanation="Test explanation",
    )
    assert len(r.factors) == 1
    assert r.levels is None


def test_llm_response_with_levels():
    from app.engine.models import LLMLevels
    r = LLMResponse(
        factors=[LLMFactor(type="level_breakout", direction="bullish", strength=3, reason="broke key level")],
        explanation="Breakout confirmed",
        levels=LLMLevels(entry=67000, stop_loss=66200, take_profit_1=67800, take_profit_2=68600),
    )
    assert r.levels.entry == 67000


def test_llm_result_has_token_fields():
    r = LLMResult(
        response=LLMResponse(
            factors=[LLMFactor(type="rsi_divergence", direction="bullish", strength=1, reason="test")],
            explanation="test",
        ),
        prompt_tokens=1250,
        completion_tokens=180,
        model="anthropic/claude-3.5-sonnet",
    )
    assert r.prompt_tokens == 1250
    assert r.model == "anthropic/claude-3.5-sonnet"


def test_default_factor_weights_has_all_types():
    for ft in FactorType:
        assert ft.value in DEFAULT_FACTOR_WEIGHTS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_models.py -v`
Expected: FAIL — imports don't exist yet

- [ ] **Step 3: Implement the models**

Update `backend/app/engine/models.py` to the following full content:

```python
from enum import Enum
from typing import Literal

from pydantic import BaseModel

Direction = Literal["LONG", "SHORT"]


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

DEFAULT_FACTOR_WEIGHTS: dict[str, float] = {
    "support_proximity": 6.0,
    "resistance_proximity": 6.0,
    "level_breakout": 8.0,
    "htf_alignment": 7.0,
    "rsi_divergence": 7.0,
    "volume_divergence": 6.0,
    "macd_divergence": 6.0,
    "volume_exhaustion": 5.0,
    "funding_extreme": 5.0,
    "crowded_positioning": 5.0,
    "pattern_confirmation": 5.0,
    "news_catalyst": 7.0,
}


class LLMLevels(BaseModel):
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float


class LLMFactor(BaseModel):
    type: FactorType
    direction: Literal["bullish", "bearish"]
    strength: Literal[1, 2, 3]
    reason: str


class LLMResponse(BaseModel):
    factors: list[LLMFactor]
    explanation: str
    levels: LLMLevels | None = None


class LLMResult(BaseModel):
    response: LLMResponse
    prompt_tokens: int
    completion_tokens: int
    model: str


class SignalResult(BaseModel):
    pair: str
    timeframe: str
    direction: Direction
    final_score: int
    traditional_score: int
    explanation: str | None = None
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    raw_indicators: dict
```

Note: `Opinion`, `Confidence` type aliases are removed. `SignalResult` drops `llm_opinion` and `llm_confidence`. `DEFAULT_FACTOR_WEIGHTS` lives in `models.py` — `config.py` will reference it via a `default_factory` lambda to avoid import-time dependency (see Task 4).

Note: `FactorType` and `FactorCategory` use `str, Enum` rather than the `Literal` pattern used for `Opinion`/`Confidence`/`Direction` elsewhere in this file. This is intentional — 12 values need iteration (for the `FACTOR_CATEGORIES` mapping), dict key access (`.value`), and exhaustive coverage checks, which `Literal` handles poorly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_models.py -v`
Expected: All PASS

---

### Task 2: Update Combiner — Factor Scoring and Levels Cascade

**Files:**
- Modify: `backend/app/engine/combiner.py`
- Modify: `backend/tests/engine/test_combiner.py`

- [ ] **Step 1: Write tests for `compute_llm_contribution`**

Add to `backend/tests/engine/test_combiner.py`, replacing the old `compute_final_score` tests (lines 156-224). Delete all old `test_final_score_*` tests and the three caution SL tests (`test_calculate_levels_caution_tightens_sl_ml`, `test_calculate_levels_caution_tightens_sl_atr_defaults`, `test_calculate_levels_caution_no_effect_with_llm_levels`).

Update the import block at the top:

```python
from app.engine.models import LLMFactor, DEFAULT_FACTOR_WEIGHTS
from app.engine.combiner import (
    compute_preliminary_score,
    compute_llm_contribution,
    compute_final_score,
    calculate_levels,
    blend_with_ml,
    compute_agreement,
    scale_atr_multipliers,
)
```

Remove the old import `from app.engine.models import LLMResponse`.

Add new tests replacing the old `compute_final_score` section:

```python
# ── compute_llm_contribution ──


def test_llm_contribution_single_aligned_factor():
    """Single bullish factor on LONG signal = positive contribution."""
    factors = [LLMFactor(type="rsi_divergence", direction="bullish", strength=2, reason="test")]
    result = compute_llm_contribution(factors, "LONG", DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == round(7.0 * 2)  # weight=7, strength=2, aligned=+1


def test_llm_contribution_single_opposing_factor():
    """Bearish factor on LONG signal = negative contribution."""
    factors = [LLMFactor(type="rsi_divergence", direction="bearish", strength=2, reason="test")]
    result = compute_llm_contribution(factors, "LONG", DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == round(-7.0 * 2)


def test_llm_contribution_short_direction():
    """Bearish factor on SHORT signal = positive (aligned)."""
    factors = [LLMFactor(type="funding_extreme", direction="bearish", strength=3, reason="test")]
    result = compute_llm_contribution(factors, "SHORT", DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == round(5.0 * 3)  # aligned with SHORT


def test_llm_contribution_multiple_factors():
    """Multiple factors sum their contributions."""
    factors = [
        LLMFactor(type="level_breakout", direction="bullish", strength=3, reason="broke key"),
        LLMFactor(type="rsi_divergence", direction="bullish", strength=1, reason="mild div"),
        LLMFactor(type="funding_extreme", direction="bearish", strength=2, reason="elevated"),
    ]
    result = compute_llm_contribution(factors, "LONG", DEFAULT_FACTOR_WEIGHTS, 35.0)
    expected = round((8.0 * 3) + (7.0 * 1) + (-5.0 * 2))  # 24 + 7 - 10 = 21
    assert result == expected


def test_llm_contribution_capped_positive():
    """Total capped at +total_cap."""
    factors = [
        LLMFactor(type="level_breakout", direction="bullish", strength=3, reason="a"),
        LLMFactor(type="htf_alignment", direction="bullish", strength=3, reason="b"),
        LLMFactor(type="rsi_divergence", direction="bullish", strength=3, reason="c"),
    ]
    # Raw: 24 + 21 + 21 = 66, should be capped at 35
    result = compute_llm_contribution(factors, "LONG", DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == 35


def test_llm_contribution_capped_negative():
    """Total capped at -total_cap."""
    factors = [
        LLMFactor(type="level_breakout", direction="bearish", strength=3, reason="a"),
        LLMFactor(type="htf_alignment", direction="bearish", strength=3, reason="b"),
        LLMFactor(type="rsi_divergence", direction="bearish", strength=3, reason="c"),
    ]
    result = compute_llm_contribution(factors, "LONG", DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == -35


def test_llm_contribution_empty_factors():
    """Empty factor list returns 0."""
    result = compute_llm_contribution([], "LONG", DEFAULT_FACTOR_WEIGHTS, 35.0)
    assert result == 0


def test_llm_contribution_custom_weights():
    """Custom weight dict overrides defaults."""
    custom = {"rsi_divergence": 10.0}
    factors = [LLMFactor(type="rsi_divergence", direction="bullish", strength=2, reason="test")]
    result = compute_llm_contribution(factors, "LONG", custom, 35.0)
    assert result == 20  # 10.0 * 2


# ── compute_final_score (new signature) ──


def test_final_score_adds_contribution():
    assert compute_final_score(60, 14) == 74


def test_final_score_subtracts_contribution():
    assert compute_final_score(60, -14) == 46


def test_final_score_no_llm():
    assert compute_final_score(60, 0) == 60


def test_final_score_clamped_high():
    assert compute_final_score(90, 35) == 100


def test_final_score_clamped_low():
    assert compute_final_score(-90, -35) == -100
```

- [ ] **Step 2: Write tests for updated `calculate_levels` (ML-first cascade)**

Replace `test_calculate_levels_llm_override` (line 247-260) with the tests below. Note: `test_levels_source_llm` (line 564) remains valid as-is — it tests LLM levels with no ML present, which still works. `test_calculate_levels_rejects_invalid_llm_levels` (line 263) also remains valid — new `llm_contribution` defaults to 0, and the invalid levels fail `_validate_llm_levels` as before.

```python
def test_calculate_levels_ml_first_over_llm():
    """ML takes priority over LLM when both available."""
    llm_levels = {
        "entry": 67000.0, "stop_loss": 66500.0,
        "take_profit_1": 67500.0, "take_profit_2": 68000.0,
    }
    ml_multiples = {"sl_atr": 1.2, "tp1_atr": 2.5, "tp2_atr": 4.0}
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        llm_levels=llm_levels, ml_atr_multiples=ml_multiples,
        llm_contribution=10,
    )
    assert levels["levels_source"] == "ml"


def test_calculate_levels_llm_fallback_no_ml():
    """LLM levels used when ML not available and contribution >= 0."""
    llm_levels = {
        "entry": 67000.0, "stop_loss": 66500.0,
        "take_profit_1": 67500.0, "take_profit_2": 68000.0,
    }
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        llm_levels=llm_levels, llm_contribution=5,
    )
    assert levels == {**llm_levels, "levels_source": "llm"}


def test_calculate_levels_llm_skipped_negative_contribution():
    """LLM levels skipped when contribution < 0."""
    llm_levels = {
        "entry": 67000.0, "stop_loss": 66500.0,
        "take_profit_1": 67500.0, "take_profit_2": 68000.0,
    }
    levels = calculate_levels(
        direction="LONG", current_price=67000.0, atr=200.0,
        llm_levels=llm_levels, llm_contribution=-5,
    )
    assert levels["levels_source"] == "atr_default"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -v`
Expected: FAIL — `compute_llm_contribution` not defined, `calculate_levels` signature changed

- [ ] **Step 4: Implement combiner changes**

Update `backend/app/engine/combiner.py`:

1. Replace imports: `from app.engine.models import LLMFactor, DEFAULT_FACTOR_WEIGHTS` (remove `LLMResponse`)
2. Delete `CONFIDENCE_MULTIPLIER` dict
3. Add `compute_llm_contribution()`:

```python
def compute_llm_contribution(
    factors: list[LLMFactor],
    direction: str,
    factor_weights: dict[str, float],
    total_cap: float,
) -> int:
    total = 0.0
    for f in factors:
        weight = factor_weights.get(f.type.value, 0.0)
        aligned = (
            (f.direction == "bullish" and direction == "LONG")
            or (f.direction == "bearish" and direction == "SHORT")
        )
        sign = 1 if aligned else -1
        total += sign * weight * f.strength
    return round(max(-total_cap, min(total_cap, total)))
```

4. Replace `compute_final_score()`:

```python
def compute_final_score(blended_score: int, llm_contribution: int) -> int:
    return max(-100, min(100, blended_score + llm_contribution))
```

5. Update `calculate_levels()` — remove `llm_opinion` and `caution_sl_factor` params, add `llm_contribution`, reorder cascade:

```python
def calculate_levels(
    direction: str,
    current_price: float,
    atr: float,
    llm_levels: dict | None = None,
    ml_atr_multiples: dict | None = None,
    llm_contribution: int = 0,
    sl_bounds: tuple[float, float] = (0.5, 3.0),
    tp1_min_atr: float = 1.0,
    tp2_max_atr: float = 8.0,
    rr_floor: float = 1.0,
    sl_atr_default: float = 1.5,
    tp1_atr_default: float = 2.0,
    tp2_atr_default: float = 3.0,
) -> dict:
    # Priority 1: ML regression multiples
    if ml_atr_multiples is not None:
        sl_atr = ml_atr_multiples["sl_atr"]
        tp1_atr = ml_atr_multiples["tp1_atr"]
        tp2_atr = ml_atr_multiples["tp2_atr"]
        levels_source = "ml"
    elif llm_levels and llm_contribution >= 0 and _validate_llm_levels(direction, llm_levels):
        # Priority 2: LLM explicit levels (only if contribution non-negative)
        return {**llm_levels, "levels_source": "llm"}
    else:
        # Priority 3: ATR defaults
        sl_atr = sl_atr_default
        tp1_atr = tp1_atr_default
        tp2_atr = tp2_atr_default
        levels_source = "atr_default"

    # Shared guardrails
    sl_atr = max(sl_bounds[0], min(sl_atr, sl_bounds[1]))
    tp1_atr = max(tp1_min_atr, tp1_atr)
    tp2_atr = max(tp1_atr * 1.2, tp2_atr)
    tp2_atr = min(tp2_max_atr, tp2_atr)
    if sl_atr > 0 and tp1_atr / sl_atr < rr_floor:
        tp1_atr = sl_atr * rr_floor

    sign = 1 if direction == "LONG" else -1
    return {
        "entry": current_price,
        "stop_loss": current_price - sign * sl_atr * atr,
        "take_profit_1": current_price + sign * tp1_atr * atr,
        "take_profit_2": current_price + sign * tp2_atr * atr,
        "levels_source": levels_source,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -v`
Expected: All PASS

- [ ] **Step 6: Do NOT commit yet** — continue to next task.

---

### Task 3: Update LLM Module — Response Parsing and Token Tracking

**Files:**
- Modify: `backend/app/engine/llm.py`
- Modify: `backend/tests/engine/test_llm.py`

- [ ] **Step 1: Write tests for factor-based parsing and token tracking**

Replace the tests in `backend/tests/engine/test_llm.py`. Update imports:

```python
from app.engine.llm import (
    OPENROUTER_URL,
    call_openrouter,
    load_prompt_template,
    parse_llm_response,
    render_prompt,
)
from app.engine.models import FactorType
```

Replace `test_parse_llm_response_valid_json`:

```python
def test_parse_llm_response_valid_factors():
    content = '{"factors": [{"type": "rsi_divergence", "direction": "bullish", "strength": 2, "reason": "RSI higher lows"}], "explanation": "Divergence forming.", "levels": {"entry": 67420, "stop_loss": 66890, "take_profit_1": 67950, "take_profit_2": 68480}}'
    result = parse_llm_response(content)
    assert result is not None
    assert len(result.factors) == 1
    assert result.factors[0].type == FactorType.RSI_DIVERGENCE
    assert result.levels.entry == 67420
```

Replace `test_parse_llm_response_with_code_fences`:

```python
def test_parse_llm_response_with_code_fences():
    content = '```json\n{"factors": [{"type": "level_breakout", "direction": "bullish", "strength": 3, "reason": "Broke resistance"}], "explanation": "Clean breakout.", "levels": null}\n```'
    result = parse_llm_response(content)
    assert result is not None
    assert result.factors[0].type == FactorType.LEVEL_BREAKOUT
    assert result.levels is None
```

Add new factor-specific validation tests:

```python
def test_parse_llm_response_empty_factors():
    """Empty factors list returns None."""
    content = '{"factors": [], "explanation": "Nothing to say."}'
    result = parse_llm_response(content)
    assert result is None


def test_parse_llm_response_unknown_factor_type():
    """Unknown factor type returns None."""
    content = '{"factors": [{"type": "made_up", "direction": "bullish", "strength": 1, "reason": "x"}], "explanation": "x"}'
    result = parse_llm_response(content)
    assert result is None


def test_parse_llm_response_invalid_strength():
    """Strength outside [1,2,3] returns None."""
    content = '{"factors": [{"type": "rsi_divergence", "direction": "bullish", "strength": 5, "reason": "x"}], "explanation": "x"}'
    result = parse_llm_response(content)
    assert result is None


def test_parse_llm_response_truncates_to_5_factors():
    """More than 5 factors truncated to 5."""
    factors = [{"type": "rsi_divergence", "direction": "bullish", "strength": 1, "reason": f"r{i}"} for i in range(7)]
    import json
    content = json.dumps({"factors": factors, "explanation": "many factors"})
    result = parse_llm_response(content)
    assert result is not None
    assert len(result.factors) == 5
```

Replace `test_parse_llm_response_missing_fields`:

```python
def test_parse_llm_response_missing_factors():
    """Missing factors field returns None."""
    content = '{"explanation": "No factors here"}'
    result = parse_llm_response(content)
    assert result is None
```

Remove `test_parse_llm_response_invalid_opinion` (no longer relevant).

Update the `prompt_file` fixture to use factor-based template:

```python
@pytest.fixture
def prompt_file(tmp_path):
    template = """Analyze the following crypto futures data for {pair} on {timeframe} timeframe.

Technical Indicators:
{indicators}

Order Flow:
{order_flow}

Preliminary Score: {preliminary_score} ({direction})

Recent Candles (last 20):
{candles}

Return 1-5 factors as JSON."""
    f = tmp_path / "signal_analysis.txt"
    f.write_text(template)
    return f
```

Replace `test_call_openrouter_success`:

```python
async def test_call_openrouter_success():
    """Successful API call returns LLMResult with token usage."""
    mock_response = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"factors": [{"type": "rsi_divergence", "direction": "bullish", "strength": 2, "reason": "RSI diverging"}], "explanation": "Looks good.", "levels": null}'}}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 150},
            "model": "anthropic/claude-3.5-sonnet",
        },
    )
    mock_response.request = httpx.Request("POST", OPENROUTER_URL)
    with patch("app.engine.llm.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _mock_async_client(post_return=mock_response)
        result = await call_openrouter("test prompt", "fake-key", "test-model")
        assert result is not None
        assert result.response.factors[0].type.value == "rsi_divergence"
        assert result.prompt_tokens == 800
        assert result.completion_tokens == 150
```

Update timeout and error tests — they should still return `None`:

```python
async def test_call_openrouter_timeout():
    """Timeout returns None gracefully."""
    with patch("app.engine.llm.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _mock_async_client(
            post_side_effect=httpx.TimeoutException("timed out"),
        )
        result = await call_openrouter("test prompt", "fake-key", "test-model")
        assert result is None


async def test_call_openrouter_api_error():
    """HTTP error returns None gracefully."""
    mock_response = httpx.Response(500, text="Internal Server Error")
    mock_response.request = httpx.Request("POST", OPENROUTER_URL)
    with patch("app.engine.llm.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = _mock_async_client(post_return=mock_response)
        result = await call_openrouter("test prompt", "fake-key", "test-model")
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_llm.py -v`
Expected: FAIL — parse/call functions return wrong types

- [ ] **Step 3: Implement LLM module changes**

Update `backend/app/engine/llm.py`:

```python
import json
import logging
from pathlib import Path

import httpx

from app.engine.models import LLMResponse, LLMResult

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a decisive crypto futures trader with 10 years of experience. "
    "You analyze quantitative data and identify specific factors that support "
    "or undermine a trade setup. You focus on concrete evidence — divergences, "
    "key levels, exhaustion signals, positioning extremes — not vague concerns "
    "about volatility or risk."
)

MAX_FACTORS = 5


def load_prompt_template(path: Path) -> str:
    return path.read_text()


def render_prompt(template: str, **kwargs) -> str:
    return template.format(**kwargs)


async def call_openrouter(
    prompt: str,
    api_key: str,
    model: str,
    timeout: int = 30,
) -> LLMResult | None:
    """Call OpenRouter API and parse response into LLMResult with token usage."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.5,
        "max_tokens": 1000,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        parsed = parse_llm_response(content)
        if parsed is None:
            return None

        usage = data.get("usage", {})
        return LLMResult(
            response=parsed,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", model),
        )
    except httpx.TimeoutException:
        logger.warning("OpenRouter request timed out")
        return None
    except Exception as e:
        logger.error(f"OpenRouter call failed: {e}")
        return None


def parse_llm_response(content: str) -> LLMResponse | None:
    """Parse LLM text response into structured LLMResponse with factors."""
    try:
        text = content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(text)

        # Truncate to max factors before validation
        if "factors" in data and isinstance(data["factors"], list):
            data["factors"] = data["factors"][:MAX_FACTORS]

        parsed = LLMResponse.model_validate(data)

        if not parsed.factors:
            logger.error("LLM returned empty factors list")
            return None

        return parsed
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"Failed to parse LLM response: {e}")
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_llm.py -v`
Expected: All PASS

- [ ] **Step 5: Do NOT commit yet** — continue to next task.

---

### Task 4: Update Config — Factor Weights and Remove Caution SL

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Update config**

In `backend/app/config.py`:

1. Do NOT add an import from `app.engine.models` — `config.py` is the lowest-layer module and should not depend on engine code.
2. Remove: `llm_caution_sl_factor: float = 0.8` (line 99)
3. Add after the ML settings block (after line 98), using `Field(default_factory=...)` to define defaults inline:

```python
    # LLM factor scoring
    llm_factor_weights: dict[str, float] = Field(default_factory=lambda: {
        "support_proximity": 6.0, "resistance_proximity": 6.0,
        "level_breakout": 8.0, "htf_alignment": 7.0,
        "rsi_divergence": 7.0, "volume_divergence": 6.0,
        "macd_divergence": 6.0, "volume_exhaustion": 5.0,
        "funding_extreme": 5.0, "crowded_positioning": 5.0,
        "pattern_confirmation": 5.0, "news_catalyst": 7.0,
    })
    llm_factor_total_cap: float = 35.0
```

4. Add `Field` import from `pydantic` (NOT `pydantic_settings` — config.py imports `BaseSettings` from `pydantic_settings` but `Field` comes from `pydantic`): add `from pydantic import Field` at the top of the file. This is the first use of `Field(default_factory=...)` in config.py — the pattern is necessary here because mutable dict defaults in Pydantic require a factory to avoid shared-state bugs.

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v`
Expected: All PASS (tests updated in previous tasks)

- [ ] **Step 3: Do NOT commit yet** — continue to next task.

---

### Task 5: Update Prompt Template

**Files:**
- Modify: `backend/app/prompts/signal_analysis.txt`

- [ ] **Step 1: Replace prompt template**

Write the following to `backend/app/prompts/signal_analysis.txt`:

```
You are a crypto futures trading analyst. Analyze the following data for {pair} on the {timeframe} timeframe.

## Technical Indicators
{indicators}

## Order Flow Metrics
{order_flow}

## Pattern Detection
{patterns}

## On-Chain Data
{onchain}

## ML Model Prediction
{ml_context}

## Recent News Context
{news}

## Current Assessment
Preliminary Indicator Score: {preliminary_score} (Direction: {direction})
Blended Score (with ML): {blended_score}
Indicator-ML Agreement: {agreement}

## Recent Price Action (last 20 candles)
{candles}

## Instructions
The quantitative signals already flagged a {direction} setup. Your job is to identify specific factors that support or undermine this trade.

Analyze the data and return 1-5 factors from the following types:

**Structure factors:**
- "support_proximity" — Price near a key support level (from recent candle lows/rejections)
- "resistance_proximity" — Price near a key resistance level (from recent candle highs/rejections)
- "level_breakout" — Price breaking through a key support/resistance level
- "htf_alignment" — Higher-timeframe trend confirms or conflicts with this setup

**Momentum factors:**
- "rsi_divergence" — RSI diverging from price (higher lows in RSI vs lower lows in price, or vice versa)
- "volume_divergence" — Volume diverging from price (declining volume on price advance, etc.)
- "macd_divergence" — MACD diverging from price direction

**Exhaustion factors:**
- "volume_exhaustion" — Volume drying up, move losing steam
- "funding_extreme" — Funding rate at extreme levels
- "crowded_positioning" — Long/short ratio heavily skewed

**Event factors:**
- "pattern_confirmation" — Candlestick pattern supports or invalidates the direction
- "news_catalyst" — News event supports or undermines the thesis

For each factor, provide:
- "type": one of the types listed above
- "direction": "bullish" or "bearish"
- "strength": 1 (weak/suggestive evidence), 2 (clear evidence in the data), 3 (strong/multiple confirming signals)
- "reason": one sentence explaining what you see in the data

Also provide:
- "explanation": 2-3 sentence overall analysis
- "levels": object with "entry", "stop_loss", "take_profit_1", "take_profit_2" as numbers. Base these on the price action, support/resistance from the candles, and ATR. Do NOT just copy the current price +/- a fixed offset.

Only report factors you actually see evidence for in the data. Do not invent factors. If you see no clear factors against the trade, report supporting factors only.

Respond ONLY with the JSON object, no other text.

Example response format:
{{"factors": [{{"type": "rsi_divergence", "direction": "bullish", "strength": 2, "reason": "RSI making higher lows while price makes lower lows on last 5 candles"}}, {{"type": "funding_extreme", "direction": "bearish", "strength": 1, "reason": "Funding slightly elevated but not extreme"}}], "explanation": "Bullish divergence forming but funding headwind limits conviction.", "levels": {{"entry": 67000, "stop_loss": 66200, "take_profit_1": 67800, "take_profit_2": 68600}}}}
```

- [ ] **Step 2: Verify prompt template renders without errors**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_llm.py::test_render_prompt -v`
Expected: PASS (template still uses same placeholders)

- [ ] **Step 3: Do NOT commit yet** — continue to next task.

---

### Task 6: DB Migration — Signal Model Changes

**Files:**
- Modify: `backend/app/db/models.py`
- Create: Alembic migration

- [ ] **Step 1: Update Signal model**

In `backend/app/db/models.py`, update the `Signal` class:

1. Remove these two lines:
```python
    llm_opinion: Mapped[str | None] = mapped_column(String(16))
    llm_confidence: Mapped[str | None] = mapped_column(String(8))
```

2. Add after the `explanation` column:
```python
    llm_factors: Mapped[list | None] = mapped_column(JSONB)
```

- [ ] **Step 2: Generate Alembic migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "replace llm_opinion and llm_confidence with llm_factors"`

- [ ] **Step 3: Review migration and preserve historical data**

Read the generated migration file in `backend/app/db/migrations/versions/`. Verify it:
- Adds `llm_factors` column (JSONB, nullable)
- Drops `llm_opinion` column
- Drops `llm_confidence` column

Edit the generated migration's `upgrade()` function to copy old opinion/confidence data into `raw_indicators` JSONB before dropping columns. Add this SQL **before** the column drops:

```python
    # preserve historical LLM opinion/confidence in raw_indicators before dropping columns
    op.execute("""
        UPDATE signals
        SET raw_indicators = COALESCE(raw_indicators, '{}'::jsonb)
            || jsonb_build_object(
                'legacy_llm_opinion', llm_opinion,
                'legacy_llm_confidence', llm_confidence
            )
        WHERE llm_opinion IS NOT NULL OR llm_confidence IS NOT NULL
    """)
```

This ensures historical signal data is not permanently lost. The `legacy_` prefix makes it clear these are archived values.

- [ ] **Step 4: Run migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head`
Expected: Migration applies successfully

- [ ] **Step 5: Do NOT commit yet** — continue to next task.

---

### Task 7: Pipeline Integration — main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Update imports**

At the top of `main.py`, update the combiner import (line 33):

```python
from app.engine.combiner import compute_preliminary_score, compute_llm_contribution, compute_final_score, calculate_levels, blend_with_ml, compute_agreement, scale_atr_multipliers
```

- [ ] **Step 2: Update Step 5 (LLM gate) — lines ~482-524**

Replace the LLM gate section. The `call_openrouter` now returns `LLMResult | None`:

```python
    # ── Step 5: LLM gate (on blended score) ──
    llm_result = None
    if abs(blended) >= settings.engine_llm_threshold and prompt_template:
        direction_label = "LONG" if blended > 0 else "SHORT"

        if ml_available and ml_prediction:
            ml_context = (
                f"Direction: {ml_prediction['direction']}, "
                f"Confidence: {ml_confidence:.2f}, "
                f"Suggested SL: {ml_prediction['sl_atr']:.2f}x ATR, "
                f"TP1: {ml_prediction['tp1_atr']:.2f}x ATR, "
                f"TP2: {ml_prediction['tp2_atr']:.2f}x ATR"
            )
        else:
            ml_context = "ML model not available for this pair."

        try:
            rendered = render_prompt(
                template=prompt_template,
                pair=pair, timeframe=timeframe,
                indicators=json.dumps(tech_result["indicators"], indent=2),
                order_flow=json.dumps(flow_result["details"], indent=2),
                patterns=json.dumps(detected_patterns, indent=2) if detected_patterns else "No patterns detected.",
                onchain=f"Score: {onchain_score}" if onchain_available else "On-chain data not available.",
                ml_context=ml_context, news=news_context,
                preliminary_score=str(indicator_preliminary),
                direction=direction_label,
                blended_score=str(blended),
                agreement=agreement,
                candles=json.dumps(candles_data[-20:], indent=2),
            )
            llm_result = await call_openrouter(
                prompt=rendered,
                api_key=settings.openrouter_api_key,
                model=settings.openrouter_model,
                timeout=settings.engine_llm_timeout_seconds,
            )
        except Exception as e:
            logger.error(f"LLM call failed for {pair}:{timeframe}: {e}")
```

- [ ] **Step 3: Update Step 6 (compute final score) — lines ~525-529**

```python
    # ── Step 6: Compute final score ──
    llm_contribution = 0
    if llm_result:
        direction_label = "LONG" if blended > 0 else "SHORT"
        llm_contribution = compute_llm_contribution(
            llm_result.response.factors,
            direction_label,
            settings.llm_factor_weights,
            settings.llm_factor_total_cap,
        )
    final = compute_final_score(blended, llm_contribution)
    direction = "LONG" if final > 0 else "SHORT"
```

- [ ] **Step 4: Update Step 7 (logging) — line ~534-544**

Update the `_log_pipeline_evaluation` call. Replace `llm_opinion=llm_opinion` with `llm_contribution=llm_contribution`. Update the `_log_pipeline_evaluation` function signature and body similarly — replace the `llm_opinion` parameter with `llm_contribution`.

In the function definition (~line 648):

```python
def _log_pipeline_evaluation(
    *, pair, timeframe, tech_score, flow_score, onchain_score,
    pattern_score, ml_score, ml_confidence, indicator_preliminary,
    blended_score, final_score, llm_contribution, ml_available, agreement, emitted,
):
```

And in the log_data dict, replace `"llm_opinion": llm_opinion` with `"llm_contribution": llm_contribution`.

- [ ] **Step 5: Update Step 8 (levels calculation) — lines ~567-600**

Replace the LLM levels extraction. Do NOT guard on `llm_contribution >= 0` here — that check lives inside `calculate_levels()` as part of the cascade. Extracting levels unconditionally keeps the policy in one place:

```python
    llm_levels = None
    if llm_result and llm_result.response.levels:
        llm_levels = llm_result.response.levels.model_dump()
```

Update `calculate_levels` call — remove `llm_opinion` and `caution_sl_factor` params, add `llm_contribution`:

```python
    levels = calculate_levels(
        direction=direction,
        current_price=float(candle["close"]),
        atr=atr,
        llm_levels=llm_levels,
        ml_atr_multiples=ml_atr_multiples,
        llm_contribution=llm_contribution,
        sl_bounds=(settings.ml_sl_min_atr, settings.ml_sl_max_atr),
        tp1_min_atr=settings.ml_tp1_min_atr,
        tp2_max_atr=settings.ml_tp2_max_atr,
        rr_floor=settings.ml_rr_floor,
        sl_atr_default=scaled["sl_atr"],
        tp1_atr_default=scaled["tp1_atr"],
        tp2_atr_default=scaled["tp2_atr"],
    )
```

- [ ] **Step 6: Update signal_data dict — lines ~602-643**

Replace the LLM fields in `signal_data`:

```python
    signal_data = {
        "pair": pair,
        "timeframe": timeframe,
        "direction": direction,
        "final_score": final,
        "traditional_score": tech_result["score"],
        "explanation": llm_result.response.explanation if llm_result else None,
        "llm_factors": [f.model_dump() for f in llm_result.response.factors] if llm_result else None,
        **levels,
        "raw_indicators": {
            **tech_result["indicators"],
            "ml_score": ml_score,
            "ml_confidence": ml_confidence,
            "blended_score": blended,
            "indicator_preliminary": indicator_preliminary,
            "effective_sl_atr": scaled["sl_atr"],
            "effective_tp1_atr": scaled["tp1_atr"],
            "effective_tp2_atr": scaled["tp2_atr"],
            "sl_strength_factor": scaled["sl_strength_factor"],
            "tp_strength_factor": scaled["tp_strength_factor"],
            "vol_factor": scaled["vol_factor"],
            "levels_source": levels["levels_source"],
            "confluence_score": confluence_score,
            "parent_tf": parent_tf,
            "parent_adx": parent_indicators["adx"] if parent_indicators else None,
            "parent_di_plus": parent_indicators["di_plus"] if parent_indicators else None,
            "parent_di_minus": parent_indicators["di_minus"] if parent_indicators else None,
            "regime_trending": tech_result["indicators"].get("regime_trending"),
            "regime_ranging": tech_result["indicators"].get("regime_ranging"),
            "regime_volatile": tech_result["indicators"].get("regime_volatile"),
            "effective_caps": {k: round(v, 2) for k, v in tech_result["caps"].items()} if regime else None,
            "effective_outer_weights": {k: round(v, 4) for k, v in outer.items()} if regime else None,
            "flow_contrarian_mult": flow_result["details"].get("contrarian_mult"),
            "flow_roc_boost": flow_result["details"].get("roc_boost"),
            "flow_final_mult": flow_result["details"].get("final_mult"),
            "flow_funding_roc": flow_result["details"].get("funding_roc"),
            "flow_ls_roc": flow_result["details"].get("ls_roc"),
            "flow_max_roc": flow_result["details"].get("max_roc"),
            "llm_contribution": llm_contribution,
            "llm_prompt_tokens": llm_result.prompt_tokens if llm_result else None,
            "llm_completion_tokens": llm_result.completion_tokens if llm_result else None,
            "llm_model": llm_result.model if llm_result else None,
        },
        "detected_patterns": detected_patterns or None,
    }
```

Note: `llm_opinion` and `llm_confidence` keys are removed. `llm_factors` is added at top level. Token usage fields are added to `raw_indicators`.

- [ ] **Step 7: Update `persist_signal` — lines ~114-140**

Replace the `llm_opinion` and `llm_confidence` lines with `llm_factors`:

```python
async def persist_signal(db: Database, signal_data: dict):
    try:
        async with db.session_factory() as session:
            row = Signal(
                pair=signal_data["pair"],
                timeframe=signal_data["timeframe"],
                direction=signal_data["direction"],
                final_score=signal_data["final_score"],
                traditional_score=signal_data["traditional_score"],
                explanation=signal_data.get("explanation"),
                llm_factors=signal_data.get("llm_factors"),
                entry=signal_data["entry"],
                stop_loss=signal_data["stop_loss"],
                take_profit_1=signal_data["take_profit_1"],
                take_profit_2=signal_data["take_profit_2"],
                raw_indicators=signal_data.get("raw_indicators"),
                risk_metrics=signal_data.get("risk_metrics"),
                detected_patterns=signal_data.get("detected_patterns"),
                correlated_news_ids=signal_data.get("correlated_news_ids"),
            )
            session.add(row)
            await session.commit()
            signal_data["id"] = row.id
    except Exception as e:
        logger.error(f"Failed to persist signal {signal_data['pair']}: {e}")
```

- [ ] **Step 8: Do NOT commit yet** — continue to next task.

---

### Task 8: API Routes — Signal Serializer

**Files:**
- Modify: `backend/app/api/routes.py`

- [ ] **Step 1: Update `_signal_to_dict` — lines 24-51**

Replace the function:

```python
def _signal_to_dict(signal: Signal) -> dict:
    return {
        "id": signal.id,
        "pair": signal.pair,
        "timeframe": signal.timeframe,
        "direction": signal.direction,
        "final_score": signal.final_score,
        "traditional_score": signal.traditional_score,
        "llm_factors": signal.llm_factors,
        "llm_contribution": (signal.raw_indicators or {}).get("llm_contribution"),
        "explanation": signal.explanation,
        "levels": {
            "entry": float(signal.entry),
            "stop_loss": float(signal.stop_loss),
            "take_profit_1": float(signal.take_profit_1),
            "take_profit_2": float(signal.take_profit_2),
        },
        "outcome": signal.outcome,
        "outcome_pnl_pct": float(signal.outcome_pnl_pct) if signal.outcome_pnl_pct else None,
        "outcome_duration_minutes": signal.outcome_duration_minutes,
        "outcome_at": signal.outcome_at.isoformat() if signal.outcome_at else None,
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
        "user_note": signal.user_note,
        "user_status": signal.user_status,
        "risk_metrics": signal.risk_metrics,
        "detected_patterns": signal.detected_patterns,
        "correlated_news_ids": signal.correlated_news_ids,
    }
```

- [ ] **Step 2: Update `test_signal` endpoint — lines ~519-535**

Update the signal_data in the test-signal endpoint to remove `llm_opinion`/`llm_confidence`:

```python
        signal_data = {
            "pair": pair,
            "timeframe": timeframe,
            "direction": direction,
            "final_score": final,
            "traditional_score": tech["score"],
            "explanation": None,
            "llm_factors": None,
            **levels,
            "raw_indicators": tech["indicators"],
        }
```

Also update the combiner import at the top of routes.py (line 14-18) — remove `compute_final_score` if it's still imported (check if test_signal uses it; it does at line 514). Keep it imported since test_signal calls `compute_final_score(prelim, 0)`:

```python
from app.engine.combiner import (
    calculate_levels,
    compute_final_score,
    compute_preliminary_score,
)
```

Update the score computation at line 514 — change from:
```python
final = compute_final_score(prelim, None)
```
to:
```python
final = compute_final_score(prelim, 0)
```
The second argument is now `llm_contribution: int`, not `llm_response: LLMResponse | None`.

- [ ] **Step 3: Do NOT commit yet** — continue to next task.

---

### Task 9: Update Remaining Test Files

**Files:**
- Modify: `backend/tests/test_db_models.py`
- Modify: `backend/tests/test_pipeline.py`
- Modify: `backend/tests/api/test_journal.py`
- Modify: `backend/tests/test_pipeline_ml.py`

These test files reference the old `llm_opinion`/`llm_confidence` system and will break after the changes in Tasks 1-8.

- [ ] **Step 1: Update test_db_models.py**

In `backend/tests/test_db_models.py`, update the `test_signal_model` function (line 23). Remove the two old fields and add the new one:

```python
def test_signal_model():
    signal = Signal(
        pair="BTC-USDT-SWAP",
        timeframe="15m",
        direction="LONG",
        final_score=78,
        traditional_score=72,
        llm_factors=[{"type": "rsi_divergence", "direction": "bullish", "strength": 2, "reason": "RSI higher lows"}],
        explanation="Strong bullish setup.",
        entry=Decimal("67420"),
        stop_loss=Decimal("66890"),
        take_profit_1=Decimal("67950"),
        take_profit_2=Decimal("68480"),
        raw_indicators={"rsi": 32, "ema_9": 67100},
    )
    assert signal.direction == "LONG"
    assert signal.final_score == 78
    assert signal.raw_indicators["rsi"] == 32
```

- [ ] **Step 2: Update test_pipeline.py**

In `backend/tests/test_pipeline.py`:

1. Update imports (lines 4-5) — remove `compute_final_score` and `parse_llm_response`:

```python
from app.engine.combiner import compute_preliminary_score, compute_final_score, calculate_levels
```

Remove line 5 entirely (`from app.engine.llm import parse_llm_response`).

2. Replace `test_full_pipeline_produces_signal` (lines 23-55). Remove the LLM JSON parsing block and use the new `compute_final_score(blended, llm_contribution)` signature:

```python
def test_full_pipeline_produces_signal():
    """End-to-end: candles + order flow -> preliminary score -> final score -> signal levels."""
    candles_data = _make_candles()
    df = pd.DataFrame(candles_data)

    tech_result = compute_technical_score(df)
    assert -100 <= tech_result["score"] <= 100

    flow_metrics = {
        "funding_rate": 0.0001,
        "open_interest_change_pct": 0.02,
        "long_short_ratio": 1.1,
    }
    flow_result = compute_order_flow_score(flow_metrics)
    assert -100 <= flow_result["score"] <= 100

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])

    # Simulate a positive LLM contribution (e.g., from factor scoring)
    final = compute_final_score(preliminary, 14)
    assert -100 <= final <= 100
    assert final > preliminary

    direction = "LONG" if final > 0 else "SHORT"
    atr = tech_result["indicators"]["atr"]
    levels = calculate_levels(direction, candles_data[-1]["close"], atr, llm_levels=None)
    assert "entry" in levels
    assert "stop_loss" in levels
    assert "take_profit_1" in levels
    assert "take_profit_2" in levels
```

3. Update `test_pipeline_without_llm` (line 67) — change `compute_final_score` call:

```python
    final = compute_final_score(preliminary, 0)
    assert final == preliminary
```

- [ ] **Step 3: Update test_journal.py**

In `backend/tests/api/test_journal.py`, update the `_make_signal` defaults dict (lines 16-38). Remove `llm_opinion` and `llm_confidence`, add `llm_factors`:

```python
    defaults = {
        "id": 1,
        "pair": "BTC-USDT-SWAP",
        "timeframe": "1h",
        "direction": "LONG",
        "final_score": 65,
        "traditional_score": 60,
        "llm_factors": [{"type": "rsi_divergence", "direction": "bullish", "strength": 2, "reason": "test"}],
        "explanation": "Test signal",
        "entry": Decimal("50000"),
        "stop_loss": Decimal("49000"),
        "take_profit_1": Decimal("51000"),
        "take_profit_2": Decimal("52000"),
        "raw_indicators": {},
        "created_at": now,
        "outcome": "TP1_HIT",
        "outcome_at": now + timedelta(hours=2),
        "outcome_pnl_pct": Decimal("2.0"),
        "outcome_duration_minutes": 120,
        "user_note": None,
        "user_status": "OBSERVED",
    }
```

- [ ] **Step 4: Update test_pipeline_ml.py**

In `backend/tests/test_pipeline_ml.py`:

1. Remove `settings.llm_caution_sl_factor = 0.8` from `_make_mock_app` (line 42).

2. Add LLM factor config settings to `_make_mock_app` after the ML settings block:

```python
    settings.llm_factor_weights = {
        "support_proximity": 6.0, "resistance_proximity": 6.0,
        "level_breakout": 8.0, "htf_alignment": 7.0,
        "rsi_divergence": 7.0, "volume_divergence": 6.0,
        "macd_divergence": 6.0, "volume_exhaustion": 5.0,
        "funding_extreme": 5.0, "crowded_positioning": 5.0,
        "pattern_confirmation": 5.0, "news_catalyst": 7.0,
    }
    settings.llm_factor_total_cap = 35.0
```

3. Replace `test_contradict_penalizes_but_does_not_veto` (lines 152-182). The test now uses `LLMResult` with factor-based response instead of `LLMResponse` with opinion/confidence:

```python
    @pytest.mark.asyncio
    async def test_opposing_factors_penalize_but_do_not_veto(self):
        """Pipeline still emits when LLM factors oppose a strong signal — penalty reduces score but threshold check decides."""
        from app.engine.models import LLMResponse, LLMResult

        app = _make_mock_app(prompt_template="fake template")
        app.state.settings.engine_signal_threshold = 10
        app.state.settings.engine_llm_threshold = 5

        llm_result = LLMResult(
            response=LLMResponse(
                factors=[
                    {"type": "resistance_proximity", "direction": "bearish", "strength": 3, "reason": "Price at major resistance"},
                    {"type": "volume_exhaustion", "direction": "bearish", "strength": 2, "reason": "Volume declining"},
                ],
                explanation="Clear reversal signal",
                levels=None,
            ),
            prompt_tokens=800,
            completion_tokens=150,
            model="test-model",
        )

        strong_tech = {"score": 100, "indicators": {
            "atr": 200, "bb_width_pct": 50.0, "adx": 30, "di_plus": 25,
            "di_minus": 15, "rsi": 35, "bb_upper": 68000, "bb_lower": 67000,
            "bb_pos": 0.8, "obv_slope": 0.5, "vol_ratio": 1.5,
        }, "regime": {"trending": 0.5, "ranging": 0.3, "volatile": 0.2}, "caps": {"trend_cap": 30.0, "mean_rev_cap": 22.0, "squeeze_cap": 25.0, "volume_cap": 21.5}}

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist, \
             patch("app.main.call_openrouter", new_callable=AsyncMock, return_value=llm_result), \
             patch("app.main.render_prompt", return_value="rendered"), \
             patch("app.main.compute_technical_score", return_value=strong_tech):
            await run_pipeline(app, CANDLE)
            assert mock_persist.called, "Opposing factors should penalize, not veto — signal should still emit"
            signal_data = mock_persist.call_args[0][1]
            assert abs(signal_data["final_score"]) >= 10, "Penalized score should still exceed threshold"
```

4. Replace `test_caution_still_emits` (lines 184-201) with a factor-based equivalent:

```python
    @pytest.mark.asyncio
    async def test_weak_opposing_factors_still_emits(self):
        """Pipeline can still emit with weak opposing factors — they just dampen score."""
        from app.engine.models import LLMResponse, LLMResult

        app = _make_mock_app(prompt_template="fake template")
        app.state.settings.engine_signal_threshold = 10

        llm_result = LLMResult(
            response=LLMResponse(
                factors=[
                    {"type": "funding_extreme", "direction": "bearish", "strength": 1, "reason": "Funding slightly elevated"},
                ],
                explanation="Some minor concern",
                levels=None,
            ),
            prompt_tokens=600,
            completion_tokens=100,
            model="test-model",
        )

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist, \
             patch("app.main.call_openrouter", new_callable=AsyncMock, return_value=llm_result), \
             patch("app.main.render_prompt", return_value="rendered"):
            await run_pipeline(app, CANDLE)
            # May or may not emit depending on indicator score, but shouldn't crash
```

- [ ] **Step 5: Run all tests to verify**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Do NOT commit yet** — continue to next task.

---

### Task 10: Frontend — TypeScript Types and Signal Detail

**Files:**
- Modify: `web/src/features/signals/types.ts`
- Modify: `web/src/features/signals/components/SignalDetail.tsx`
- Modify: `web/src/features/signals/store.test.ts`

- [ ] **Step 1: Update TypeScript types**

In `web/src/features/signals/types.ts`:

1. Remove `Confidence` and `LlmOpinion` type aliases (lines 2-3)
2. Add `LLMFactor` interface and `FactorType` after the `DetectedPattern` interface:

```typescript
export type FactorDirection = "bullish" | "bearish";

export interface LLMFactor {
  type: string;
  direction: FactorDirection;
  strength: 1 | 2 | 3;
  reason: string;
}
```

3. Update the `Signal` interface — remove `confidence` and `llm_opinion`, add `llm_factors` and `llm_contribution`:

```typescript
export interface Signal {
  id: number;
  pair: string;
  timeframe: Timeframe;
  direction: Direction;
  final_score: number;
  traditional_score: number;
  llm_factors: LLMFactor[] | null;
  llm_contribution: number | null;
  explanation: string | null;
  levels: SignalLevels;
  outcome: SignalOutcome;
  outcome_pnl_pct: number | null;
  outcome_duration_minutes: number | null;
  outcome_at: string | null;
  created_at: string;
  user_note: string | null;
  user_status: UserStatus;
  risk_metrics: RiskMetrics | null;
  detected_patterns: DetectedPattern[] | null;
  correlated_news_ids: number[] | null;
}
```

- [ ] **Step 2: Update SignalDetail component**

In `web/src/features/signals/components/SignalDetail.tsx`, replace the Score Breakdown section (lines 49-59):

```tsx
      <div className="p-4 border-b border-border">
        <h3 className="text-sm text-muted mb-2">Score Breakdown</h3>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            Traditional: <span className="font-mono">{formatScore(signal.traditional_score)}</span>
          </div>
          <div>
            LLM: <span className="font-mono">{signal.llm_contribution != null ? (signal.llm_contribution >= 0 ? "+" : "") + signal.llm_contribution : "N/A"}</span>
          </div>
        </div>
        {signal.llm_factors && signal.llm_factors.length > 0 && (
          <div className="mt-2 space-y-1">
            {signal.llm_factors.map((f, i) => (
              <div key={i} className="flex items-center gap-2 text-xs" title={f.reason}>
                <span className={f.direction === "bullish" ? "text-long" : "text-short"}>
                  {f.direction === "bullish" ? "+" : "-"}
                </span>
                <span className="text-muted">{f.type.replace(/_/g, " ")}</span>
                <span className="font-mono">{"*".repeat(f.strength)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
```

- [ ] **Step 3: Update store test fixture**

In `web/src/features/signals/store.test.ts`, update `createSignal`:

```typescript
function createSignal(overrides: Partial<Signal> = {}): Signal {
  return {
    id: 1,
    pair: "BTC-USDT-SWAP",
    timeframe: "1h",
    direction: "LONG",
    final_score: 75,
    traditional_score: 70,
    llm_factors: [{ type: "rsi_divergence", direction: "bullish", strength: 2, reason: "RSI higher lows" }],
    llm_contribution: 14,
    explanation: "Strong trend",
    levels: { entry: 85000, stop_loss: 84000, take_profit_1: 87000, take_profit_2: 89000 },
    outcome: "PENDING",
    outcome_pnl_pct: null,
    outcome_duration_minutes: null,
    outcome_at: null,
    user_note: null,
    user_status: "OBSERVED",
    risk_metrics: null,
    detected_patterns: null,
    correlated_news_ids: null,
    created_at: "2026-02-27T12:00:00Z",
    ...overrides,
  };
}
```

- [ ] **Step 4: Run frontend build and tests**

Run: `cd web && pnpm build && pnpm test`
Expected: Build succeeds, tests pass

- [ ] **Step 5: Do NOT commit yet** — continue to next task.

---

### Task 11: Final Verification — Run Full Test Suite

- [ ] **Step 1: Run all backend tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Run frontend build and tests**

Run: `cd web && pnpm build && pnpm test`
Expected: Build succeeds, tests pass

- [ ] **Step 3: Update signal-algorithm-improvements.md**

In `docs/signal-algorithm-improvements.md`:

1. Update item #3 status from "Not started" to "Implemented"
2. Update item #5 status from "Not started" to "Implemented — see `docs/superpowers/specs/2026-03-18-structured-llm-factors-design.md`"

- [ ] **Step 4: Single commit for entire feature**

Stage all changed files and commit once (per project CLAUDE.md git policy — no incremental commits):

```bash
git add backend/app/engine/models.py backend/app/engine/llm.py backend/app/engine/combiner.py \
  backend/app/config.py backend/app/prompts/signal_analysis.txt backend/app/db/models.py \
  backend/app/db/migrations/versions/ backend/app/main.py backend/app/api/routes.py \
  backend/tests/engine/test_models.py backend/tests/engine/test_combiner.py backend/tests/engine/test_llm.py \
  backend/tests/test_db_models.py backend/tests/test_pipeline.py backend/tests/api/test_journal.py \
  backend/tests/test_pipeline_ml.py \
  web/src/features/signals/types.ts web/src/features/signals/components/SignalDetail.tsx \
  web/src/features/signals/store.test.ts docs/signal-algorithm-improvements.md
git commit -m "feat(engine): replace LLM opinion/confidence with structured factor scoring"
```
