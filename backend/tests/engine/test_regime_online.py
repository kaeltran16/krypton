from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.engine.regime import DEFAULT_OUTER_WEIGHTS, OUTER_KEYS, REGIMES
from app.engine.regime_online import (
    BASE_LR,
    EFFECTIVE_WEIGHT_CEILING,
    EFFECTIVE_WEIGHT_FLOOR,
    MAX_WINDOW_SIGNALS,
    MIN_WINDOW_SIGNALS,
    ONLINE_ELIGIBLE_OUTCOMES,
    apply_resolved_signal,
    apply_resolved_signals_batch,
    build_overlay_state_from_records,
    build_runtime_states_from_history,
    clear_runtime_state_for_key,
    compute_outcome_effect,
    compute_source_influence,
    empty_overlay,
    resolve_effective_outer_weight_rows,
    resolve_effective_outer_weights,
    signal_to_online_record,
    trim_retained_window,
)
from app.main import _active_regime_online_keys, check_pending_signals, rebuild_regime_online_state


def _baseline_row():
    row = SimpleNamespace()
    for regime in REGIMES:
        for source in OUTER_KEYS:
            setattr(row, f"{regime}_{source}_weight", DEFAULT_OUTER_WEIGHTS[regime][source])
    return row


def _complete_raw(**overrides):
    raw = {}
    for source in OUTER_KEYS:
        raw[f"{source}_score"] = 0.0
        raw[f"{source}_confidence"] = 0.0
    raw.update(overrides)
    return raw


def _signal(
    *,
    signal_id: int,
    pair: str = "BTC-USDT-SWAP",
    timeframe: str = "1h",
    direction: str = "LONG",
    outcome: str = "TP1_HIT",
    outcome_at: datetime | None = None,
    created_at: datetime | None = None,
    raw_indicators: dict | None = None,
    regime_mix: dict | None = None,
):
    outcome_at = outcome_at or datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    created_at = created_at or (outcome_at - timedelta(hours=2))
    return {
        "id": signal_id,
        "pair": pair,
        "timeframe": timeframe,
        "direction": direction,
        "outcome": outcome,
        "outcome_at": outcome_at,
        "created_at": created_at,
        "raw_indicators": raw_indicators or _complete_raw(),
        "engine_snapshot": {
            "regime_mix": regime_mix
            or {
                "trending": 1.0,
                "ranging": 0.0,
                "volatile": 0.0,
                "steady": 0.0,
            }
        },
    }


def test_compute_source_influence_respects_bounds():
    assert compute_source_influence(0.0, 0.0) == pytest.approx(0.25)
    assert compute_source_influence(100.0, 1.0) == pytest.approx(1.0)
    assert compute_source_influence(-50.0, 0.5) == pytest.approx(0.5625)


def test_compute_outcome_effect_covers_win_loss_and_expired():
    assert compute_outcome_effect("TP1_HIT", "LONG", 20.0) == 1.0
    assert compute_outcome_effect("TP1_HIT", "LONG", -20.0) == -1.0
    assert compute_outcome_effect("SL_HIT", "LONG", 20.0) == -1.0
    assert compute_outcome_effect("SL_HIT", "LONG", -20.0) == 1.0
    assert compute_outcome_effect("EXPIRED", "LONG", 20.0) == -0.5
    assert compute_outcome_effect("EXPIRED", "LONG", -20.0) == 0.0
    assert compute_outcome_effect("TP1_HIT", "LONG", 0.0) == 0.0


def test_apply_resolved_signal_distributes_delta_across_full_regime_mix():
    overlay = empty_overlay()
    record, reason = signal_to_online_record(
        _signal(
            signal_id=1,
            raw_indicators=_complete_raw(tech_score=100.0, tech_confidence=1.0),
            regime_mix={"trending": 0.75, "ranging": 0.25, "volatile": 0.0, "steady": 0.0},
        )
    )
    assert reason is None
    apply_resolved_signal(overlay, record)
    assert overlay["trending"]["tech"] == pytest.approx(BASE_LR * 0.75)
    assert overlay["ranging"]["tech"] == pytest.approx(BASE_LR * 0.25)
    assert overlay["volatile"]["tech"] == pytest.approx(0.0)
    assert overlay["steady"]["tech"] == pytest.approx(0.0)


def test_apply_resolved_signal_loss_is_symmetric_to_win():
    win_overlay = empty_overlay()
    loss_overlay = empty_overlay()
    win_record, _ = signal_to_online_record(
        _signal(
            signal_id=2,
            raw_indicators=_complete_raw(flow_score=80.0, flow_confidence=1.0),
        )
    )
    loss_record, _ = signal_to_online_record(
        _signal(
            signal_id=3,
            outcome="SL_HIT",
            raw_indicators=_complete_raw(flow_score=80.0, flow_confidence=1.0),
        )
    )
    apply_resolved_signal(win_overlay, win_record)
    apply_resolved_signal(loss_overlay, loss_record)
    assert loss_overlay["trending"]["flow"] == pytest.approx(-win_overlay["trending"]["flow"])


