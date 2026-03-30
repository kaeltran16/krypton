# Risk & Execution Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fractional Kelly position sizing and partial-exit ATR trailing stops to the signal engine.

**Architecture:** Two independent features sharing outcome type changes. Kelly computes adaptive `risk_per_trade` from resolved signal history before position sizing. The outcome resolver gains a two-pass mode: TP1 triggers a 50% exit, then an ATR trailing stop manages the remainder. New outcome types (`TP1_TRAIL`, `TP1_TP2`) propagate to API filters and frontend.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, pytest, React/TypeScript

**Spec:** `docs/superpowers/specs/2026-03-31-risk-execution-improvements-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/engine/risk.py` | Modify | Add `compute_kelly_risk()` pure function |
| `backend/app/engine/outcome_resolver.py` | Modify | Rewrite to support two-pass resolution with trailing stop |
| `backend/app/engine/performance_tracker.py` | Modify | Forward `atr` to `resolve_signal_outcome` in `replay_signal` |
| `backend/app/main.py` | Modify | Kelly integration in `_emit_signal`; ATR + force-close in `check_pending_signals` |
| `backend/app/api/routes.py` | Modify | Add `TP1_TRAIL`, `TP1_TP2` to all win outcome checks (lines 66, 367, 385, 398, 409, 493) |
| `backend/app/api/risk.py` | Modify | Add `TP1_TRAIL`, `TP1_TP2` to daily P&L filter |
| `backend/app/engine/regime_optimizer.py` | Modify | Add `TP1_TRAIL`, `TP1_TP2` to win outcome check (line 283) |
| `web/src/features/signals/components/SignalCard.tsx` | Modify | Add outcome color + label map entries |
| `web/src/features/signals/types.ts` | Modify | Add `TP1_TRAIL`, `TP1_TP2` to `SignalOutcome` type |
| `web/src/shared/lib/api.ts` | Modify | Fix outcome type union in `TradeHistoryEntry` |
| `web/src/features/home/components/RecentSignals.tsx` | Modify | Add outcome badge entries |
| `web/src/features/positions/components/HistorySegment.tsx` | Modify | Add outcome color entries |
| `web/src/features/signals/components/CalendarView.tsx` | Modify | Update inline outcome color logic |
| `backend/app/config.py` | Modify | Add `engine_kelly_fraction`, `engine_partial_fraction`, `engine_trail_atr_multiplier` settings |
| `backend/app/engine/param_groups.py` | Modify | Add `execution` parameter group for Kelly/partial/trail tuning |
| `backend/app/engine/optimizer.py` | Modify | Add `execution` to `_NON_BACKTESTABLE` set |
| `backend/tests/engine/test_kelly.py` | Create | Tests for `compute_kelly_risk()` |
| `backend/tests/engine/test_outcome_resolver.py` | Modify | Add tests for two-pass resolution, trailing stop, force-close |

---

### Task 1: `compute_kelly_risk()` — Tests

**Files:**
- Create: `backend/tests/engine/test_kelly.py`

- [ ] **Step 1: Write all Kelly tests**

```python
# backend/tests/engine/test_kelly.py
import pytest

from app.engine.risk import compute_kelly_risk


def _make_outcomes(wins: int, losses: int, win_pnl: float = 1.0, loss_pnl: float = -1.0):
    """Build a list of outcome dicts for testing."""
    outcomes = []
    for _ in range(wins):
        outcomes.append({"outcome": "TP1_HIT", "outcome_pnl_pct": win_pnl})
    for _ in range(losses):
        outcomes.append({"outcome": "SL_HIT", "outcome_pnl_pct": loss_pnl})
    return outcomes


class TestComputeKellyRisk:
    def test_insufficient_history_returns_default(self):
        outcomes = _make_outcomes(10, 10)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "default"
        assert result["risk_per_trade"] == 0.01
        assert result["sample_size"] == 20

    def test_empty_outcomes_returns_default(self):
        result = compute_kelly_risk([])
        assert result["source"] == "default"
        assert result["risk_per_trade"] == 0.01
        assert result["sample_size"] == 0

    def test_barely_profitable_in_range(self):
        # 26W/24L at ±1% → win_rate=0.52, odds=1.0
        # kelly = 0.52 - 0.48/1.0 = 0.04, fractional = 0.04*0.35 = 0.014
        outcomes = _make_outcomes(26, 24)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["risk_per_trade"] == pytest.approx(0.014, abs=0.001)
        assert result["win_rate"] == pytest.approx(0.52)
        assert result["odds"] == pytest.approx(1.0)
        assert result["sample_size"] == 50

    def test_strong_performance_hits_ceiling(self):
        # 40W/10L at ±1% → win_rate=0.80, odds=1.0
        # kelly = 0.80 - 0.20/1.0 = 0.60, fractional = 0.21 → clamped to 0.02
        outcomes = _make_outcomes(40, 10)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["risk_per_trade"] == 0.02  # ceiling

    def test_losing_strategy_hits_floor(self):
        # 15W/35L at ±1% → win_rate=0.30, odds=1.0
        # kelly = 0.30 - 0.70/1.0 = -0.40, fractional = -0.14 → clamped to 0.005
        outcomes = _make_outcomes(15, 35)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["risk_per_trade"] == 0.005  # floor

    def test_all_wins_returns_ceiling(self):
        outcomes = _make_outcomes(50, 0)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["risk_per_trade"] == 0.02

    def test_all_losses_returns_floor(self):
        outcomes = _make_outcomes(0, 50)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["risk_per_trade"] == 0.005

    def test_all_breakeven_returns_default(self):
        outcomes = [{"outcome": "TP1_HIT", "outcome_pnl_pct": 0.0} for _ in range(50)]
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "default"
        assert result["risk_per_trade"] == 0.01

    def test_filters_terminal_outcomes_only(self):
        outcomes = _make_outcomes(26, 24)
        # Add non-terminal outcomes that should be ignored
        outcomes.append({"outcome": "PENDING", "outcome_pnl_pct": 0.0})
        outcomes.append({"outcome": "EXPIRED", "outcome_pnl_pct": 0.0})
        result = compute_kelly_risk(outcomes)
        assert result["sample_size"] == 50  # PENDING and EXPIRED excluded

    def test_new_outcome_types_counted(self):
        # TP1_TRAIL and TP1_TP2 are wins
        outcomes = [
            {"outcome": "TP1_TRAIL", "outcome_pnl_pct": 1.5} for _ in range(26)
        ] + [
            {"outcome": "TP1_TP2", "outcome_pnl_pct": 2.0} for _ in range(4)
        ] + [
            {"outcome": "SL_HIT", "outcome_pnl_pct": -1.0} for _ in range(20)
        ]
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["win_rate"] == pytest.approx(0.60)

    def test_custom_parameters(self):
        outcomes = _make_outcomes(10, 10)  # only 20
        result = compute_kelly_risk(
            outcomes, min_signals=10, floor=0.003, ceiling=0.05, default_risk=0.02
        )
        assert result["source"] == "kelly"  # 20 >= min_signals=10
        assert result["risk_per_trade"] >= 0.003
        assert result["risk_per_trade"] <= 0.05
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_kelly.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_kelly_risk' from 'app.engine.risk'`

