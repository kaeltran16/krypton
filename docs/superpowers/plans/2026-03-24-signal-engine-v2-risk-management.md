# Signal Engine v2 — Risk Management

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade position sizing with correlation-adjusted sizing, fractional Kelly criterion, confidence-based scaling, and drawdown-aware daily limits.

**Architecture:** Position sizing follows a sequential reduction chain: `kelly_base * confidence_multiplier * correlation_adjustment`. Each step can only reduce, never increase beyond Kelly base. A 30-day rolling correlation matrix (3x3 for current pairs) is recomputed daily and stored in `app.state`. Drawdown tracking compares equity against intraday peak, pausing signals if the drop exceeds 3%.

**Tech Stack:** Python, NumPy, pytest

**Spec:** `docs/superpowers/specs/2026-03-24-signal-engine-v2-design.md` (Section 7)

**Depends on:** Plan 1 (confidence tiers for confidence-based sizing)

---

## File Structure

### Modified Files

| File | Responsibility |
|------|---------------|
| `backend/app/engine/risk.py` | Fractional Kelly, confidence sizing, correlation adjustment, drawdown tracker |
| `backend/app/main.py` | Initialize correlation matrix in app.state, wire drawdown check before signal emission |

### Test Files

| File | What it covers |
|------|---------------|
| `backend/tests/engine/test_risk_v2.py` | Kelly, correlation sizing, confidence scaling, drawdown pausing |

---

## Task 1: Fractional Kelly Position Sizing

**Files:**
- Modify: `backend/app/engine/risk.py`
- Test: `backend/tests/engine/test_risk_v2.py`

Replace fixed `risk_per_trade` with 20% Kelly fraction. Falls back to fixed % when <40 resolved signals.

- [ ] **Step 1: Write test**

```python
# backend/tests/engine/test_risk_v2.py
from app.engine.risk import compute_kelly_fraction


def test_kelly_fraction_positive_edge():
    """Positive edge (win rate > breakeven) should return positive Kelly fraction."""
    # win_rate=0.55, avg_win=2.0, avg_loss=1.0 → f* = (2*0.55 - 0.45)/2 = 0.325
    # 20% Kelly = 0.065
    kelly = compute_kelly_fraction(win_rate=0.55, avg_win=2.0, avg_loss=1.0)
    assert 0.05 < kelly < 0.08


def test_kelly_fraction_negative_edge():
    """Negative edge (losing strategy) should return probe size."""
    kelly = compute_kelly_fraction(win_rate=0.30, avg_win=1.0, avg_loss=1.5, fallback_risk=0.01)
    # Kelly is negative → use 25% of fallback = 0.0025
    assert kelly == 0.0025


def test_kelly_fraction_insufficient_data():
    """With fewer than min_signals resolved, should return fallback."""
    kelly = compute_kelly_fraction(
        win_rate=0.55, avg_win=2.0, avg_loss=1.0,
        resolved_count=20, min_signals=40, fallback_risk=0.01,
    )
    assert kelly == 0.01


def test_kelly_fraction_zero_loss():
    """Zero avg_loss (all winners) should cap at reasonable value."""
    kelly = compute_kelly_fraction(win_rate=1.0, avg_win=2.0, avg_loss=0.0)
    assert kelly > 0
    assert kelly <= 0.05  # capped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_risk_v2.py::test_kelly_fraction_positive_edge -v`
Expected: FAIL

- [ ] **Step 3: Implement compute_kelly_fraction**

Add to `backend/app/engine/risk.py`:
```python
KELLY_FRACTION = 0.20
KELLY_PROBE_FRACTION = 0.25


def compute_kelly_fraction(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    resolved_count: int | None = None,
    min_signals: int = 40,
    fallback_risk: float = 0.01,
) -> float:
    """Compute 20% Kelly criterion for position sizing.

    Returns risk_per_trade fraction (0.0 to ~0.05).
    Falls back to fixed risk when insufficient data.
    If Kelly is negative (losing strategy), returns 25% of fallback as probe size.
    """
    if resolved_count is not None and resolved_count < min_signals:
        return fallback_risk

    if avg_loss <= 0:
        # all winners — use capped Kelly
        return min(0.05, KELLY_FRACTION * win_rate)

    b = avg_win / avg_loss  # odds ratio
    p = win_rate
    q = 1.0 - p

    kelly_full = (b * p - q) / b
    if kelly_full <= 0:
        return KELLY_PROBE_FRACTION * fallback_risk

    kelly_sized = KELLY_FRACTION * kelly_full
    return min(kelly_sized, 0.05)  # hard cap at 5% risk per trade
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_risk_v2.py -v -k "kelly"`
Expected: PASS

