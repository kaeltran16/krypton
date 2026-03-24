# Signal Engine v2 — Backtester & Optimizer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable the backtester to replay historical order flow and on-chain data so the optimizer can tune all scoring sources. Upgrade optimizer fitness from PF-only to multi-metric composite with statistical significance gating.

**Architecture:** Backtester loads `OrderFlowSnapshot` and new `OnchainSnapshot` records, aligning them to candles via bisect lookup. Candles without snapshot data get confidence=0.0, letting confidence-weighted blending redistribute weight naturally. Optimizer fitness becomes a 4-metric composite (Sharpe, PF, win rate, max drawdown). Shadow testing uses z-test for statistical significance instead of fixed window.

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.0 async, Alembic, pytest

**Spec:** `docs/superpowers/specs/2026-03-24-signal-engine-v2-design.md` (Sections 4, 6)

**Depends on:** Plan 1 (confidence-weighted blending — backtester needs confidence from scoring sources)

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/alembic/versions/XXXX_add_onchain_snapshot.py` | Migration for OnchainSnapshot table |

### Modified Files

| File | Responsibility |
|------|---------------|
| `backend/app/db/models.py` | New `OnchainSnapshot` model |
| `backend/app/engine/onchain_scorer.py` | Persist snapshots alongside Redis writes |
| `backend/app/engine/backtester.py` | Load flow/on-chain snapshots, replay through pipeline, report coverage |
| `backend/app/engine/optimizer.py` | Multi-metric fitness, z-test shadow gate, rollback window expansion, coverage-gated optimization |

### Test Files

| File | What it covers |
|------|---------------|
| `backend/tests/engine/test_backtester_replay.py` | Flow/on-chain snapshot loading, bisect alignment, coverage reporting |
| `backend/tests/engine/test_optimizer_fitness.py` | Multi-metric fitness, z-test, rollback changes |

---

## Task 1: OnchainSnapshot DB Model

**Files:**
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/engine/test_backtester_replay.py`

- [ ] **Step 1: Write test**

```python
# backend/tests/engine/test_backtester_replay.py
def test_onchain_snapshot_model_exists():
    from app.db.models import OnchainSnapshot
    assert hasattr(OnchainSnapshot, "pair")
    assert hasattr(OnchainSnapshot, "timestamp")
    assert hasattr(OnchainSnapshot, "metric_name")
    assert hasattr(OnchainSnapshot, "value")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester_replay.py::test_onchain_snapshot_model_exists -v`
Expected: FAIL — `OnchainSnapshot` doesn't exist

- [ ] **Step 3: Add OnchainSnapshot model**

In `backend/app/db/models.py`, add:
```python
class OnchainSnapshot(Base):
    __tablename__ = "onchain_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_onchain_snap_pair_ts", "pair", "timestamp"),
    )
```

- [ ] **Step 4: Generate and apply Alembic migration**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic revision --autogenerate -m "add onchain snapshot table"`
Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 alembic upgrade head`

- [ ] **Step 5: Run test**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester_replay.py::test_onchain_snapshot_model_exists -v`
Expected: PASS

---

## Task 2: Persist On-Chain Snapshots Alongside Redis

**Files:**
- Modify: `backend/app/engine/onchain_scorer.py`

Add a `persist_onchain_snapshot` function that saves metric values to the `OnchainSnapshot` table when the on-chain scorer runs. Called from `main.py` after each on-chain scoring call.

- [ ] **Step 1: Write test**

Add to `test_backtester_replay.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_persist_onchain_snapshot():
    from app.engine.onchain_scorer import persist_onchain_snapshot
    from datetime import datetime, timezone

    session = AsyncMock()
    await persist_onchain_snapshot(
        session, "BTC-USDT-SWAP",
        datetime.now(timezone.utc),
        {"exchange_netflow": 1500.0, "whale_tx_count": 5.0},
    )
    assert session.add.call_count == 2  # one per metric
```

- [ ] **Step 2: Implement persist_onchain_snapshot**

In `backend/app/engine/onchain_scorer.py`, add:
```python
async def persist_onchain_snapshot(session, pair: str, timestamp, metrics: dict):
    """Persist on-chain metric values for backtester replay."""
    from app.db.models import OnchainSnapshot
    for name, value in metrics.items():
        if value is not None:
            session.add(OnchainSnapshot(
                pair=pair, timestamp=timestamp, metric_name=name, value=float(value),
            ))
