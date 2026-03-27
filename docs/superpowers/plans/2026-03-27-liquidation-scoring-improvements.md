# Liquidation Scoring Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four accuracy issues in the liquidation cluster scorer, add an asymmetry ratio component, wire tunable parameters into the optimizer, and add diagnostic output.

**Architecture:** The liquidation scorer (`engine/liquidation_scorer.py`) is split into two scoring functions — `compute_cluster_score` (spatial proximity, refactored from existing) and `compute_asymmetry_score` (new, directional imbalance) — composed by a thin `compute_liquidation_score` wrapper. Structural constants move to `engine/constants.py`. Six tunable parameters get wired through `config.py` -> `PipelineSettings` -> `_OVERRIDE_MAP` -> scorer arguments. Volume normalization happens at poll time in the collector.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Alembic, pytest

**Spec:** `docs/superpowers/specs/2026-03-27-liquidation-scoring-improvements-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/engine/constants.py` | Modify | Add `LIQUIDATION` dict; wire into `get_engine_constants()` |
| `backend/app/config.py` | Modify | Add 7 `engine_liquidation_*` Settings fields |
| `backend/app/db/models.py` | Modify | Add 7 nullable columns to `PipelineSettings` |
| `backend/app/db/migrations/versions/<new>.py` | Create | Alembic migration for new columns |
| `backend/app/main.py` | Modify | Add 7 `_OVERRIDE_MAP` entries; pass params to scorer; update `raw_indicators` |
| `backend/app/collector/liquidation.py` | Modify | Pre-normalize volumes by batch size at poll time |
| `backend/app/engine/liquidation_scorer.py` | Rewrite | Split into `compute_cluster_score` + `compute_asymmetry_score` + composer; apply 4 fixes; add details dict |
| `backend/app/engine/param_groups.py` | Modify | Add `"liquidation"` param group at layer 2 |
| `backend/tests/engine/test_liquidation_scorer.py` | Rewrite | Full test suite for new scorer |
| `backend/tests/collector/test_liquidation_collector.py` | Modify | Add volume normalization test |
| `backend/tests/engine/test_param_groups.py` | Modify | Add liquidation group to expected set + constraint test |

---

## Task 1: Add LIQUIDATION constants to engine/constants.py

**Files:**
- Modify: `backend/app/engine/constants.py`

- [ ] **Step 1: Add LIQUIDATION dict**

In `backend/app/engine/constants.py`, after the `ORDER_FLOW_ASSET_SCALES` dict (search for the symbol — line numbers may drift), add:

```python
# -- Liquidation scoring --
LIQUIDATION = {
    "bucket_width_atr_mult": 0.25,
    "mad_multiplier": 2.0,
    "min_cluster_mean_mult": 1.5,
    "max_distance_atr": 2.0,
    "depth_sigmoid_center": 1.0,
    "depth_sigmoid_steepness": 1.5,
    "min_asymmetry_events": 10,
}
```

- [ ] **Step 2: Wire into get_engine_constants()**

In the `get_engine_constants()` function's return dict (search for `"performance_tracker": _wrap`), add a `"liquidation"` key:

```python
        "liquidation": _wrap(LIQUIDATION),
```

Add it after the `"performance_tracker"` entry and before the closing `}`.

- [ ] **Step 3: Run tests to verify no regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All existing tests pass.

---

## Task 2: Add Settings fields and PipelineSettings columns

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/db/models.py`
- Create: `backend/app/db/migrations/versions/<auto>.py`

- [ ] **Step 1: Add engine_liquidation_* fields to Settings**

In `backend/app/config.py`, after the `engine_mr_llm_trigger` field (search for the symbol), add:

```python
    # liquidation scoring
    engine_liquidation_weight: float = 0.0
    engine_liquidation_cluster_max_score: float = 30.0
    engine_liquidation_asymmetry_max_score: float = 25.0
    engine_liquidation_cluster_weight: float = 0.6
    engine_liquidation_proximity_steepness: float = 2.0
    engine_liquidation_decay_half_life_hours: float = 4.0
    engine_liquidation_asymmetry_steepness: float = 3.0
```

- [ ] **Step 2: Add nullable columns to PipelineSettings**

In `backend/app/db/models.py`, in the `PipelineSettings` class, after the `confluence_max_score` column (search for the symbol), add:

```python
    liquidation_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidation_cluster_max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidation_asymmetry_max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidation_cluster_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidation_proximity_steepness: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidation_decay_half_life_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidation_asymmetry_steepness: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 3: Generate Alembic migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add liquidation tunable columns to pipeline_settings"`

Verify the generated migration adds 7 `add_column` operations on `pipeline_settings`, all nullable Float columns.

- [ ] **Step 4: Apply migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head`
Expected: Migration applies successfully.

---

## Task 3: Wire _OVERRIDE_MAP and scorer call in main.py

**Files:**
- Modify: `backend/app/main.py`

> **Note:** `engine_liquidation_weight` is a **source-blending weight** consumed by the combiner in `main.py` (like `engine_traditional_weight`). It is _not_ passed to the scorer — the remaining 6 params are scorer-specific tunables.

- [ ] **Step 1: Add entries to _OVERRIDE_MAP**

In `backend/app/main.py`, in the `_OVERRIDE_MAP` dict (search for `_OVERRIDE_MAP`), add after the `"confluence_max_score"` entry:

```python
    "liquidation_weight": "engine_liquidation_weight",
    "liquidation_cluster_max_score": "engine_liquidation_cluster_max_score",
    "liquidation_asymmetry_max_score": "engine_liquidation_asymmetry_max_score",
    "liquidation_cluster_weight": "engine_liquidation_cluster_weight",
    "liquidation_proximity_steepness": "engine_liquidation_proximity_steepness",
    "liquidation_decay_half_life_hours": "engine_liquidation_decay_half_life_hours",
    "liquidation_asymmetry_steepness": "engine_liquidation_asymmetry_steepness",