---

### Task 2: `compute_kelly_risk()` — Implementation

**Files:**
- Modify: `backend/app/engine/risk.py` (add function after `compute_rr_ratios`, before `class RiskGuard`)

- [ ] **Step 1: Add `compute_kelly_risk()` to `engine/risk.py`**

Insert after the `compute_rr_ratios` function (after line 100) and before `class RiskGuard` (line 103):

```python
_TERMINAL_OUTCOMES = frozenset({"TP1_HIT", "TP2_HIT", "SL_HIT", "TP1_TRAIL", "TP1_TP2"})
_WIN_OUTCOMES = frozenset({"TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2"})


def compute_kelly_risk(
    recent_outcomes: list[dict],
    kelly_fraction: float = 0.35,
    min_signals: int = 50,
    default_risk: float = 0.01,
    floor: float = 0.005,
    ceiling: float = 0.02,
) -> dict:
    """Compute adaptive risk_per_trade using fractional Kelly criterion.

    Returns dict with risk_per_trade, kelly_raw, win_rate, odds, sample_size, source.
    """
    terminal = [o for o in recent_outcomes if o["outcome"] in _TERMINAL_OUTCOMES]
    n = len(terminal)

    if n < min_signals:
        return {
            "risk_per_trade": default_risk,
            "kelly_raw": 0.0,
            "win_rate": 0.0,
            "odds": 0.0,
            "sample_size": n,
            "source": "default",
        }

    wins = [o for o in terminal if o["outcome"] in _WIN_OUTCOMES]
    win_rate = len(wins) / n

    pos_pnls = [o["outcome_pnl_pct"] for o in terminal if o["outcome_pnl_pct"] > 0]
    neg_pnls = [abs(o["outcome_pnl_pct"]) for o in terminal if o["outcome_pnl_pct"] < 0]

    avg_win = sum(pos_pnls) / len(pos_pnls) if pos_pnls else 0.0
    avg_loss = sum(neg_pnls) / len(neg_pnls) if neg_pnls else 0.0

    # Edge cases: division by zero
    if avg_win == 0.0 and avg_loss == 0.0:
        return {
            "risk_per_trade": default_risk,
            "kelly_raw": 0.0,
            "win_rate": win_rate,
            "odds": 0.0,
            "sample_size": n,
            "source": "default",
        }
    if avg_loss == 0.0:
        return {
            "risk_per_trade": ceiling,
            "kelly_raw": 1.0,
            "win_rate": win_rate,
            "odds": float("inf"),
            "sample_size": n,
            "source": "kelly",
        }
    if avg_win == 0.0:
        return {
            "risk_per_trade": floor,
            "kelly_raw": -1.0,
            "win_rate": win_rate,
            "odds": 0.0,
            "sample_size": n,
            "source": "kelly",
        }

    odds = avg_win / avg_loss
    kelly_raw = win_rate - (1 - win_rate) / odds
    kelly_frac = kelly_raw * kelly_fraction
    risk = max(floor, min(ceiling, kelly_frac))

    return {
        "risk_per_trade": round(risk, 6),
        "kelly_raw": round(kelly_raw, 6),
        "win_rate": round(win_rate, 4),
        "odds": round(odds, 4),
        "sample_size": n,
        "source": "kelly",
    }
```

- [ ] **Step 2: Run Kelly tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_kelly.py -v`
Expected: All 11 tests PASS

- [ ] **Step 3: Run existing risk guard tests to confirm no regression**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_risk_guard.py -v`
Expected: All existing tests PASS (no changes to RiskGuard or PositionSizer)

---

### Task 3: Two-Pass Outcome Resolver — Tests

**Files:**
- Modify: `backend/tests/engine/test_outcome_resolver.py`

- [ ] **Step 1: Add two-pass resolution tests**

Append to the existing test file after the last test (`test_no_resolution_yet`):

