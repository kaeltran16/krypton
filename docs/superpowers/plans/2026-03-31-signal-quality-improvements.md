# Signal Quality Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve signal scoring quality with three independent changes: exponentially weighted IC pruning, LLM dual-pass consistency hardening, and joint Bayesian ATR optimization.

**Architecture:** EW IC pruning replaces the 30-day consecutive counter in `optimizer.py` with an exponentially weighted moving average (~10-day half-life). LLM dual-pass adds concurrent devil's advocate calls via `asyncio.gather` with aggregation logic and reduces the contribution cap from 35 to 25. Bayesian ATR replaces sequential 1D sweeps with a GP-based 3D optimization using `scikit-optimize`.

**Tech Stack:** Python 3.11, scikit-optimize (new), FastAPI, SQLAlchemy 2.0, asyncio, Alembic, pytest

**Spec:** `docs/superpowers/specs/2026-03-31-signal-quality-improvements-design.md`

**Run tests with:** `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest <path> -v`

**Commit once** at the end of all tasks (per project convention).

---

### Task 1: Exponentially Weighted IC Pruning

**Files:**
- Modify: `backend/app/engine/optimizer.py:522-582` (pruning functions)
- Modify: `backend/app/engine/optimizer.py:585-662` (`run_ic_pruning_cycle`)
- Modify: `backend/app/engine/constants.py:177` (remove `IC_MIN_DAYS`)
- Modify: `backend/tests/engine/test_optimizer.py` (add IC pruning tests)

- [x] **Step 1: Write tests for `compute_ew_ic` and updated pruning functions**

Add to `backend/tests/engine/test_optimizer.py`:

```python
from app.engine.optimizer import (
    compute_ew_ic,
    should_prune_source,
    should_reenable_source,
    IC_PRUNE_THRESHOLD,
    IC_REENABLE_THRESHOLD,
)


# -- compute_ew_ic tests --


def test_compute_ew_ic_empty():
    assert compute_ew_ic([]) == 0.0


def test_compute_ew_ic_single_value():
    assert compute_ew_ic([0.3]) == 0.3


def test_compute_ew_ic_short_history():
    """With < 3 values, returns simple mean."""
    assert compute_ew_ic([0.1, 0.2]) == pytest.approx(0.15)


def test_compute_ew_ic_normal():
    """Hand-calculated: init=mean(0.1,0.2,0.3)=0.2, then EW over 0.4, 0.5."""
    # i=3: 0.1*0.4 + 0.9*0.2 = 0.22
    # i=4: 0.1*0.5 + 0.9*0.22 = 0.248
    result = compute_ew_ic([0.1, 0.2, 0.3, 0.4, 0.5])
    assert result == pytest.approx(0.248)


def test_compute_ew_ic_negative_trend():
    """All negative ICs produce strongly negative EW-IC."""
    result = compute_ew_ic([-0.1, -0.08, -0.12, -0.09, -0.11])
    # init = mean(-0.1, -0.08, -0.12) = -0.1
    # i=3: 0.1*(-0.09) + 0.9*(-0.1) = -0.099
    # i=4: 0.1*(-0.11) + 0.9*(-0.099) = -0.1001
    assert result == pytest.approx(-0.1001)


def test_compute_ew_ic_exactly_three_values():
    """With exactly 3 values, returns their mean (no EW iteration)."""
    assert compute_ew_ic([0.1, 0.2, 0.3]) == pytest.approx(0.2)


# -- should_prune_source tests --


def test_should_prune_excluded_source():
    """tech and liquidation are never pruned regardless of IC."""
    bad_history = [-0.2] * 10
    assert should_prune_source("tech", bad_history) is False
    assert should_prune_source("liquidation", bad_history) is False


def test_should_prune_insufficient_data():
    """Less than 5 days of history should not trigger pruning."""
    assert should_prune_source("order_flow", [-0.2, -0.3, -0.1, -0.2]) is False


def test_should_prune_positive_ew_ic():
    """Source with positive EW-IC should not be pruned."""
    history = [0.1, 0.15, 0.2, 0.1, 0.12]
    assert should_prune_source("order_flow", history) is False


def test_should_prune_negative_ew_ic():
    """Source with EW-IC below threshold should be pruned."""
    history = [-0.1, -0.08, -0.12, -0.09, -0.11]
    assert compute_ew_ic(history) < IC_PRUNE_THRESHOLD
    assert should_prune_source("order_flow", history) is True


def test_should_prune_borderline():
    """Source with EW-IC exactly at threshold should not be pruned (< not <=)."""
    # Construct history where EW-IC ≈ -0.05
    history = [-0.05, -0.05, -0.05, -0.05, -0.05]
    assert compute_ew_ic(history) == pytest.approx(-0.05)
    assert should_prune_source("order_flow", history) is False


# -- should_reenable_source tests --


def test_should_reenable_insufficient_data():
    """Less than 5 days of history should not trigger re-enable."""
    assert should_reenable_source([0.1, 0.2, 0.3]) is False


def test_should_reenable_positive_ew_ic():
    """Source with EW-IC above 0 should be re-enabled."""
    history = [-0.1, -0.05, 0.0, 0.05, 0.1]
    assert compute_ew_ic(history) > IC_REENABLE_THRESHOLD
    assert should_reenable_source(history) is True


def test_should_reenable_still_negative():
    """Source with negative EW-IC should not be re-enabled."""
    history = [-0.2, -0.15, -0.1, -0.12, -0.08]
    assert compute_ew_ic(history) < IC_REENABLE_THRESHOLD
    assert should_reenable_source(history) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py -k "test_compute_ew_ic or test_should_prune or test_should_reenable" -v`