---

## Task 2: Confidence-Based Position Sizing

**Files:**
- Modify: `backend/app/engine/risk.py`
- Test: `backend/tests/engine/test_risk_v2.py`

Scale position size by signal confidence tier: high=100%, medium=70%, low=50%.

- [ ] **Step 1: Write test**

Add to `test_risk_v2.py`:
```python
from app.engine.risk import confidence_size_multiplier


def test_confidence_high_full_size():
    assert confidence_size_multiplier("high") == 1.0


def test_confidence_medium_reduced():
    assert confidence_size_multiplier("medium") == 0.7


def test_confidence_low_half():
    assert confidence_size_multiplier("low") == 0.5


def test_confidence_none_default():
    assert confidence_size_multiplier(None) == 1.0
```

- [ ] **Step 2: Implement**

Add to `risk.py`:
```python
CONFIDENCE_MULTIPLIERS = {"high": 1.0, "medium": 0.7, "low": 0.5}


def confidence_size_multiplier(tier: str | None) -> float:
    """Return position size multiplier based on confidence tier."""
    if tier is None:
        return 1.0
    return CONFIDENCE_MULTIPLIERS.get(tier, 1.0)
```

- [ ] **Step 3: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_risk_v2.py -v -k "confidence"`
Expected: PASS

---

## Task 3: Correlation-Adjusted Position Sizing

**Files:**
- Modify: `backend/app/engine/risk.py`
- Test: `backend/tests/engine/test_risk_v2.py`

Reduce position size when correlated pairs have open positions in the same direction.

- [ ] **Step 1: Write test**

Add to `test_risk_v2.py`:
```python
import numpy as np
from app.engine.risk import compute_correlation_adjustment


def test_correlation_reduces_size_for_correlated_pairs():
    """Correlated pairs with same-direction positions should reduce new position size."""
    corr_matrix = np.array([
        [1.0, 0.8, 0.3],
        [0.8, 1.0, 0.2],
        [0.3, 0.2, 1.0],
    ])
    pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "WIF-USDT-SWAP"]
    open_positions = [
        {"pair": "BTC-USDT-SWAP", "direction": "LONG", "size_usd": 1000.0},
    ]
    equity = 10000.0

    # ETH LONG with BTC LONG open, correlation 0.8
    adj = compute_correlation_adjustment(
        new_pair="ETH-USDT-SWAP", new_direction="LONG",
        open_positions=open_positions, corr_matrix=corr_matrix,
        pairs=pairs, equity=equity,
    )
    # reduction = 0.8 * (1000/10000) = 0.08 → multiplier = 0.92
    assert 0.85 < adj < 0.98


def test_no_reduction_for_uncorrelated():
    """Uncorrelated pairs should have no reduction."""
    corr_matrix = np.eye(3)
    pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "WIF-USDT-SWAP"]
    open_positions = [
        {"pair": "BTC-USDT-SWAP", "direction": "LONG", "size_usd": 5000.0},
    ]
    adj = compute_correlation_adjustment(
        new_pair="WIF-USDT-SWAP", new_direction="LONG",
        open_positions=open_positions, corr_matrix=corr_matrix,
        pairs=pairs, equity=10000.0,
    )
    assert adj == 1.0


def test_opposite_direction_no_reduction():
    """Opposite direction positions should not trigger reduction."""
    corr_matrix = np.array([[1.0, 0.9], [0.9, 1.0]])
    pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    open_positions = [
        {"pair": "BTC-USDT-SWAP", "direction": "LONG", "size_usd": 5000.0},
    ]
    adj = compute_correlation_adjustment(
        new_pair="ETH-USDT-SWAP", new_direction="SHORT",
        open_positions=open_positions, corr_matrix=corr_matrix,
        pairs=pairs, equity=10000.0,
    )
    assert adj == 1.0


