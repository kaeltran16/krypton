# Signal Engine v2 — New Data Sources & Adaptive Threshold

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add liquidation level scoring as a new data source, implement IC-based source pruning, improve on-chain graceful degradation, and introduce per-pair/per-regime adaptive signal thresholds.

**Architecture:** Liquidation data is polled from OKX REST API every 5 minutes, aggregated into price-level buckets, and scored based on cluster density near current price. IC (Information Coefficient) tracking monitors per-source predictive value over 30 days; sources with persistently negative IC get auto-pruned. Adaptive thresholds are learned per (pair, regime) via 1D sweeps in the optimizer, with a fallback cascade to pair/regime/global defaults.

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.0 async, Alembic, React/TypeScript, pytest

**Spec:** `docs/superpowers/specs/2026-03-24-signal-engine-v2-design.md` (Sections 8, 9)

**Depends on:** Plans 1 (confidence blending, regime outer weights), 3 (optimizer fitness)

**Prerequisite from Plan 1:** On-chain graceful degradation (unsupported pairs returning `confidence=0.0` instead of `score=0` with implicit `confidence=1.0`) is handled by Plan 1 Task 11, which changes `compute_onchain_score` to return `{"score": 0, "confidence": 0.0}` for unknown pairs. Verify this is in place before starting this plan.

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/collector/liquidation.py` | OKX liquidation endpoint poller, event aggregation, rolling 24h window |
| `backend/app/engine/liquidation_scorer.py` | Score liquidation clusters, emit confidence, identify S/R zones |
| `backend/tests/collector/test_liquidation_collector.py` | Collector state management, pruning, poll failure resilience |

### Modified Files

| File | Responsibility |
|------|---------------|
| `backend/app/exchange/okx_client.py` | Add `get_liquidation_orders()` method |
| `backend/app/engine/combiner.py` | Add 5th source slot for liquidation |
| `backend/app/engine/regime.py` | Add liquidation to DEFAULT_OUTER_WEIGHTS |
| `backend/app/engine/structure.py` | Integrate liquidation zones as S/R |
| `backend/app/engine/optimizer.py` | IC tracking, threshold sweep pass |
| `backend/app/engine/param_groups.py` | Add liquidation weight to regime_outer, per-pair threshold params |
| `backend/app/db/models.py` | SourceICHistory model, RegimeWeights liquidation columns, PipelineSettings threshold columns |
| `backend/app/main.py` | Wire liquidation collector, IC tracking, adaptive threshold lookup |
| `web/src/features/signals/types.ts` | Already updated in Plan 1 |
| `backend/app/api/routes.py` | Add GET `/engine/thresholds` endpoint for learned threshold overrides |
| `web/src/features/engine/components/EnginePage.tsx` | Display per-pair/regime threshold overrides |
| `web/src/features/settings/components/SettingsPage.tsx` | Rename threshold slider label |

### Test Files

| File | What it covers |
|------|---------------|
| `backend/tests/engine/test_liquidation_scorer.py` | Bucket aggregation, decay, cluster detection, scoring |
| `backend/tests/engine/test_ic_pruning.py` | IC tracking, pruning threshold, re-enable, pipeline wiring |
| `backend/tests/engine/test_adaptive_threshold.py` | Fallback cascade, per-pair lookup, LLM threshold interaction |
| `backend/tests/collector/test_liquidation_collector.py` | Collector state management, pruning, poll failure resilience |

---

## Task 1: Liquidation Event Aggregation

**Files:**
- Create: `backend/app/collector/liquidation.py`
- Test: `backend/tests/engine/test_liquidation_scorer.py`

- [ ] **Step 1: Write test for bucket aggregation**

```python
# backend/tests/engine/test_liquidation_scorer.py
from datetime import datetime, timezone, timedelta
from app.engine.liquidation_scorer import aggregate_liquidation_buckets


def test_bucket_aggregation_groups_by_price_level():
    """Liquidation events should be bucketed by price level (0.25 * ATR width)."""
    atr = 100.0  # bucket width = 25
    now = datetime.now(timezone.utc)
    events = [
        {"price": 50010.0, "volume": 100.0, "timestamp": now},
        {"price": 50020.0, "volume": 200.0, "timestamp": now},  # same bucket as 50010
        {"price": 50200.0, "volume": 150.0, "timestamp": now},  # different bucket
    ]
    buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0)
    # 50010 and 50020 should be in the same bucket
    assert len(buckets) >= 2
    # Find the bucket containing 50010-50020
    near_bucket = [b for b in buckets if abs(b["center"] - 50015) < 25]
    assert len(near_bucket) == 1
    assert near_bucket[0]["total_volume"] == 300.0


