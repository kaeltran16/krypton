import statistics
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.performance_tracker import (
    PerformanceTracker,
    DEFAULT_SL, DEFAULT_TP1, DEFAULT_TP2,
    SL_RANGE, TP1_RANGE, TP2_RANGE,
    MAX_SL_ADJ, MAX_TP_ADJ,
    MIN_SIGNALS, TRIGGER_INTERVAL,
)


@pytest.fixture
def mock_session_factory():
    """Create a mock async session factory."""
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


# ── get_multipliers ──


@pytest.mark.asyncio
async def test_get_multipliers_returns_defaults_when_no_cache(mock_session_factory):
    factory, _ = mock_session_factory
    tracker = PerformanceTracker(factory)
    result = await tracker.get_multipliers("BTC-USDT-SWAP", "1h")
    assert result == (1.5, 2.0, 3.0)


@pytest.mark.asyncio
async def test_get_multipliers_returns_cached_values(mock_session_factory):
    factory, _ = mock_session_factory
    tracker = PerformanceTracker(factory)
    tracker._cache[("BTC-USDT-SWAP", "1h")] = (1.8, 2.5, 4.0)
    result = await tracker.get_multipliers("BTC-USDT-SWAP", "1h")
    assert result == (1.8, 2.5, 4.0)


@pytest.mark.asyncio
async def test_reload_cache_populates_from_db(mock_session_factory):
    factory, session = mock_session_factory
    row = MagicMock()
    row.pair = "BTC-USDT-SWAP"
    row.timeframe = "1h"
    row.current_sl_atr = 1.8
    row.current_tp1_atr = 2.5
    row.current_tp2_atr = 4.0
    session.execute.return_value = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = [row]

    tracker = PerformanceTracker(factory)
    await tracker.reload_cache()

    result = await tracker.get_multipliers("BTC-USDT-SWAP", "1h")
    assert result == (1.8, 2.5, 4.0)


# ── compute_sortino ──


def test_sortino_normal():
    """Standard Sortino with mix of wins and losses."""
    pnls = [2.0, -1.0, 3.0, -0.5, 1.5]
    result = PerformanceTracker.compute_sortino(pnls)
    assert result is not None
    assert result > 0


def test_sortino_all_winners():
    """All wins → no downside deviation → return inf."""
    pnls = [1.0, 2.0, 3.0, 1.5]
    result = PerformanceTracker.compute_sortino(pnls)
    assert result == float("inf")


def test_sortino_all_losers():
    """All losses → negative Sortino."""
    pnls = [-1.0, -2.0, -0.5]
    result = PerformanceTracker.compute_sortino(pnls)
    assert result is not None
    assert result < 0


def test_sortino_single_loss():
    """One loss → uses abs(loss) as downside deviation."""
    pnls = [2.0, 3.0, -1.0, 1.5]
    result = PerformanceTracker.compute_sortino(pnls)
    mean_r = statistics.mean(pnls)
    expected = mean_r / abs(-1.0)
    assert abs(result - expected) < 0.01


def test_sortino_empty():
    """Empty pnls → None."""
    assert PerformanceTracker.compute_sortino([]) is None


# ── replay_signal ──