def test_correlation_floor():
    """Adjustment should never go below 0.2 floor."""
    corr_matrix = np.array([[1.0, 0.95], [0.95, 1.0]])
    pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    open_positions = [
        {"pair": "BTC-USDT-SWAP", "direction": "LONG", "size_usd": 8000.0},
    ]
    adj = compute_correlation_adjustment(
        new_pair="ETH-USDT-SWAP", new_direction="LONG",
        open_positions=open_positions, corr_matrix=corr_matrix,
        pairs=pairs, equity=10000.0,
    )
    assert adj >= 0.2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_risk_v2.py::test_correlation_reduces_size_for_correlated_pairs -v`
Expected: FAIL

- [ ] **Step 3: Implement correlation adjustment**

Add to `risk.py`:
```python
CORRELATION_FLOOR = 0.2


def compute_correlation_adjustment(
    new_pair: str,
    new_direction: str,
    open_positions: list[dict],
    corr_matrix: np.ndarray,
    pairs: list[str],
    equity: float,
) -> float:
    """Compute correlation-based position size reduction.

    Returns multiplier in [CORRELATION_FLOOR, 1.0].
    """
    if not open_positions or equity <= 0:
        return 1.0

    pair_idx = {p: i for i, p in enumerate(pairs)}
    new_idx = pair_idx.get(new_pair)
    if new_idx is None:
        return 1.0

    total_reduction = 0.0
    for pos in open_positions:
        # only reduce for same-direction correlated positions
        if pos["direction"] != new_direction:
            continue
        pos_idx = pair_idx.get(pos["pair"])
        if pos_idx is None or pos_idx == new_idx:
            continue
        correlation = corr_matrix[new_idx, pos_idx]
        if correlation <= 0:
            continue
        pos_weight = pos["size_usd"] / equity
        total_reduction += correlation * pos_weight

    return max(CORRELATION_FLOOR, 1.0 - total_reduction)
```

- [ ] **Step 4: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_risk_v2.py -v -k "correlation"`
Expected: PASS

---

## Task 4: Correlation Matrix Computation

**Files:**
- Modify: `backend/app/engine/risk.py`
- Test: `backend/tests/engine/test_risk_v2.py`

Compute 30-day rolling return correlation matrix from 1h candle returns. Cold start (<7 days) uses identity matrix.

- [ ] **Step 1: Write test**

Add to `test_risk_v2.py`:
```python
def test_compute_correlation_matrix_cold_start():
    """With <7 days of data, should return identity matrix."""
    from app.engine.risk import compute_return_correlation

    # 5 days of hourly candles = 120 candles per pair
    pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    returns = {
        "BTC-USDT-SWAP": np.random.randn(120),
        "ETH-USDT-SWAP": np.random.randn(120),
    }
    corr = compute_return_correlation(returns, pairs, min_days=7, hours_per_day=24)
    np.testing.assert_array_equal(corr, np.eye(2))


def test_compute_correlation_matrix_sufficient_data():
    """With sufficient data, should compute actual correlations."""
    from app.engine.risk import compute_return_correlation

    np.random.seed(42)
    pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    base = np.random.randn(720)
    returns = {
        "BTC-USDT-SWAP": base + np.random.randn(720) * 0.1,
        "ETH-USDT-SWAP": base + np.random.randn(720) * 0.1,
    }
    corr = compute_return_correlation(returns, pairs, min_days=7, hours_per_day=24)
    # Highly correlated signals should show correlation > 0.5
    assert corr[0, 1] > 0.5
    assert corr[1, 0] > 0.5
```

- [ ] **Step 2: Implement**

Add to `risk.py`:
```python
import numpy as np

CORRELATION_WARM_UP_DAYS = 7


def compute_return_correlation(
    returns: dict[str, np.ndarray],
    pairs: list[str],
    min_days: int = CORRELATION_WARM_UP_DAYS,
    hours_per_day: int = 24,
) -> np.ndarray:
    """Compute rolling return correlation matrix.

    Returns identity matrix if any pair has fewer than min_days * hours_per_day data points.
    """
    n = len(pairs)
    min_points = min_days * hours_per_day

    for pair in pairs:
        if pair not in returns or len(returns[pair]) < min_points:
            return np.eye(n)

    # take last 30 days (720 1h candles)
    window = 30 * hours_per_day
    data = np.column_stack([
        returns[pair][-window:] if len(returns[pair]) >= window else returns[pair]
        for pair in pairs
    ])

    corr = np.corrcoef(data, rowvar=False)
    # handle NaN from constant columns
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    return corr
```