def test_bucket_decay_reduces_old_events():
    """Events older than half-life should have reduced weight."""
    atr = 100.0
    now = datetime.now(timezone.utc)
    events = [
        {"price": 50000.0, "volume": 100.0, "timestamp": now},
        {"price": 50000.0, "volume": 100.0, "timestamp": now - timedelta(hours=8)},  # 2x half-life
    ]
    buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0, decay_half_life_hours=4)
    # Old event should be decayed to ~25% weight
    assert buckets[0]["total_volume"] < 200.0
    assert buckets[0]["total_volume"] > 100.0


def test_cluster_detection():
    """Buckets with volume > 2x median should be identified as clusters."""
    from app.engine.liquidation_scorer import detect_clusters

    buckets = [
        {"center": 50000, "total_volume": 100},
        {"center": 50100, "total_volume": 100},
        {"center": 50200, "total_volume": 500},  # cluster
        {"center": 50300, "total_volume": 80},
    ]
    clusters = detect_clusters(buckets, threshold_mult=2.0)
    assert len(clusters) == 1
    assert clusters[0]["center"] == 50200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_liquidation_scorer.py::test_bucket_aggregation_groups_by_price_level -v`
Expected: FAIL

- [ ] **Step 3: Create liquidation_scorer.py**

```python
# backend/app/engine/liquidation_scorer.py
"""Liquidation level scoring — aggregates liquidation events into price clusters."""

import math
from datetime import datetime, timezone, timedelta

BUCKET_WIDTH_ATR_MULT = 0.25
DECAY_HALF_LIFE_HOURS = 4.0
CLUSTER_THRESHOLD_MULT = 2.0


def aggregate_liquidation_buckets(
    events: list[dict],
    atr: float,
    current_price: float,
    decay_half_life_hours: float = DECAY_HALF_LIFE_HOURS,
) -> list[dict]:
    """Aggregate liquidation events into price-level buckets with exponential decay."""
    if not events or atr <= 0:
        return []

    bucket_width = BUCKET_WIDTH_ATR_MULT * atr
    now = datetime.now(timezone.utc)
    buckets: dict[int, float] = {}

    for event in events:
        price = event["price"]
        volume = event["volume"]
        ts = event["timestamp"]

        # exponential decay
        age_hours = (now - ts).total_seconds() / 3600
        decay = math.exp(-math.log(2) * age_hours / decay_half_life_hours)
        weighted_vol = volume * decay

        bucket_idx = round((price - current_price) / bucket_width)
        buckets[bucket_idx] = buckets.get(bucket_idx, 0.0) + weighted_vol

    return [
        {"center": current_price + idx * bucket_width, "total_volume": vol}
        for idx, vol in sorted(buckets.items())
        if vol > 0
    ]