def test_apply_resolved_signal_expired_only_blames_aligned_sources():
    overlay = empty_overlay()
    record, _ = signal_to_online_record(
        _signal(
            signal_id=4,
            outcome="EXPIRED",
            raw_indicators=_complete_raw(
                tech_score=100.0,
                tech_confidence=1.0,
                flow_score=-100.0,
                flow_confidence=1.0,
            ),
        )
    )
    apply_resolved_signal(overlay, record)
    assert overlay["trending"]["tech"] == pytest.approx(-0.5 * BASE_LR)
    assert overlay["trending"]["flow"] == pytest.approx(0.0)


def test_trim_retained_window_enforces_age_and_size_limits():
    now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    stale = {"id": 1, "outcome_at": now - timedelta(days=14, minutes=1)}
    recent = [
        {"id": idx + 2, "outcome_at": now - timedelta(minutes=idx)}
        for idx in range(MAX_WINDOW_SIGNALS + 5)
    ]
    trimmed = trim_retained_window([stale, *recent], now=now)
    assert len(trimmed) == MAX_WINDOW_SIGNALS
    assert all(item["outcome_at"] >= now - timedelta(days=14) for item in trimmed)
    assert trimmed[0]["id"] == 101
    assert trimmed[-1]["id"] == 2


def test_build_overlay_state_returns_none_below_min_sample_gate():
    now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    records = []
    for idx in range(MIN_WINDOW_SIGNALS - 1):
        record, _ = signal_to_online_record(
            _signal(
                signal_id=idx + 1,
                outcome_at=now - timedelta(minutes=idx),
                raw_indicators=_complete_raw(tech_score=50.0, tech_confidence=1.0),
            )
        )
        records.append(record)
    assert build_overlay_state_from_records(records, now=now) is None


def test_resolve_effective_outer_weight_rows_clamps_and_normalizes():
    baseline = _baseline_row()
    overlay = empty_overlay()
    overlay["eligible_count"] = MIN_WINDOW_SIGNALS
    overlay["trending"]["tech"] = 0.30
    overlay["trending"]["flow"] = -0.30
    rows = resolve_effective_outer_weight_rows(baseline, overlay)
    trending = rows["trending"]
    assert trending["tech"] <= EFFECTIVE_WEIGHT_CEILING
    assert trending["flow"] >= EFFECTIVE_WEIGHT_FLOOR
    assert sum(trending.values()) == pytest.approx(1.0)


def test_resolve_effective_outer_weights_falls_back_without_active_overlay():
    baseline = _baseline_row()
    regime = {"trending": 0.6, "ranging": 0.2, "volatile": 0.1, "steady": 0.1}
    baseline_weights = resolve_effective_outer_weights(regime, baseline, overlay_state=None)
    inactive_overlay = empty_overlay()
    inactive_overlay["eligible_count"] = MIN_WINDOW_SIGNALS - 1
    overlay_weights = resolve_effective_outer_weights(regime, baseline, overlay_state=inactive_overlay)
    assert overlay_weights == baseline_weights


def test_resolve_effective_outer_weights_supports_default_baseline_overlay():
    regime = {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}
    overlay = empty_overlay()
    overlay["eligible_count"] = MIN_WINDOW_SIGNALS
    overlay["trending"]["tech"] = 0.02
    weights = resolve_effective_outer_weights(regime, regime_weights=None, overlay_state=overlay)
    assert weights["tech"] > DEFAULT_OUTER_WEIGHTS["trending"]["tech"]
    assert sum(weights.values()) == pytest.approx(1.0)


def test_build_runtime_states_uses_outcome_at_not_created_at():
    now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    history = [
        _signal(
        signal_id=1,
        created_at=now - timedelta(minutes=5),
            outcome_at=now - timedelta(minutes=20),
        raw_indicators=_complete_raw(tech_score=50.0, tech_confidence=1.0),
        ),
        _signal(
            signal_id=2,
            created_at=now - timedelta(hours=3),
            outcome_at=now - timedelta(minutes=19),
            raw_indicators=_complete_raw(tech_score=50.0, tech_confidence=1.0),
        ),
    ]
    for idx in range(18):
        history.append(
            _signal(
                signal_id=idx + 3,
                created_at=now - timedelta(hours=idx + 1),
                outcome_at=now - timedelta(minutes=18 - idx),
                raw_indicators=_complete_raw(tech_score=50.0, tech_confidence=1.0),
            )
        )

    windows, overlays = build_runtime_states_from_history(
        history,
        now=now,
        allowed_keys={("BTC-USDT-SWAP", "1h")},
    )
    retained = windows[("BTC-USDT-SWAP", "1h")]
    assert [retained[0]["id"], retained[1]["id"]] == [1, 2]
    assert overlays[("BTC-USDT-SWAP", "1h")]["eligible_count"] == MIN_WINDOW_SIGNALS


