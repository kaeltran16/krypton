# Indicator Redundancy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge RSI + BB position into a unified mean-reversion component and separate BB width into its own squeeze component, producing 4 orthogonal scoring caps with configurable shape parameters.

**Architecture:** Replace `bb_vol_cap` with `squeeze_cap` across the regime system. Unify RSI and BB position scoring under `mean_rev_cap` with a configurable blend ratio. Add steepness and blend parameters to `PipelineSettings`. Single Alembic migration handles all DB schema changes.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Alembic, pytest

**Spec:** `docs/superpowers/specs/2026-03-18-indicator-redundancy-design.md`

---

### Task 1: Update regime constants and defaults

**Files:**
- Modify: `backend/app/engine/regime.py:5-12`

- [ ] **Step 1: Write the failing test**

Add a test to `backend/tests/engine/test_traditional.py` that verifies the new cap key exists:

```python
class TestCapKeys:
    def test_squeeze_cap_in_cap_keys(self):
        from app.engine.regime import CAP_KEYS
        assert "squeeze_cap" in CAP_KEYS
        assert "bb_vol_cap" not in CAP_KEYS

    def test_default_caps_sum_to_100(self):
        from app.engine.regime import DEFAULT_CAPS
        for regime, caps in DEFAULT_CAPS.items():
            total = sum(caps.values())
            assert total == 100, f"{regime} caps sum to {total}, expected 100"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestCapKeys -v`
Expected: FAIL — `squeeze_cap` not in CAP_KEYS

- [ ] **Step 3: Update regime.py constants**

In `backend/app/engine/regime.py`, replace lines 5-12:

```python
CAP_KEYS = ["trend_cap", "mean_rev_cap", "squeeze_cap", "volume_cap"]
OUTER_KEYS = ["tech", "flow", "onchain", "pattern"]

DEFAULT_CAPS = {
    "trending": {"trend_cap": 38, "mean_rev_cap": 22, "squeeze_cap": 12, "volume_cap": 28},
    "ranging": {"trend_cap": 18, "mean_rev_cap": 40, "squeeze_cap": 16, "volume_cap": 26},
    "volatile": {"trend_cap": 25, "mean_rev_cap": 28, "squeeze_cap": 22, "volume_cap": 25},
}
```

Also update `blend_caps()` docstring at line 82 — replace `bb_vol_cap` with `squeeze_cap`.

- [ ] **Step 4: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestCapKeys -v`
Expected: PASS

---

### Task 2: Add scoring shape parameters to PipelineSettings model

**Files:**
- Modify: `backend/app/db/models.py:150-174`

- [ ] **Step 1: Add 4 new columns to PipelineSettings**

After the `news_context_window` column (line 167), add:

```python
    mean_rev_rsi_steepness: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.25
    )
    mean_rev_bb_pos_steepness: Mapped[float] = mapped_column(
        Float, nullable=False, default=10.0
    )
    squeeze_steepness: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.10
    )
    mean_rev_blend_ratio: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.6
    )
```

- [ ] **Step 2: Verify model loads without error**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "from app.db.models import PipelineSettings; print('OK')"`
Expected: `OK`

---

### Task 3: Update RegimeWeights model — replace bb_vol_cap with squeeze_cap

**Files:**
- Modify: `backend/app/db/models.py:296-341`

- [ ] **Step 1: Replace bb_vol_cap columns with squeeze_cap**

Replace the 3 `bb_vol_cap` lines (306, 311, 316) and update `mean_rev_cap` defaults (305, 310, 315):

```python
    # Inner caps (3 regimes x 4 caps = 12 floats)
    trending_trend_cap: Mapped[float] = mapped_column(Float, nullable=False, default=38.0)
    trending_mean_rev_cap: Mapped[float] = mapped_column(Float, nullable=False, default=22.0)
    trending_squeeze_cap: Mapped[float] = mapped_column(Float, nullable=False, default=12.0)
    trending_volume_cap: Mapped[float] = mapped_column(Float, nullable=False, default=28.0)

    ranging_trend_cap: Mapped[float] = mapped_column(Float, nullable=False, default=18.0)
    ranging_mean_rev_cap: Mapped[float] = mapped_column(Float, nullable=False, default=40.0)
    ranging_squeeze_cap: Mapped[float] = mapped_column(Float, nullable=False, default=16.0)
    ranging_volume_cap: Mapped[float] = mapped_column(Float, nullable=False, default=26.0)

    volatile_trend_cap: Mapped[float] = mapped_column(Float, nullable=False, default=25.0)
    volatile_mean_rev_cap: Mapped[float] = mapped_column(Float, nullable=False, default=28.0)
    volatile_squeeze_cap: Mapped[float] = mapped_column(Float, nullable=False, default=22.0)
    volatile_volume_cap: Mapped[float] = mapped_column(Float, nullable=False, default=25.0)
```