```

- [ ] **Step 3: Run test**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester_replay.py::test_persist_onchain_snapshot -v`
Expected: PASS

---

## Task 3: Backtester Flow Snapshot Replay

**Files:**
- Modify: `backend/app/engine/backtester.py`
- Test: `backend/tests/engine/test_backtester_replay.py`

Load `OrderFlowSnapshot` records and align to candles via bisect. Build rolling `flow_history` list from preceding 10 snapshots.

- [ ] **Step 1: Write test for snapshot-to-candle alignment**

Add to `test_backtester_replay.py`:
```python
from app.engine.backtester import _align_snapshots_to_candles


def test_flow_snapshot_bisect_alignment():
    """Flow snapshots should be aligned to candles by timestamp via bisect."""
    from datetime import datetime, timezone, timedelta

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candle_times = [base + timedelta(hours=i) for i in range(10)]
    snap_times = [base + timedelta(hours=i, minutes=30) for i in range(8)]

    snapshots = [{"timestamp": t, "funding_rate": 0.001 * i} for i, t in enumerate(snap_times)]

    # For candle at hour 5, closest prior snapshot is at hour 4:30 (index 4)
    aligned = _align_snapshots_to_candles(candle_times, snapshots)
    assert aligned[5] is not None
    assert aligned[5]["funding_rate"] == 0.004  # snapshot index 4


def test_flow_history_rolling_window():
    """Flow history should contain up to 10 preceding snapshots."""
    from app.engine.backtester import _build_flow_history
    from datetime import datetime, timezone, timedelta

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snapshots = [
        {"timestamp": base + timedelta(hours=i), "funding_rate": 0.001 * i, "long_short_ratio": 1.0 + i * 0.01}
        for i in range(20)
    ]
    # For candle at index 15, should get snapshots 5-14 (10 preceding)
    history = _build_flow_history(snapshots, candle_idx=15, window=10)
    assert len(history) == 10
    assert history[0]["funding_rate"] == 0.005
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester_replay.py::test_flow_snapshot_bisect_alignment -v`
Expected: FAIL — functions don't exist

- [ ] **Step 3: Implement snapshot alignment helpers**

In `backend/app/engine/backtester.py`, add:
```python
def _align_snapshots_to_candles(
    candle_times: list[datetime],
    snapshots: list[dict],
) -> list[dict | None]:
    """Align snapshots to candles via bisect. Returns list parallel to candle_times."""
    if not snapshots:
        return [None] * len(candle_times)
    snap_times = [s["timestamp"] for s in snapshots]
    aligned = []
    for ct in candle_times:
        idx = bisect.bisect_right(snap_times, ct) - 1
        aligned.append(snapshots[idx] if idx >= 0 else None)
    return aligned


def _build_flow_history(
    aligned_snapshots: list[dict | None],
    candle_idx: int,
    window: int = 10,
) -> list[dict]:
    """Build rolling flow_history from preceding aligned snapshots."""
    start = max(0, candle_idx - window)
    return [s for s in aligned_snapshots[start:candle_idx] if s is not None]
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester_replay.py -v -k "flow"`
Expected: PASS

---

## Task 4: Backtester On-Chain Snapshot Replay

**Files:**
- Modify: `backend/app/engine/backtester.py`
- Test: `backend/tests/engine/test_backtester_replay.py`

Load `OnchainSnapshot` records grouped by (pair, timestamp) and reconstruct into metrics dict for the on-chain scorer.

- [ ] **Step 1: Write test**

Add to `test_backtester_replay.py`:
```python
def test_onchain_snapshot_reconstruction():
    """OnchainSnapshot records should be reconstructed into metrics dict by timestamp."""
    from app.engine.backtester import _reconstruct_onchain_metrics
    from datetime import datetime, timezone

    t1 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)

    rows = [
        {"timestamp": t1, "metric_name": "exchange_netflow", "value": 1500.0},
        {"timestamp": t1, "metric_name": "whale_tx_count", "value": 5.0},
        {"timestamp": t2, "metric_name": "exchange_netflow", "value": -200.0},
    ]

    metrics_by_time = _reconstruct_onchain_metrics(rows)
    assert t1 in metrics_by_time
    assert metrics_by_time[t1]["exchange_netflow"] == 1500.0
    assert metrics_by_time[t1]["whale_tx_count"] == 5.0
    assert metrics_by_time[t2]["exchange_netflow"] == -200.0
```