def detect_clusters(
    buckets: list[dict],
    threshold_mult: float = CLUSTER_THRESHOLD_MULT,
) -> list[dict]:
    """Identify clusters: buckets with volume > threshold_mult * median."""
    if len(buckets) < 2:
        return buckets

    volumes = sorted(b["total_volume"] for b in buckets)
    median_vol = volumes[len(volumes) // 2]

    if median_vol <= 0:
        return []

    return [b for b in buckets if b["total_volume"] > threshold_mult * median_vol]
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_liquidation_scorer.py -v`
Expected: PASS

---

## Task 2: Liquidation Scoring Function

**Files:**
- Modify: `backend/app/engine/liquidation_scorer.py`
- Test: `backend/tests/engine/test_liquidation_scorer.py`

Score liquidation clusters based on proximity to price. Return `{"score": int, "confidence": float, "clusters": list}`.

- [ ] **Step 1: Write test**

Add to `test_liquidation_scorer.py`:
```python
from app.engine.liquidation_scorer import compute_liquidation_score


def test_liquidation_score_near_cluster_boosts():
    """Price near a dense cluster should produce a directional score."""
    now = datetime.now(timezone.utc)
    events = [
        {"price": 50500.0, "volume": 1000.0, "timestamp": now},
        {"price": 50520.0, "volume": 800.0, "timestamp": now},
    ] + [
        {"price": 49000.0 + i * 10, "volume": 50.0, "timestamp": now}
        for i in range(20)  # background noise
    ]
    result = compute_liquidation_score(
        events=events, current_price=50400.0, atr=200.0,
    )
    assert isinstance(result, dict)
    assert "score" in result
    assert "confidence" in result
    assert "clusters" in result
    assert -100 <= result["score"] <= 100


def test_liquidation_score_no_events():
    """No events should return score=0, confidence=0."""
    result = compute_liquidation_score(events=[], current_price=50000.0, atr=200.0)
    assert result["score"] == 0
    assert result["confidence"] == 0.0
```

- [ ] **Step 2: Implement compute_liquidation_score**

Add to `liquidation_scorer.py`:
```python
from app.engine.scoring import sigmoid_score


def compute_liquidation_score(
    events: list[dict],
    current_price: float,
    atr: float,
) -> dict:
    """Score liquidation levels based on cluster proximity to current price.

    Returns {"score": int, "confidence": float, "clusters": list}.
    """
    if not events or atr <= 0:
        return {"score": 0, "confidence": 0.0, "clusters": []}

    buckets = aggregate_liquidation_buckets(events, atr, current_price)
    clusters = detect_clusters(buckets)

    if not clusters:
        return {"score": 0, "confidence": 0.1, "clusters": []}

    # Normalize density relative to median bucket volume for the pair,
    # so scoring works across assets with vastly different volumes (BTC vs WIF).
    all_vols = [b["total_volume"] for b in buckets]
    median_vol = sorted(all_vols)[len(all_vols) // 2] if all_vols else 1.0
    density_norm = max(median_vol * 3, 1.0)  # 3x median = full density contribution

    score = 0.0
    for cluster in clusters:
        distance = cluster["center"] - current_price
        distance_atr = abs(distance) / atr if atr > 0 else float("inf")

        # only score clusters within 2 ATR
        if distance_atr > 2.0:
            continue

        proximity = sigmoid_score(2.0 - distance_atr, center=0, steepness=2.0)
        density = cluster["total_volume"]

        # Direction rationale (per spec Section 8):
        # Cluster ABOVE price = dense short liquidation levels = potential short squeeze
        # as cascading liquidations push price up → bullish.
        # Cluster BELOW price = dense long liquidation levels = potential long cascade
        # as cascading liquidations push price down → bearish.
        direction = 1 if distance > 0 else -1
        score += direction * proximity * min(density / density_norm, 1.0) * 30

    score = max(min(round(score), 100), -100)

    # confidence based on data freshness and cluster density
    total_vol = sum(b["total_volume"] for b in buckets)
    confidence = min(1.0, len(clusters) / 3.0) * min(1.0, total_vol / density_norm)

    return {
        "score": score,
        "confidence": min(1.0, confidence),
        "clusters": [{"price": c["center"], "volume": c["total_volume"]} for c in clusters],
    }
```

- [ ] **Step 3: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_liquidation_scorer.py -v`
Expected: PASS

---

## Task 3: OKX Client — Add `get_liquidation_orders()` Method

**Files:**
- Modify: `backend/app/exchange/okx_client.py`

The OKX client currently has no method for fetching liquidation data. This is a prerequisite for the collector.

- [ ] **Step 1: Add `parse_liquidation_response` helper**

Add above `OKXClient` class in `okx_client.py`:
```python
def parse_liquidation_response(raw: dict) -> list[dict]:
    """Parse OKX liquidation orders response into list of event dicts."""
    if raw.get("code") != "0" or not raw.get("data"):
        return []
    events = []
    for item in raw["data"]:
        details = item.get("details", [])
        for d in details:
            bk_px = _safe_float(d.get("bkPx"))
            sz = _safe_float(d.get("sz"))
            if bk_px > 0 and sz > 0:
                events.append({
                    "bkPx": str(bk_px),
                    "sz": str(sz),
                    "side": d.get("side", ""),
                    "ts": d.get("ts", "0"),
                })
    return events
```

- [ ] **Step 2: Add `get_liquidation_orders` method to `OKXClient`**

Add to `OKXClient` class (public endpoint, no auth headers needed):
```python
async def get_liquidation_orders(self, inst_id: str) -> list[dict]:
    """Fetch recent liquidation orders for an instrument. Public endpoint, no auth required."""
    path = f"/api/v5/public/liquidation-orders?instType=SWAP&instId={inst_id}&state=filled"
    try:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            resp = await client.get(path)
            resp.raise_for_status()
            return parse_liquidation_response(resp.json())
    except Exception:
        logger.debug("Failed to fetch liquidation orders for %s", inst_id, exc_info=True)
        return []
```

- [ ] **Step 3: Verify no regressions**

Run: `docker exec krypton-api-1 python -m pytest tests/exchange/ -v`
Expected: PASS

---

## Task 4: Liquidation Data Collector

**Files:**
- Create: `backend/app/collector/liquidation.py`
- Create: `backend/tests/collector/test_liquidation_collector.py`

- [ ] **Step 1: Write collector unit test**

```python
# backend/tests/collector/test_liquidation_collector.py
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import pytest
from app.collector.liquidation import LiquidationCollector


@pytest.mark.asyncio
async def test_events_stored_after_poll():
    """Poll should store parsed events in the events dict."""
    mock_client = AsyncMock()
    mock_client.get_liquidation_orders.return_value = [
        {"bkPx": "50000", "sz": "100", "side": "buy", "ts": "0"},
    ]
    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"])
    await collector._poll()
    assert len(collector.events["BTC-USDT-SWAP"]) == 1
    assert collector.events["BTC-USDT-SWAP"][0]["price"] == 50000.0


@pytest.mark.asyncio
async def test_old_events_pruned():
    """Events older than 24h window should be pruned."""
    mock_client = AsyncMock()
    mock_client.get_liquidation_orders.return_value = []
    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"])
    # inject an old event
    old_ts = datetime.now(timezone.utc) - timedelta(hours=25)
    collector._events["BTC-USDT-SWAP"] = [
        {"price": 50000.0, "volume": 100.0, "timestamp": old_ts, "side": "buy"},
    ]
    await collector._poll()
    assert len(collector.events["BTC-USDT-SWAP"]) == 0


@pytest.mark.asyncio
async def test_pruning_runs_even_when_poll_fails():
    """Pruning should still happen if the API call for a pair fails."""
    mock_client = AsyncMock()
    mock_client.get_liquidation_orders.side_effect = Exception("API down")
    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"])
    old_ts = datetime.now(timezone.utc) - timedelta(hours=25)
    collector._events["BTC-USDT-SWAP"] = [
        {"price": 50000.0, "volume": 100.0, "timestamp": old_ts, "side": "buy"},
    ]
    await collector._poll()
    # old event should still be pruned despite poll failure
    assert len(collector.events["BTC-USDT-SWAP"]) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_liquidation_collector.py -v`
Expected: FAIL

- [ ] **Step 3: Create the collector**

```python
# backend/app/collector/liquidation.py
"""Polls OKX liquidation endpoint every 5 minutes, maintains rolling 24h window."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 300  # 5 minutes
WINDOW_HOURS = 24


class LiquidationCollector:
    def __init__(self, okx_client, pairs: list[str]):
        self._client = okx_client
        self._pairs = pairs
        self._events: dict[str, list[dict]] = {p: [] for p in pairs}
        self._task = None

    @property
    def events(self) -> dict[str, list[dict]]:
        return self._events

    async def start(self):
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _poll_loop(self):
        while True:
            try:
                await self._poll()
            except Exception as e:
                logger.warning("Liquidation poll error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _poll(self):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        for pair in self._pairs:
            try:
                raw = await self._client.get_liquidation_orders(pair)
                if raw:
                    for item in raw:
                        self._events[pair].append({
                            "price": float(item.get("bkPx", 0)),
                            "volume": float(item.get("sz", 0)),
                            "timestamp": datetime.now(timezone.utc),
                            "side": item.get("side", ""),
                        })
            except Exception as e:
                logger.debug("Liquidation poll for %s failed: %s", pair, e)
            finally:
                # Always prune old events, even if the API call failed,
                # to prevent unbounded memory growth
                self._events[pair] = [
                    e for e in self._events[pair] if e["timestamp"] > cutoff
                ]
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/collector/test_liquidation_collector.py -v`
Expected: PASS

---

## Task 5: Add Liquidation to Combiner and Regime Weights

**Files:**
- Modify: `backend/app/engine/regime.py:15-20`
- Modify: `backend/app/engine/combiner.py`
- Modify: `backend/app/db/models.py` (RegimeWeights — add liquidation columns)
- Modify: `backend/app/engine/param_groups.py`

- [ ] **Step 1: Add liquidation to DEFAULT_OUTER_WEIGHTS**

In `regime.py`, add a 5th key `liquidation` to each regime in `DEFAULT_OUTER_WEIGHTS`. Redistribute small weight from existing sources:
```python
DEFAULT_OUTER_WEIGHTS = {
    "trending": {"tech": 0.42, "flow": 0.23, "onchain": 0.16, "pattern": 0.11, "liquidation": 0.08},
    "ranging": {"tech": 0.35, "flow": 0.16, "onchain": 0.24, "pattern": 0.16, "liquidation": 0.09},
    "volatile": {"tech": 0.27, "flow": 0.18, "onchain": 0.22, "pattern": 0.22, "liquidation": 0.11},
    "steady": {"tech": 0.45, "flow": 0.20, "onchain": 0.16, "pattern": 0.11, "liquidation": 0.08},
}
```

Update `OUTER_KEYS`:
```python
OUTER_KEYS = ["tech", "flow", "onchain", "pattern", "liquidation"]
```

- [ ] **Step 2: Add liquidation weight columns to RegimeWeights**

In `models.py`, add 4 new columns (one per regime):
```python
trending_liquidation_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.08, server_default="0.08")
ranging_liquidation_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.09, server_default="0.09")
volatile_liquidation_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.11, server_default="0.11")
steady_liquidation_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.08, server_default="0.08")
```

- [ ] **Step 3: Update compute_preliminary_score for 5th source**

In `combiner.py`, add `liquidation_score`, `liquidation_weight`, `liquidation_confidence` parameters to `compute_preliminary_score`.

- [ ] **Step 4: Update param_groups.py**

Add liquidation weight to the `regime_outer` param group so it's included in the optimizer sweep. Also update the `source_weights` param group and its `_source_weights_ok` constraint to validate 5 sources instead of 4:
```python
# In _source_weights_ok: add "liquidation" to the expected keys
# In source_weights params: add "liquidation" with range matching other sources
# In _regime_outer_ok: update to validate 5-key normalization per regime
```

- [ ] **Step 5: Run regime tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_regime.py tests/engine/test_combiner.py -v`
Expected: PASS (after updating tests for 5th source)

---

## Task 6: Integrate Liquidation Zones into Structure Snapping

**Files:**
- Modify: `backend/app/engine/structure.py`

- [ ] **Step 1: Update collect_structure_levels to accept liquidation clusters**

Add optional `liquidation_clusters` parameter:
```python
def collect_structure_levels(candles, indicators, atr, liquidation_clusters=None):
```

If clusters provided, add them as S/R zones with label "liq_cluster":
```python
if liquidation_clusters:
    for cluster in liquidation_clusters:
        levels.append({
            "price": cluster["price"],
            "label": "liq_cluster",
            "strength": min(10, int(cluster["volume"] / 100)),
        })
```

- [ ] **Step 2: Run structure tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_structure.py -v`
Expected: PASS

---

## Task 7: SourceICHistory DB Model and IC Tracking

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/tests/engine/test_ic_pruning.py`

- [ ] **Step 1: Write test**

```python
# backend/tests/engine/test_ic_pruning.py
from app.engine.optimizer import compute_ic, should_prune_source


def test_ic_positive_correlation():
    """Positive IC means source scores predict outcomes."""
    source_scores = [10, -20, 30, -15, 25]
    outcomes = [0.02, -0.03, 0.04, -0.02, 0.03]  # same direction
    ic = compute_ic(source_scores, outcomes)
    assert ic > 0.5


def test_ic_negative_correlation():
    """Negative IC means source scores anti-predict outcomes."""
    source_scores = [10, -20, 30, -15, 25]
    outcomes = [-0.02, 0.03, -0.04, 0.02, -0.03]  # opposite direction
    ic = compute_ic(source_scores, outcomes)
    assert ic < -0.5


def test_prune_below_threshold():
    """Source with IC < -0.05 for 30 days should be pruned."""
    ic_history = [-0.06, -0.07, -0.08]  # 3 entries all below threshold
    assert should_prune_source("technical", ic_history, threshold=-0.05, min_days=3) is True


def test_no_prune_above_threshold():
    ic_history = [-0.02, 0.01, 0.05]
    assert should_prune_source("order_flow", ic_history, threshold=-0.05, min_days=3) is False


def test_liquidation_excluded_from_pruning():
    """Liquidation source must be excluded from IC pruning per spec."""
    ic_history = [-0.10, -0.10, -0.10]  # would normally be pruned
    assert should_prune_source("liquidation", ic_history, threshold=-0.05, min_days=3) is False


def test_re_enable_when_ic_recovers():
    """Source should be re-enabled when IC recovers above 0.0."""
    from app.engine.optimizer import should_reenable_source
    ic_history = [-0.06, -0.03, 0.01, 0.02]
    assert should_reenable_source(ic_history) is True
```

- [ ] **Step 2: Add SourceICHistory model**

In `models.py`:
```python
class SourceICHistory(Base):
    __tablename__ = "source_ic_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    ic_value: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_source_ic_source_pair_date", "source", "pair", "date"),
    )
