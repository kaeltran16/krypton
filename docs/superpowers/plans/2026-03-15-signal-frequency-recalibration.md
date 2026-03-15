# Signal Frequency Recalibration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Increase signal frequency from near-zero to ~1-2 signals per pair per day by recalibrating sigmoid steepness, replacing the LLM double-veto with a penalty, and aligning thresholds across all layers.

**Architecture:** Four independent changes converge: (1) widen sigmoid outputs so scores use more of the ±100 range, (2) replace LLM contradict's hard clamp + pipeline veto with a proportional penalty, (3) lower signal/LLM thresholds across config.yaml, DB model, and live DB row, (4) align backtester defaults with live config.

**Tech Stack:** Python/FastAPI backend, SQLAlchemy/Alembic (Postgres), React/TypeScript frontend, pytest

**Spec:** `docs/superpowers/specs/2026-03-15-signal-frequency-recalibration-design.md`

---

## Chunk 1: LLM Contradict Rework

### Task 1: Update combiner contradict tests (TDD - red)

**Files:**
- Modify: `backend/tests/engine/test_combiner.py:171-180`

- [ ] **Step 1: Update existing contradict tests and add new ones**

Replace the two existing contradict tests and add new ones. The old tests assert hard-clamp behavior (`<= 40`, `>= -40`). The new logic uses a sign-aware penalty clamped toward zero: `score - sign * min(30 * multiplier, abs(score))`.

In `backend/tests/engine/test_combiner.py`, replace lines 171-180:

```python
# OLD:
def test_final_score_with_contradict():
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="No way", levels=None)
    final = compute_final_score(preliminary_score=80, llm_response=llm)
    assert final <= 40


def test_final_score_with_contradict_negative():
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Not that bad", levels=None)
    final = compute_final_score(preliminary_score=-80, llm_response=llm)
    assert final >= -40
```

with:

```python
# NEW:
def test_final_score_with_contradict():
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="No way", levels=None)
    final = compute_final_score(preliminary_score=80, llm_response=llm)
    assert final == 50  # 80 - 1 * min(30, 80) * 1.0 = 50


def test_final_score_with_contradict_negative():
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Not that bad", levels=None)
    final = compute_final_score(preliminary_score=-80, llm_response=llm)
    assert final == -50  # -80 - (-1) * min(30, 80) * 1.0 = -50


def test_final_score_with_contradict_medium():
    llm = LLMResponse(opinion="contradict", confidence="MEDIUM", explanation="Meh", levels=None)
    final = compute_final_score(preliminary_score=80, llm_response=llm)
    assert final == 62  # 80 - 1 * min(18, 80) * 1.0 = 62 (multiplier 0.6: 30*0.6=18)


def test_final_score_with_contradict_zero():
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Zero", levels=None)
    final = compute_final_score(preliminary_score=0, llm_response=llm)
    assert final == 0  # zero guard: no directional bias


def test_final_score_with_contradict_clamps_at_zero():
    """Penalty larger than abs(score) clamps to zero instead of flipping sign."""
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Disagree", levels=None)
    final = compute_final_score(preliminary_score=20, llm_response=llm)
    assert final == 0  # 20 - 1 * min(30, 20) * 1.0 = 0 (clamped, not -10)


def test_final_score_with_contradict_clamps_at_zero_negative():
    """Negative score: penalty clamps to zero instead of flipping to positive."""
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Disagree", levels=None)
    final = compute_final_score(preliminary_score=-25, llm_response=llm)
    assert final == 0  # -25 - (-1) * min(30, 25) * 1.0 = 0 (clamped, not +5)


def test_final_score_with_contradict_borderline_emission():
    """Score of 70 with HIGH contradict lands exactly at threshold=40."""
    llm = LLMResponse(opinion="contradict", confidence="HIGH", explanation="Doubt", levels=None)
    final = compute_final_score(preliminary_score=70, llm_response=llm)
    assert final == 40  # 70 - 1 * min(30, 70) * 1.0 = 40 (borderline emit)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py::test_final_score_with_contradict tests/engine/test_combiner.py::test_final_score_with_contradict_negative tests/engine/test_combiner.py::test_final_score_with_contradict_medium tests/engine/test_combiner.py::test_final_score_with_contradict_zero -v`