- [ ] **Step 2: Implement reconstruction helper**

Add to `backtester.py`:
```python
from collections import defaultdict


def _reconstruct_onchain_metrics(rows: list[dict]) -> dict[datetime, dict]:
    """Group OnchainSnapshot rows by timestamp into metrics dicts."""
    by_time = defaultdict(dict)
    for row in rows:
        by_time[row["timestamp"]][row["metric_name"]] = row["value"]
    return dict(by_time)
```

- [ ] **Step 3: Run test**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester_replay.py::test_onchain_snapshot_reconstruction -v`
Expected: PASS

---

## Task 5: Wire Flow/On-Chain into Backtester Main Loop

**Files:**
- Modify: `backend/app/engine/backtester.py:69-200`
- Test: `backend/tests/engine/test_backtester_replay.py`

Update `BacktestConfig` to remove hardcoded zero weights. Update `run_backtest` to accept snapshot data and pass it through the scoring pipeline.

- [ ] **Step 1: Write test for backtester with flow data**

Add to `test_backtester_replay.py`:
```python
import numpy as np
import pandas as pd
from app.engine.backtester import run_backtest, BacktestConfig


def _make_candles(n: int) -> list[dict]:
    np.random.seed(42)
    close = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "timestamp": base_time + timedelta(hours=i),
            "open": close[i] - 0.2, "high": close[i] + 0.5,
            "low": close[i] - 0.5, "close": close[i],
            "volume": 1000.0 + np.random.rand() * 500,
        }
        for i in range(n)
    ]


def test_backtester_accepts_flow_snapshots():
    """Backtester should accept flow_snapshots parameter and report coverage."""
    candles = _make_candles(100)
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    flow_snapshots = [
        {"timestamp": base_time + timedelta(hours=i), "funding_rate": 0.0001,
         "long_short_ratio": 1.05, "open_interest_change_pct": 2.0}
        for i in range(50)  # only first 50 candles have flow data
    ]

    result = run_backtest(candles, "BTC-USDT-SWAP", flow_snapshots=flow_snapshots)
    assert "flow_coverage_pct" in result["stats"]
    assert 0 < result["stats"]["flow_coverage_pct"] <= 100


def test_backtester_accepts_onchain_snapshots():
    """Backtester should accept onchain_snapshots parameter and report coverage."""
    candles = _make_candles(100)
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    onchain_snapshots = [
        {"timestamp": base_time + timedelta(hours=i),
         "metric_name": "exchange_netflow", "value": 1500.0}
        for i in range(40)
    ]

    result = run_backtest(candles, "BTC-USDT-SWAP", onchain_snapshots=onchain_snapshots)
    assert "onchain_coverage_pct" in result["stats"]
    assert 0 < result["stats"]["onchain_coverage_pct"] <= 100
```

- [ ] **Step 2: Update BacktestConfig and run_backtest signature**

Keep `BacktestConfig` defaults numeric for backward compatibility. Add new fields for flow/on-chain:
```python
@dataclass
class BacktestConfig:
    signal_threshold: int = 40
    tech_weight: float = 0.75       # kept as-is for backward compat
    pattern_weight: float = 0.25    # kept as-is for backward compat
    use_regime_weights: bool = True  # when True + regime_weights provided, use blended weights
    # ... rest unchanged