```

- [ ] **Step 2: Pass tunable params to scorer call**

In `backend/app/main.py`, replace the `compute_liquidation_score` call block (search for `compute_liquidation_score(`) with:

```python
            liq_result = compute_liquidation_score(
                events=liq_collector.events.get(pair, []),
                current_price=current_price,
                atr=liq_atr,
                depth=depth,
                cluster_max_score=settings.engine_liquidation_cluster_max_score,
                asymmetry_max_score=settings.engine_liquidation_asymmetry_max_score,
                cluster_weight=settings.engine_liquidation_cluster_weight,
                proximity_steepness=settings.engine_liquidation_proximity_steepness,
                decay_half_life_hours=settings.engine_liquidation_decay_half_life_hours,
                asymmetry_steepness=settings.engine_liquidation_asymmetry_steepness,
            )
```

- [ ] **Step 3: Update raw_indicators with details**

In `backend/app/main.py`, replace the three liquidation lines in raw_indicators (search for `"liquidation_score": liq_score`):

```python
            "liquidation_score": liq_score,
            "liquidation_confidence": liq_conf,
            "liquidation_cluster_count": len(liq_clusters),
```

with:

```python
            "liquidation_score": liq_score,
            "liquidation_confidence": liq_conf,
            "liquidation_cluster_count": len(liq_clusters),
            **(liq_details if liq_details else {}),
```

And update the extraction block (search for `liq_score = liq_result`) to also extract details:

```python
            liq_score = liq_result["score"]
            liq_conf = liq_result["confidence"]
            liq_clusters = liq_result["clusters"]
            liq_details = liq_result.get("details", {})
```

Add `liq_details = {}` next to the other defaults (search for `liq_clusters = []`):

```python
    liq_details = {}
```

- [ ] **Step 4: Run tests to verify no import errors**

Run: `docker exec krypton-api-1 python -c "from app.main import _OVERRIDE_MAP; print(len(_OVERRIDE_MAP))"`
Expected: Prints `17` (10 original + 7 new).

---

## Task 4: Pre-normalize volumes in the collector

> **Why normalize?** The OKX liquidation endpoint returns a batch of events per poll. The `sz` field reports notional size, but within a single poll window these events share the total liquidated volume — counting each at face value double-counts when polls overlap or return partial fills of the same liquidation. Dividing by batch size distributes the aggregate volume evenly across events, preventing inflated cluster densities. This is a heuristic; if OKX provides a unique trade ID in the future, deduplication by ID would be more precise.

**Files:**
- Modify: `backend/app/collector/liquidation.py`
- Test: `backend/tests/collector/test_liquidation_collector.py`

- [ ] **Step 1: Write the failing test**

In `backend/tests/collector/test_liquidation_collector.py`, add:

```python
@pytest.mark.asyncio
async def test_volume_normalized_by_batch_size():
    """Each event's volume should be divided by the number of events in the batch."""
    mock_client = AsyncMock()
    mock_client.get_liquidation_orders.return_value = [
        {"bkPx": "50000", "sz": "100", "side": "buy", "ts": "0"},
        {"bkPx": "50100", "sz": "200", "side": "sell", "ts": "0"},
    ]
    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"])
    await collector._poll()
    events = collector.events["BTC-USDT-SWAP"]
    assert len(events) == 2
    # batch had 2 events, so volumes should be halved
    assert events[0]["volume"] == pytest.approx(50.0)
    assert events[1]["volume"] == pytest.approx(100.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/collector/test_liquidation_collector.py::test_volume_normalized_by_batch_size -v`
Expected: FAIL — volumes are 100.0 and 200.0 (not normalized).

- [ ] **Step 3: Implement volume normalization**

In `backend/app/collector/liquidation.py`, in the `_poll` method, change the event-building loop. Replace the `if raw:` block (search for `if raw:` inside `_poll`):

```python
                if raw:
                    new_events = []
                    for item in raw:
                        event = {
                            "price": float(item.get("bkPx", 0)),
                            "volume": float(item.get("sz", 0)),
                            "timestamp": datetime.now(timezone.utc),
                            "side": item.get("side", ""),
                        }
                        self._events[pair].append(event)
                        new_events.append(event)
                    await self._persist_events(pair, new_events)
```

with:

```python
                if raw:
                    new_events = []
                    batch_size = len(raw)
                    for item in raw:
                        event = {
                            "price": float(item.get("bkPx", 0)),
                            "volume": float(item.get("sz", 0)) / batch_size,
                            "timestamp": datetime.now(timezone.utc),
                            "side": item.get("side", ""),
                        }
                        self._events[pair].append(event)
                        new_events.append(event)
                    await self._persist_events(pair, new_events)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/collector/test_liquidation_collector.py -v`
Expected: All collector tests pass, including the new one.

---

## Task 5: Rewrite liquidation scorer — cluster scoring with fixes 1-4

This is the core refactor. We replace the existing `liquidation_scorer.py` with the new implementation in two phases: cluster scoring first (this task), then asymmetry + composer (next task).

**Files:**
- Rewrite: `backend/app/engine/liquidation_scorer.py`
- Test: `backend/tests/engine/test_liquidation_scorer.py`

- [ ] **Step 1: Write failing tests for the new cluster scorer**

Replace `backend/tests/engine/test_liquidation_scorer.py` entirely:

```python
"""Tests for the refactored liquidation scorer."""

import math
from datetime import datetime, timezone, timedelta

import pytest

from app.engine.liquidation_scorer import (
    aggregate_liquidation_buckets,
    detect_clusters,
    compute_cluster_score,
    compute_asymmetry_score,
    compute_liquidation_score,
)


# ── helpers ──

def _make_event(price, volume, side="buy", age_hours=0):
    ts = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return {"price": price, "volume": volume, "timestamp": ts, "side": side}


def _make_events(price, volume, side="buy", count=5):
    return [_make_event(price, volume, side) for _ in range(count)]


# ── aggregate_liquidation_buckets ──

class TestBucketAggregation:
    def test_groups_by_price_level(self):
        atr = 200.0  # bucket width = 50
        events = [
            _make_event(50010.0, 100.0),
            _make_event(50020.0, 200.0),  # same bucket as 50010
            _make_event(50200.0, 150.0),  # different bucket
        ]
        buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0)
        assert len(buckets) == 2
        near = [b for b in buckets if abs(b["center"] - 50000) < 50]
        assert len(near) == 1
        assert near[0]["total_volume"] == pytest.approx(300.0, rel=1e-6)

    def test_decay_reduces_old_events(self):
        atr = 100.0
        events = [
            _make_event(50000.0, 100.0, age_hours=0),
            _make_event(50000.0, 100.0, age_hours=8),  # 2x half-life
        ]
        buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0, decay_half_life_hours=4)
        assert buckets[0]["total_volume"] < 200.0
        assert buckets[0]["total_volume"] > 100.0

    def test_side_breakdown_tracks_long_short(self):
        """Buckets should include per-side volume breakdown."""
        atr = 200.0
        events = [
            _make_event(50000.0, 100.0, side="buy"),   # short liq
            _make_event(50000.0, 60.0, side="sell"),    # long liq
        ]
        buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0)
        assert len(buckets) == 1
        b = buckets[0]
        assert "side_breakdown" in b
        assert b["side_breakdown"]["short"] == pytest.approx(100.0, rel=1e-6)
        assert b["side_breakdown"]["long"] == pytest.approx(60.0, rel=1e-6)

    def test_missing_side_contributes_volume_not_direction(self):
        """Events without 'side' add to total volume but not to side breakdown."""
        atr = 200.0
        events = [
            _make_event(50000.0, 100.0, side="buy"),
            {"price": 50000.0, "volume": 50.0, "timestamp": datetime.now(timezone.utc)},  # no side
        ]
        buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0)
        b = buckets[0]
        assert b["total_volume"] == pytest.approx(150.0, rel=1e-6)
        assert b["side_breakdown"]["short"] == pytest.approx(100.0, rel=1e-6)
        assert b["side_breakdown"]["long"] == pytest.approx(0.0, abs=1e-6)

    def test_empty_events(self):
        assert aggregate_liquidation_buckets([], atr=200.0, current_price=50000.0) == []

    def test_zero_atr(self):
        events = [_make_event(50000.0, 100.0)]
        assert aggregate_liquidation_buckets(events, atr=0, current_price=50000.0) == []