```python
# -- Two-pass resolution tests (atr provided) --

def _long_signal():
    return {
        "direction": "LONG",
        "entry": 67000.0,
        "stop_loss": 66500.0,
        "take_profit_1": 67500.0,
        "take_profit_2": 68500.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }


def _short_signal():
    return {
        "direction": "SHORT",
        "entry": 67000.0,
        "stop_loss": 67500.0,
        "take_profit_1": 66500.0,
        "take_profit_2": 65500.0,
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }


class TestTwoPassLong:
    def test_tp1_then_trail_hit(self):
        """TP1 hit on candle 1, trail ratchets up, trail hit on candle 3."""
        candles = [
            {"high": 67600.0, "low": 67050.0, "close": 67550.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit (67600>=67500)
            {"high": 67900.0, "low": 67600.0, "close": 67850.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # trail ratchets: max(67300, 67900-200)=67700
            {"high": 67800.0, "low": 67650.0, "close": 67700.0,
             "timestamp": "2026-03-01T12:45:00+00:00"},  # trail: max(67700, 67800-200)=67700, low=67650<=67700 → HIT
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result["outcome"] == "TP1_TRAIL"
        # tp1_pnl = (67500-67000)/67000*100 = 0.7463%
        # trail_pnl = (67700-67000)/67000*100 = 1.0448%
        # blended = 0.5*0.7463 + 0.5*1.0448 = 0.8955%
        assert result["outcome_pnl_pct"] == pytest.approx(0.8955, abs=0.01)
        assert result["partial_exit_pnl_pct"] == pytest.approx(0.7463, abs=0.01)
        assert result["trail_exit_pnl_pct"] == pytest.approx(1.0448, abs=0.01)
        assert result["trail_exit_price"] == pytest.approx(67700.0, abs=1.0)

    def test_tp1_then_tp2_hit(self):
        """TP1 hit, then TP2 hit → TP1_TP2."""
        candles = [
            {"high": 67600.0, "low": 67100.0, "close": 67500.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit
            {"high": 68600.0, "low": 67800.0, "close": 68500.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # TP2 hit (68600>=68500)
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result["outcome"] == "TP1_TP2"
        # tp1_pnl = 0.7463%, tp2_pnl = (68500-67000)/67000*100 = 2.2388%
        # blended = 0.5*0.7463 + 0.5*2.2388 = 1.4925%
        assert result["outcome_pnl_pct"] == pytest.approx(1.4925, abs=0.01)

    def test_trail_still_running_returns_none(self):
        """TP1 hit, trail not yet triggered → None (still pending)."""
        candles = [
            {"high": 67600.0, "low": 67100.0, "close": 67500.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit
            {"high": 67700.0, "low": 67600.0, "close": 67650.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # trail=max(67300,67700-200)=67500, low=67600>67500
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result is None

    def test_tp1_hit_on_last_candle_returns_none(self):
        """TP1 hit on the last candle, no more candles for Pass 2."""
        candles = [
            {"high": 67600.0, "low": 67100.0, "close": 67500.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit, no more candles
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result is None

    def test_force_close_on_expiry(self):
        """TP1 hit, trail still running at expiry → force close at given price."""
        candles = [
            {"high": 67600.0, "low": 67100.0, "close": 67500.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit
            {"high": 67700.0, "low": 67600.0, "close": 67650.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # no trail hit
        ]
        result = resolve_signal_outcome(
            _long_signal(), candles, atr=200.0, force_close_price=67650.0,
        )
        assert result["outcome"] == "TP1_TRAIL"
        # tp1_pnl = 0.7463%, remainder_pnl = (67650-67000)/67000*100 = 0.9701%
        # blended = 0.5*0.7463 + 0.5*0.9701 = 0.8582%
        assert result["outcome_pnl_pct"] == pytest.approx(0.8582, abs=0.01)

    def test_sl_before_tp1_unchanged(self):
        """SL hit before TP1 → SL_HIT (same as legacy)."""
        candles = [
            {"high": 67050.0, "low": 66400.0, "close": 66450.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result["outcome"] == "SL_HIT"
        assert "partial_exit_pnl_pct" not in result

    def test_tp2_before_tp1_unchanged(self):
        """TP2 hit before TP1 (price blew past) → TP2_HIT."""
        candles = [
            {"high": 68600.0, "low": 67100.0, "close": 68500.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result["outcome"] == "TP2_HIT"
        assert "partial_exit_pnl_pct" not in result


class TestTwoPassShort:
    def test_tp1_then_trail_hit(self):
        """SHORT: TP1 hit, trail ratchets down, trail hit."""
        candles = [
            {"high": 66900.0, "low": 66400.0, "close": 66450.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit (66400<=66500)
            {"high": 66300.0, "low": 66100.0, "close": 66200.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # trail=min(66700, 66100+200)=66300
            {"high": 66350.0, "low": 66050.0, "close": 66100.0,
             "timestamp": "2026-03-01T12:45:00+00:00"},  # trail=min(66300, 66050+200)=66250, high=66350>=66250 → HIT
        ]
        result = resolve_signal_outcome(_short_signal(), candles, atr=200.0)
        assert result["outcome"] == "TP1_TRAIL"
        # tp1_pnl = (67000-66500)/67000*100 = 0.7463%
        # trail_pnl = (67000-66250)/67000*100 = 1.1194%
        # blended = 0.5*0.7463 + 0.5*1.1194 = 0.9328%
        assert result["outcome_pnl_pct"] == pytest.approx(0.9328, abs=0.02)

    def test_tp1_then_tp2_hit(self):
        """SHORT: TP1 hit, then TP2 hit → TP1_TP2."""
        candles = [
            {"high": 66900.0, "low": 66400.0, "close": 66450.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},  # TP1 hit
            {"high": 66100.0, "low": 65400.0, "close": 65500.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},  # TP2 hit (65400<=65500)
        ]
        result = resolve_signal_outcome(_short_signal(), candles, atr=200.0)
        assert result["outcome"] == "TP1_TP2"


class TestBackwardCompatibility:
    def test_atr_none_returns_tp1_hit(self):
        """Without ATR, TP1 hit returns TP1_HIT (legacy behavior)."""
        candles = [
            {"high": 67600.0, "low": 67000.0, "close": 67550.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
        ]
        result = resolve_signal_outcome(_long_signal(), candles)
        assert result["outcome"] == "TP1_HIT"
        assert "partial_exit_pnl_pct" not in result

    def test_atr_none_default_matches_legacy(self):
        """Calling with no extra args matches original behavior exactly."""
        signal = {
            "direction": "LONG",
            "entry": 67000.0,
            "stop_loss": 66500.0,
            "take_profit_1": 67500.0,
            "take_profit_2": 68000.0,
            "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        }
        candles = [
            {"high": 67100.0, "low": 66900.0, "close": 67050.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
            {"high": 67600.0, "low": 67000.0, "close": 67550.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},
        ]
        result = resolve_signal_outcome(signal, candles)
        assert result["outcome"] == "TP1_HIT"
        assert result["outcome_pnl_pct"] == pytest.approx(0.7463, rel=0.01)


class TestPartialResultFields:
    def test_partial_exit_at_is_tp1_time(self):
        """partial_exit_at should be the TP1 hit candle timestamp."""
        candles = [
            {"high": 67600.0, "low": 67050.0, "close": 67550.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
            {"high": 67800.0, "low": 67650.0, "close": 67700.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},
            {"high": 67750.0, "low": 67550.0, "close": 67600.0,
             "timestamp": "2026-03-01T12:45:00+00:00"},  # trail hit
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        assert result is not None
        # partial_exit_at = TP1 candle timestamp
        assert result["partial_exit_at"] == datetime(2026, 3, 1, 12, 15, tzinfo=timezone.utc)
        # outcome_at = final exit timestamp
        assert result["outcome_at"] == datetime(2026, 3, 1, 12, 45, tzinfo=timezone.utc)

    def test_outcome_duration_is_creation_to_final_exit(self):
        """outcome_duration_minutes spans signal creation to final exit."""
        candles = [
            {"high": 67600.0, "low": 67050.0, "close": 67550.0,
             "timestamp": "2026-03-01T12:15:00+00:00"},
            {"high": 67800.0, "low": 67650.0, "close": 67700.0,
             "timestamp": "2026-03-01T12:30:00+00:00"},
            {"high": 67750.0, "low": 67550.0, "close": 67600.0,
             "timestamp": "2026-03-01T12:45:00+00:00"},  # trail hit
        ]
        result = resolve_signal_outcome(_long_signal(), candles, atr=200.0)
        # 12:00 → 12:45 = 45 minutes
        assert result["outcome_duration_minutes"] == 45
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_outcome_resolver.py -v`
Expected: FAIL — new tests fail because `resolve_signal_outcome` doesn't accept `atr`/`force_close_price` params