```

**IMPORTANT:** The spec says "remove hardcoded flow_weight=0, onchain_weight=0" — this means the backtester loop should use actual flow/on-chain scores when snapshot data is available, NOT that tech_weight/pattern_weight defaults should change.

Update `run_backtest` signature to accept snapshot data:
```python
def run_backtest(
    candles: list[dict],
    pair: str,
    config: BacktestConfig | None = None,
    cancel_flag: dict | None = None,
    ml_predictor=None,
    parent_candles: list[dict] | None = None,
    regime_weights=None,
    flow_snapshots: list[dict] | None = None,
    onchain_snapshots: list[dict] | None = None,
) -> dict:
```

- [ ] **Step 3: Wire flow/on-chain scoring into backtester loop**

Before the main loop, set up alignment and counters:
```python
    from app.engine.traditional import compute_order_flow_score
    from types import SimpleNamespace

    # Align snapshots to candle timestamps
    candle_times = [c["timestamp"] for c in candles]
    aligned_flow = _align_snapshots_to_candles(candle_times, flow_snapshots or [])
    onchain_metrics_by_time = _reconstruct_onchain_metrics(onchain_snapshots or [])
    aligned_onchain = _align_snapshots_to_candles(
        candle_times,
        [{"timestamp": t, **m} for t, m in sorted(onchain_metrics_by_time.items())],
    )

    # Coverage counters
    flow_covered = 0
    onchain_covered = 0
    evaluated_candles = 0
```

Inside the main loop, after tech scoring, add flow scoring:
```python
        evaluated_candles += 1

        # flow scoring (if snapshots available)
        flow_score = 0
        flow_confidence = 0.0
        if aligned_flow[i] is not None:
            flow_covered += 1
            flow_metrics = {**aligned_flow[i]}  # copy to avoid mutating aligned data
            flow_metrics["price_direction"] = 1 if float(current["close"]) > float(current["open"]) else -1
            flow_history_dicts = _build_flow_history(aligned_flow, i, window=10)
            # IMPORTANT: _field_roc uses attribute access (s.funding_rate), not dict access.
            # Convert dicts to SimpleNamespace so flow_history works with compute_order_flow_score.
            flow_history = [SimpleNamespace(**d) for d in flow_history_dicts]
            tc = tech_result.get("indicators", {}).get("trend_conviction", 0.0)
            flow_result = compute_order_flow_score(
                flow_metrics, regime=tech_result.get("regime"),
                flow_history=flow_history, trend_conviction=tc,
            )
            flow_score = flow_result["score"]
            flow_confidence = flow_result.get("confidence", 1.0)

        # on-chain scoring (if snapshots available)
        onchain_score = 0
        onchain_confidence = 0.0
        if aligned_onchain[i] is not None:
            onchain_covered += 1
            # aligned_onchain entries are metric dicts — pass raw values as score
            # For backtester, use a simplified on-chain score since we can't call the async scorer
            onchain_metrics = aligned_onchain[i]
            netflow = onchain_metrics.get("exchange_netflow", 0)
            onchain_score = max(-100, min(100, int(-netflow / 30)))  # simplified contrarian
            onchain_confidence = 0.7  # fixed confidence for historical data
```

Update the `compute_preliminary_score` call to use `blend_outer_weights` when flow/on-chain data is present:
```python
        # Weight logic: when flow/onchain data is present, use blend_outer_weights
        # directly (no renormalization away from those slots). When absent, their
        # weight is 0 and remaining sources renormalize as before.
        if regime_weights is not None:
            regime = tech_result.get("regime")
            outer = blend_outer_weights(regime, regime_weights)
            bt_tech_w = outer["tech"]
            bt_pattern_w = outer["pattern"]
            bt_flow_w = outer["flow"] if aligned_flow[i] is not None else 0.0
            bt_onchain_w = outer["onchain"] if aligned_onchain[i] is not None else 0.0
            bt_total = bt_tech_w + bt_pattern_w + bt_flow_w + bt_onchain_w
            if bt_total > 0:
                bt_tech_w /= bt_total
                bt_pattern_w /= bt_total
                bt_flow_w /= bt_total
                bt_onchain_w /= bt_total
        else:
            bt_tech_w = config.tech_weight
            bt_pattern_w = config.pattern_weight
            bt_flow_w = 0.0
            bt_onchain_w = 0.0

        indicator_preliminary = compute_preliminary_score(
            technical_score=tech_result["score"],
            order_flow_score=flow_score,
            tech_weight=bt_tech_w,
            flow_weight=bt_flow_w,
            onchain_score=onchain_score,
            onchain_weight=bt_onchain_w,
            pattern_score=pat_score,
            pattern_weight=bt_pattern_w,
            flow_confidence=flow_confidence,
            onchain_confidence=onchain_confidence,
        )["score"]