- [ ] **Step 2: Verify model loads**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "from app.db.models import RegimeWeights; print('OK')"`
Expected: `OK`

---

### Task 4: Create Alembic migration

**Files:**
- Create: `backend/alembic/versions/<auto>_unify_mean_reversion_add_squeeze_cap.py`

- [ ] **Step 1: Generate migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "unify mean reversion and add squeeze cap"`

- [ ] **Step 2: Edit migration to include data migration**

Open the generated migration file. After the `add_column` operations for `squeeze_cap` and before the `drop_column` for `bb_vol_cap`, add a data migration step:

```python
    # Data migration: populate squeeze_cap from old bb_vol_cap budget
    op.execute("""
        UPDATE regime_weights SET
            trending_squeeze_cap = trending_bb_vol_cap * 0.55,
            ranging_squeeze_cap = ranging_bb_vol_cap * 0.57,
            volatile_squeeze_cap = volatile_bb_vol_cap * 0.79,
            trending_mean_rev_cap = trending_mean_rev_cap + trending_bb_vol_cap * 0.45,
            ranging_mean_rev_cap = ranging_mean_rev_cap + ranging_bb_vol_cap * 0.43,
            volatile_mean_rev_cap = volatile_mean_rev_cap + volatile_bb_vol_cap * 0.21
    """)
```

This proportionally redistributes the old `bb_vol_cap` budget into `mean_rev_cap` (BB position portion) and `squeeze_cap` (BB width portion) for any existing rows. Note: this preserves whatever the original cap sum was per regime — if volatile rows summed to 85 (pre-existing bug), they'll still sum to 85 after migration. New rows inserted after migration will use the corrected defaults that sum to 100.

**Note on backtester:** `backend/app/engine/backtester.py` calls `compute_technical_score()` without `scoring_params` — this is intentional. The backtester uses default steepness/blend values, which is correct for optimization runs.

- [ ] **Step 3: Run migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head`
Expected: Migration succeeds

- [ ] **Step 4: Verify schema**

Run: `docker exec krypton-postgres-1 psql -U postgres krypton -c "SELECT column_name FROM information_schema.columns WHERE table_name='regime_weights' AND column_name LIKE '%_cap' ORDER BY ordinal_position;"`
Expected: `squeeze_cap` columns present, `bb_vol_cap` columns absent

---

### Task 5: Implement unified mean-reversion and squeeze scoring

**Files:**
- Modify: `backend/app/engine/traditional.py:59-172`
- Test: `backend/tests/engine/test_traditional.py`

- [ ] **Step 1: Write failing tests for new scoring behavior**

Add to `backend/tests/engine/test_traditional.py`:

```python
class TestUnifiedMeanReversion:
    def test_both_oversold_stronger_than_rsi_alone(self):
        """When RSI and BB position both signal oversold, unified score > RSI-only contribution."""
        # Use ranging regime (high mean_rev_cap) to make differences visible
        df_oversold = _make_candles(80, "down")  # RSI will be low, price near lower BB
        result = compute_technical_score(df_oversold)
        indicators = result["indicators"]
        # Both debug fields should be present
        assert "mean_rev_rsi_raw" in indicators
        assert "mean_rev_bb_pos_raw" in indicators
        assert "mean_rev_score" in indicators
        assert "squeeze_score" in indicators

    def test_scoring_params_accepted(self):
        """compute_technical_score accepts optional scoring_params dict."""
        df = _make_candles(80, "up")
        params = {
            "mean_rev_rsi_steepness": 0.25,
            "mean_rev_bb_pos_steepness": 10.0,
            "squeeze_steepness": 0.10,
            "mean_rev_blend_ratio": 0.6,
        }
        result = compute_technical_score(df, scoring_params=params)
        assert -100 <= result["score"] <= 100

    def test_different_blend_ratio_changes_score(self):
        """Different blend ratios produce different mean_rev_score."""
        df = _make_candles(80, "down")
        r1 = compute_technical_score(df, scoring_params={"mean_rev_blend_ratio": 0.9})
        r2 = compute_technical_score(df, scoring_params={"mean_rev_blend_ratio": 0.1})
        # With different blend ratios on a directional dataset, mean_rev_score should differ
        assert r1["indicators"]["mean_rev_score"] != r2["indicators"]["mean_rev_score"]

    def test_squeeze_sign_matches_mean_rev_sign(self):
        """Squeeze score sign must match mean_rev_score sign (direction inheritance)."""
        for direction in ("up", "down"):
            df = _make_candles(80, direction)
            result = compute_technical_score(df)
            mr = result["indicators"]["mean_rev_score"]
            sq = result["indicators"]["squeeze_score"]
            if mr > 0:
                assert sq >= 0, f"{direction}: squeeze should be >= 0 when mean_rev > 0"
            elif mr < 0:
                assert sq <= 0, f"{direction}: squeeze should be <= 0 when mean_rev < 0"
            else:
                assert sq == 0, f"{direction}: squeeze must be 0 when mean_rev == 0"

    def test_partial_scoring_params_uses_defaults(self):
        """Missing keys in scoring_params should fall back to defaults, not crash."""
        df = _make_candles(80, "up")
        result = compute_technical_score(df, scoring_params={"mean_rev_blend_ratio": 0.8})
        assert -100 <= result["score"] <= 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestUnifiedMeanReversion -v`
Expected: FAIL — `scoring_params` not accepted, indicator keys missing

- [ ] **Step 3: Update compute_technical_score signature and scoring logic**

In `backend/app/engine/traditional.py`, update `compute_technical_score`:

**Signature** (line 59): add `scoring_params` parameter:
```python
def compute_technical_score(candles: pd.DataFrame, regime_weights=None, scoring_params: dict | None = None) -> dict:
```

**Extract params** (add after line 133, before scoring section):
```python
    # === Scoring parameters (shape + blend) ===
    sp = scoring_params or {}
    mr_rsi_steep = sp.get("mean_rev_rsi_steepness", 0.25)
    mr_bb_steep = sp.get("mean_rev_bb_pos_steepness", 10.0)
    sq_steep = sp.get("squeeze_steepness", 0.10)
    blend_ratio = sp.get("mean_rev_blend_ratio", 0.6)