```

- [ ] **Step 3: Implement IC computation and pruning in optimizer.py**

Add to `optimizer.py`:
```python
import numpy as np

IC_PRUNE_THRESHOLD = -0.05
IC_REENABLE_THRESHOLD = 0.0


def compute_ic(source_scores: list[float], outcomes: list[float]) -> float:
    """Compute Information Coefficient (Pearson correlation) between scores and outcomes."""
    if len(source_scores) < 5 or len(outcomes) < 5:
        return 0.0
    scores = np.array(source_scores, dtype=float)
    outs = np.array(outcomes, dtype=float)
    if np.std(scores) == 0 or np.std(outs) == 0:
        return 0.0
    return float(np.corrcoef(scores, outs)[0, 1])


# Sources excluded from IC pruning (per spec: liquidation excluded until persistence added)
IC_PRUNE_EXCLUDED_SOURCES = {"liquidation"}


def should_prune_source(
    source_name: str,
    ic_history: list[float],
    threshold: float = IC_PRUNE_THRESHOLD,
    min_days: int = 30,
) -> bool:
    """Check if a source should be pruned based on IC history.

    Liquidation source is excluded from pruning until persistence is added.
    """
    if source_name in IC_PRUNE_EXCLUDED_SOURCES:
        return False
    if len(ic_history) < min_days:
        return False
    recent = ic_history[-min_days:]
    return all(ic < threshold for ic in recent)