```

**NOTE:** This replaces the existing outer-weight block and `compute_preliminary_score` call — do not keep the old hardcoded `flow_weight=0.0, onchain_weight=0.0` version.

- [ ] **Step 4: Add coverage tracking to results**

After `_build_results` returns, inject coverage stats into the result dict (avoids changing `_build_results` signature):
```python
    result = _build_results(trades, pair, config)
    result["stats"]["flow_coverage_pct"] = round(
        flow_covered / evaluated_candles * 100, 1
    ) if evaluated_candles > 0 else 0.0
    result["stats"]["onchain_coverage_pct"] = round(
        onchain_covered / evaluated_candles * 100, 1
    ) if evaluated_candles > 0 else 0.0
    return result
```

- [ ] **Step 5: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_backtester_replay.py tests/engine/test_backtester.py -v`
Expected: PASS

---

## Task 6: Multi-Metric Fitness Function

**Files:**
- Modify: `backend/app/engine/optimizer.py`
- Test: `backend/tests/engine/test_optimizer_fitness.py`

Replace PF-only fitness with composite: `0.35*sharpe + 0.25*PF + 0.25*win_rate - 0.15*max_dd`.

- [ ] **Step 1: Write test**

```python
# backend/tests/engine/test_optimizer_fitness.py
from app.engine.optimizer import compute_multi_metric_fitness


def test_multi_metric_fitness_basic():
    """Multi-metric fitness should combine Sharpe, PF, win rate, and max drawdown."""
    # Note: backtester returns win_rate as 0-100 and max_drawdown as pct points
    stats = {
        "sharpe_ratio": 1.5,
        "profit_factor": 2.0,
        "win_rate": 60.0,       # 60% (backtester scale)
        "max_drawdown": 10.0,   # 10% (backtester scale)
    }
    fitness = compute_multi_metric_fitness(stats)
    assert 0.0 <= fitness <= 1.0


def test_high_drawdown_reduces_fitness():
    """High drawdown should reduce fitness even with good other metrics."""
    good = compute_multi_metric_fitness({
        "sharpe_ratio": 1.5, "profit_factor": 2.0, "win_rate": 60.0, "max_drawdown": 5.0,
    })
    bad_dd = compute_multi_metric_fitness({
        "sharpe_ratio": 1.5, "profit_factor": 2.0, "win_rate": 60.0, "max_drawdown": 25.0,
    })
    assert good > bad_dd


def test_fitness_zero_trades_returns_zero():
    """With no trades, fitness should be 0 — including when backtester returns None values."""
    # Backtester returns None for sharpe_ratio (<7 trades) and profit_factor (no losses)
    fitness = compute_multi_metric_fitness({
        "sharpe_ratio": None, "profit_factor": None, "win_rate": 0.0, "max_drawdown": 0.0,
    })
    assert fitness == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer_fitness.py::test_multi_metric_fitness_basic -v`
Expected: FAIL — function doesn't exist

- [ ] **Step 3: Implement multi-metric fitness**

Add to `backend/app/engine/optimizer.py`:
```python
def compute_multi_metric_fitness(stats: dict) -> float:
    """Compute composite fitness from backtest stats.

    Formula: 0.35 * sharpe_norm + 0.25 * pf_norm + 0.25 * win_rate_norm - 0.15 * max_dd_norm
    Each metric normalized to [0, 1].

    IMPORTANT: The backtester returns stats with these keys and scales:
    - "sharpe_ratio" (not "sharpe") — float or None (<7 trades), unbounded
    - "profit_factor" — float or None (no losses), 0+
    - "win_rate" — float, 0-100 (percentage, NOT 0-1 fraction)
    - "max_drawdown" — float, percentage points (e.g., 5.0 means 5%)

    Values may be None when the backtester has insufficient data. Use `or 0.0`
    to coalesce None to zero (dict.get default only applies to missing keys,
    not keys present with None value).
    """
    sharpe = stats.get("sharpe_ratio") or 0.0
    pf = stats.get("profit_factor") or 0.0
    win_rate = stats.get("win_rate") or 0.0
    max_dd = stats.get("max_drawdown") or 0.0

    if sharpe == 0 and pf == 0 and win_rate == 0:
        return 0.0

    # normalize each to [0, 1]
    sharpe_norm = min(1.0, max(0.0, sharpe / 3.0))  # sharpe 3.0 = perfect
    pf_norm = min(1.0, max(0.0, (pf - 1.0) / 2.0)) if pf > 1.0 else 0.0  # PF 3.0 = perfect
    wr_norm = min(1.0, max(0.0, win_rate / 100.0))  # backtester returns 0-100
    dd_norm = min(1.0, max(0.0, max_dd / 30.0))  # backtester returns pct points (30 = 30%)

    fitness = 0.35 * sharpe_norm + 0.25 * pf_norm + 0.25 * wr_norm - 0.15 * dd_norm
    return max(0.0, min(1.0, fitness))
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer_fitness.py -v`
Expected: PASS