```

**Replace sections 2 and 3** (lines 140-146) with:
```python
    # 2. Unified mean reversion (RSI + BB position)
    rsi_raw = sigmoid_score(50 - rsi_val, center=0, steepness=mr_rsi_steep)
    bb_pos_raw = sigmoid_score(0.5 - bb_pos, center=0, steepness=mr_bb_steep)
    mean_rev_score = (blend_ratio * rsi_raw + (1 - blend_ratio) * bb_pos_raw) * caps["mean_rev_cap"]

    # 3. Squeeze / expansion
    mean_rev_sign = 1 if mean_rev_score > 0 else (-1 if mean_rev_score < 0 else 0)
    squeeze_score = mean_rev_sign * sigmoid_score(50 - bb_width_pct, center=0, steepness=sq_steep) * caps["squeeze_cap"]
```

**Update total** (line 152):
```python
    total = trend_score + mean_rev_score + squeeze_score + obv_score + vol_score
```

**Update indicators dict** — add debug fields after `"atr"` (line 166):
```python
        "mean_rev_score": round(mean_rev_score, 2),
        "squeeze_score": round(squeeze_score, 2),
        "mean_rev_rsi_raw": round(rsi_raw, 4),
        "mean_rev_bb_pos_raw": round(bb_pos_raw, 4),
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_traditional.py::TestUnifiedMeanReversion -v`
Expected: PASS

- [ ] **Step 5: Proceed directly to Task 6**

Do NOT run the full test suite yet — existing tests still reference `bb_vol_cap` and will fail. The full suite validation happens at Task 6 Step 6 after all references are updated.

---

### Task 6: Fix all tests referencing bb_vol_cap

**Files:**
- Modify: `backend/tests/engine/test_traditional.py:247,251,255`
- Modify: `backend/tests/engine/test_regime_backtest.py:36,57`
- Modify: `backend/tests/engine/test_regime.py:58`
- Modify: `backend/tests/engine/test_regime_pipeline.py:108`
- Modify: `backend/tests/test_pipeline_ml.py:171`

- [ ] **Step 1: Update test_traditional.py mock RegimeWeights**

In `test_with_regime_weights_changes_score` (line 236), replace all `bb_vol_cap` mock attributes with `squeeze_cap`:

Lines 247, 251, 255 — change `bb_vol_cap` to `squeeze_cap`:
```python
        rw.trending_squeeze_cap = 25.0
        # ...
        rw.ranging_squeeze_cap = 25.0
        # ...
        rw.volatile_squeeze_cap = 25.0