Expected: FAIL — `compute_ew_ic` not importable.

- [ ] **Step 3: Implement `compute_ew_ic` in optimizer.py**

Add after `IC_PRUNE_EXCLUDED_SOURCES` (line 524) in `backend/app/engine/optimizer.py`:

```python
EW_IC_LOOKBACK_DAYS = 90


def compute_ew_ic(ic_history: list[float], alpha: float = 0.1) -> float:
    """Compute exponentially weighted IC from daily IC history.

    Initializes with mean of first 3 values to avoid first-value bias.
    Alpha=0.1 gives ~10-day half-life.
    """
    if not ic_history:
        return 0.0
    if len(ic_history) < 3:
        return sum(ic_history) / len(ic_history)
    ew_ic = sum(ic_history[:3]) / 3
    for ic in ic_history[3:]:
        ew_ic = alpha * ic + (1 - alpha) * ew_ic
    return ew_ic
```

- [ ] **Step 4: Update `should_prune_source` to use EW-IC**

Replace the existing `should_prune_source` function (lines 540-552) in `backend/app/engine/optimizer.py`:

```python
def should_prune_source(
    source_name: str,
    ic_history: list[float],
    threshold: float = IC_PRUNE_THRESHOLD,
) -> bool:
    """Check if a source should be pruned based on EW-IC."""
    if source_name in IC_PRUNE_EXCLUDED_SOURCES:
        return False
    if len(ic_history) < 5:
        return False
    return compute_ew_ic(ic_history) < threshold
```

- [ ] **Step 5: Update `should_reenable_source` to use EW-IC**

Replace the existing `should_reenable_source` function (lines 555-559) in `backend/app/engine/optimizer.py`:

```python
def should_reenable_source(ic_history: list[float]) -> bool:
    """Check if a pruned source should be re-enabled based on EW-IC."""
    if len(ic_history) < 5:
        return False
    return compute_ew_ic(ic_history) > IC_REENABLE_THRESHOLD
```

- [ ] **Step 6: Update `get_pruned_sources` — remove `min_days` parameter**

Replace the existing `get_pruned_sources` function (lines 572-582) in `backend/app/engine/optimizer.py`:

```python
def get_pruned_sources(
    ic_histories: dict[str, list[float]],
    threshold: float = IC_PRUNE_THRESHOLD,
) -> set[str]:
    """Return set of source names that should be pruned based on EW-IC."""
    pruned = set()
    for source_name, history in ic_histories.items():
        if should_prune_source(source_name, history, threshold):
            pruned.add(source_name)
    return pruned
```

- [ ] **Step 7: Update `run_ic_pruning_cycle` — remove `IC_MIN_DAYS` usage**

In `backend/app/engine/optimizer.py`, in the `run_ic_pruning_cycle` function (lines 585-662):

1. Change the import line inside the function from:
   ```python
   from app.engine.constants import IC_WINDOW_DAYS, IC_MIN_DAYS
   ```
   to:
   ```python
   from app.engine.constants import IC_WINDOW_DAYS
   ```

2. Change the `SourceICHistory` query window from:
   ```python
   .where(SourceICHistory.date >= today - timedelta(days=IC_MIN_DAYS))
   ```
   to:
   ```python
   .where(SourceICHistory.date >= today - timedelta(days=EW_IC_LOOKBACK_DAYS))
   ```

3. Change the `get_pruned_sources` call from:
   ```python
   new_pruned = get_pruned_sources(ic_histories, min_days=IC_MIN_DAYS)
   ```
   to:
   ```python
   new_pruned = get_pruned_sources(ic_histories)
   ```