def test_build_runtime_states_skips_incomplete_snapshots():
    now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    good = [
        _signal(
            signal_id=idx + 1,
            outcome_at=now - timedelta(minutes=idx),
            raw_indicators=_complete_raw(tech_score=50.0, tech_confidence=1.0),
        )
        for idx in range(MIN_WINDOW_SIGNALS)
    ]
    bad = _signal(
        signal_id=999,
        outcome_at=now,
        raw_indicators={"tech_score": 50.0},
    )
    bad["engine_snapshot"] = {}
    windows, overlays = build_runtime_states_from_history(
        [*good, bad],
        now=now,
        allowed_keys={("BTC-USDT-SWAP", "1h")},
    )
    assert len(windows[("BTC-USDT-SWAP", "1h")]) == MIN_WINDOW_SIGNALS
    assert overlays[("BTC-USDT-SWAP", "1h")]["eligible_count"] == MIN_WINDOW_SIGNALS


def test_apply_resolved_signals_batch_matches_fresh_restart_replay():
    now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    history = [
        _signal(
            signal_id=idx + 1,
            outcome_at=now - timedelta(hours=idx),
            raw_indicators=_complete_raw(
                tech_score=50.0 if idx % 2 == 0 else -50.0,
                tech_confidence=1.0,
                flow_score=-40.0 if idx % 3 == 0 else 40.0,
                flow_confidence=0.9,
            ),
        )
        for idx in range(30)
    ]
    initial_windows, _ = build_runtime_states_from_history(
        history[:24],
        now=now,
        allowed_keys={("BTC-USDT-SWAP", "1h")},
    )
    next_windows, next_overlays = apply_resolved_signals_batch(
        history[24:],
        initial_windows,
        now=now,
        allowed_keys={("BTC-USDT-SWAP", "1h")},
    )
    replay_windows, replay_overlays = build_runtime_states_from_history(
        history,
        now=now,
        allowed_keys={("BTC-USDT-SWAP", "1h")},
    )
    assert next_windows == replay_windows
    assert next_overlays == replay_overlays


def test_clear_runtime_state_for_key_removes_overlay_and_window():
    key = ("BTC-USDT-SWAP", "1h")
    windows = {key: [{"id": 1}]}
    overlays = {key: {"eligible_count": MIN_WINDOW_SIGNALS}}
    clear_runtime_state_for_key(windows, overlays, key)
    assert key not in windows
    assert key not in overlays


def test_signal_to_online_record_only_accepts_supported_outcomes():
    record, reason = signal_to_online_record(_signal(signal_id=50, outcome="PENDING"))
    assert record is None
    assert reason == "unsupported_outcome"
    assert ONLINE_ELIGIBLE_OUTCOMES == frozenset(
        {
            "TP1_HIT",
            "TP2_HIT",
            "TP1_TRAIL",
            "TP1_TP2",
            "SL_HIT",
            "EXPIRED",
        }
    )


def test_active_regime_online_keys_uses_configured_runtime_scope():
    settings = SimpleNamespace(
        pairs=["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
        timeframes=["1h", "4h", "1D"],
    )
    assert _active_regime_online_keys(settings) == {
        ("BTC-USDT-SWAP", "1h"),
        ("BTC-USDT-SWAP", "4h"),
        ("ETH-USDT-SWAP", "1h"),
        ("ETH-USDT-SWAP", "4h"),
    }


@pytest.mark.asyncio
async def test_rebuild_regime_online_state_uses_configured_keys_without_baseline_row():
    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        {
            "id": idx + 1,
            "pair": "BTC-USDT-SWAP",
            "timeframe": "1h",
            "direction": "LONG",
            "outcome": "TP1_HIT",
            "outcome_at": datetime(2026, 4, 1, 12, 30, tzinfo=timezone.utc) - timedelta(minutes=idx),
            "raw_indicators": _complete_raw(tech_score=50.0, tech_confidence=1.0),
            "engine_snapshot": {
                "regime_mix": {
                    "trending": 1.0,
                    "ranging": 0.0,
                    "volatile": 0.0,
                    "steady": 0.0,
                }
            },
        }
        for idx in range(MIN_WINDOW_SIGNALS)
    ]

    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False
    session.execute = AsyncMock(return_value=result)

    db = MagicMock()
    db.session_factory = MagicMock(return_value=session)

    app = FastAPI()
    app.state.db = db
    app.state.settings = SimpleNamespace(
        pairs=["BTC-USDT-SWAP"],
        timeframes=["1h"],
    )
    app.state.regime_weights = {}
    app.state.regime_weight_signal_windows = {}
    app.state.regime_weight_overlays = {}

    await rebuild_regime_online_state(app, now=datetime(2026, 4, 1, 12, 31, tzinfo=timezone.utc))

    assert ("BTC-USDT-SWAP", "1h") in app.state.regime_weight_signal_windows
    assert app.state.regime_weight_overlays[("BTC-USDT-SWAP", "1h")]["eligible_count"] == MIN_WINDOW_SIGNALS