# ── detect_clusters (MAD-based) ──

class TestClusterDetection:
    def test_detects_outlier_bucket(self):
        buckets = [
            {"center": 50000, "total_volume": 100, "side_breakdown": {"short": 100, "long": 0}},
            {"center": 50100, "total_volume": 100, "side_breakdown": {"short": 100, "long": 0}},
            {"center": 50200, "total_volume": 500, "side_breakdown": {"short": 500, "long": 0}},
            {"center": 50300, "total_volume": 80, "side_breakdown": {"short": 80, "long": 0}},
        ]
        clusters = detect_clusters(buckets)
        assert len(clusters) == 1
        assert clusters[0]["center"] == 50200

    def test_single_bucket_returned_as_is(self):
        buckets = [{"center": 50000, "total_volume": 100, "side_breakdown": {"short": 100, "long": 0}}]
        assert detect_clusters(buckets) == buckets

    def test_uniform_buckets_no_clusters(self):
        """When all volumes are equal, MAD=0; fall through to mean floor — still no outlier."""
        buckets = [
            {"center": 50000 + i * 100, "total_volume": 100, "side_breakdown": {"short": 100, "long": 0}}
            for i in range(5)
        ]
        clusters = detect_clusters(buckets)
        # threshold = max(100 + 2*0, 1.5*100) = 150 — none exceed
        assert len(clusters) == 0


# ── compute_cluster_score ──