def should_reenable_source(ic_history: list[float]) -> bool:
    """Check if a pruned source should be re-enabled."""
    if not ic_history:
        return False
    return ic_history[-1] > IC_REENABLE_THRESHOLD
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_ic_pruning.py -v`
Expected: PASS

---

## Task 8: Wire IC Tracking into Pipeline

**Files:**
- Modify: `backend/app/engine/optimizer.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/engine/test_ic_pruning.py`

IC computation functions from Task 7 need to be called from the pipeline. Daily IC is computed from resolved signals; pruning decisions feed into the combiner via zeroed confidence.

- [ ] **Step 1: Write test for IC pipeline integration**

Add to `test_ic_pruning.py`:
```python
from app.engine.optimizer import compute_daily_ic_for_sources, get_pruned_sources


def test_compute_daily_ic_for_sources():
    """Should compute IC per source from resolved signal data."""
    resolved_signals = [
        {"raw_indicators": {"tech_score": 30, "flow_score": -10, "onchain_score": 5, "pattern_score": 10, "liquidation_score": 5}, "outcome_pct": 0.03},
        {"raw_indicators": {"tech_score": -20, "flow_score": 15, "onchain_score": -8, "pattern_score": -5, "liquidation_score": -3}, "outcome_pct": -0.02},
        {"raw_indicators": {"tech_score": 40, "flow_score": -5, "onchain_score": 10, "pattern_score": 15, "liquidation_score": 8}, "outcome_pct": 0.05},
        {"raw_indicators": {"tech_score": -15, "flow_score": 20, "onchain_score": -12, "pattern_score": -8, "liquidation_score": -6}, "outcome_pct": -0.03},
        {"raw_indicators": {"tech_score": 25, "flow_score": -15, "onchain_score": 7, "pattern_score": 12, "liquidation_score": 4}, "outcome_pct": 0.02},
    ]
    ic_map = compute_daily_ic_for_sources(resolved_signals)
    assert "tech" in ic_map
    assert "flow" in ic_map
    assert "onchain" in ic_map
    assert "pattern" in ic_map
    assert "liquidation" in ic_map
    # tech scores correlate positively with outcomes
    assert ic_map["tech"] > 0