---

### Task 4: Two-Pass Outcome Resolver — Implementation

**Files:**
- Modify: `backend/app/engine/outcome_resolver.py` (full rewrite)

- [ ] **Step 1: Rewrite `outcome_resolver.py` with two-pass support**

Replace the entire file contents with:

```python
from datetime import datetime, timezone


def resolve_signal_outcome(
    signal: dict,
    candles: list[dict],
    atr: float | None = None,
    partial_fraction: float = 0.50,
    force_close_price: float | None = None,
) -> dict | None:
    """Check if signal hit TP1, TP2, or SL based on candle data.

    When atr is provided, enables two-pass resolution:
      Pass 1 — SL/TP2 → full exit; TP1 → 50% partial exit, enter Pass 2.
      Pass 2 — ATR trailing stop on remainder; checks TP2 and trail hit.

    When atr is None, behavior is identical to the original single-pass resolver.

    force_close_price: if provided and Pass 2 runs out of candles, close
    the remainder at this price (used for 24h expiry of partial exits).

    Returns outcome dict if resolved, None if still pending.
    """
    direction = signal["direction"]
    entry = signal["entry"]
    sl = signal["stop_loss"]
    tp1 = signal["take_profit_1"]
    tp2 = signal["take_profit_2"]
    created_at = signal["created_at"]
    is_long = direction == "LONG"

    # -- Pass 1: Find first level hit --
    tp1_hit_idx = None
    tp1_pnl = None
    tp1_at = None

    for i, candle in enumerate(candles):
        high = candle["high"]
        low = candle["low"]
        ts = candle["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        if is_long:
            if low <= sl:
                pnl = (sl - entry) / entry * 100
                return _result("SL_HIT", pnl, created_at, ts)
            if high >= tp2:
                pnl = (tp2 - entry) / entry * 100
                return _result("TP2_HIT", pnl, created_at, ts)
            if high >= tp1:
                if atr is None:
                    pnl = (tp1 - entry) / entry * 100
                    return _result("TP1_HIT", pnl, created_at, ts)
                tp1_pnl = (tp1 - entry) / entry * 100
                tp1_hit_idx = i
                tp1_at = ts
                break
        else:
            if high >= sl:
                pnl = (entry - sl) / entry * 100
                return _result("SL_HIT", pnl, created_at, ts)
            if low <= tp2:
                pnl = (entry - tp2) / entry * 100
                return _result("TP2_HIT", pnl, created_at, ts)
            if low <= tp1:
                if atr is None:
                    pnl = (entry - tp1) / entry * 100
                    return _result("TP1_HIT", pnl, created_at, ts)
                tp1_pnl = (entry - tp1) / entry * 100
                tp1_hit_idx = i
                tp1_at = ts
                break

    if tp1_hit_idx is None:
        return None

    # -- Pass 2: Trailing stop on remainder (starts on candle AFTER TP1 hit) --
    trail = (tp1 - atr) if is_long else (tp1 + atr)
    last_ts = tp1_at

    for candle in candles[tp1_hit_idx + 1 :]:
        high = candle["high"]
        low = candle["low"]
        ts = candle["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        last_ts = ts

        # Ratchet trail
        if is_long:
            trail = max(trail, high - atr)
        else:
            trail = min(trail, low + atr)

        # Check TP2
        if is_long and high >= tp2:
            r_pnl = (tp2 - entry) / entry * 100
            blended = partial_fraction * tp1_pnl + (1 - partial_fraction) * r_pnl
            return _partial_result("TP1_TP2", blended, tp1_pnl, r_pnl, tp2, tp1_at, created_at, ts)
        if not is_long and low <= tp2:
            r_pnl = (entry - tp2) / entry * 100
            blended = partial_fraction * tp1_pnl + (1 - partial_fraction) * r_pnl
            return _partial_result("TP1_TP2", blended, tp1_pnl, r_pnl, tp2, tp1_at, created_at, ts)

        # Check trail hit
        if is_long and low <= trail:
            r_pnl = (trail - entry) / entry * 100
            blended = partial_fraction * tp1_pnl + (1 - partial_fraction) * r_pnl
            return _partial_result("TP1_TRAIL", blended, tp1_pnl, r_pnl, trail, tp1_at, created_at, ts)
        if not is_long and high >= trail:
            r_pnl = (entry - trail) / entry * 100
            blended = partial_fraction * tp1_pnl + (1 - partial_fraction) * r_pnl
            return _partial_result("TP1_TRAIL", blended, tp1_pnl, r_pnl, trail, tp1_at, created_at, ts)

    # End of candles — force close if expired
    if force_close_price is not None:
        if is_long:
            r_pnl = (force_close_price - entry) / entry * 100
        else:
            r_pnl = (entry - force_close_price) / entry * 100
        blended = partial_fraction * tp1_pnl + (1 - partial_fraction) * r_pnl
        return _partial_result(
            "TP1_TRAIL", blended, tp1_pnl, r_pnl, force_close_price, tp1_at, created_at, last_ts,
        )

    return None  # Trail still running


def _result(outcome: str, pnl_pct: float, created_at, resolved_at) -> dict:
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    if isinstance(resolved_at, str):
        resolved_at = datetime.fromisoformat(resolved_at)
    duration = (resolved_at - created_at).total_seconds() / 60
    return {
        "outcome": outcome,
        "outcome_pnl_pct": round(pnl_pct, 4),
        "outcome_duration_minutes": round(duration),
        "outcome_at": resolved_at,
    }


def _partial_result(
    outcome: str,
    blended_pnl: float,
    tp1_pnl: float,
    remainder_pnl: float,
    exit_price: float,
    tp1_at,
    created_at,
    resolved_at,
) -> dict:
    base = _result(outcome, blended_pnl, created_at, resolved_at)
    base["partial_exit_pnl_pct"] = round(tp1_pnl, 4)
    base["partial_exit_at"] = tp1_at if not isinstance(tp1_at, str) else datetime.fromisoformat(tp1_at)
    base["trail_exit_pnl_pct"] = round(remainder_pnl, 4)
    base["trail_exit_price"] = round(exit_price, 8)
    return base
```