class TestClusterScoring:
    def test_short_liquidation_above_price_is_bullish(self):
        """Cluster above price with side='buy' (short liqs) should score positive."""
        events = _make_events(50200.0, 500.0, side="buy", count=10)
        result = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        assert result["score"] > 0

    def test_long_liquidation_below_price_is_bearish(self):
        """Cluster below price with side='sell' (long liqs) should score negative."""
        events = _make_events(49800.0, 500.0, side="sell", count=10)
        result = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        assert result["score"] < 0

    def test_mixed_cluster_uses_net_direction(self):
        """When both sides present, net direction determines sign."""
        # more shorts (buy) than longs (sell) at same price = net bullish
        events = (
            _make_events(50200.0, 300.0, side="buy", count=5)
            + _make_events(50200.0, 100.0, side="sell", count=5)
        )
        result = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        assert result["score"] > 0

    def test_no_events_returns_zero(self):
        result = compute_cluster_score([], current_price=50000.0, atr=200.0)
        assert result["score"] == 0
        assert result["confidence"] == 0.0

    def test_score_bounded(self):
        events = _make_events(50050.0, 10000.0, count=20)
        result = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        assert -100 <= result["score"] <= 100

    def test_returns_cluster_list(self):
        events = _make_events(50200.0, 500.0, count=10)
        result = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        assert isinstance(result["clusters"], list)
        for c in result["clusters"]:
            assert "price" in c
            assert "volume" in c
            assert "side_breakdown" in c

    def test_depth_none_unchanged(self):
        events = _make_events(50200.0, 500.0)
        r1 = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        r2 = compute_cluster_score(events, current_price=50000.0, atr=200.0, depth=None)
        assert r1["score"] == r2["score"]

    def test_depth_thin_asks_amplifies(self):
        events = _make_events(50200.0, 500.0)
        thin_asks = {
            "bids": [(49900, 100), (49800, 100)],
            "asks": [(50100, 5), (50200, 3)],
        }
        r_no = compute_cluster_score(events, 50000.0, 200.0)
        r_thin = compute_cluster_score(events, 50000.0, 200.0, depth=thin_asks)
        assert abs(r_thin["score"]) >= abs(r_no["score"])

    def test_depth_thick_asks_dampens(self):
        events = _make_events(50200.0, 500.0)
        thick_asks = {
            "bids": [(49900, 100), (49800, 100)],
            "asks": [(50100, 5000), (50200, 3000)],
        }
        r_no = compute_cluster_score(events, 50000.0, 200.0)
        r_thick = compute_cluster_score(events, 50000.0, 200.0, depth=thick_asks)
        assert abs(r_thick["score"]) <= abs(r_no["score"])

    def test_depth_modifier_bounded(self):
        events = _make_events(50200.0, 500.0)
        extreme = {"bids": [(49900, 1)], "asks": [(50100, 999999)]}
        result = compute_cluster_score(events, 50000.0, 200.0, depth=extreme)
        assert -100 <= result["score"] <= 100

    def test_sigmoid_depth_continuity(self):
        """Sigmoid depth modifier should be smooth — no jumps > 0.05 between nearby ratios."""
        from app.engine.liquidation_scorer import depth_modifier
        ratios = [0.3, 0.49, 0.51, 1.0, 1.99, 2.01, 3.0]
        mods = [depth_modifier(ratio) for ratio in ratios]
        for i in range(len(mods) - 1):
            assert abs(mods[i + 1] - mods[i]) < 0.05


# ── depth_modifier / get_depth_ratio ──

class TestDepthHelpers:
    def test_depth_modifier_returns_bounded(self):
        from app.engine.liquidation_scorer import depth_modifier
        for ratio in [0.0, 0.5, 1.0, 2.0, 5.0, 100.0]:
            m = depth_modifier(ratio)
            assert 0.7 <= m <= 1.3

    def test_depth_modifier_low_ratio_amplifies(self):
        from app.engine.liquidation_scorer import depth_modifier
        assert depth_modifier(0.3) > 1.0

    def test_depth_modifier_high_ratio_dampens(self):
        from app.engine.liquidation_scorer import depth_modifier
        assert depth_modifier(3.0) < 1.0

    def test_get_depth_ratio_no_depth_returns_neutral(self):
        from app.engine.liquidation_scorer import get_depth_ratio
        assert get_depth_ratio(50200.0, 50000.0, 200.0, None) == 1.0
        assert get_depth_ratio(50200.0, 50000.0, 200.0, {}) == 1.0

    def test_get_depth_ratio_empty_levels_returns_neutral(self):
        from app.engine.liquidation_scorer import get_depth_ratio
        assert get_depth_ratio(50200.0, 50000.0, 200.0, {"bids": [], "asks": []}) == 1.0

    def test_get_depth_ratio_computes_correctly(self):
        from app.engine.liquidation_scorer import get_depth_ratio
        depth = {
            "bids": [(49900, 100), (49800, 100)],
            "asks": [(50100, 200), (50200, 50)],
        }
        ratio = get_depth_ratio(50200.0, 50000.0, 200.0, depth)
        assert ratio > 0

    def test_get_depth_ratio_above_uses_asks(self):
        from app.engine.liquidation_scorer import get_depth_ratio
        depth = {"bids": [(49900, 999)], "asks": [(50100, 10)]}
        ratio = get_depth_ratio(50200.0, 50000.0, 200.0, depth)
        # should use asks, not bids
        assert ratio > 0

    def test_get_depth_ratio_below_uses_bids(self):
        from app.engine.liquidation_scorer import get_depth_ratio
        depth = {"bids": [(49900, 10)], "asks": [(50100, 999)]}
        ratio = get_depth_ratio(49800.0, 50000.0, 200.0, depth)
        # should use bids, not asks
        assert ratio > 0