def test_get_pruned_sources_returns_set():
    """Should return set of source names that should be pruned."""
    ic_histories = {
        "tech": [-0.06, -0.07, -0.08],  # below threshold for 3 days
        "flow": [0.1, 0.2, 0.15],       # healthy
        "liquidation": [-0.10, -0.10, -0.10],  # excluded from pruning
    }
    pruned = get_pruned_sources(ic_histories, threshold=-0.05, min_days=3)
    assert "tech" in pruned
    assert "flow" not in pruned
    assert "liquidation" not in pruned  # excluded per spec
```

- [ ] **Step 2: Implement IC pipeline helpers**

Add to `optimizer.py`:
```python
# Source key mapping for IC computation
_IC_SOURCE_KEYS = {
    "tech": "tech_score",
    "flow": "flow_score",
    "onchain": "onchain_score",
    "pattern": "pattern_score",
    "liquidation": "liquidation_score",
}


def compute_daily_ic_for_sources(resolved_signals: list[dict]) -> dict[str, float]:
    """Compute IC for each scoring source from resolved signals.

    Each signal must have raw_indicators with per-source scores and an outcome_pct.
    """
    outcomes = [s["outcome_pct"] for s in resolved_signals]
    ic_map = {}
    for source_name, score_key in _IC_SOURCE_KEYS.items():
        scores = [s["raw_indicators"].get(score_key, 0) for s in resolved_signals]
        ic_map[source_name] = compute_ic(scores, outcomes)
    return ic_map


def get_pruned_sources(
    ic_histories: dict[str, list[float]],
    threshold: float = IC_PRUNE_THRESHOLD,
    min_days: int = 30,
) -> set[str]:
    """Return set of source names that should be pruned based on IC history."""
    pruned = set()
    for source_name, history in ic_histories.items():
        if should_prune_source(source_name, history, threshold, min_days):
            pruned.add(source_name)
    return pruned
```

- [ ] **Step 3: Wire IC computation into optimizer loop**

In `optimizer.py`'s `run_optimizer_loop`, add a daily IC computation pass:
```python
# After existing optimizer logic, once per day:
# 1. Query resolved signals from last 24h
# 2. Call compute_daily_ic_for_sources()
# 3. Persist results to SourceICHistory table
# 4. Load 30-day IC history, call get_pruned_sources()
# 5. Store pruned set in app.state.pruned_sources
```

- [ ] **Step 4: Apply pruning in run_pipeline**

In `main.py`'s `run_pipeline`, before calling `compute_preliminary_score`, zero the confidence for pruned sources:
```python
pruned = getattr(app.state, "pruned_sources", set())
if "tech" in pruned:
    tech_conf = 0.0
if "flow" in pruned:
    flow_conf = 0.0
if "onchain" in pruned:
    onchain_conf = 0.0
if "pattern" in pruned:
    pattern_conf = 0.0
if "liquidation" in pruned:
    liq_confidence = 0.0
```

This leverages the existing confidence-weighted blending: a source with `confidence=0.0` contributes zero effective weight, effectively pruning it without changing the combiner API.

- [ ] **Step 5: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_ic_pruning.py -v`
Expected: PASS

---

## Task 9: Adaptive Signal Threshold — DB and Lookup