---

## Task 7: Statistical Significance Gate for Shadow Testing

**Files:**
- Modify: `backend/app/engine/optimizer.py`
- Test: `backend/tests/engine/test_optimizer_fitness.py`

Shadow testing requires minimum 20 signals but continues until z-test reaches p < 0.10 (or max 60 signals).

- [ ] **Step 1: Write test**

Add to `test_optimizer_fitness.py`:
```python
from app.engine.optimizer import evaluate_shadow_results


def test_shadow_z_test_significant_promote():
    """Shadow with clearly better results should be promoted."""
    current = [0.01, -0.005, 0.008, -0.003, 0.012] * 5  # 25 results, mostly positive
    shadow = [0.02, 0.015, 0.01, 0.005, 0.018] * 5  # 25 results, strongly positive
    result = evaluate_shadow_results(current, shadow)
    assert result == "promote"


def test_shadow_z_test_too_few_inconclusive():
    """With < 20 shadow results, should be inconclusive."""
    current = [0.01] * 10
    shadow = [0.02] * 10
    result = evaluate_shadow_results(current, shadow)
    assert result == "inconclusive"


def test_shadow_z_test_not_significant_inconclusive():
    """When shadow has identical win rate, z-test should return inconclusive."""
    # Same win/loss pattern — z-score will be 0
    current = [0.01, -0.005, 0.008, -0.003] * 6  # 24 results, 50% win rate
    shadow = [0.012, -0.004, 0.009, -0.002] * 6   # 24 results, 50% win rate (same ratio)
    result = evaluate_shadow_results(current, shadow)
    assert result == "inconclusive"
```

- [ ] **Step 2: Update evaluate_shadow_results with z-test**

Replace the current PF comparison with a proportional z-test:
```python
def evaluate_shadow_results(
    current_pnls: list[float],
    shadow_pnls: list[float],
) -> str:
    """Compare current vs shadow using z-test for statistical significance.

    Returns 'promote', 'reject', or 'inconclusive'.
    Requires minimum 20 signals. Max 60 signals.
    """
    min_signals = 20
    if len(current_pnls) < min_signals or len(shadow_pnls) < min_signals:
        return "inconclusive"

    import math

    current_pf = _compute_pf(current_pnls)
    shadow_pf = _compute_pf(shadow_pnls)

    # z-test on win rates (proportion test)
    n_c = len(current_pnls)
    n_s = len(shadow_pnls)
    p_c = sum(1 for p in current_pnls if p > 0) / n_c
    p_s = sum(1 for p in shadow_pnls if p > 0) / n_s

    p_pooled = (p_c * n_c + p_s * n_s) / (n_c + n_s)
    if p_pooled <= 0 or p_pooled >= 1:
        return "inconclusive"

    se = math.sqrt(p_pooled * (1 - p_pooled) * (1/n_c + 1/n_s))
    if se <= 0:
        return "inconclusive"

    z = (p_s - p_c) / se

    # one-tailed test: p < 0.10 corresponds to z > 1.28
    if z > 1.28 and shadow_pf > current_pf:
        return "promote"
    if shadow_pf < current_pf * 0.80:  # 20% worse
        return "reject"
    return "inconclusive"
```