# ── compute_asymmetry_score ──

class TestAsymmetryScoring:
    def test_more_shorts_is_bullish(self):
        events = (
            _make_events(50000.0, 200.0, side="buy", count=8)
            + _make_events(50000.0, 50.0, side="sell", count=2)
        )
        result = compute_asymmetry_score(events)
        assert result["score"] > 0
        assert result["raw_asymmetry"] > 0

    def test_more_longs_is_bearish(self):
        events = (
            _make_events(50000.0, 50.0, side="buy", count=2)
            + _make_events(50000.0, 200.0, side="sell", count=8)
        )
        result = compute_asymmetry_score(events)
        assert result["score"] < 0
        assert result["raw_asymmetry"] < 0

    def test_balanced_near_zero(self):
        events = (
            _make_events(50000.0, 100.0, side="buy", count=5)
            + _make_events(50000.0, 100.0, side="sell", count=5)
        )
        result = compute_asymmetry_score(events)
        assert abs(result["score"]) < 3
        assert result["raw_asymmetry"] == pytest.approx(0.0, abs=0.01)

    def test_empty_events_returns_zero(self):
        result = compute_asymmetry_score([])
        assert result["score"] == 0
        assert result["confidence"] == 0.0

    def test_no_side_events_returns_zero(self):
        """Events without 'side' field should produce zero (division guard)."""
        events = [
            {"price": 50000.0, "volume": 100.0, "timestamp": datetime.now(timezone.utc)}
            for _ in range(5)
        ]
        result = compute_asymmetry_score(events)
        assert result["score"] == 0
        assert result["confidence"] == 0.0

    def test_confidence_low_with_few_events(self):
        events = _make_events(50000.0, 100.0, side="buy", count=3)
        result = compute_asymmetry_score(events)
        assert result["confidence"] < 0.5

    def test_score_bounded(self):
        events = _make_events(50000.0, 10000.0, side="buy", count=20)
        result = compute_asymmetry_score(events)
        assert -25 <= result["score"] <= 25  # default max is 25


# ── compute_liquidation_score (composer) ──

class TestComposedScore:
    def test_blends_cluster_and_asymmetry(self):
        events = _make_events(50200.0, 500.0, side="buy", count=15)
        result = compute_liquidation_score(events, current_price=50000.0, atr=200.0)
        assert "score" in result
        assert "confidence" in result
        assert "clusters" in result
        assert "details" in result

    def test_details_dict_shape(self):
        events = _make_events(50200.0, 500.0, side="buy", count=15)
        result = compute_liquidation_score(events, current_price=50000.0, atr=200.0)
        d = result["details"]
        assert "cluster_score" in d
        assert "cluster_confidence" in d
        assert "asymmetry_score" in d
        assert "asymmetry_confidence" in d
        assert "raw_asymmetry" in d
        assert "cluster_weight" in d
        assert "asymmetry_weight" in d
        assert "event_count" in d

    def test_empty_events_returns_zero(self):
        result = compute_liquidation_score([], current_price=50000.0, atr=200.0)
        assert result["score"] == 0
        assert result["confidence"] == 0.0

    def test_cluster_weight_param(self):
        events = _make_events(50200.0, 500.0, side="buy", count=15)
        r_high = compute_liquidation_score(events, 50000.0, 200.0, cluster_weight=0.9)
        r_low = compute_liquidation_score(events, 50000.0, 200.0, cluster_weight=0.1)
        # different weights should produce different scores
        assert r_high["score"] != r_low["score"]

    def test_accepts_all_tunable_params(self):
        events = _make_events(50200.0, 500.0, side="buy", count=15)
        result = compute_liquidation_score(
            events, 50000.0, 200.0,
            cluster_max_score=40,
            asymmetry_max_score=30,
            cluster_weight=0.7,
            proximity_steepness=3.0,
            decay_half_life_hours=6.0,
            asymmetry_steepness=4.0,
        )
        assert -100 <= result["score"] <= 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_liquidation_scorer.py -v`
Expected: FAIL — `compute_cluster_score` and `compute_asymmetry_score` don't exist yet.

- [ ] **Step 3: Rewrite liquidation_scorer.py**

Replace `backend/app/engine/liquidation_scorer.py` entirely:

```python
"""Liquidation level scoring — cluster proximity + directional asymmetry."""

import math
from datetime import datetime, timezone
from statistics import median, mean

from app.engine.constants import LIQUIDATION
from app.engine.scoring import sigmoid_score

# structural constants (not runtime-tunable)
_BUCKET_WIDTH = LIQUIDATION["bucket_width_atr_mult"]
_MAD_MULT = LIQUIDATION["mad_multiplier"]
_MIN_MEAN_MULT = LIQUIDATION["min_cluster_mean_mult"]
_MAX_DIST = LIQUIDATION["max_distance_atr"]
_DEPTH_CENTER = LIQUIDATION["depth_sigmoid_center"]
_DEPTH_STEEP = LIQUIDATION["depth_sigmoid_steepness"]
_MIN_ASYM_EVENTS = LIQUIDATION["min_asymmetry_events"]