Expected: `test_final_score_with_contradict` FAILS (returns 40 not 50), `test_final_score_with_contradict_negative` FAILS (returns -40 not -50), `test_final_score_with_contradict_medium` FAILS (function returns 40 not 62), `test_final_score_with_contradict_zero` FAILS (returns 0 via clamp, but this one may accidentally pass — that's fine). `test_final_score_with_contradict_clamps_at_zero` FAILS (returns -10 not 0 with old clamp logic), `test_final_score_with_contradict_clamps_at_zero_negative` FAILS, `test_final_score_with_contradict_borderline_emission` FAILS (returns 40 via old clamp, but for wrong reason — may accidentally pass).

### Task 2: Implement combiner contradict penalty (TDD - green)

**Files:**
- Modify: `backend/app/engine/combiner.py:74-75`

- [ ] **Step 3: Replace hard clamp with sign-aware penalty**

In `backend/app/engine/combiner.py`, replace lines 74-75:

```python
    else:  # contradict
        final = max(min(preliminary_score, 40), -40)
```

with:

```python
    else:  # contradict
        if preliminary_score == 0:
            final = 0
        else:
            sign = 1 if preliminary_score > 0 else -1
            penalty = sign * min(30 * multiplier, abs(preliminary_score))
            final = preliminary_score - penalty
```

The `min(30 * multiplier, abs(preliminary_score))` clamp ensures the penalty never exceeds the score's magnitude, preventing sign flips. For example, preliminary=20 with HIGH contradict: `min(30, 20) = 20`, so `final = 20 - 20 = 0` instead of `20 - 30 = -10`.

- [ ] **Step 4: Run combiner tests to verify they pass**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py -v`

Expected: ALL PASS. The seven contradict tests should now pass with the new penalty logic. Existing confirm/caution/bounded tests are unchanged.

### Task 3: Update pipeline contradict test (TDD - red)

**Files:**
- Modify: `backend/tests/test_pipeline_ml.py:152-169`

- [ ] **Step 5: Change pipeline contradict test to expect emission**

The current test `test_hard_veto_on_contradict` asserts `mock_persist.assert_not_called()`. After removing the hard veto, a strong signal with contradict should still emit (the penalty reduces but doesn't kill it).

In `backend/tests/test_pipeline_ml.py`, replace lines 152-169:

```python
    @pytest.mark.asyncio
    async def test_hard_veto_on_contradict(self):
        """Pipeline does not emit when LLM opinion is contradict, even with high score."""
        from app.engine.models import LLMResponse

        app = _make_mock_app(prompt_template="fake template")
        app.state.settings.engine_signal_threshold = 10
        app.state.settings.engine_llm_threshold = 5  # low threshold so LLM gate triggers

        llm_resp = LLMResponse(
            opinion="contradict", confidence="HIGH",
            explanation="Clear reversal signal", levels=None,
        )

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist, \
             patch("app.main.call_openrouter", new_callable=AsyncMock, return_value=llm_resp), \
             patch("app.main.render_prompt", return_value="rendered"):
            await run_pipeline(app, CANDLE)
            mock_persist.assert_not_called()
```

with:

```python
    @pytest.mark.asyncio
    async def test_contradict_penalizes_but_does_not_veto(self):
        """Pipeline still emits when LLM contradicts a strong signal — penalty reduces score but threshold check decides."""
        from app.engine.models import LLMResponse

        app = _make_mock_app(prompt_template="fake template")
        app.state.settings.engine_signal_threshold = 10  # low threshold so penalized score still emits
        app.state.settings.engine_llm_threshold = 5

        llm_resp = LLMResponse(
            opinion="contradict", confidence="HIGH",
            explanation="Clear reversal signal", levels=None,
        )

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist, \
             patch("app.main.call_openrouter", new_callable=AsyncMock, return_value=llm_resp), \
             patch("app.main.render_prompt", return_value="rendered"):
            await run_pipeline(app, CANDLE)
            # With low threshold, penalized score should still emit
            assert mock_persist.called, "Contradict should penalize, not veto — signal should still emit"
            # Verify the emitted signal_data dict has a reduced score (penalty applied)
            signal_data = mock_persist.call_args[0][1]  # persist_signal(db, signal_data)
            assert abs(signal_data["score"]) >= 10, "Penalized score should still exceed threshold"
```

- [ ] **Step 6: Run pipeline test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/test_pipeline_ml.py::TestUnifiedPipelineLLMBehavior::test_contradict_penalizes_but_does_not_veto -v`

Expected: FAIL — the hard veto in `main.py` still returns early before `persist_signal` is called.

### Task 4: Remove pipeline hard veto (TDD - green)

**Files:**
- Modify: `backend/app/main.py:454-469`

- [ ] **Step 7: Delete the hard veto block**

In `backend/app/main.py`, delete lines 454-469 (Step 7 hard veto block):

```python
    # ── Step 7: Hard veto on LLM contradict ──
    llm_opinion = llm_response.opinion if llm_response else None
    if llm_opinion == "contradict":
        _log_pipeline_evaluation(
            pair=pair, timeframe=timeframe,
            tech_score=tech_result["score"], flow_score=flow_result["score"],
            onchain_score=onchain_score if onchain_available else None,
            pattern_score=pat_score,
            ml_score=ml_score, ml_confidence=ml_confidence,
            indicator_preliminary=indicator_preliminary,
            blended_score=blended, final_score=final,
            llm_opinion=llm_opinion, ml_available=ml_available,
            agreement=agreement, emitted=False,
        )
        logger.info(f"Pipeline {pair}:{timeframe} — LLM contradict hard veto (final={final})")
        return
```

Note: The `llm_opinion` variable is still assigned on the line just before the deleted block. Check if it's used later (it is — in `_log_pipeline_evaluation` at the threshold check on line 474+). Keep the assignment but move it up to right after Step 6:

After line 452 (`direction = "LONG" if final > 0 else "SHORT"`), ensure this line exists:
```python
    llm_opinion = llm_response.opinion if llm_response else None
```

Then delete the entire `if llm_opinion == "contradict":` block (the 13 lines starting with the comment `# ── Step 7`).

- [ ] **Step 8: Run all pipeline and combiner tests**

Run: `docker exec krypton-api-1 python -m pytest tests/test_pipeline_ml.py tests/engine/test_combiner.py -v`

Expected: ALL PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/engine/combiner.py backend/app/main.py backend/tests/engine/test_combiner.py backend/tests/test_pipeline_ml.py
git commit -m "feat: replace LLM contradict hard veto with sign-aware penalty"
```

---

## Chunk 2: Sigmoid Recalibration

### Task 5: Update technical score tests for new steepness values (TDD - red)

**Files:**
- Modify: `backend/tests/engine/test_traditional.py:79-100`

The existing tests in `test_traditional.py` use behavioral assertions (bounds, direction, indicator presence) that will still pass after steepness changes. The `TestTechnicalScoreContinuity` class hardcodes the old steepness values in direct `sigmoid_score` calls. Update those.

- [ ] **Step 10: Update sigmoid steepness values in continuity tests**

In `backend/tests/engine/test_traditional.py`, replace lines 80-88:

```python
    def test_rsi_no_dead_zone(self):
        """RSI values in the old dead zone (40-60) should produce non-zero sigmoid contribution."""
        from app.engine.scoring import sigmoid_score
        # RSI=45 is in the old dead zone (40-60 gave 0). New sigmoid should not.
        rsi_contribution = sigmoid_score(50 - 45, center=0, steepness=0.15) * 25
        assert rsi_contribution > 0
        # RSI=55 should produce negative contribution
        rsi_contribution_55 = sigmoid_score(50 - 55, center=0, steepness=0.15) * 25
        assert rsi_contribution_55 < 0
```

with:

```python
    def test_rsi_no_dead_zone(self):
        """RSI values in the old dead zone (40-60) should produce non-zero sigmoid contribution."""
        from app.engine.scoring import sigmoid_score
        # RSI=45 is in the old dead zone (40-60 gave 0). New sigmoid should not.
        rsi_contribution = sigmoid_score(50 - 45, center=0, steepness=0.25) * 25
        assert rsi_contribution > 0
        # RSI=55 should produce negative contribution
        rsi_contribution_55 = sigmoid_score(50 - 55, center=0, steepness=0.25) * 25
        assert rsi_contribution_55 < 0
```

- [ ] **Step 11: Add score magnitude tests for recalibrated steepness**

Add a new test class at the end of `backend/tests/engine/test_traditional.py` (after `TestOrderFlowDirectionalOI`):

```python
class TestRecalibratedScoreMagnitude:
    """Verify recalibrated sigmoid steepness produces expected score ranges."""

    def test_uptrend_score_higher_than_old_ceiling(self):
        """After recalibration, a clear uptrend should score above the old ~45 ceiling."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df)
        # Old steepness produced scores clustering in ±20-45.
        # Recalibrated steepness should push aligned signals higher.
        assert abs(result["score"]) > 20, f"Score {result['score']} still too compressed"

    def test_order_flow_score_magnitude(self):
        """Strong order flow inputs should produce meaningful scores with new steepness."""
        result = compute_order_flow_score({
            "funding_rate": -0.0005,  # negative = bullish (contrarian)
            "open_interest_change_pct": 0.03,
            "price_direction": 1,
            "long_short_ratio": 0.8,  # low = bullish (contrarian)
        })
        # With recalibrated steepness, this should be a strong bullish flow signal.
        # Old steepness produces ~54; new produces ~68. Threshold of 55 ensures
        # this test only passes after recalibration.
        assert result["score"] > 55, f"Flow score {result['score']} too compressed"
```

- [ ] **Step 12: Run tests to verify current state**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`

Expected: All existing tests PASS. The new `test_order_flow_score_magnitude` should FAIL with old steepness (old produces ~54, threshold is 55). It becomes a proper TDD-red test for the order flow recalibration.

### Task 6: Recalibrate technical score sigmoids

**Files:**
- Modify: `backend/app/engine/traditional.py:129-141`

- [ ] **Step 13: Update steepness values in compute_technical_score**

In `backend/app/engine/traditional.py`, make these six changes (lines 129-141):

Line 129 — Trend (ADX): change `center=20, steepness=0.15` to `center=15, steepness=0.30`:
```python
    trend_score = di_sign * sigmoid_scale(adx_val, center=15, steepness=0.30) * 30
```

Line 132 — RSI: change `steepness=0.15` to `steepness=0.25`:
```python
    rsi_score = sigmoid_score(50 - rsi_val, center=0, steepness=0.25) * 25
```

Line 135 — BB Position: change `steepness=6` to `steepness=10`:
```python
    bb_pos_score = sigmoid_score(0.5 - bb_pos, center=0, steepness=10) * 15
```

Line 137 — BB Width: change `steepness=0.06` to `steepness=0.10`:
```python
    bb_width_score = bb_pos_sign * sigmoid_score(50 - bb_width_pct, center=0, steepness=0.10) * 10
```

Line 140 — OBV Slope: change `steepness=2` to `steepness=4`:
```python
    obv_score = sigmoid_score(obv_slope_norm, center=0, steepness=4) * 12
```

Line 141 — Volume Ratio: change `steepness=1.5` to `steepness=3.0`:
```python
    vol_score = candle_direction * sigmoid_score(vol_ratio - 1, center=0, steepness=3.0) * 8
```

- [ ] **Step 14: Run technical score tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestTechnicalScoreBounds tests/engine/test_traditional.py::TestTechnicalScoreDirection tests/engine/test_traditional.py::TestTechnicalScoreContinuity tests/engine/test_traditional.py::TestRecalibratedScoreMagnitude -v`

Expected: ALL PASS.

### Task 7: Recalibrate order flow sigmoids

**Files:**
- Modify: `backend/app/engine/traditional.py:171-183`

- [ ] **Step 15: Update steepness values in compute_order_flow_score**

In `backend/app/engine/traditional.py`, make these three changes:

Line 171 — Funding Rate: change `steepness=5000` to `steepness=8000`:
```python
    funding_score = sigmoid_score(-funding, center=0, steepness=8000) * 35
```

Line 179 — OI Change: change `steepness=40` to `steepness=65`:
```python
        oi_score = price_dir * sigmoid_score(oi_change, center=0, steepness=65) * 20
```

Line 183 — L/S Ratio: change `steepness=4` to `steepness=6`:
```python
    ls_score = sigmoid_score(1.0 - ls, center=0, steepness=6) * 35
```

- [ ] **Step 16: Run all traditional tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py -v`

Expected: ALL PASS.

- [ ] **Step 17: Commit**

```bash
git add backend/app/engine/traditional.py backend/tests/engine/test_traditional.py
git commit -m "feat: recalibrate sigmoid steepness for tech and order flow scores"
```

---

## Chunk 3: Config & Defaults Alignment

### Task 8: Update config.py Pydantic defaults

**Files:**
- Modify: `backend/app/config.py:59-60`

- [ ] **Step 18: Update Settings model defaults**

`config.py` is the base fallback when neither `config.yaml` nor the DB provides a value. Update to match the new thresholds.

In `backend/app/config.py`, replace lines 59-60:

```python
    engine_signal_threshold: int = 35
    engine_llm_threshold: int = 25
```

with:

```python
    engine_signal_threshold: int = 40
    engine_llm_threshold: int = 20
```

### Task 9: Update config.yaml thresholds

**Files:**
- Modify: `backend/config.yaml:17-21`

- [ ] **Step 19: Update thresholds and remove dead key**

In `backend/config.yaml`, replace lines 16-21:

```yaml
engine:
  signal_threshold: 50
  llm_threshold: 30
  llm_timeout_seconds: 30
  traditional_weight: 0.60
  llm_weight: 0.40
```

with:

```yaml
engine:
  signal_threshold: 40
  llm_threshold: 20
  llm_timeout_seconds: 30
  traditional_weight: 0.60
```

Changes: `signal_threshold` 50→40, `llm_threshold` 30→20, removed dead `llm_weight` key (no matching Settings field).

### Task 10: Update PipelineSettings model default

**Files:**
- Modify: `backend/app/db/models.py:160`

- [ ] **Step 20: Change column default from 50 to 40**

In `backend/app/db/models.py`, replace line 160:

```python
    signal_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
```

with:

```python
    signal_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
```

### Task 11: Create Alembic migration

**Files:**
- Create: `backend/app/db/migrations/versions/<generated>_lower_signal_threshold_to_40.py`

- [ ] **Step 21: Generate and edit migration**

Run: `docker exec krypton-api-1 alembic revision --autogenerate -m "lower signal threshold to 40"`

The autogenerate won't detect the data change (only the column default change). Edit the generated migration file to add the data update. The `upgrade()` function should contain:

```python
def upgrade() -> None:
    op.execute("UPDATE pipeline_settings SET signal_threshold = 40 WHERE id = 1")
```

And `downgrade()`:

```python
def downgrade() -> None:
    op.execute("UPDATE pipeline_settings SET signal_threshold = 50 WHERE id = 1")
```

Remove any auto-detected schema changes (there shouldn't be any since `default` is a Python-side default, not a `server_default`).

- [ ] **Step 22: Run migration**

Run: `docker exec krypton-api-1 alembic upgrade head`

Expected: Migration applies successfully.

### Task 12: Update backtester defaults

**Files:**
- Modify: `backend/app/api/backtest.py:38`
- Modify: `backend/app/engine/backtester.py:23`
- Modify: `web/src/features/backtest/store.ts:55`

- [ ] **Step 23: Update RunRequest default**

In `backend/app/api/backtest.py`, replace line 38:

```python
    signal_threshold: int = Field(default=50, ge=1, le=100)
```

with:

```python
    signal_threshold: int = Field(default=40, ge=1, le=100)
```

- [ ] **Step 24: Update BacktestConfig default**

In `backend/app/engine/backtester.py`, replace line 23:

```python
    signal_threshold: int = 35
```

with:

```python
    signal_threshold: int = 40  # weights (tech=0.75/pattern=0.25) intentionally differ from live (0.60/0.22/0.23/0.15) — backtester lacks flow/onchain components
```

- [ ] **Step 25: Update frontend default**

In `web/src/features/backtest/store.ts`, replace line 55:

```typescript
  signal_threshold: 30,
```

with:

```typescript
  signal_threshold: 40,
```

### Task 13: Update scale_atr_multipliers default and tests

**Files:**
- Modify: `backend/app/engine/combiner.py:102`
- Modify: `backend/tests/engine/test_combiner.py:388-390,404-406,449-451,476-478`

The `scale_atr_multipliers` function has a default parameter `signal_threshold: int = 35`. Production always passes the value explicitly via `settings.engine_signal_threshold`, but the default and test values should match the new threshold for consistency.

- [ ] **Step 26: Update function default**

In `backend/app/engine/combiner.py`, replace line 102:

```python
    signal_threshold: int = 35,
```

with:

```python
    signal_threshold: int = 40,
```

- [ ] **Step 27: Update test threshold values**

In `backend/tests/engine/test_combiner.py`, update the four tests that explicitly pass `signal_threshold=35`:

Line 388 and 390 (`test_scale_at_threshold_minimum`): change `score=35` and `signal_threshold=35` to `score=40` and `signal_threshold=40`:
```python
def test_scale_at_threshold_minimum():
    """Score exactly at threshold -> t=0 -> all factors = 0.8."""
    result = scale_atr_multipliers(
        score=40, bb_width_pct=50.0,
        sl_base=1.5, tp1_base=2.0, tp2_base=3.0,
        signal_threshold=40,
    )
```

Line 406 (`test_scale_at_max_score`): change `signal_threshold=35` to `signal_threshold=40`:
```python
        signal_threshold=40,
```

Line 451 (`test_scale_combined_effect`): change `signal_threshold=35` to `signal_threshold=40`:
```python
        signal_threshold=40,
```

Line 478 (`test_scale_below_threshold_clamps_to_zero`): change `signal_threshold=35` to `signal_threshold=40`:
```python
        signal_threshold=40,
```

All assertions remain unchanged — the factors depend on `t = (abs(score) - threshold) / (100 - threshold)`, and t=0 and t=1 cases produce the same factors regardless of threshold.

Also update `backend/tests/engine/test_backtester.py` line 301: change `signal_threshold=35` to `signal_threshold=40` (assertions use inequalities like `!=` and `>`, so they'll still pass).

### Task 14: Update test mock defaults for consistency

**Files:**
- Modify: `backend/tests/test_pipeline_ml.py:29,34`
- Modify: `backend/tests/api/test_pipeline_settings.py:24,57,99`

These mocks hardcode old threshold values. While tests that care about thresholds override explicitly, updating the defaults prevents stale values from misleading future developers.

- [ ] **Step 28: Update pipeline test mock defaults**

In `backend/tests/test_pipeline_ml.py`, update `_make_mock_app`:

Line 29: change `settings.engine_signal_threshold = 50` to:
```python
    settings.engine_signal_threshold = 40
```

Line 34: change `settings.engine_llm_threshold = 30` to:
```python
    settings.engine_llm_threshold = 20
```

- [ ] **Step 29: Update pipeline settings test defaults**

In `backend/tests/api/test_pipeline_settings.py`:

Line 24: change `overrides.get("signal_threshold", 50)` to:
```python
    row.signal_threshold = overrides.get("signal_threshold", 40)
```

Line 57: change `mock_settings.engine_signal_threshold = 50` to:
```python
    mock_settings.engine_signal_threshold = 40
```

Line 99: change `assert data["signal_threshold"] == 50` to:
```python
    assert data["signal_threshold"] == 40
```

- [ ] **Step 30: Run all backend tests**

Run: `docker exec krypton-api-1 python -m pytest -v`

Expected: ALL PASS. This is the final verification that all changes work together.

- [ ] **Step 31: Run frontend build check**

Run: `cd web && pnpm build`

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 32: Commit**

```bash
git add backend/app/config.py backend/config.yaml backend/app/db/models.py backend/app/engine/combiner.py backend/app/api/backtest.py backend/app/engine/backtester.py web/src/features/backtest/store.ts backend/app/db/migrations/versions/ backend/tests/engine/test_combiner.py backend/tests/engine/test_backtester.py backend/tests/test_pipeline_ml.py backend/tests/api/test_pipeline_settings.py
git commit -m "feat: lower signal threshold to 40 and align all defaults"
```