- [ ] **Step 3: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_risk_v2.py -v -k "correlation_matrix"`
Expected: PASS

---

## Task 5: Drawdown-Aware Daily Limit

**Files:**
- Modify: `backend/app/engine/risk.py`
- Test: `backend/tests/engine/test_risk_v2.py`

Track peak equity intraday. If drawdown from peak exceeds 3%, pause signal emission until next UTC day.

- [ ] **Step 1: Write test**

Add to `test_risk_v2.py`:
```python
from app.engine.risk import DrawdownTracker


def test_drawdown_tracker_no_drawdown():
    """No drawdown when equity is at peak."""
    tracker = DrawdownTracker(max_drawdown_pct=0.03)
    tracker.update_equity(10000.0)
    assert tracker.should_pause() is False


def test_drawdown_tracker_pauses_on_drawdown():
    """Should pause when drawdown exceeds threshold."""
    tracker = DrawdownTracker(max_drawdown_pct=0.03)
    tracker.update_equity(10000.0)
    tracker.update_equity(9600.0)  # 4% drawdown
    assert tracker.should_pause() is True


def test_drawdown_tracker_resets_on_new_day():
    """Pause should reset at next UTC day."""
    tracker = DrawdownTracker(max_drawdown_pct=0.03)
    tracker.update_equity(10000.0)
    tracker.update_equity(9600.0)  # pause

    # simulate next day
    tracker.reset_daily()
    tracker.update_equity(9600.0)  # new peak for new day
    assert tracker.should_pause() is False
```

- [ ] **Step 2: Implement DrawdownTracker**

Add to `risk.py`:
```python
class DrawdownTracker:
    """Tracks intraday peak equity and pauses signals on excessive drawdown."""

    def __init__(self, max_drawdown_pct: float = 0.03):
        self.max_drawdown_pct = max_drawdown_pct
        self._peak_equity = 0.0
        self._paused = False

    def update_equity(self, equity: float):
        if equity > self._peak_equity:
            self._peak_equity = equity
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown >= self.max_drawdown_pct:
                self._paused = True

    def should_pause(self) -> bool:
        return self._paused

    def reset_daily(self):
        self._peak_equity = 0.0
        self._paused = False
```

- [ ] **Step 3: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_risk_v2.py -v -k "drawdown"`
Expected: PASS

---

## Task 6: Integrated Position Sizing Chain

**Files:**
- Modify: `backend/app/engine/risk.py`
- Test: `backend/tests/engine/test_risk_v2.py`

Create a function that chains: `kelly_base * confidence_multiplier * correlation_adjustment`.

- [ ] **Step 1: Write test**

Add to `test_risk_v2.py`:
```python
from app.engine.risk import compute_adjusted_risk_per_trade


def test_sizing_chain_all_reductions():
    """Full chain: kelly * confidence * correlation. Each step can only reduce."""
    result = compute_adjusted_risk_per_trade(
        kelly_risk=0.04,           # 4% kelly
        confidence_tier="medium",  # 0.7x
        correlation_adj=0.9,       # 0.9x
    )
    expected = 0.04 * 0.7 * 0.9  # = 0.0252
    assert abs(result - expected) < 0.001


def test_sizing_chain_no_increase_above_kelly():
    """Result should never exceed kelly_risk."""
    result = compute_adjusted_risk_per_trade(
        kelly_risk=0.02,
        confidence_tier="high",    # 1.0x
        correlation_adj=1.0,       # 1.0x
    )
    assert result <= 0.02
```

- [ ] **Step 2: Implement**

Add to `risk.py`:
```python
def compute_adjusted_risk_per_trade(
    kelly_risk: float,
    confidence_tier: str | None = None,
    correlation_adj: float = 1.0,
) -> float:
    """Compute final risk_per_trade through sequential reduction chain.

    kelly_base * confidence_multiplier * correlation_adjustment
    Each step can only reduce, never increase beyond kelly_base.
    """
    conf_mult = confidence_size_multiplier(confidence_tier)
    return kelly_risk * conf_mult * correlation_adj
```

- [ ] **Step 3: Run tests**

Run: `docker exec krypton-api-1 python -m pytest tests/engine/test_risk_v2.py -v -k "sizing_chain"`
Expected: PASS

---

## Task 7: Wire Risk Improvements into Main Pipeline

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Initialize correlation state and drawdown tracker in lifespan**