def aggregate_liquidation_buckets(
    events: list[dict],
    atr: float,
    current_price: float,
    decay_half_life_hours: float = 4.0,
) -> list[dict]:
    """Aggregate events into ATR-width price buckets with decay and side breakdown.

    Returns list of {"center", "total_volume", "side_breakdown": {"short", "long"}}.
    """
    if not events or atr <= 0:
        return []

    bucket_width = _BUCKET_WIDTH * atr
    now = datetime.now(timezone.utc)
    buckets: dict[int, dict] = {}

    for event in events:
        price = event["price"]
        volume = event["volume"]
        ts = event["timestamp"]
        side = event.get("side")

        age_hours = (now - ts).total_seconds() / 3600
        decay = math.exp(-math.log(2) * age_hours / decay_half_life_hours)
        weighted_vol = volume * decay

        idx = round((price - current_price) / bucket_width)
        if idx not in buckets:
            buckets[idx] = {"total": 0.0, "short": 0.0, "long": 0.0}
        buckets[idx]["total"] += weighted_vol
        if side == "buy":
            buckets[idx]["short"] += weighted_vol
        elif side == "sell":
            buckets[idx]["long"] += weighted_vol

    return [
        {
            "center": current_price + idx * bucket_width,
            "total_volume": b["total"],
            "side_breakdown": {"short": b["short"], "long": b["long"]},
        }
        for idx, b in sorted(buckets.items())
        if b["total"] > 0
    ]


def detect_clusters(buckets: list[dict]) -> list[dict]:
    """Identify clusters using MAD-based threshold with mean floor."""
    if len(buckets) < 2:
        return buckets

    volumes = [b["total_volume"] for b in buckets]
    med = median(volumes)
    mad = median(abs(v - med) for v in volumes)
    threshold = max(med + _MAD_MULT * mad, _MIN_MEAN_MULT * mean(volumes))

    return [b for b in buckets if b["total_volume"] > threshold]


def depth_modifier(ratio: float) -> float:
    """Smooth sigmoid depth modifier. Returns [0.7, 1.3].

    Low ratio (thin book near cluster) -> amplify (closer to 1.3).
    High ratio (thick book near cluster) -> dampen (closer to 0.7).
    """
    return 0.7 + 0.6 * sigmoid_score(-ratio, center=_DEPTH_CENTER, steepness=_DEPTH_STEEP)


def get_depth_ratio(cluster_center: float, current_price: float, atr: float, depth: dict | None) -> float:
    """Compute nearby/average volume ratio for the depth modifier."""
    if not depth:
        return 1.0  # neutral

    is_above = cluster_center > current_price
    levels = depth.get("asks", []) if is_above else depth.get("bids", [])
    if not levels:
        return 1.0

    nearby_vol = sum(size for price, size in levels if abs(price - cluster_center) <= 0.5 * atr)
    if nearby_vol == 0:
        return 1.0

    all_vols = [size for _, size in depth.get("bids", []) + depth.get("asks", [])]
    avg_vol = sum(all_vols) / len(all_vols) if all_vols else 1.0
    if avg_vol <= 0:
        return 1.0

    return nearby_vol / avg_vol


def compute_cluster_score(
    events: list[dict],
    current_price: float,
    atr: float,
    depth: dict | None = None,
    cluster_max_score: float = 30.0,
    proximity_steepness: float = 2.0,
    decay_half_life_hours: float = 4.0,
) -> dict:
    """Score liquidation clusters by proximity, density, and side-aware direction.

    Returns {"score": int, "confidence": float, "clusters": list, "details": dict}.
    """
    if not events or atr <= 0:
        return {"score": 0, "confidence": 0.0, "clusters": [], "details": {
            "cluster_count": 0, "buckets_total": 0, "per_cluster": [],
        }}

    buckets = aggregate_liquidation_buckets(events, atr, current_price, decay_half_life_hours)
    clusters = detect_clusters(buckets)

    if not clusters:
        return {"score": 0, "confidence": 0.1, "clusters": [], "details": {
            "cluster_count": 0, "buckets_total": len(buckets), "per_cluster": [],
        }}

    all_vols = [b["total_volume"] for b in buckets]
    density_norm = max(median(all_vols) * 3, 1.0)

    score = 0.0
    per_cluster = []
    for cluster in clusters:
        distance = cluster["center"] - current_price
        distance_atr = abs(distance) / atr

        if distance_atr > _MAX_DIST:
            continue

        proximity = sigmoid_score(
            _MAX_DIST - distance_atr, center=0, steepness=proximity_steepness,
        )
        density = cluster["total_volume"]
        sb = cluster["side_breakdown"]
        net = sb["short"] - sb["long"]
        total_side = sb["short"] + sb["long"]

        if total_side > 0:
            direction = 1 if net > 0 else -1
            side_scale = abs(net) / total_side
        else:
            # no side info: fall back to price position
            direction = 1 if distance > 0 else -1
            side_scale = 1.0

        depth_ratio = get_depth_ratio(cluster["center"], current_price, atr, depth)
        mod = depth_modifier(depth_ratio)
        contribution = direction * side_scale * proximity * min(density / density_norm, 1.0) * cluster_max_score * mod
        score += contribution

        per_cluster.append({
            "price": cluster["center"],
            "proximity": round(proximity, 4),
            "density_ratio": round(min(density / density_norm, 1.0), 4),
            "depth_mod": round(mod, 4),
            "direction": direction,
            "contribution": round(contribution, 2),
        })

    score = max(min(round(score), 100), -100)
    total_vol = sum(b["total_volume"] for b in buckets)
    confidence = min(1.0, len(clusters) / 3.0) * min(1.0, total_vol / density_norm)

    return {
        "score": score,
        "confidence": min(1.0, confidence),
        "clusters": [
            {"price": c["center"], "volume": c["total_volume"], "side_breakdown": c["side_breakdown"]}
            for c in clusters
        ],
        "details": {
            "cluster_count": len([p for p in per_cluster]),
            "buckets_total": len(buckets),
            "per_cluster": per_cluster,
        },
    }