- [ ] **Step 2: Run all outcome resolver tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_outcome_resolver.py -v`
Expected: ALL tests PASS (both old and new)

---

### Task 5: Forward ATR in `performance_tracker.py`

**Files:**
- Modify: `backend/app/engine/performance_tracker.py:118`

- [ ] **Step 1: Update `replay_signal` to pass `atr` through**

Change line 118 from:

```python
        return resolve_signal_outcome(signal_dict, candles)
```

to:

```python
        return resolve_signal_outcome(signal_dict, candles, atr=atr)
```

- [ ] **Step 2: Run full test suite to confirm no regression**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v`
Expected: All tests PASS

---

### Task 6: Kelly Integration in `main.py` `_emit_signal`

**Files:**
- Modify: `backend/app/main.py` — `_emit_signal` function (lines 349-412)

- [ ] **Step 1: Add `kelly_meta` variable and Kelly computation**

In `_emit_signal`, change the risk computation block. Replace lines 357-379:

```python
    risk_metrics = None
    okx_client = getattr(app.state, "okx_client", None)
    if okx_client:
        try:
            balance = await okx_client.get_balance()
            if balance:
                equity = balance["total_equity"]
                from app.db.models import RiskSettings
                risk_per_trade = 0.01
                max_pos_usd = None
                try:
                    async with db.session_factory() as session:
                        result = await session.execute(
                            select(RiskSettings).where(RiskSettings.id == 1)
                        )
                        rs = result.scalar_one_or_none()
                        if rs:
                            risk_per_trade = rs.risk_per_trade
                            max_pos_usd = rs.max_position_size_usd
                except Exception:
                    pass

                sizer = PositionSizer(equity, risk_per_trade, max_pos_usd)
```

with:

```python
    risk_metrics = None
    kelly_meta = None
    okx_client = getattr(app.state, "okx_client", None)
    if okx_client:
        try:
            balance = await okx_client.get_balance()
            if balance:
                equity = balance["total_equity"]
                from app.db.models import RiskSettings
                risk_per_trade = 0.01
                max_pos_usd = None
                try:
                    async with db.session_factory() as session:
                        result = await session.execute(
                            select(RiskSettings).where(RiskSettings.id == 1)
                        )
                        rs = result.scalar_one_or_none()
                        if rs:
                            risk_per_trade = rs.risk_per_trade
                            max_pos_usd = rs.max_position_size_usd

                        # Kelly position sizing: adapt risk_per_trade from history
                        from app.engine.risk import compute_kelly_risk
                        outcomes_result = await session.execute(
                            select(Signal.outcome, Signal.outcome_pnl_pct).where(
                                Signal.pair == signal_data["pair"],
                                Signal.timeframe == signal_data["timeframe"],
                                Signal.outcome.in_(
                                    ["TP1_HIT", "TP2_HIT", "SL_HIT", "TP1_TRAIL", "TP1_TP2"]
                                ),
                            ).order_by(Signal.created_at.desc()).limit(100)
                        )
                        rows = outcomes_result.all()
                        recent_outcomes = [
                            {"outcome": r.outcome, "outcome_pnl_pct": float(r.outcome_pnl_pct)}
                            for r in rows
                        ]
                        kelly_meta = compute_kelly_risk(
                            recent_outcomes,
                            kelly_fraction=settings.engine_kelly_fraction,
                        )
                        # Kelly can reduce risk but never exceed user's DB setting
                        risk_per_trade = min(kelly_meta["risk_per_trade"], risk_per_trade)
                except Exception:
                    pass

                sizer = PositionSizer(equity, risk_per_trade, max_pos_usd)
```