**Files:**
- Modify: `backend/app/db/models.py` (PipelineSettings or new table)
- Create: `backend/tests/engine/test_adaptive_threshold.py`

- [ ] **Step 1: Write test for fallback cascade**

```python
# backend/tests/engine/test_adaptive_threshold.py
from app.engine.optimizer import lookup_signal_threshold


def test_threshold_specific_pair_regime():
    """Should return specific learned threshold when available."""
    thresholds = {
        ("BTC-USDT-SWAP", "trending"): 35,
        ("BTC-USDT-SWAP", None): 38,
    }
    result = lookup_signal_threshold("BTC-USDT-SWAP", "trending", thresholds, default=40)
    assert result == 35


def test_threshold_fallback_to_pair_level():
    """Should fall back to pair-level average when regime-specific not available."""
    thresholds = {
        ("BTC-USDT-SWAP", None): 38,
    }
    result = lookup_signal_threshold("BTC-USDT-SWAP", "ranging", thresholds, default=40)
    assert result == 38


def test_threshold_fallback_to_regime_level():
    """Should fall back to regime-level average when pair not available."""
    thresholds = {
        (None, "trending"): 36,
    }
    result = lookup_signal_threshold("WIF-USDT-SWAP", "trending", thresholds, default=40)
    assert result == 36


def test_threshold_fallback_to_global():
    """Should fall back to global default when nothing learned."""
    result = lookup_signal_threshold("WIF-USDT-SWAP", "volatile", {}, default=40)
    assert result == 40
```

- [ ] **Step 2: Implement fallback cascade**

Add to `optimizer.py`:
```python
def lookup_signal_threshold(
    pair: str,
    dominant_regime: str,
    learned_thresholds: dict,
    default: int = 40,
) -> int:
    """Look up signal threshold with fallback cascade.

    Cascade: (pair, regime) → (pair, any) → (any, regime) → global default.
    """
    # 1. specific (pair, regime)
    t = learned_thresholds.get((pair, dominant_regime))
    if t is not None:
        return t
    # 2. pair-level
    t = learned_thresholds.get((pair, None))
    if t is not None:
        return t
    # 3. regime-level
    t = learned_thresholds.get((None, dominant_regime))
    if t is not None:
        return t
    # 4. global default
    return default
```

- [ ] **Step 3: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_adaptive_threshold.py -v`
Expected: PASS

---

## Task 10: Adaptive Threshold Learning (Optimizer 1D Sweep)

**Files:**
- Modify: `backend/app/engine/optimizer.py`
- Test: `backend/tests/engine/test_adaptive_threshold.py`

After main parameter optimization, run a separate 1D sweep per (pair, regime) to find optimal threshold.

- [ ] **Step 1: Write test**

Add to `test_adaptive_threshold.py`:
```python
from app.engine.optimizer import sweep_threshold_1d


def test_threshold_sweep_finds_optimal():
    """1D sweep should find threshold maximizing fitness."""
    # Mock fitness function: best at threshold=45
    def mock_fitness(threshold):
        return -abs(threshold - 45) / 100 + 0.5

    best, fitness = sweep_threshold_1d(mock_fitness, low=20, high=60, step=5)
    assert best == 45
    assert fitness > 0.4


def test_threshold_sweep_skips_insufficient_data():
    """Should return None when fewer than 10 resolved signals in bucket."""
    best, fitness = sweep_threshold_1d(None, low=20, high=60, step=5, signal_count=5, min_signals=10)
    assert best is None
```

- [ ] **Step 2: Implement sweep_threshold_1d**

Add to `optimizer.py`:
```python
def sweep_threshold_1d(
    fitness_fn,
    low: int = 20,
    high: int = 60,
    step: int = 5,
    signal_count: int | None = None,
    min_signals: int = 10,
) -> tuple[int | None, float]:
    """1D sweep to find optimal signal threshold.

    Returns (best_threshold, best_fitness) or (None, 0.0) if insufficient data.
    """
    if signal_count is not None and signal_count < min_signals:
        return None, 0.0

    best_threshold = None
    best_fitness = -float("inf")
    for t in range(low, high + 1, step):
        f = fitness_fn(t)
        if f > best_fitness:
            best_fitness = f
            best_threshold = t

    return best_threshold, best_fitness
```

- [ ] **Step 3: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_adaptive_threshold.py -v`
Expected: PASS

---

## Task 11: Wire Adaptive Threshold in Main Pipeline

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Load learned thresholds on startup**

In lifespan, load threshold overrides from DB into `app.state.learned_thresholds`:
```python
app.state.learned_thresholds = {}  # populated by optimizer
```

- [ ] **Step 2: Replace static threshold check with adaptive lookup**

In `run_pipeline`, where the signal threshold check happens (around line 697):
```python
# determine dominant regime
dominant = max(regime, key=regime.get) if regime else "steady"
effective_threshold = lookup_signal_threshold(
    pair, dominant, app.state.learned_thresholds,
    default=settings.engine_signal_threshold,
)
emitted = abs(final) >= effective_threshold
```