- [ ] **Step 8: Remove `IC_MIN_DAYS` from constants.py**

In `backend/app/engine/constants.py`, remove line 177:

```python
IC_MIN_DAYS = 30
```

Keep `IC_WINDOW_DAYS = 7` on line 176 (still used for daily IC computation).

- [ ] **Step 9: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py -k "test_compute_ew_ic or test_should_prune or test_should_reenable" -v`

Expected: All PASS.

Then run full optimizer tests to check nothing is broken:

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py -v`

Expected: All PASS.

---

### Task 2: LLM Cap Reduction + DB Migration

**Files:**
- Modify: `backend/app/config.py:132`
- Create: `backend/alembic/versions/<auto>_reduce_llm_factor_cap.py`

- [ ] **Step 1: Update default in config.py**

In `backend/app/config.py`, change line 132 from:

```python
llm_factor_total_cap: float = 35.0
```

to:

```python
llm_factor_total_cap: float = 25.0
```

- [ ] **Step 2: Create Alembic migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision -m "reduce llm factor total cap to 25"`

Then edit the generated migration file in `backend/alembic/versions/`. Replace the empty `upgrade()` and `downgrade()` bodies:

```python
def upgrade():
    op.execute(
        "UPDATE pipeline_settings "
        "SET llm_factor_total_cap = 25.0 "
        "WHERE llm_factor_total_cap = 35.0 OR llm_factor_total_cap IS NULL"
    )


def downgrade():
    op.execute(
        "UPDATE pipeline_settings "
        "SET llm_factor_total_cap = 35.0 "
        "WHERE llm_factor_total_cap = 25.0"
    )
```

- [ ] **Step 3: Run migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head`

Expected: Migration applies successfully.

---

### Task 3: Dual-Pass LLM Aggregation

**Files:**
- Modify: `backend/app/engine/combiner.py:157` (add `aggregate_dual_pass` after `compute_final_score`)
- Modify: `backend/tests/engine/test_combiner.py` (add aggregation tests)

- [ ] **Step 1: Write tests for `aggregate_dual_pass`**

Add to `backend/tests/engine/test_combiner.py`:

```python
from app.engine.combiner import aggregate_dual_pass


def test_aggregate_dual_pass_both_positive():
    """Both calls agree bullish — average the contributions."""
    result, agreed = aggregate_dual_pass(10, 8, 25.0)
    assert result == 9
    assert agreed is True


def test_aggregate_dual_pass_both_negative():
    """Both calls agree bearish — average the contributions."""
    result, agreed = aggregate_dual_pass(-12, -8, 25.0)
    assert result == -10
    assert agreed is True


def test_aggregate_dual_pass_disagree_positive_standard():
    """Standard bullish, devil's advocate bearish — small positive."""
    result, agreed = aggregate_dual_pass(12, -6, 25.0)
    # magnitude = min(12, 6) / 2 = 3.0, sign = +1
    assert result == 3
    assert agreed is False


def test_aggregate_dual_pass_disagree_negative_standard():
    """Standard bearish, devil's advocate bullish — small negative."""
    result, agreed = aggregate_dual_pass(-15, 8, 25.0)
    # magnitude = min(15, 8) / 2 = 4.0, sign = -1
    assert result == -4
    assert agreed is False


def test_aggregate_dual_pass_capped():
    """Agreed contributions exceeding cap are clamped."""
    result, agreed = aggregate_dual_pass(30, 30, 25.0)
    assert result == 25
    assert agreed is True


def test_aggregate_dual_pass_negative_capped():
    """Agreed negative contributions exceeding cap are clamped."""
    result, agreed = aggregate_dual_pass(-30, -30, 25.0)
    assert result == -25
    assert agreed is True


def test_aggregate_dual_pass_zero_standard():
    """Zero standard contribution counts as agreement."""
    result, agreed = aggregate_dual_pass(0, 5, 25.0)
    assert agreed is True
    assert result == 2  # round((0+5)/2) with banker's rounding


def test_aggregate_dual_pass_both_zero():
    """Both zero — trivial agreement."""
    result, agreed = aggregate_dual_pass(0, 0, 25.0)
    assert result == 0
    assert agreed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -k "test_aggregate_dual_pass" -v`

Expected: FAIL — `aggregate_dual_pass` not importable.

- [ ] **Step 3: Implement `aggregate_dual_pass`**

Add after `compute_final_score` (line 158) in `backend/app/engine/combiner.py`:

```python
def aggregate_dual_pass(
    contrib_a: int, contrib_b: int, cap: float,
) -> tuple[int, bool]:
    """Aggregate standard and devil's advocate LLM contributions.

    Returns (merged_contribution, agreed). Standard call direction is preferred
    on disagreement since it uses the primary analysis prompt.
    """
    agreed = (contrib_a >= 0) == (contrib_b >= 0) or contrib_a == 0 or contrib_b == 0

    if agreed:
        merged = round((contrib_a + contrib_b) / 2)
    else:
        magnitude = min(abs(contrib_a), abs(contrib_b)) / 2
        sign = 1 if contrib_a >= 0 else -1
        merged = round(sign * magnitude)

    return round(max(-cap, min(cap, merged))), agreed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -k "test_aggregate_dual_pass" -v`

Expected: All PASS.

---

### Task 4: Dual-Pass LLM Orchestration

**Files:**
- Modify: `backend/app/engine/llm.py` (add system prompt constant, add `system_prompt` param, add `call_openrouter_dual_pass`)
- Modify: `backend/tests/engine/test_llm.py` (add dual-pass tests)

- [ ] **Step 1: Write tests for `call_openrouter_dual_pass`**

Add to `backend/tests/engine/test_llm.py`:

```python
import asyncio
from unittest.mock import AsyncMock, patch

from app.engine.llm import (
    call_openrouter_dual_pass,
    SYSTEM_PROMPT,
    DEVILS_ADVOCATE_SYSTEM_PROMPT,
)


@pytest.mark.asyncio
async def test_call_openrouter_dual_pass_both_succeed():
    """Both standard and devil's advocate calls succeed."""
    mock_result = LLMResult(
        response=LLMResponse(
            factors=[LLMFactor(type="level_breakout", direction="bullish", strength=2, reason="test")],
            explanation="test",
        ),
        prompt_tokens=100,
        completion_tokens=50,
        model="test-model",
    )
    with patch("app.engine.llm.call_openrouter", new_callable=AsyncMock, return_value=mock_result) as mock_call:
        standard, devils = await call_openrouter_dual_pass("prompt", "key", "model")
        assert standard is not None
        assert devils is not None
        assert mock_call.call_count == 2
        # Verify different system prompts used
        calls = mock_call.call_args_list
        assert calls[0].kwargs["system_prompt"] == SYSTEM_PROMPT
        assert calls[1].kwargs["system_prompt"] == DEVILS_ADVOCATE_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_call_openrouter_dual_pass_standard_fails():
    """Standard call fails — both results reflect failure."""
    async def side_effect(prompt, api_key, model, timeout=30, system_prompt=SYSTEM_PROMPT):
        if system_prompt == SYSTEM_PROMPT:
            return None
        return LLMResult(
            response=LLMResponse(
                factors=[LLMFactor(type="level_breakout", direction="bearish", strength=1, reason="test")],
                explanation="test",
            ),
            prompt_tokens=100,
            completion_tokens=50,
            model="test-model",
        )

    with patch("app.engine.llm.call_openrouter", side_effect=side_effect):
        standard, devils = await call_openrouter_dual_pass("prompt", "key", "model")
        assert standard is None
        assert devils is not None


@pytest.mark.asyncio
async def test_call_openrouter_dual_pass_devils_fails():
    """Devil's advocate call fails — standard result still returned."""
    async def side_effect(prompt, api_key, model, timeout=30, system_prompt=SYSTEM_PROMPT):
        if system_prompt == DEVILS_ADVOCATE_SYSTEM_PROMPT:
            return None
        return LLMResult(
            response=LLMResponse(
                factors=[LLMFactor(type="level_breakout", direction="bullish", strength=2, reason="test")],
                explanation="test",
            ),
            prompt_tokens=100,
            completion_tokens=50,
            model="test-model",
        )

    with patch("app.engine.llm.call_openrouter", side_effect=side_effect):
        standard, devils = await call_openrouter_dual_pass("prompt", "key", "model")
        assert standard is not None
        assert devils is None


@pytest.mark.asyncio
async def test_call_openrouter_dual_pass_both_fail():
    """Both calls fail — both None."""
    with patch("app.engine.llm.call_openrouter", new_callable=AsyncMock, return_value=None):
        standard, devils = await call_openrouter_dual_pass("prompt", "key", "model")
        assert standard is None
        assert devils is None
```

The test file already imports `pytest` and `AsyncMock`/`patch`. Add the following imports that are NOT already present:

```python
from app.engine.models import LLMFactor, LLMResponse, LLMResult
```