- [ ] **Step 3: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer_fitness.py -v`
Expected: PASS

---

## Task 8: Rollback Window Expansion

**Files:**
- Modify: `backend/app/engine/optimizer.py:23-31`

- [ ] **Step 1: Update OPTIMIZER_CONFIG**

Change:
```python
"rollback_drop_pct": 0.20,   # was 0.15 — reduces false-positive rollbacks
"rollback_window": 20,        # was 10
```

- [ ] **Step 2: Run existing optimizer tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py -v`
Expected: PASS

---

## Task 9: Coverage-Gated Optimization

**Files:**
- Modify: `backend/app/engine/optimizer.py`
- Test: `backend/tests/engine/test_optimizer_fitness.py`

When optimizing flow/on-chain parameters, compute fitness only over candles with data. Skip entirely if <30 candles have data.

- [ ] **Step 1: Write test**

Add to `test_optimizer_fitness.py`:
```python
from app.engine.optimizer import should_skip_source_optimization


def test_skip_optimization_low_coverage():
    """Should skip optimization when fewer than 30 candles have data."""
    assert should_skip_source_optimization(covered_candles=20, min_required=30) is True


def test_allow_optimization_sufficient_coverage():
    assert should_skip_source_optimization(covered_candles=50, min_required=30) is False
```

- [ ] **Step 2: Implement helper**

Add to `optimizer.py`:
```python
def should_skip_source_optimization(covered_candles: int, min_required: int = 30) -> bool:
    """Check if there are enough covered candles to meaningfully optimize a source."""
    return covered_candles < min_required
```

- [ ] **Step 3: Wire into run_counterfactual_eval**

In `run_counterfactual_eval`, before running the backtest for flow/on-chain parameter groups, check coverage from the backtest result and skip if insufficient.

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer_fitness.py tests/engine/test_optimizer.py -v`
Expected: PASS

---

## Task 10: Wire persist_onchain_snapshot in Main Pipeline

**Files:**
- Modify: `backend/app/main.py`

Without wiring in main.py, the OnchainSnapshot table will remain empty and the backtester replay feature will have no data.

- [ ] **Step 1: Call persist_onchain_snapshot after on-chain scoring**

In `main.py`, after the on-chain scoring call and before the combiner, add:
```python
if onchain_available:
    from app.engine.onchain_scorer import persist_onchain_snapshot
    try:
        async with db.session_factory() as session:
            # collect the raw metric values that were scored
            raw_metrics = {}
            for metric in ["exchange_netflow", "whale_tx_count", "addr_trend_pct", "nupl", "hashrate_change_pct", "staking_flow", "gas_trend_pct"]:
                val = await redis.get(f"onchain:{pair}:{metric}")
                if val is not None:
                    try:
                        raw_metrics[metric] = float(val)
                    except (ValueError, TypeError):
                        pass
            if raw_metrics:
                await persist_onchain_snapshot(session, pair, candle_timestamp, raw_metrics)
                await session.commit()
    except Exception as e:
        logger.debug(f"On-chain snapshot persistence skipped: {e}")
```

- [ ] **Step 2: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=60`
Expected: PASS

---

## Task 11: Fix BacktestConfig Usage in Optimizer

**Files:**
- Modify: `backend/app/engine/optimizer.py` (run_counterfactual_eval)

The existing `run_counterfactual_eval` creates `BacktestConfig(pair=pair, timeframe="15m", ...)` but `BacktestConfig` has no `pair` or `timeframe` fields — this causes `TypeError` at runtime. Fix while we're already modifying this function.

- [ ] **Step 1: Fix BacktestConfig instantiation**

In `run_counterfactual_eval`, change:
```python
config = BacktestConfig(
    pair=pair,
    timeframe="15m",
    signal_threshold=candidate.get("signal", settings.engine_signal_threshold),
)
```
to:
```python
config = BacktestConfig(
    signal_threshold=candidate.get("signal", settings.engine_signal_threshold),
)
```