- [ ] **Step 2: Store Kelly metadata in risk_metrics**

Between the `except` block (after `sizer.calculate`) and `signal_data["risk_metrics"] = risk_metrics`, add Kelly enrichment. Change:

```python
    signal_data["risk_metrics"] = risk_metrics
```

to:

```python
    if risk_metrics and kelly_meta:
        risk_metrics["kelly"] = kelly_meta
    signal_data["risk_metrics"] = risk_metrics
```

---

### Task 7: ATR + Force-Close in `main.py` `check_pending_signals`

**Files:**
- Modify: `backend/app/main.py` — `check_pending_signals` function (lines 1352-1448)

- [ ] **Step 1: Add ATR helper function**

Add this function above `check_pending_signals` (before line 1352):

```python
def _compute_atr_from_candles(candles: list[dict], period: int = 14) -> float | None:
    """Compute ATR(period) from raw candle dicts. Returns None if insufficient data."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h = float(candles[i].get("high", candles[i].get("h", 0)))
        l = float(candles[i].get("low", candles[i].get("l", 0)))
        prev_c = float(candles[i - 1].get("close", candles[i - 1].get("c", 0)))
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    return sum(trs[-period:]) / period
```

- [ ] **Step 2: Rewrite the signal processing loop in `check_pending_signals`**

Replace the `for signal in pending:` loop body (lines 1367-1416) with:

```python
        for signal in pending:
            age = (datetime.now(timezone.utc) - signal.created_at).total_seconds()

            cache_key = f"candles:{signal.pair}:{signal.timeframe}"
            raw_candles = await redis.lrange(cache_key, -200, -1)
            if not raw_candles:
                if age > 86400:
                    signal.outcome = "EXPIRED"
                    signal.outcome_at = datetime.now(timezone.utc)
                    signal.outcome_duration_minutes = round(age / 60)
                    resolved_pairs_timeframes.add((signal.pair, signal.timeframe))
                continue

            import json as _json
            candles_data = [_json.loads(c) for c in raw_candles]

            # Compute ATR from full candle history for trailing stop
            atr_val = _compute_atr_from_candles(candles_data)

            # Only check candles after signal creation
            signal_ts = signal.created_at.isoformat()
            candles_after = [c for c in candles_data if c["timestamp"] > signal_ts]
            if not candles_after:
                if age > 86400:
                    signal.outcome = "EXPIRED"
                    signal.outcome_at = datetime.now(timezone.utc)
                    signal.outcome_duration_minutes = round(age / 60)
                    resolved_pairs_timeframes.add((signal.pair, signal.timeframe))
                continue

            signal_dict = {
                "direction": signal.direction,
                "entry": float(signal.entry),
                "stop_loss": float(signal.stop_loss),
                "take_profit_1": float(signal.take_profit_1),
                "take_profit_2": float(signal.take_profit_2),
                "created_at": signal.created_at,
            }

            # Parse candle floats
            parsed = []
            for c in candles_after:
                parsed.append({
                    "high": float(c.get("high", c.get("h", 0))),
                    "low": float(c.get("low", c.get("l", 0))),
                    "close": float(c.get("close", c.get("c", 0))),
                    "timestamp": c["timestamp"],
                })

            # Force-close price for expired partial exits
            force_close = parsed[-1]["close"] if age > 86400 else None

            outcome = resolve_signal_outcome(
                signal_dict, parsed,
                atr=atr_val * settings.engine_trail_atr_multiplier if atr_val else None,
                partial_fraction=settings.engine_partial_fraction,
                force_close_price=force_close,
            )
            if outcome:
                signal.outcome = outcome["outcome"]
                signal.outcome_at = outcome["outcome_at"]
                signal.outcome_pnl_pct = outcome["outcome_pnl_pct"]
                signal.outcome_duration_minutes = outcome["outcome_duration_minutes"]
                # Store partial exit details in risk_metrics JSONB
                if outcome.get("partial_exit_pnl_pct") is not None:
                    meta = {
                        "partial_exit_pnl_pct": outcome["partial_exit_pnl_pct"],
                        "partial_exit_at": outcome["partial_exit_at"].isoformat() if outcome.get("partial_exit_at") else None,
                        "trail_exit_pnl_pct": outcome.get("trail_exit_pnl_pct"),
                        "trail_exit_price": outcome.get("trail_exit_price"),
                    }
                    signal.risk_metrics = {**(signal.risk_metrics or {}), "partial_exit": meta}
                resolved_pairs_timeframes.add((signal.pair, signal.timeframe))
            elif age > 86400:
                signal.outcome = "EXPIRED"
                signal.outcome_at = datetime.now(timezone.utc)
                signal.outcome_duration_minutes = round(age / 60)
                resolved_pairs_timeframes.add((signal.pair, signal.timeframe))
```

---

### Task 8: Propagate New Outcome Types — Backend