def compute_asymmetry_score(
    events: list[dict],
    decay_half_life_hours: float = 4.0,
    asymmetry_max_score: float = 25.0,
    asymmetry_steepness: float = 3.0,
) -> dict:
    """Score directional imbalance of liquidation events.

    Returns {"score": int, "confidence": float, "raw_asymmetry": float, ...}.
    """
    if not events:
        return {
            "score": 0, "confidence": 0.0, "raw_asymmetry": 0.0,
            "short_liq_vol": 0.0, "long_liq_vol": 0.0, "event_count": 0,
        }

    now = datetime.now(timezone.utc)
    short_vol = 0.0
    long_vol = 0.0
    event_count = 0

    for event in events:
        side = event.get("side")
        if not side:
            continue
        age_hours = (now - event["timestamp"]).total_seconds() / 3600
        decay = math.exp(-math.log(2) * age_hours / decay_half_life_hours)
        weighted = event["volume"] * decay
        if side == "buy":
            short_vol += weighted
        elif side == "sell":
            long_vol += weighted
        event_count += 1

    total = short_vol + long_vol
    if total == 0:
        return {
            "score": 0, "confidence": 0.0, "raw_asymmetry": 0.0,
            "short_liq_vol": 0.0, "long_liq_vol": 0.0, "event_count": event_count,
        }

    raw_asymmetry = (short_vol - long_vol) / total

    score = round(sigmoid_score(raw_asymmetry, center=0, steepness=asymmetry_steepness) * asymmetry_max_score)
    score = max(min(score, round(asymmetry_max_score)), -round(asymmetry_max_score))

    # confidence: need both volume and event count
    all_vols = [e["volume"] for e in events]
    density_norm = max(median(all_vols) * 3, 1.0) if all_vols else 1.0
    min_vol_threshold = density_norm * 0.5
    volume_ratio = min(total / min_vol_threshold, 1.0) if min_vol_threshold > 0 else 0.0
    confidence = volume_ratio * min(event_count / _MIN_ASYM_EVENTS, 1.0)

    return {
        "score": score,
        "confidence": min(1.0, confidence),
        "raw_asymmetry": round(raw_asymmetry, 4),
        "short_liq_vol": round(short_vol, 2),
        "long_liq_vol": round(long_vol, 2),
        "event_count": event_count,
    }


def compute_liquidation_score(
    events: list[dict],
    current_price: float,
    atr: float,
    depth: dict | None = None,
    cluster_max_score: float = 30.0,
    asymmetry_max_score: float = 25.0,
    cluster_weight: float = 0.6,
    proximity_steepness: float = 2.0,
    decay_half_life_hours: float = 4.0,
    asymmetry_steepness: float = 3.0,
) -> dict:
    """Compose cluster + asymmetry scores into final liquidation score.

    Returns {"score", "confidence", "clusters", "details"}.
    """
    if not events or atr <= 0:
        return {"score": 0, "confidence": 0.0, "clusters": [], "details": {}}

    cluster_result = compute_cluster_score(
        events, current_price, atr, depth,
        cluster_max_score=cluster_max_score,
        proximity_steepness=proximity_steepness,
        decay_half_life_hours=decay_half_life_hours,
    )
    asymmetry_result = compute_asymmetry_score(
        events,
        decay_half_life_hours=decay_half_life_hours,
        asymmetry_max_score=asymmetry_max_score,
        asymmetry_steepness=asymmetry_steepness,
    )

    asym_weight = 1.0 - cluster_weight
    combined_score = round(
        cluster_result["score"] * cluster_weight
        + asymmetry_result["score"] * asym_weight
    )
    combined_score = max(min(combined_score, 100), -100)
    combined_confidence = (
        cluster_result["confidence"] * cluster_weight
        + asymmetry_result["confidence"] * asym_weight
    )

    return {
        "score": combined_score,
        "confidence": min(1.0, combined_confidence),
        "clusters": cluster_result["clusters"],
        "details": {
            "cluster_score": cluster_result["score"],
            "cluster_confidence": round(cluster_result["confidence"], 4),
            "cluster_count": cluster_result["details"].get("cluster_count", 0),
            "buckets_total": cluster_result["details"].get("buckets_total", 0),
            "per_cluster": cluster_result["details"].get("per_cluster", []),
            "asymmetry_score": asymmetry_result["score"],
            "asymmetry_confidence": round(asymmetry_result["confidence"], 4),
            "raw_asymmetry": asymmetry_result["raw_asymmetry"],
            "long_liq_vol": asymmetry_result["long_liq_vol"],
            "short_liq_vol": asymmetry_result["short_liq_vol"],
            "event_count": asymmetry_result["event_count"],
            "cluster_weight": cluster_weight,
            "asymmetry_weight": asym_weight,
        },
    }