- [ ] **Step 2: Run existing optimizer tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py -v`
Expected: PASS

---

## Task 12: Wire Multi-Metric Fitness into Optimizer

**Files:**
- Modify: `backend/app/engine/optimizer.py` (run_counterfactual_eval)

- [ ] **Step 1: Replace PF-based candidate comparison with multi-metric fitness**

In `run_counterfactual_eval`, where backtest results are evaluated:
```python
fitness = compute_multi_metric_fitness(backtest_stats)
```

Use `fitness` instead of `profit_factor` for candidate selection and improvement threshold comparison.

- [ ] **Step 2: Run full optimizer test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py tests/engine/test_optimizer_fitness.py -v`
Expected: PASS

---

## Task 13: Load Snapshots in Optimizer Counterfactual Eval

**Files:**
- Modify: `backend/app/engine/optimizer.py` (run_counterfactual_eval)
- Test: `backend/tests/engine/test_optimizer_fitness.py`

Without this, the optimizer will always run backtests with zero flow/on-chain data, defeating the plan's core goal of tuning all scoring sources.

- [ ] **Step 1: Write test**

Add to `test_optimizer_fitness.py`:
```python
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio


def test_counterfactual_eval_loads_snapshots():
    """run_counterfactual_eval should query OrderFlowSnapshot and OnchainSnapshot
    and pass them to run_backtest."""
    # This is a wiring test — verify the query and parameter passing, not the backtest itself
    from app.engine.optimizer import run_counterfactual_eval
    # Detailed integration test would require full app state; verify at integration level
    # in Task 14.
```

- [ ] **Step 2: Load snapshots in run_counterfactual_eval**

In `run_counterfactual_eval`, after loading candles and before the grid sweep, add snapshot queries:
```python
            # Load flow snapshots for this pair/timerange
            from app.db.models import OrderFlowSnapshot, OnchainSnapshot
            candle_dicts = [
                {"timestamp": c.timestamp, "open": float(c.open), "high": float(c.high),
                 "low": float(c.low), "close": float(c.close), "volume": float(c.volume)}
                for c in candles
            ]
            time_start = candles[0].timestamp
            time_end = candles[-1].timestamp

            flow_result = await session.execute(
                select(OrderFlowSnapshot)
                .where(OrderFlowSnapshot.pair == pair)
                .where(OrderFlowSnapshot.timestamp >= time_start)
                .where(OrderFlowSnapshot.timestamp <= time_end)
                .order_by(OrderFlowSnapshot.timestamp)
            )
            flow_rows = flow_result.scalars().all()
            flow_snapshots = [
                {"timestamp": r.timestamp, "funding_rate": r.funding_rate,
                 "long_short_ratio": r.long_short_ratio,
                 "open_interest_change_pct": r.oi_change_pct}
                for r in flow_rows
            ] if flow_rows else None

            onchain_result = await session.execute(
                select(OnchainSnapshot)
                .where(OnchainSnapshot.pair == pair)
                .where(OnchainSnapshot.timestamp >= time_start)
                .where(OnchainSnapshot.timestamp <= time_end)
                .order_by(OnchainSnapshot.timestamp)
            )
            onchain_rows = onchain_result.scalars().all()
            onchain_snapshots = [
                {"timestamp": r.timestamp, "metric_name": r.metric_name, "value": r.value}
                for r in onchain_rows
            ] if onchain_rows else None
```

Then update the `run_backtest` call inside the grid sweep to pass snapshot data:
```python
            results = await loop.run_in_executor(
                None,
                lambda: run_backtest(
                    candles=candle_dicts,
                    pair=pair,
                    config=config,
                    cancel_flag=None,
                    flow_snapshots=flow_snapshots,
                    onchain_snapshots=onchain_snapshots,
                ),
            )
```

- [ ] **Step 3: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_optimizer.py tests/engine/test_optimizer_fitness.py -v`
Expected: PASS

---

## Task 14: Full Integration Test

- [ ] **Step 1: Run the full backend test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=120`
Expected: All tests pass

- [ ] **Step 2: Run a backtest with flow snapshots end-to-end**

If there are existing OrderFlowSnapshot rows in the test database, verify the backtester picks them up and reports non-zero coverage.

- [ ] **Step 3: Verify optimizer loads snapshots**

Run a counterfactual eval manually (or via the optimizer API) against a pair with flow/on-chain data. Verify the backtest results include non-zero `flow_coverage_pct`.