- [ ] **Step 3: Verify LLM threshold non-interaction**

The LLM gate check (line 643: `abs(blended) >= settings.engine_llm_threshold`) remains unchanged — it uses the global LLM threshold, not the per-pair signal threshold. This is correct per spec: the signal threshold check happens after LLM contribution.

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=120`
Expected: PASS

---

## Task 12: Wire Liquidation Scoring in Main Pipeline

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Initialize liquidation collector in lifespan + shutdown**

In lifespan startup:
```python
from app.collector.liquidation import LiquidationCollector

liq_collector = LiquidationCollector(okx_client, settings.pairs)
await liq_collector.start()
app.state.liquidation_collector = liq_collector
app.state.pruned_sources = set()  # populated by IC tracking in optimizer
```

In lifespan shutdown (after `yield`, alongside other `.stop()` / `.cancel()` calls):
```python
liq_collector = getattr(app.state, "liquidation_collector", None)
if liq_collector:
    await liq_collector.stop()
```

- [ ] **Step 2: Call liquidation scorer in run_pipeline**

After pattern scoring, before combiner:
```python
liq_score = 0
liq_confidence = 0.0
liq_clusters = []
liq_collector = getattr(app.state, "liquidation_collector", None)
if liq_collector:
    from app.engine.liquidation_scorer import compute_liquidation_score
    atr = tech_result["indicators"].get("atr", None)
    current_price = float(candle["close"])
    # Use price-relative fallback (2%) instead of fixed value,
    # so bucket widths scale correctly across assets (BTC ~$60k vs WIF ~$1)
    if atr is None or atr <= 0:
        atr = current_price * 0.02
    liq_result = compute_liquidation_score(
        events=liq_collector.events.get(pair, []),
        current_price=current_price,
        atr=atr,
    )
    liq_score = liq_result["score"]
    liq_confidence = liq_result["confidence"]
    liq_clusters = liq_result["clusters"]
```

- [ ] **Step 3: Store liquidation scores in engine_snapshot JSONB**

The spec requires per-signal liquidation scores stored in `raw_indicators` for IC computation. In `run_pipeline`, when building `signal_data["raw_indicators"]`, add:
```python
"liquidation_score": liq_score,
"liquidation_confidence": liq_confidence,
"liquidation_cluster_count": len(liq_clusters),
```

This is required even though liquidation persistence is deferred — it enables IC computation once persistence is added.

- [ ] **Step 4: Pass liquidation clusters to structure snapping**

```python
structure = collect_structure_levels(df, tech_result["indicators"], atr,
                                     liquidation_clusters=liq_clusters)
```

- [ ] **Step 5: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=120`
Expected: PASS

---

## Task 13: Frontend — Threshold Display Updates

**Files:**
- Modify: `backend/app/api/routes.py` (add threshold endpoint)
- Modify: `web/src/features/settings/components/SettingsPage.tsx`
- Modify: `web/src/features/engine/components/EnginePage.tsx`

- [ ] **Step 1: Add API endpoint for learned thresholds**

In `routes.py`, add a GET endpoint that serves the learned threshold overrides so the frontend can display them:
```python
@router.get("/engine/thresholds")
async def get_learned_thresholds(request: Request):
    thresholds = getattr(request.app.state, "learned_thresholds", {})
    # Convert tuple keys to serializable format
    return {
        "thresholds": [
            {"pair": k[0], "regime": k[1], "value": v}
            for k, v in thresholds.items()
        ],
        "default": request.app.state.settings.engine_signal_threshold,
    }
```

- [ ] **Step 2: Rename threshold slider label**

In `SettingsPage.tsx`, change the signal threshold slider label from "Signal Threshold" to "Default Threshold".

- [ ] **Step 3: Display per-pair/regime overrides on engine page**

In `EnginePage.tsx`, add a section showing learned threshold overrides (read-only) fetched from `/engine/thresholds`, alongside other optimizer-tuned parameters.

- [ ] **Step 4: Build frontend**

Run: `cd web && pnpm build`
Expected: No TypeScript errors

---

## Task 14: Alembic Migration for All Model Changes

- [ ] **Step 1: Generate migration**

This migration covers:
- `RegimeWeights`: 4 liquidation weight columns
- `SourceICHistory`: new table
- Any threshold storage additions to PipelineSettings

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "signal engine v2 data sources and threshold"`
Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head`

---

## Task 15: Final Integration Test

- [ ] **Step 1: Run the full backend test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=120`
Expected: All tests pass

- [ ] **Step 2: Run frontend build**

Run: `cd web && pnpm build`
Expected: Clean build

- [ ] **Step 3: Verify adaptive threshold non-interaction with LLM threshold**

Write a specific test: per-pair threshold lower than LLM threshold should not cause unnecessary LLM calls. The LLM gate checks `abs(blended) >= llm_threshold` which happens before the signal threshold check, so this is inherently safe.