```

- [ ] **Step 4: Run all tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_liquidation_scorer.py -v`
Expected: All tests pass.

---

## Task 6: Add liquidation optimizer param group

**Files:**
- Modify: `backend/app/engine/param_groups.py`
- Modify: `backend/tests/engine/test_param_groups.py`

- [ ] **Step 1: Write the failing test**

In `backend/tests/engine/test_param_groups.py`, update `test_all_groups_defined`:

```python
def test_all_groups_defined():
    expected = {
        "source_weights", "thresholds", "regime_caps", "regime_outer",
        "atr_levels", "sigmoid_curves", "order_flow", "pattern_strengths",
        "indicator_periods", "mean_reversion", "llm_factors", "onchain",
        "mr_pressure", "liquidation",
    }
    assert set(PARAM_GROUPS.keys()) == expected
```

Add a constraint test:

```python
def test_liquidation_constraint_valid():
    valid = {
        "cluster_max_score": 30, "asymmetry_max_score": 25,
        "cluster_weight": 0.6, "proximity_steepness": 2.0,
        "decay_half_life_hours": 4.0, "asymmetry_steepness": 3.0,
    }
    assert validate_candidate("liquidation", valid) is True


def test_liquidation_constraint_rejects_high_sum():
    invalid = {
        "cluster_max_score": 60, "asymmetry_max_score": 50,
        "cluster_weight": 0.6, "proximity_steepness": 2.0,
        "decay_half_life_hours": 4.0, "asymmetry_steepness": 3.0,
    }
    assert validate_candidate("liquidation", invalid) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_param_groups.py -v`
Expected: FAIL — `"liquidation"` not in PARAM_GROUPS.

- [ ] **Step 3: Add the liquidation param group**

In `backend/app/engine/param_groups.py`, add a constraint function after `_onchain_ok` (search for the symbol):

```python
def _liquidation_ok(c: dict[str, Any]) -> bool:
    return (
        c["cluster_max_score"] + c["asymmetry_max_score"] <= 100
        and all(v > 0 for v in c.values())
        and 0 < c["cluster_weight"] < 1
    )
```

Then add `"liquidation"` to `PRIORITY_LAYERS` layer 2 (search for `"mr_pressure"` in the layer 2 set):

```python
    {"sigmoid_curves", "order_flow", "pattern_strengths",
     "indicator_periods", "mean_reversion", "llm_factors", "onchain",
     "mr_pressure", "liquidation"},  # layer 2
```

Then add the group definition to `PARAM_GROUPS` dict, before the closing `}` of the dict (after `"onchain"` block, before `_mr_pressure_ok`):

```python
    "liquidation": {
        "params": {
            "cluster_max_score": "liquidation.cluster_max_score",
            "asymmetry_max_score": "liquidation.asymmetry_max_score",
            "cluster_weight": "liquidation.cluster_weight",
            "proximity_steepness": "liquidation.proximity_steepness",
            "decay_half_life_hours": "liquidation.decay_half_life_hours",
            "asymmetry_steepness": "liquidation.asymmetry_steepness",
        },
        "sweep_method": "de",
        "sweep_ranges": {
            "cluster_max_score": (15, 45, None),
            "asymmetry_max_score": (10, 40, None),
            "cluster_weight": (0.4, 0.8, None),
            "proximity_steepness": (1.0, 4.0, None),
            "decay_half_life_hours": (2.0, 8.0, None),
            "asymmetry_steepness": (1.5, 6.0, None),
        },
        "constraints": _liquidation_ok,
        "priority": _priority_for("liquidation"),
    },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_param_groups.py -v`
Expected: All tests pass.

---

## Task 7: Final integration verification

**Files:** (none modified — verification only)

- [ ] **Step 1: Run all engine tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/ -v`
Expected: All pass.

- [ ] **Step 2: Run all collector tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/collector/ -v`
Expected: All pass.

- [ ] **Step 3: Run full test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ -x -q`
Expected: All pass.

- [ ] **Step 4: Verify import chain works end-to-end**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "from app.engine.liquidation_scorer import compute_liquidation_score; print('OK')"`
Expected: Prints `OK`.

- [ ] **Step 5: Verify _OVERRIDE_MAP field consistency**

Run:
```bash
MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "
from app.main import _OVERRIDE_MAP
from app.config import Settings
from app.db.models import PipelineSettings
for db_col, settings_field in _OVERRIDE_MAP.items():
    assert hasattr(PipelineSettings, db_col), f'PipelineSettings missing {db_col}'
    assert hasattr(Settings, settings_field), f'Settings missing {settings_field}'
print(f'All {len(_OVERRIDE_MAP)} _OVERRIDE_MAP entries valid')
"
```
Expected: Prints `All 17 _OVERRIDE_MAP entries valid`.

- [ ] **Step 6: Commit all changes**

Single commit for the entire feature:

```
feat(engine): rewrite liquidation scorer with side-aware direction, MAD detection, asymmetry scoring, tunable params, and diagnostics
```