```

- [ ] **Step 2: Update test_regime_backtest.py mock attributes**

In `backend/tests/engine/test_regime_backtest.py`, replace `bb_vol_cap` at lines 36 and 57:

Change `setattr(rw, f"{regime}_bb_vol_cap", 25.0)` to `setattr(rw, f"{regime}_squeeze_cap", 25.0)` in both locations.

- [ ] **Step 3: Update test_regime.py assertion**

In `backend/tests/engine/test_regime.py` line 58, change:
```python
assert "bb_vol_cap" in caps
```
To:
```python
assert "squeeze_cap" in caps
```

- [ ] **Step 4: Update test_regime_pipeline.py mock**

In `backend/tests/engine/test_regime_pipeline.py` line 108, change:
```python
setattr(rw, f"{regime}_bb_vol_cap", 25.0)
```
To:
```python
setattr(rw, f"{regime}_squeeze_cap", 25.0)
```

- [ ] **Step 5: Update test_pipeline_ml.py caps dict**

In `backend/tests/test_pipeline_ml.py` line 171, change `"bb_vol_cap": 25.0` to `"squeeze_cap": 25.0`.

- [ ] **Step 6: Run full test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v`
Expected: ALL PASS

---

### Task 7: Update regime_optimizer.py comments and docstring

**Files:**
- Modify: `backend/app/engine/regime_optimizer.py:23-29,53-58`

- [ ] **Step 1: Update parameter layout comments**

Replace lines 23-29:
```python
# Parameter layout:
# [0-3]   trending: trend_cap, mean_rev_cap, squeeze_cap, volume_cap
# [4-7]   ranging:  trend_cap, mean_rev_cap, squeeze_cap, volume_cap
# [8-11]  volatile: trend_cap, mean_rev_cap, squeeze_cap, volume_cap
# [12-13] trending: tech_weight, pattern_weight
# [14-15] ranging:  tech_weight, pattern_weight
# [16-17] volatile: tech_weight, pattern_weight
```

- [ ] **Step 2: Update vector_to_regime_dict docstring**

Replace line 57:
```python
    Each has: trend_cap, mean_rev_cap, squeeze_cap, volume_cap, tech, pattern.
```

- [ ] **Step 3: Verify optimizer still works**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "from app.engine.regime_optimizer import vector_to_regime_dict, regime_dict_to_vector; from app.engine.regime import DEFAULT_CAPS; d = {r: {**DEFAULT_CAPS[r], 'tech': 0.5, 'pattern': 0.5} for r in DEFAULT_CAPS}; v = regime_dict_to_vector(d); d2 = vector_to_regime_dict(v); assert 'squeeze_cap' in d2['trending']; print('OK')"`
Expected: `OK`

---

### Task 8: Wire scoring_params through main.py pipeline

**Files:**
- Modify: `backend/app/main.py:268,938-944`

- [ ] **Step 1: Load scoring params from PipelineSettings at startup**

In the PipelineSettings loading section, after the `logger.info("Pipeline settings loaded from DB")` line (line 942), add:

```python
                app.state.scoring_params = {
                    "mean_rev_rsi_steepness": ps.mean_rev_rsi_steepness,
                    "mean_rev_bb_pos_steepness": ps.mean_rev_bb_pos_steepness,
                    "squeeze_steepness": ps.squeeze_steepness,
                    "mean_rev_blend_ratio": ps.mean_rev_blend_ratio,
                }
```

In the `else` branch (line 944, `logger.warning("No PipelineSettings row found; ...")`), add after the log line:
```python
                app.state.scoring_params = None
```

- [ ] **Step 2: Pass scoring_params to compute_technical_score**

At line 268, update the call:
```python
        tech_result = compute_technical_score(
            df, regime_weights=regime_weights,
            scoring_params=getattr(app.state, "scoring_params", None),
        )
```

- [ ] **Step 3: Run full test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -v`
Expected: ALL PASS

---

### Task 9: Update signal-algorithm-improvements.md status

**Files:**
- Modify: `docs/signal-algorithm-improvements.md:68`

- [ ] **Step 1: Update status**

Change line 68 from:
```
**Status:** Not started
```
To:
```
**Status:** Implemented — see `docs/superpowers/specs/2026-03-18-indicator-redundancy-design.md`
```