def test_replay_long_tp1_hit():
    """Replay LONG signal where TP1 is hit, then trail resolves."""
    # tp1=51000, trail starts at 51000-500=50500
    # candle 2: trail ratchets to max(50500, 51200-500)=50700, low=50400<=50700 → trail hit
    candles = [
        {"high": 51100.0, "low": 50500.0, "timestamp": datetime(2025, 1, 1, 1, tzinfo=timezone.utc)},
        {"high": 51200.0, "low": 50400.0, "timestamp": datetime(2025, 1, 1, 2, tzinfo=timezone.utc)},
    ]
    result = PerformanceTracker.replay_signal(
        direction="LONG", entry=50000.0, atr=500.0,
        sl_atr=1.5, tp1_atr=2.0, tp2_atr=3.0,
        candles=candles, created_at=datetime(2025, 1, 1, 0, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result["outcome"] == "TP1_TRAIL"
    assert result["outcome_pnl_pct"] > 0


def test_replay_long_sl_hit():
    """Replay LONG signal where SL is hit."""
    candles = [
        {"high": 50100.0, "low": 49200.0, "timestamp": datetime(2025, 1, 1, 1, tzinfo=timezone.utc)},
    ]
    result = PerformanceTracker.replay_signal(
        direction="LONG", entry=50000.0, atr=500.0,
        sl_atr=1.5, tp1_atr=2.0, tp2_atr=3.0,
        candles=candles, created_at=datetime(2025, 1, 1, 0, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result["outcome"] == "SL_HIT"
    assert result["outcome_pnl_pct"] < 0


def test_replay_no_hit():
    """No candle triggers any level → returns None (expired)."""
    candles = [
        {"high": 50500.0, "low": 49800.0, "timestamp": datetime(2025, 1, 1, 1, tzinfo=timezone.utc)},
    ]
    result = PerformanceTracker.replay_signal(
        direction="LONG", entry=50000.0, atr=500.0,
        sl_atr=1.5, tp1_atr=2.0, tp2_atr=3.0,
        candles=candles, created_at=datetime(2025, 1, 1, 0, tzinfo=timezone.utc),
    )
    assert result is None


def test_replay_short_tp2_hit():
    """Replay SHORT signal where TP2 is hit."""
    candles = [
        {"high": 50100.0, "low": 48400.0, "timestamp": datetime(2025, 1, 1, 1, tzinfo=timezone.utc)},
    ]
    result = PerformanceTracker.replay_signal(
        direction="SHORT", entry=50000.0, atr=500.0,
        sl_atr=1.5, tp1_atr=2.0, tp2_atr=3.0,
        candles=candles, created_at=datetime(2025, 1, 1, 0, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result["outcome"] == "TP2_HIT"


# ── _apply_guardrails ──


def test_guardrails_no_change():
    """No change needed when new value is within bounds and adjustment limit."""
    result = PerformanceTracker._apply_guardrails(
        old=1.5, new=1.7, bounds=SL_RANGE, max_adj=MAX_SL_ADJ,
    )
    assert result == 1.7


def test_guardrails_clamps_to_bounds():
    """Value outside absolute bounds gets clamped, then max_adj limits further."""
    result = PerformanceTracker._apply_guardrails(
        old=1.5, new=0.5, bounds=SL_RANGE, max_adj=MAX_SL_ADJ,
    )
    # Bounds clamp 0.5 → 0.8, but delta (1.5→0.8 = -0.7) exceeds max_adj (0.3)
    # so result is 1.5 - 0.3 = 1.2
    assert result == 1.2


def test_guardrails_clamps_to_max_adjustment():
    """Large change gets limited to max_adj per cycle."""
    result = PerformanceTracker._apply_guardrails(
        old=1.5, new=2.5, bounds=SL_RANGE, max_adj=MAX_SL_ADJ,
    )
    assert result == 1.5 + MAX_SL_ADJ  # 1.8


def test_guardrails_clamps_negative_adjustment():
    """Large downward change gets limited to max_adj per cycle."""
    result = PerformanceTracker._apply_guardrails(
        old=2.0, new=1.0, bounds=SL_RANGE, max_adj=MAX_SL_ADJ,
    )
    assert result == 2.0 - MAX_SL_ADJ  # 1.7


# ── _sweep_dimension ──


def _make_signal_data(
    direction="LONG", entry=50000.0, atr=500.0,
    sl_eff=1.5, tp1_eff=2.0, tp2_eff=3.0,
    sl_strength=1.0, tp_strength=1.0, vol_factor=1.0,
    created_at=None, outcome_at=None, outcome="TP1_HIT",
):
    """Helper to build a signal data dict for sweep tests."""
    if created_at is None:
        created_at = datetime(2025, 1, 1, 0, tzinfo=timezone.utc)
    if outcome_at is None:
        outcome_at = created_at + timedelta(hours=4)
    return {
        "direction": direction, "entry": entry, "atr": atr,
        "effective_sl_atr": sl_eff, "effective_tp1_atr": tp1_eff,
        "effective_tp2_atr": tp2_eff,
        "sl_strength_factor": sl_strength, "tp_strength_factor": tp_strength,
        "vol_factor": vol_factor,
        "created_at": created_at, "outcome_at": outcome_at,
        "outcome": outcome,
    }


def test_sweep_returns_best_candidate():
    """Sweep picks candidate that maximizes Sortino."""
    t0 = datetime(2025, 1, 1, 0, tzinfo=timezone.utc)
    t1 = datetime(2025, 1, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2025, 1, 1, 4, tzinfo=timezone.utc)

    signals = [
        _make_signal_data(created_at=t0, outcome_at=t2, outcome="TP1_HIT"),
        _make_signal_data(created_at=t0, outcome_at=t2, outcome="SL_HIT"),
    ]
    candles_map = {
        0: [{"high": 51100.0, "low": 49900.0, "timestamp": t1}],
        1: [{"high": 50200.0, "low": 49200.0, "timestamp": t1}],
    }
    results = PerformanceTracker._sweep_dimension(
        signals_data=signals,
        candles_map=candles_map,
        dimension="sl",
        candidates=[0.8, 1.0, 1.2, 1.5, 2.0],
    )
    scored = [(v, s) for v, s in results.items() if s is not None]
    assert len(scored) > 0
    best, best_sortino = max(scored, key=lambda x: x[1])
    assert isinstance(best_sortino, (float, int))


# ── optimize (end-to-end mock) ──


@pytest.mark.asyncio
async def test_optimize_updates_multipliers(mock_session_factory):
    """Full optimize flow: fetch signals, replay, sweep, apply guardrailed updates."""
    factory, session = mock_session_factory

    # Mock tracker row
    row = MagicMock()
    row.current_sl_atr = 1.5
    row.current_tp1_atr = 2.0
    row.current_tp2_atr = 3.0
    row.last_optimized_at = None
    row.updated_at = None

    # Mock 50 signals (above MIN_SIGNALS=40)
    base_time = datetime(2025, 1, 1, 0, tzinfo=timezone.utc)
    mock_signals = []
    for i in range(50):
        sig = MagicMock()
        sig.direction = "LONG"
        sig.entry = 50000.0
        sig.stop_loss = 49250.0  # 1.5 * 500 ATR
        sig.take_profit_1 = 51000.0  # 2.0 * 500 ATR
        sig.take_profit_2 = 51500.0  # 3.0 * 500 ATR
        sig.created_at = base_time + timedelta(hours=i * 2)
        sig.outcome_at = base_time + timedelta(hours=i * 2 + 1)
        sig.outcome = "TP1_HIT" if i % 3 != 0 else "SL_HIT"
        sig.pair = "BTC-USDT-SWAP"
        sig.timeframe = "1h"
        sig.raw_indicators = {
            "atr": 500.0,
            "effective_sl_atr": 1.5,
            "effective_tp1_atr": 2.0,
            "effective_tp2_atr": 3.0,
            "sl_strength_factor": 1.0,
            "tp_strength_factor": 1.0,
            "vol_factor": 1.0,
            "levels_source": "atr_default",
        }
        mock_signals.append(sig)

    # Mock candles (2 per signal: +30min and +45min so trail resolves for TP1 hits)
    mock_candles = []
    for i in range(50):
        c1 = MagicMock()
        c1.timestamp = base_time + timedelta(hours=i * 2, minutes=30)
        c2 = MagicMock()
        c2.timestamp = base_time + timedelta(hours=i * 2, minutes=45)
        if i % 3 != 0:
            c1.high = 51100.0
            c1.low = 49900.0
            # trail starts at tp1-atr=50500, ratchets to max(50500,51100-500)=50600
            c2.high = 51100.0
            c2.low = 50400.0  # low<=50600 → trail hit
        else:
            c1.high = 50100.0
            c1.low = 49200.0
            c2.high = 50100.0
            c2.low = 49500.0
        mock_candles.append(c1)
        mock_candles.append(c2)

    call_count = 0
    def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = row
        elif call_count == 2:
            result.scalars.return_value.all.return_value = mock_signals
        elif call_count == 3:
            result.scalars.return_value.all.return_value = mock_candles
        elif call_count == 4:
            result.scalar_one.return_value = row
        return result

    session.execute = AsyncMock(side_effect=mock_execute)

    tracker = PerformanceTracker(factory)
    await tracker.optimize("BTC-USDT-SWAP", "1h")

    session.commit.assert_called()


# ── check_optimization_triggers ──


@pytest.mark.asyncio
async def test_check_triggers_schedules_optimization_when_threshold_met(mock_session_factory):
    """Optimization is scheduled when resolved count crosses trigger interval."""
    factory, session = mock_session_factory

    row = MagicMock()
    row.last_optimized_count = 40
    row.updated_at = None

    call_count = 0
    def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one.return_value = 50
        else:
            result.scalar_one_or_none.return_value = row
        return result

    session.execute = AsyncMock(side_effect=mock_execute)
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    tracker = PerformanceTracker(factory)
    tracker._optimize_safe = AsyncMock()

    import asyncio
    with pytest.MonkeyPatch.context() as mp:
        tasks_created = []
        original_create_task = asyncio.create_task
        def mock_create_task(coro):
            task = original_create_task(coro)
            tasks_created.append(task)
            return task
        mp.setattr(asyncio, "create_task", mock_create_task)

        await tracker.check_optimization_triggers(
            session, {("BTC-USDT-SWAP", "1h")}
        )

    assert row.last_optimized_count == 50
    session.commit.assert_called()


@pytest.mark.asyncio
async def test_check_triggers_skips_below_min_signals(mock_session_factory):
    """No optimization when resolved count is below MIN_SIGNALS."""
    factory, session = mock_session_factory

    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one=MagicMock(return_value=30))
    )
    session.commit = AsyncMock()

    tracker = PerformanceTracker(factory)
    tracker._optimize_safe = AsyncMock()

    await tracker.check_optimization_triggers(
        session, {("BTC-USDT-SWAP", "1h")}
    )

    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_check_triggers_skips_below_interval(mock_session_factory):
    """No optimization when delta since last optimization is below TRIGGER_INTERVAL."""
    factory, session = mock_session_factory

    row = MagicMock()
    row.last_optimized_count = 45

    call_count = 0
    def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one.return_value = 50
        else:
            result.scalar_one_or_none.return_value = row
        return result

    session.execute = AsyncMock(side_effect=mock_execute)
    session.commit = AsyncMock()

    tracker = PerformanceTracker(factory)
    await tracker.check_optimization_triggers(
        session, {("BTC-USDT-SWAP", "1h")}
    )

    session.commit.assert_not_called()


# ── bootstrap_from_backtests ──


@pytest.mark.asyncio
async def test_bootstrap_creates_rows_from_backtests(mock_session_factory):
    """Bootstrap reads best backtest config per pair/timeframe and seeds tracker rows."""
    factory, session = mock_session_factory

    mock_run = MagicMock()
    mock_run.pairs = ["BTC-USDT-SWAP"]
    mock_run.timeframe = "1h"
    mock_run.config = {
        "sl_atr_multiplier": 1.8,
        "tp1_atr_multiplier": 2.5,
        "tp2_atr_multiplier": 4.0,
    }
    mock_run.results = {"stats": {"profit_factor": 2.0}}

    call_count = 0
    def mock_execute(query):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalars.return_value.all.return_value = [mock_run]
        else:
            result.scalar_one_or_none.return_value = None
        return result

    session.execute = AsyncMock(side_effect=mock_execute)

    tracker = PerformanceTracker(factory)
    await tracker.bootstrap_from_backtests()

    session.add.assert_called_once()
    added_row = session.add.call_args[0][0]
    assert added_row.pair == "BTC-USDT-SWAP"
    assert added_row.timeframe == "1h"
    assert added_row.current_sl_atr == 1.8
    assert added_row.current_tp1_atr == 2.5
    assert added_row.current_tp2_atr == 4.0


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
    sig_candles = [
        {"high": 51500.0, "low": 49500.0, "timestamp": datetime(2026, 1, 1, 1, tzinfo=timezone.utc)},
        {"high": 52000.0, "low": 50500.0, "timestamp": datetime(2026, 1, 1, 2, tzinfo=timezone.utc)},
    ]
    signals = [
        {
            "direction": "LONG",
            "entry": 50000.0,
            "atr": 500.0,
            "sl_strength_factor": 1.0,
            "tp_strength_factor": 1.0,
            "vol_factor": 1.0,
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
            "sl_strength_factor": 1.0,
            "tp_strength_factor": 1.0,
            "vol_factor": 1.0,
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