@pytest.mark.asyncio
async def test_rebuild_regime_online_state_falls_back_to_empty_state_on_failure():
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False
    session.execute = AsyncMock(side_effect=RuntimeError("boom"))

    db = MagicMock()
    db.session_factory = MagicMock(return_value=session)

    app = FastAPI()
    app.state.db = db
    app.state.settings = SimpleNamespace(
        pairs=["BTC-USDT-SWAP"],
        timeframes=["1h"],
    )
    app.state.regime_weights = {}
    app.state.regime_weight_signal_windows = {("BTC-USDT-SWAP", "1h"): [{"id": 1}]}
    app.state.regime_weight_overlays = {("BTC-USDT-SWAP", "1h"): {"eligible_count": MIN_WINDOW_SIGNALS}}

    await rebuild_regime_online_state(app, now=datetime(2026, 4, 1, 12, 31, tzinfo=timezone.utc))

    assert app.state.regime_weight_signal_windows == {}
    assert app.state.regime_weight_overlays == {}


@pytest.mark.asyncio
async def test_check_pending_signals_rebuilds_online_state_after_commit():
    resolved_at = datetime(2026, 4, 1, 12, 30, tzinfo=timezone.utc)
    signal = SimpleNamespace(
        id=7,
        pair="BTC-USDT-SWAP",
        timeframe="1h",
        direction="LONG",
        entry=50000.0,
        stop_loss=49000.0,
        take_profit_1=51000.0,
        take_profit_2=52000.0,
        created_at=datetime(2026, 4, 1, 11, 0, tzinfo=timezone.utc),
        outcome="PENDING",
        outcome_at=None,
        outcome_pnl_pct=None,
        outcome_duration_minutes=None,
        raw_indicators=_complete_raw(tech_score=50.0, tech_confidence=1.0),
        engine_snapshot={
            "regime_mix": {
                "trending": 1.0,
                "ranging": 0.0,
                "volatile": 0.0,
                "steady": 0.0,
            }
        },
        llm_factors=None,
        risk_metrics=None,
    )

    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = [signal]

    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False
    session.execute = AsyncMock(return_value=execute_result)
    session.commit = AsyncMock()

    db = MagicMock()
    db.session_factory = MagicMock(return_value=session)

    app = FastAPI()
    app.state.db = db
    app.state.redis = AsyncMock()
    app.state.redis.lrange = AsyncMock(
        return_value=[
            json.dumps(
                {
                    "timestamp": "2026-04-01T12:30:00+00:00",
                    "open": 50000.0,
                    "high": 51100.0,
                    "low": 49900.0,
                    "close": 51050.0,
                }
            )
        ]
    )
    app.state.settings = MagicMock()
    app.state.settings.engine_trail_atr_multiplier = 1.0
    app.state.settings.engine_partial_fraction = 0.5
    app.state.settings.pairs = ["BTC-USDT-SWAP"]
    app.state.settings.timeframes = ["1h"]
    app.state.optimizer = None
    app.state.llm_calibration = None
    app.state.regime_weights = {}
    app.state.regime_weight_signal_windows = {}
    app.state.regime_weight_overlays = {}

    with patch(
        "app.engine.outcome_resolver.resolve_signal_outcome",
        return_value={
            "outcome": "TP1_HIT",
            "outcome_at": resolved_at,
            "outcome_pnl_pct": 2.0,
            "outcome_duration_minutes": 90,
        },
    ), patch(
        "app.main.apply_resolved_signals_batch",
        return_value=(
            {("BTC-USDT-SWAP", "1h"): [{"id": idx} for idx in range(20)]},
            {
                ("BTC-USDT-SWAP", "1h"): {
                    "trending": {"tech": 0.01, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                    "ranging": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                    "volatile": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                    "steady": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                    "eligible_count": 20,
                    "window_oldest_outcome_at": "2026-03-20T00:00:00+00:00",
                    "window_newest_outcome_at": "2026-04-01T12:30:00+00:00",
                    "rebuilt_at": "2026-04-01T12:31:00+00:00",
                }
            },
        ),
    ) as apply_mock, patch("app.main.reset_streak", new=AsyncMock()):
        await check_pending_signals(app)

    apply_mock.assert_called_once()
    assert app.state.regime_weight_overlays[("BTC-USDT-SWAP", "1h")]["eligible_count"] == 20