In `main.py` lifespan:
```python
app.state.correlation_matrix = np.eye(3)
app.state.correlation_pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "WIF-USDT-SWAP"]
app.state.drawdown_tracker = DrawdownTracker(max_drawdown_pct=0.03)
```

- [ ] **Step 2: Add daily correlation recomputation**

In the outcome resolution loop (or a timestamp-checked guard in `run_pipeline`), recompute correlation when >24h have elapsed:
```python
import numpy as np
from datetime import datetime, timezone

# at start of run_pipeline or outcome loop:
last_corr_update = getattr(app.state, "_last_corr_update", None)
now = datetime.now(timezone.utc)
if last_corr_update is None or (now - last_corr_update).total_seconds() > 86400:
    # fetch 30 days of 1h candle closes from DB, compute log returns per pair
    from app.engine.risk import compute_return_correlation
    returns = {}  # populated from DB query
    for pair in app.state.correlation_pairs:
        # query 1h candles, compute close-to-close returns
        # returns[pair] = np.diff(np.log(closes))
        pass  # actual DB query here
    app.state.correlation_matrix = compute_return_correlation(
        returns, app.state.correlation_pairs
    )
    app.state._last_corr_update = now
```

- [ ] **Step 3: Wire drawdown check before signal emission**

In `run_pipeline`, before `_emit_signal`:
```python
if app.state.drawdown_tracker.should_pause():
    logger.info("Signal emission paused: intraday drawdown limit reached")
    return
```

- [ ] **Step 4: Wire drawdown daily reset**

Add a UTC day boundary check at the start of `run_pipeline` or the outcome loop:
```python
from datetime import date
tracker = app.state.drawdown_tracker
today = date.today()
if getattr(tracker, "_last_reset_date", None) != today:
    tracker.reset_daily()
    tracker._last_reset_date = today
```

- [ ] **Step 5: Compute Kelly inputs from rolling 100 signals**

Add a helper that queries the last 100 resolved signals per (pair, timeframe) to compute win_rate, avg_win, avg_loss:
```python
async def get_kelly_inputs(session, pair: str, timeframe: str, window: int = 100):
    """Query last N resolved signals to compute Kelly criterion inputs."""
    from sqlalchemy import select
    from app.db.models import Signal
    result = await session.execute(
        select(Signal.outcome_pnl_pct)
        .where(Signal.pair == pair, Signal.timeframe == timeframe,
               Signal.outcome.in_(["TP1_HIT", "TP2_HIT", "SL_HIT"]))
        .order_by(Signal.outcome_at.desc())
        .limit(window)
    )
    pnls = [row[0] for row in result.all() if row[0] is not None]
    if len(pnls) < 10:
        return None  # insufficient data
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    return {
        "win_rate": len(wins) / len(pnls),
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "resolved_count": len(pnls),
    }
```

- [ ] **Step 6: Wire adjusted sizing into _emit_signal**

In `_emit_signal`, replace fixed `risk_per_trade` with the computed adjusted risk:
```python
# compute Kelly from rolling 100 signals
kelly_inputs = await get_kelly_inputs(session, pair, timeframe)
if kelly_inputs:
    kelly_risk = compute_kelly_fraction(
        win_rate=kelly_inputs["win_rate"],
        avg_win=kelly_inputs["avg_win"],
        avg_loss=kelly_inputs["avg_loss"],
        resolved_count=kelly_inputs["resolved_count"],
        fallback_risk=risk_settings.risk_per_trade,
    )
else:
    kelly_risk = risk_settings.risk_per_trade  # fallback

# compute correlation adjustment
corr_adj = compute_correlation_adjustment(
    new_pair=pair, new_direction=direction,
    open_positions=open_positions_list,  # from app.state or DB
    corr_matrix=app.state.correlation_matrix,
    pairs=app.state.correlation_pairs,
    equity=balance,
)

adjusted_risk = compute_adjusted_risk_per_trade(
    kelly_risk=kelly_risk,
    confidence_tier=signal_data.get("confidence_tier"),
    correlation_adj=corr_adj,
)
# Note: max_position_size_usd and 25% equity caps are enforced by PositionSizer.calculate()
sizer = PositionSizer(equity=balance, risk_per_trade=adjusted_risk, ...)
```

- [ ] **Step 5: Run full test suite**

Run: `docker exec krypton-api-1 python -m pytest tests/ -v --timeout=120`
Expected: PASS