**Files:**
- Modify: `backend/app/api/routes.py` (lines 66, 367, 385, 398, 409, 493)
- Modify: `backend/app/api/risk.py` (line 209)
- Modify: `backend/app/engine/regime_optimizer.py` (line 283)

- [ ] **Step 1: Update all win outcome checks in `routes.py`**

In `backend/app/api/routes.py`, update every hardcoded win-outcome tuple to include the new types.

Line 66 — `_compute_streaks`:
```python
        is_win = s.outcome in ("TP1_HIT", "TP2_HIT")
```
→
```python
        is_win = s.outcome in ("TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2")
```

Line 367 — analytics wins filter:
```python
                wins = [s for s in resolved if s.outcome in ("TP1_HIT", "TP2_HIT")]
```
→
```python
                wins = [s for s in resolved if s.outcome in ("TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2")]
```

Line 385 — by_pair win counter:
```python
                    if s.outcome in ("TP1_HIT", "TP2_HIT"):
```
→
```python
                    if s.outcome in ("TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2"):
```

Line 398 — by_timeframe win counter:
```python
                    if s.outcome in ("TP1_HIT", "TP2_HIT"):
```
→
```python
                    if s.outcome in ("TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2"):
```

Line 409 — by_direction win counter:
```python
                    if s.outcome in ("TP1_HIT", "TP2_HIT"):
```
→
```python
                    if s.outcome in ("TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2"):
```

Line 493 — calendar day wins:
```python
            if s.outcome in ("TP1_HIT", "TP2_HIT"):
```
→
```python
            if s.outcome in ("TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2"):
```

- [ ] **Step 2: Update daily P&L filter in `risk.py`**

In `backend/app/api/risk.py`, change line 209 from:

```python
                    Signal.outcome.in_(["TP1_HIT", "TP2_HIT", "SL_HIT"]),
```

to:

```python
                    Signal.outcome.in_(["TP1_HIT", "TP2_HIT", "SL_HIT", "TP1_TRAIL", "TP1_TP2"]),
```

- [ ] **Step 3: Update win outcome check in `regime_optimizer.py`**

In `backend/app/engine/regime_optimizer.py`, change line 283 from:

```python
        is_win = sig["outcome"] in ("TP1_HIT", "TP2_HIT")
```

to:

```python
        is_win = sig["outcome"] in ("TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2")
```

---

### Task 9: Propagate New Outcome Types — Frontend

**Files:**
- Modify: `web/src/features/signals/types.ts:3`
- Modify: `web/src/shared/lib/api.ts:151`
- Modify: `web/src/features/signals/components/SignalCard.tsx:144-156`
- Modify: `web/src/features/home/components/RecentSignals.tsx:12-18`
- Modify: `web/src/features/positions/components/HistorySegment.tsx:20-25`
- Modify: `web/src/features/signals/components/CalendarView.tsx:250`

- [ ] **Step 1: Update `SignalOutcome` type**

In `web/src/features/signals/types.ts`, change line 3 from:

```typescript
export type SignalOutcome = "PENDING" | "TP1_HIT" | "TP2_HIT" | "SL_HIT" | "EXPIRED";
```

to:

```typescript
export type SignalOutcome = "PENDING" | "TP1_HIT" | "TP2_HIT" | "TP1_TRAIL" | "TP1_TP2" | "SL_HIT" | "EXPIRED";
```

- [ ] **Step 2: Fix outcome type in `api.ts` `TradeHistoryEntry`**

In `web/src/shared/lib/api.ts`, change line 151 from:

```typescript
  outcome: "TP1_HIT" | "SL_HIT" | "EXPIRED";
```

to:

```typescript
  outcome: "TP1_HIT" | "TP2_HIT" | "TP1_TRAIL" | "TP1_TP2" | "SL_HIT" | "EXPIRED";
```

(Also fixes pre-existing bug: `TP2_HIT` was missing.)

- [ ] **Step 3: Update `SignalCard.tsx` color and label maps**

Change the `OUTCOME_COLOR` map from:

```typescript
const OUTCOME_COLOR: Record<string, "long" | "short" | "muted"> = {
  TP1_HIT: "long",
  TP2_HIT: "long",
  SL_HIT:  "short",
  EXPIRED: "muted",
};
```

to:

```typescript
const OUTCOME_COLOR: Record<string, "long" | "short" | "muted"> = {
  TP1_HIT:   "long",
  TP2_HIT:   "long",
  TP1_TRAIL: "long",
  TP1_TP2:   "long",
  SL_HIT:    "short",
  EXPIRED:   "muted",
};
```

Change the `OUTCOME_LABEL` map from:

```typescript
const OUTCOME_LABEL: Record<string, string> = {
  TP1_HIT: "TP1 Hit",
  TP2_HIT: "TP2 Hit",
  SL_HIT:  "SL Hit",
  EXPIRED: "Expired",
};
```

to:

```typescript
const OUTCOME_LABEL: Record<string, string> = {
  TP1_HIT:   "TP1 Hit",
  TP2_HIT:   "TP2 Hit",
  TP1_TRAIL: "TP1 + Trail",
  TP1_TP2:   "TP1 + TP2",
  SL_HIT:    "SL Hit",
  EXPIRED:   "Expired",
};
```

- [ ] **Step 4: Update `RecentSignals.tsx` badge map**

In `web/src/features/home/components/RecentSignals.tsx`, change the `OUTCOME_BADGE` map from:

```typescript
const OUTCOME_BADGE: Record<string, { label: string; color: BadgeColor }> = {
  PENDING: { label: "PENDING", color: "accent" },
  TP1_HIT: { label: "TP1",     color: "long" },
  TP2_HIT: { label: "TP2",     color: "long" },
  SL_HIT:  { label: "SL",      color: "short" },
  EXPIRED: { label: "EXP",     color: "muted" },
};
```