(`LLMResult` and `LLMResponse` are in `app.engine.models`, same module as the already-imported `FactorType`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_llm.py -k "test_call_openrouter_dual_pass" -v`

Expected: FAIL — `call_openrouter_dual_pass` and `DEVILS_ADVOCATE_SYSTEM_PROMPT` not importable.

- [ ] **Step 3: Add `DEVILS_ADVOCATE_SYSTEM_PROMPT` constant to llm.py**

Add after `SYSTEM_PROMPT` (line 19) in `backend/app/engine/llm.py`:

```python
DEVILS_ADVOCATE_SYSTEM_PROMPT = (
    "You are a critical analyst reviewing a crypto futures trade setup. "
    "Your task is to identify the strongest case AGAINST the prevailing signal "
    "direction. Score the top 3-5 factors that support the opposing view. "
    "Focus on concrete evidence — divergences, overextension, exhaustion signals, "
    "positioning extremes, key levels. Be genuinely contrarian."
)
```

- [ ] **Step 4: Add `system_prompt` parameter to `call_openrouter`**

In `backend/app/engine/llm.py`, update the `call_openrouter` signature (line 32) to add `system_prompt` parameter:

```python
async def call_openrouter(
    prompt: str,
    api_key: str,
    model: str,
    timeout: int = 30,
    system_prompt: str = SYSTEM_PROMPT,
) -> LLMResult | None:
```

And update the payload inside the function to use the parameter instead of the hardcoded constant. Change:

```python
{"role": "system", "content": SYSTEM_PROMPT},
```

to:

```python
{"role": "system", "content": system_prompt},
```

- [ ] **Step 5: Add `import asyncio` and `call_openrouter_dual_pass` function**

Add `import asyncio` to the top of `backend/app/engine/llm.py` (it is NOT currently imported — the module uses `async`/`await` but doesn't import the `asyncio` module directly).

Add after `call_openrouter` (after line ~70) in `backend/app/engine/llm.py`:

```python
async def call_openrouter_dual_pass(
    prompt: str,
    api_key: str,
    model: str,
    timeout: int = 30,
) -> tuple[LLMResult | None, LLMResult | None]:
    """Call OpenRouter twice concurrently: standard + devil's advocate.

    Returns (standard_result, devils_result). Either may be None on failure.
    """
    results = await asyncio.gather(
        call_openrouter(prompt, api_key, model, timeout, system_prompt=SYSTEM_PROMPT),
        call_openrouter(prompt, api_key, model, timeout, system_prompt=DEVILS_ADVOCATE_SYSTEM_PROMPT),
        return_exceptions=True,
    )
    standard = results[0] if not isinstance(results[0], BaseException) else None
    devils = results[1] if not isinstance(results[1], BaseException) else None
    return standard, devils
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_llm.py -v`

Expected: All PASS (both new and existing tests).

---

### Task 5: Wire Dual-Pass into Pipeline

**Files:**
- Modify: `backend/app/main.py:39` (import)
- Modify: `backend/app/main.py:953-1000` (LLM call + score computation)
- Modify: `backend/app/main.py:1174-1197` (signal_data dict — add `dual_pass_agreed`)
- Modify: `backend/app/main.py:412` (`_emit_signal` — merge `dual_pass_agreed` into `risk_metrics`)

- [ ] **Step 1: Update imports in main.py**

In `backend/app/main.py`, update the llm import (line 39) from:

```python
from app.engine.llm import load_prompt_template, render_prompt, call_openrouter
```

to:

```python
from app.engine.llm import load_prompt_template, render_prompt, call_openrouter_dual_pass
```

Add the combiner import for `aggregate_dual_pass`. Find the existing combiner import line (search for `from app.engine.combiner import`) and add `aggregate_dual_pass` to it.

- [ ] **Step 2: Replace LLM call with dual-pass**

In `backend/app/main.py`, replace the LLM call block. Change the `call_openrouter` call (lines 983-988) from:

```python
            llm_result = await call_openrouter(
                prompt=rendered,
                api_key=settings.openrouter_api_key,
                model=settings.openrouter_model,
                timeout=settings.engine_llm_timeout_seconds,
            )
```

to:

```python
            standard_result, devils_result = await call_openrouter_dual_pass(
                prompt=rendered,
                api_key=settings.openrouter_api_key,
                model=settings.openrouter_model,
                timeout=settings.engine_llm_timeout_seconds,
            )
            llm_result = standard_result
```

`llm_result` is reassigned to `standard_result` so all downstream code that reads `llm_result` for levels and factors continues to work unchanged.

- [ ] **Step 3: Update score computation for dual-pass aggregation**

Replace the score computation block (lines 993-1000) from:

```python
    llm_contribution = 0
    if llm_result:
        llm_contribution = compute_llm_contribution(
            llm_result.response.factors,
            settings.llm_factor_weights,
            settings.llm_factor_total_cap,
        )
    final = compute_final_score(blended, llm_contribution)
```

to:

```python
    llm_contribution = 0
    dual_pass_agreed = None
    if standard_result:
        contrib_standard = compute_llm_contribution(
            standard_result.response.factors,
            settings.llm_factor_weights,
            settings.llm_factor_total_cap,
        )
        if devils_result:
            contrib_devils = compute_llm_contribution(
                devils_result.response.factors,
                settings.llm_factor_weights,
                settings.llm_factor_total_cap,
            )
            llm_contribution, dual_pass_agreed = aggregate_dual_pass(
                contrib_standard, contrib_devils, settings.llm_factor_total_cap,
            )
        else:
            llm_contribution = contrib_standard
    final = compute_final_score(blended, llm_contribution)
```

- [ ] **Step 4: Store `dual_pass_agreed` in risk_metrics**

`risk_metrics` is NOT built in `run_pipeline()` — it's built inside `_emit_signal()` (line 357-412) from OKX position sizing data. We need two changes:

**4a.** In `run_pipeline()`, add `dual_pass_agreed` to the `signal_data` dict (around line 1197, inside the dict literal that ends with `"confidence_tier": confidence_tier`):

```python
        "dual_pass_agreed": dual_pass_agreed,
```

**4b.** In `_emit_signal()`, after the line `signal_data["risk_metrics"] = risk_metrics` (line 412), merge `dual_pass_agreed` into risk_metrics:

```python
    signal_data["risk_metrics"] = risk_metrics
    # Merge dual-pass LLM agreement into risk_metrics for observability
    if signal_data.get("dual_pass_agreed") is not None:
        if signal_data["risk_metrics"] is None:
            signal_data["risk_metrics"] = {}
        signal_data["risk_metrics"]["llm_dual_pass_agreed"] = signal_data.pop("dual_pass_agreed")
```

This ensures `dual_pass_agreed` is stored in the `risk_metrics` JSONB column (not `raw_indicators`, which IC pruning reads).

- [ ] **Step 5: Run API tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v`

Expected: All PASS. The existing pipeline tests mock the LLM call; verify they still work with the renamed import. If any test imports `call_openrouter` from main's scope, update those imports to `call_openrouter_dual_pass`.

---

### Task 6: Joint Bayesian ATR Optimization

**Files:**
- Modify: `backend/requirements.txt` (add scikit-optimize)
- Modify: `backend/app/config.py` (add `atr_optimizer_mode`)
- Modify: `backend/app/engine/performance_tracker.py:92-180` (add GP methods)
- Modify: `backend/app/engine/performance_tracker.py:182-451` (update `optimize()`)
- Modify: `backend/tests/engine/test_performance_tracker.py` (add GP tests)

- [ ] **Step 1: Add scikit-optimize to requirements.txt**

Add to `backend/requirements.txt` (before the `# testing` section):

```
scikit-optimize>=0.10
```

Rebuild the container to install it:

Run: `cd backend && docker compose up -d --build`

- [ ] **Step 2: Add `atr_optimizer_mode` to config.py**

In `backend/app/config.py`, add near the other engine settings (around line 88):

```python
    atr_optimizer_mode: str = "gp"  # "gp" for Bayesian optimization, "sweep" for legacy 1D sweeps
```

- [ ] **Step 3: Write tests for GP objective and optimization**

Add to `backend/tests/engine/test_performance_tracker.py`:

```python
from app.engine.performance_tracker import PerformanceTracker


def test_gp_objective_constraint_violation():
    """Constraint violations return penalty value."""
    tracker = PerformanceTracker(session_factory=None)
    # tp1 < sl violates constraint
    result = tracker._gp_objective([2.0, 1.5, 4.0], [], {})
    assert result == 999.0
    # tp2 < tp1 * 1.2 violates constraint
    result = tracker._gp_objective([1.0, 2.0, 2.2], [], {})
    assert result == 999.0


def test_gp_objective_valid_params():
    """Valid parameters compute negative Sortino from replayed signals."""
    tracker = PerformanceTracker(session_factory=None)
    # Candle dicts must match the format built by optimize():
    # {"high": float, "low": float, "timestamp": datetime}
    sig_candles = [
        {"high": 51500.0, "low": 49500.0, "timestamp": datetime(2026, 1, 1, 1, tzinfo=timezone.utc)},
        {"high": 52000.0, "low": 50500.0, "timestamp": datetime(2026, 1, 1, 2, tzinfo=timezone.utc)},
    ]
    signals = [
        {
            "direction": "LONG",
            "entry": 50000.0,
            "atr": 500.0,
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    ]
    candles_map = {0: sig_candles}
    # sl=1.5, tp1=2.0, tp2=3.0 — within constraints (tp2 >= tp1*1.2)
    result = tracker._gp_objective([1.5, 2.0, 3.0], signals, candles_map)
    # Should return a finite number (negative Sortino or 0.0)
    assert result != 999.0
    assert isinstance(result, float)


def test_gp_objective_empty_signals():
    """No signals produces neutral result (0.0), not penalty."""
    tracker = PerformanceTracker(session_factory=None)
    result = tracker._gp_objective([1.5, 2.0, 3.0], [], {})
    assert result == 0.0


def test_gp_optimize_returns_tuple_or_none():
    """_gp_optimize returns (sl, tp1, tp2) tuple or None on failure."""
    tracker = PerformanceTracker(session_factory=None)
    sig_candles = [
        {"high": 51500.0, "low": 49500.0, "timestamp": datetime(2026, 1, 1, 1, tzinfo=timezone.utc)},
        {"high": 52000.0, "low": 50500.0, "timestamp": datetime(2026, 1, 1, 2, tzinfo=timezone.utc)},
        {"high": 52500.0, "low": 51000.0, "timestamp": datetime(2026, 1, 1, 3, tzinfo=timezone.utc)},
    ]
    signals = [
        {
            "direction": "LONG",
            "entry": 50000.0,
            "atr": 500.0,
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    ]
    candles_map = {0: sig_candles}
    result = tracker._gp_optimize(signals, candles_map, 1.5, 2.0, 3.0)
    if result is not None:
        sl, tp1, tp2 = result
        assert 0.8 <= sl <= 2.5
        assert 1.0 <= tp1 <= 4.0
        assert 2.0 <= tp2 <= 6.0
```

Note: Import `datetime` and `timezone` if not already imported in the test file.

- [ ] **Step 4: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py -k "test_gp_" -v`

Expected: FAIL — `_gp_objective` and `_gp_optimize` not defined.

Note: the tests use `candles_map` as a separate dict (matching the production `optimize()` pattern), not embedded candles in the signal dicts.

- [ ] **Step 5: Implement `_gp_objective` method**

Add after `_sweep_dimension` (line ~180) in the `PerformanceTracker` class in `backend/app/engine/performance_tracker.py`:

```python
    def _gp_objective(self, params, signals, candles_map):
        """Objective function for GP optimizer. Returns value to minimize.

        signals: list of signal dicts (same schema as signals_data in optimize())
        candles_map: dict mapping signal index to candle list (same as optimize())
        """
        sl_atr, tp1_atr, tp2_atr = params

        if tp1_atr < sl_atr or tp2_atr < tp1_atr * 1.2:
            return 999.0

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
            return 0.0
        return -sortino
```

- [ ] **Step 6: Implement `_gp_optimize` method**

Add after `_gp_objective` in the `PerformanceTracker` class:

```python
    def _gp_optimize(self, signals, candles_map, current_sl, current_tp1, current_tp2):
        """Run GP-based 3D joint optimization of SL/TP1/TP2 ATR multipliers.

        signals: list of signal dicts (same schema as signals_data in optimize())
        candles_map: dict mapping signal index to candle list (same as optimize())
        Returns (sl, tp1, tp2) tuple or None on failure (triggers sweep fallback).
        """
        try:
            from skopt import gp_minimize
            from skopt.space import Real
        except ImportError:
            logger.warning("scikit-optimize not installed, falling back to sweep")
            return None

        space = [
            Real(SL_RANGE[0], SL_RANGE[1], name="sl_atr"),
            Real(TP1_RANGE[0], TP1_RANGE[1], name="tp1_atr"),
            Real(TP2_RANGE[0], TP2_RANGE[1], name="tp2_atr"),
        ]

        def objective(params):
            return self._gp_objective(params, signals, candles_map)

        try:
            result = gp_minimize(
                func=objective,
                dimensions=space,
                n_calls=40,
                n_initial_points=8,
                acq_func="EI",
                random_state=42,
            )
            best_sl, best_tp1, best_tp2 = result.x
            best_sortino = -result.fun if result.fun != 0.0 else 0.0
            logger.info(
                f"GP optimizer: best_sortino={best_sortino:.3f}, "
                f"params=({best_sl:.2f}, {best_tp1:.2f}, {best_tp2:.2f}), "
                f"n_calls={len(result.func_vals)}"
            )
            return best_sl, best_tp1, best_tp2
        except Exception as e:
            logger.error(f"GP optimization failed: {e}, falling back to sweep")
            return None
```

- [ ] **Step 7: Add `settings` parameter to `optimize()` and wire GP path**

The `optimize()` method (line 182) does NOT currently receive `settings`. Add it as an optional parameter:

Change the signature from:
```python
    async def optimize(self, pair: str, timeframe: str, dry_run: bool = False):
```
to:
```python
    async def optimize(self, pair: str, timeframe: str, dry_run: bool = False, settings=None):
```

Then find all callers of `optimize()` (search for `.optimize(` in the codebase — it's called from `check_optimization_triggers` in the same file, around line 453+). Update each caller to pass `settings` if available, or `None` if not (the GP path falls back to sweep when settings is None).

Now insert the GP path. In `optimize()`, immediately after `current_tp2 = row.current_tp2_atr` (line 329) and before the sweep loop that starts with `adjustments = []` (line 331), insert:

```python
            # -- Try GP optimization if configured --
            gp_result = None
            if settings is not None and getattr(settings, "atr_optimizer_mode", "gp") == "gp":
                gp_result = self._gp_optimize(
                    signals_data, candles_map, current_sl, current_tp1, current_tp2,
                )

            if gp_result is not None:
                gp_sl, gp_tp1, gp_tp2 = gp_result
                # Apply same guardrails as sweep path
                gp_sl = self._apply_guardrails(current_sl, gp_sl, SL_RANGE, MAX_SL_ADJ)
                gp_tp1 = self._apply_guardrails(current_tp1, gp_tp1, TP1_RANGE, MAX_TP_ADJ)
                gp_tp2 = self._apply_guardrails(current_tp2, gp_tp2, TP2_RANGE, MAX_TP_ADJ)

                adjustments = []
                if gp_sl != current_sl:
                    adjustments.append({"dimension": "sl", "old": current_sl, "new": gp_sl, "sortino": None, "clamped": gp_sl != gp_result[0]})
                if gp_tp1 != current_tp1:
                    adjustments.append({"dimension": "tp1", "old": current_tp1, "new": gp_tp1, "sortino": None, "clamped": gp_tp1 != gp_result[1]})
                if gp_tp2 != current_tp2:
                    adjustments.append({"dimension": "tp2", "old": current_tp2, "new": gp_tp2, "sortino": None, "clamped": gp_tp2 != gp_result[2]})
            else:
```

Then indent the existing sweep block (lines 331-363, from `adjustments = []` through the last `adjustments.append({...})`) one level to become the `else` body.

The code after the sweep block (starting with `if not adjustments:` at line 365) remains at the original indentation and is shared by both paths.

**Variable reference (all from `optimize()`):**
- `signals_data`: list of signal dicts, built at lines 245-312
- `candles_map`: dict mapping integer index → candle list, built at lines 246/311
- `current_sl`, `current_tp1`, `current_tp2`: read from `row` at lines 327-329
- `SL_RANGE`, `TP1_RANGE`, `TP2_RANGE`, `MAX_SL_ADJ`, `MAX_TP_ADJ`: module-level constants from lines 28-32

The GP path applies its own guardrails inline (in the `if gp_result is not None` block above). The sweep path continues to use its existing per-dimension guardrails. The shared code after both paths (`if not adjustments:`, dry_run return, DB persistence) is unchanged.

- [ ] **Step 8: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_performance_tracker.py -v`

Expected: All PASS (both new GP tests and existing sweep tests).

---

### Task 7: Final Verification and Commit

- [ ] **Step 1: Run full test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v`

Expected: All PASS.

- [ ] **Step 2: Verify no import errors**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "from app.engine.optimizer import compute_ew_ic, should_prune_source, should_reenable_source; from app.engine.llm import call_openrouter_dual_pass, DEVILS_ADVOCATE_SYSTEM_PROMPT; from app.engine.combiner import aggregate_dual_pass; print('All imports OK')"`

Expected: `All imports OK`

- [ ] **Step 3: Commit all changes**

```bash
git add backend/requirements.txt backend/app/config.py \
  backend/app/engine/optimizer.py backend/app/engine/constants.py \
  backend/app/engine/llm.py backend/app/engine/combiner.py \
  backend/app/engine/performance_tracker.py backend/app/main.py \
  backend/alembic/versions/ \
  backend/tests/engine/test_optimizer.py \
  backend/tests/engine/test_combiner.py \
  backend/tests/engine/test_llm.py \
  backend/tests/engine/test_performance_tracker.py \
  docs/superpowers/specs/2026-03-31-signal-quality-improvements-design.md
git commit -m "feat(engine): signal quality improvements — EW IC pruning, LLM dual-pass, Bayesian ATR"
```