to:

```typescript
const OUTCOME_BADGE: Record<string, { label: string; color: BadgeColor }> = {
  PENDING:   { label: "PENDING",   color: "accent" },
  TP1_HIT:   { label: "TP1",       color: "long" },
  TP2_HIT:   { label: "TP2",       color: "long" },
  TP1_TRAIL: { label: "TP1+Trail", color: "long" },
  TP1_TP2:   { label: "TP1+TP2",   color: "long" },
  SL_HIT:    { label: "SL",        color: "short" },
  EXPIRED:   { label: "EXP",       color: "muted" },
};
```

- [ ] **Step 5: Update `HistorySegment.tsx` color map**

In `web/src/features/positions/components/HistorySegment.tsx`, change the `OUTCOME_COLOR` map from:

```typescript
const OUTCOME_COLOR: Record<string, "long" | "short" | "muted"> = {
  TP1_HIT: "long",
  TP2_HIT: "long",
  SL_HIT: "short",
  EXPIRED: "muted",
};
```

to:

```typescript
const OUTCOME_COLOR: Record<string, "long" | "short" | "muted"> = {
  TP1_HIT:   "long",
  TP2_HIT:   "long",
  TP1_TRAIL: "long",
  TP1_TP2:   "long",
  SL_HIT:    "short",
  EXPIRED:   "muted",
};
```

- [ ] **Step 6: Update `CalendarView.tsx` inline color logic**

In `web/src/features/signals/components/CalendarView.tsx`, change line 250 from:

```typescript
      color={(signal.outcome === "TP1_HIT" || signal.outcome === "TP2_HIT") ? "long" : signal.outcome === "EXPIRED" ? "muted" : "short"}
```

to:

```typescript
      color={(signal.outcome === "TP1_HIT" || signal.outcome === "TP2_HIT" || signal.outcome === "TP1_TRAIL" || signal.outcome === "TP1_TP2") ? "long" : signal.outcome === "EXPIRED" ? "muted" : "short"}
```

---

### Task 10: Wire Execution Params into Optimizer

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/engine/param_groups.py`
- Modify: `backend/app/engine/optimizer.py`

- [ ] **Step 1: Add settings fields to `config.py`**

After the `engine_mr_llm_trigger` line (line 78), add:

```python
    # execution parameters (optimizer-tunable)
    engine_kelly_fraction: float = 0.35
    engine_partial_fraction: float = 0.50
    engine_trail_atr_multiplier: float = 1.0
```

- [ ] **Step 2: Add `execution` parameter group to `param_groups.py`**

Before the `get_group` function (line 554), add:

```python
def _execution_ok(c: dict[str, Any]) -> bool:
    return (
        0.1 <= c["kelly_fraction"] <= 0.5
        and 0.25 <= c["partial_fraction"] <= 0.75
        and 0.5 <= c["trail_atr_multiplier"] <= 2.0
    )


PARAM_GROUPS["execution"] = {
    "params": {
        "kelly_fraction": "execution.kelly_fraction",
        "partial_fraction": "execution.partial_fraction",
        "trail_atr_multiplier": "execution.trail_atr_multiplier",
    },
    "sweep_method": "grid",
    "sweep_ranges": {
        "kelly_fraction": (0.15, 0.50, 0.05),
        "partial_fraction": (0.25, 0.75, 0.05),
        "trail_atr_multiplier": (0.75, 1.50, 0.25),
    },
    "constraints": _execution_ok,
    "priority": _priority_for("execution"),
}
```

- [ ] **Step 3: Add `execution` to `_NON_BACKTESTABLE` in `optimizer.py`**

Change line 25 from:

```python
_NON_BACKTESTABLE = frozenset({"order_flow", "llm_factors", "onchain", "ensemble"})
```

to:

```python
_NON_BACKTESTABLE = frozenset({"order_flow", "llm_factors", "onchain", "ensemble", "execution"})
```

- [ ] **Step 4: Add `execution` to priority layer 2 in `param_groups.py`**

Change the layer 2 set (line 24) from:

```python
    {"sigmoid_curves", "order_flow", "pattern_strengths", "pattern_boosts",
     "indicator_periods", "mean_reversion", "llm_factors", "onchain",
     "mr_pressure", "liquidation", "confluence", "ensemble"},  # layer 2
```

to:

```python
    {"sigmoid_curves", "order_flow", "pattern_strengths", "pattern_boosts",
     "indicator_periods", "mean_reversion", "llm_factors", "onchain",
     "mr_pressure", "liquidation", "confluence", "ensemble", "execution"},  # layer 2
```

---

### Task 11: Final Verification

- [ ] **Step 1: Run the full backend test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v`
Expected: All tests PASS

- [ ] **Step 2: Run frontend build check**

Run: `cd web && pnpm build`
Expected: Build succeeds with no type errors

- [ ] **Step 3: Commit all changes**

Stage and commit all modified/created files:

```bash
git add backend/app/config.py backend/app/engine/risk.py backend/app/engine/outcome_resolver.py backend/app/engine/performance_tracker.py backend/app/engine/regime_optimizer.py backend/app/engine/param_groups.py backend/app/engine/optimizer.py backend/app/main.py backend/app/api/routes.py backend/app/api/risk.py web/src/features/signals/types.ts web/src/shared/lib/api.ts web/src/features/signals/components/SignalCard.tsx web/src/features/signals/components/CalendarView.tsx web/src/features/home/components/RecentSignals.tsx web/src/features/positions/components/HistorySegment.tsx backend/tests/engine/test_kelly.py backend/tests/engine/test_outcome_resolver.py
git commit -m "feat(engine): fractional Kelly sizing + partial-exit ATR trailing stops"
```
