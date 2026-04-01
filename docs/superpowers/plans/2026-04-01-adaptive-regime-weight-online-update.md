# Adaptive Regime Weight Online Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a restart-safe online overlay that adapts per-regime outer source weights from recent resolved signals without mutating the durable `RegimeWeights` baseline rows.

**Architecture:** A new pure-Python `regime_online.py` module owns the adaptive learning rule, retained-window trimming, restart rebuild, and baseline-plus-overlay effective weight resolution. `main.py` derives the active runtime `(pair, timeframe)` set from configured pairs/timeframes, rebuilds runtime state from recent durable signals after settings are loaded at startup and after outcome resolution, and supports overlays for keys that still use `DEFAULT_OUTER_WEIGHTS` because no materialized `RegimeWeights` row exists. `api/engine.py` clears the overlay/window state whenever a materialized `RegimeWeights` refresh is reloaded into memory.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, PostgreSQL JSONB models, pytest, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-04-01-adaptive-regime-weight-online-update-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/engine/regime_online.py` | Create | Online learning constants, signal eligibility extraction, retained-window trimming, overlay rebuild, baseline-plus-overlay effective outer weight resolution, runtime state helper functions |
| `backend/app/engine/regime.py` | Modify | Expose baseline outer-weight tables cleanly and allow blending from precomputed effective per-regime rows |
| `backend/app/main.py` | Modify | Initialize runtime overlay/window state, derive active runtime keys from configured pairs/timeframes, rebuild overlays from recent durable signals on startup via an extracted helper, use effective weights in `run_pipeline()`, rebuild runtime overlay state after resolved outcomes |
| `backend/app/api/engine.py` | Modify | Clear overlay/window runtime state for any `(pair, timeframe)` whose baseline `RegimeWeights` row was reloaded after a confirmed apply |
| `backend/tests/engine/test_regime_online.py` | Create | Unit and module-integration tests for learning rule, gating, replay ordering, trimming, restart equivalence, effective weight resolution, and startup rebuild helper behavior |
| `backend/tests/engine/test_regime_pipeline.py` | Modify | Verify `run_pipeline()` routes regime outer-weight resolution through the online helper and passes overlay state for the active `(pair, timeframe)` |
| `backend/tests/api/test_engine_apply.py` | Modify | Verify confirmed `regime_weights.*` updates clear the in-memory overlay/window state for the touched pair/timeframe |
| `backend/tests/conftest.py` | Modify | Initialize `app.state.regime_weight_overlays` and `app.state.regime_weight_signal_windows` on API test apps |

---

### Task 1: Build the Online Overlay Core Module

**Files:**
- Create: `backend/app/engine/regime_online.py`
- Create: `backend/tests/engine/test_regime_online.py`

- [ ] **Step 1: Write the failing tests for the learning rule, trimming, and replay-derived state**

Create `backend/tests/engine/test_regime_online.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.engine.regime import DEFAULT_OUTER_WEIGHTS, OUTER_KEYS, REGIMES
from app.engine.regime_online import (
    BASE_LR,
    EFFECTIVE_WEIGHT_CEILING,
    EFFECTIVE_WEIGHT_FLOOR,
    MAX_WINDOW_SIGNALS,
    MIN_WINDOW_SIGNALS,
    WINDOW_DAYS,
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
            "regime_mix": regime_mix or {
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
    record, reason = signal_to_online_record(_signal(
        signal_id=1,
        raw_indicators=_complete_raw(tech_score=100.0, tech_confidence=1.0),
        regime_mix={"trending": 0.75, "ranging": 0.25, "volatile": 0.0, "steady": 0.0},
    ))
    assert reason is None
    apply_resolved_signal(overlay, record)
    assert overlay["trending"]["tech"] == pytest.approx(BASE_LR * 0.75)
    assert overlay["ranging"]["tech"] == pytest.approx(BASE_LR * 0.25)
    assert overlay["volatile"]["tech"] == pytest.approx(0.0)
    assert overlay["steady"]["tech"] == pytest.approx(0.0)


def test_apply_resolved_signal_loss_is_symmetric_to_win():
    win_overlay = empty_overlay()
    loss_overlay = empty_overlay()
    win_record, _ = signal_to_online_record(_signal(
        signal_id=2,
        raw_indicators=_complete_raw(flow_score=80.0, flow_confidence=1.0),
    ))
    loss_record, _ = signal_to_online_record(_signal(
        signal_id=3,
        outcome="SL_HIT",
        raw_indicators=_complete_raw(flow_score=80.0, flow_confidence=1.0),
    ))
    apply_resolved_signal(win_overlay, win_record)
    apply_resolved_signal(loss_overlay, loss_record)
    assert loss_overlay["trending"]["flow"] == pytest.approx(-win_overlay["trending"]["flow"])
```

- [ ] **Step 2: Add the retained-window, gating, and restart-equivalence tests**

Append to `backend/tests/engine/test_regime_online.py`:

```python
def test_apply_resolved_signal_expired_only_blames_aligned_sources():
    overlay = empty_overlay()
    record, _ = signal_to_online_record(_signal(
        signal_id=4,
        outcome="EXPIRED",
        raw_indicators=_complete_raw(
            tech_score=100.0,
            tech_confidence=1.0,
            flow_score=-100.0,
            flow_confidence=1.0,
        ),
    ))
    apply_resolved_signal(overlay, record)
    assert overlay["trending"]["tech"] == pytest.approx(-0.5 * BASE_LR)
    assert overlay["trending"]["flow"] == pytest.approx(0.0)


def test_trim_retained_window_enforces_age_and_size_limits():
    now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    stale = {"id": 1, "outcome_at": now - timedelta(days=WINDOW_DAYS, minutes=1)}
    recent = [
        {"id": idx + 2, "outcome_at": now - timedelta(minutes=idx)}
        for idx in range(MAX_WINDOW_SIGNALS + 5)
    ]
    trimmed = trim_retained_window([stale, *recent], now=now)
    assert len(trimmed) == MAX_WINDOW_SIGNALS
    assert all(item["outcome_at"] >= now - timedelta(days=WINDOW_DAYS) for item in trimmed)
    assert trimmed[0]["id"] == 101
    assert trimmed[-1]["id"] == 2


def test_build_overlay_state_returns_none_below_min_sample_gate():
    now = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    records = []
    for idx in range(MIN_WINDOW_SIGNALS - 1):
        record, _ = signal_to_online_record(_signal(
            signal_id=idx + 1,
            outcome_at=now - timedelta(minutes=idx),
            raw_indicators=_complete_raw(tech_score=50.0, tech_confidence=1.0),
        ))
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
    older_created_later = _signal(
        signal_id=1,
        created_at=now - timedelta(minutes=5),
        outcome_at=now - timedelta(minutes=2),
        raw_indicators=_complete_raw(tech_score=50.0, tech_confidence=1.0),
    )
    newer_created_earlier = _signal(
        signal_id=2,
        created_at=now - timedelta(hours=3),
        outcome_at=now - timedelta(minutes=1),
        raw_indicators=_complete_raw(tech_score=50.0, tech_confidence=1.0),
    )
    history = [older_created_later, newer_created_earlier] * 10
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
    assert ONLINE_ELIGIBLE_OUTCOMES == frozenset({
        "TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2", "SL_HIT", "EXPIRED",
    })
```

- [ ] **Step 3: Run the new test file and confirm it fails**

Run:

```bash
cd backend
docker exec krypton-api-1 python -m pytest tests/engine/test_regime_online.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine.regime_online'`

- [ ] **Step 4: Implement the full online overlay module**

Create `backend/app/engine/regime_online.py`:

```python
"""Replay-derived online regime outer-weight adaptation."""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta, timezone

from app.engine.regime import OUTER_KEYS, REGIMES, blend_outer_weights, get_outer_weight_table

logger = logging.getLogger(__name__)

WINDOW_DAYS = 14
MIN_WINDOW_SIGNALS = 20
MAX_WINDOW_SIGNALS = 100
BASE_LR = 0.01
OVERLAY_DELTA_MIN = -0.12
OVERLAY_DELTA_MAX = 0.12
EFFECTIVE_WEIGHT_FLOOR = 0.02
EFFECTIVE_WEIGHT_CEILING = 0.50
ONLINE_ELIGIBLE_OUTCOMES = frozenset({
    "TP1_HIT",
    "TP2_HIT",
    "TP1_TRAIL",
    "TP1_TP2",
    "SL_HIT",
    "EXPIRED",
})
ONLINE_WIN_OUTCOMES = frozenset({"TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2"})


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def empty_overlay() -> dict:
    return {
        regime: {source: 0.0 for source in OUTER_KEYS}
        for regime in REGIMES
    }


def compute_source_influence(score: float, confidence: float) -> float:
    confidence_factor = 0.5 + 0.5 * _clamp(float(confidence), 0.0, 1.0)
    magnitude_factor = 0.5 + 0.5 * _clamp(abs(float(score)) / 100.0, 0.0, 1.0)
    return confidence_factor * magnitude_factor


def compute_outcome_effect(outcome: str, direction: str, score: float) -> float:
    if score == 0:
        return 0.0

    aligned = (direction == "LONG" and score > 0) or (direction == "SHORT" and score < 0)
    opposed = (direction == "LONG" and score < 0) or (direction == "SHORT" and score > 0)

    if outcome in ONLINE_WIN_OUTCOMES:
        return 1.0 if aligned else (-1.0 if opposed else 0.0)

    if outcome == "SL_HIT":
        return -1.0 if aligned else (1.0 if opposed else 0.0)

    if outcome == "EXPIRED":
        return -0.5 if aligned else 0.0

    return 0.0


def signal_to_online_record(signal: dict) -> tuple[dict | None, str | None]:
    outcome = signal.get("outcome")
    if outcome not in ONLINE_ELIGIBLE_OUTCOMES:
        return None, "unsupported_outcome"

    outcome_at = signal.get("outcome_at")
    if outcome_at is None:
        return None, "missing_outcome_at"

    raw = signal.get("raw_indicators") or {}
    snapshot = signal.get("engine_snapshot") or {}
    regime_mix = snapshot.get("regime_mix")
    if not regime_mix:
        return None, "missing_regime_mix"

    scores = {}
    confidences = {}
    for source in OUTER_KEYS:
        score_key = f"{source}_score"
        conf_key = f"{source}_confidence"
        if score_key not in raw or conf_key not in raw:
            return None, f"missing_{source}_inputs"
        scores[source] = float(raw[score_key] or 0.0)
        confidences[source] = float(raw[conf_key] or 0.0)

    normalized_mix = {regime: float(regime_mix.get(regime, 0.0) or 0.0) for regime in REGIMES}
    mix_total = sum(normalized_mix.values())
    if mix_total <= 0:
        return None, "empty_regime_mix"
    normalized_mix = {regime: value / mix_total for regime, value in normalized_mix.items()}

    return {
        "id": int(signal["id"]),
        "pair": signal["pair"],
        "timeframe": signal["timeframe"],
        "direction": signal["direction"],
        "outcome": outcome,
        "outcome_at": outcome_at,
        "scores": scores,
        "confidences": confidences,
        "regime_mix": normalized_mix,
    }, None


def apply_resolved_signal(overlay: dict, record: dict) -> None:
    for source in OUTER_KEYS:
        score = record["scores"][source]
        effect = compute_outcome_effect(record["outcome"], record["direction"], score)
        if effect == 0.0:
            continue
        influence = compute_source_influence(score, record["confidences"][source])
        for regime in REGIMES:
            prior = overlay[regime][source]
            delta = BASE_LR * record["regime_mix"][regime] * effect * influence
            overlay[regime][source] = _clamp(
                prior + delta,
                OVERLAY_DELTA_MIN,
                OVERLAY_DELTA_MAX,
            )


def trim_retained_window(records: list[dict], *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    eligible = [record for record in records if record["outcome_at"] >= cutoff]
    eligible.sort(key=lambda item: (item["outcome_at"], item["id"]))
    if len(eligible) > MAX_WINDOW_SIGNALS:
        eligible = eligible[-MAX_WINDOW_SIGNALS:]
    return eligible


def build_overlay_state_from_records(records: list[dict], *, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    retained = trim_retained_window(records, now=now)
    if len(retained) < MIN_WINDOW_SIGNALS:
        return None

    overlay = empty_overlay()
    for record in retained:
        apply_resolved_signal(overlay, record)

    overlay["eligible_count"] = len(retained)
    overlay["window_oldest_outcome_at"] = retained[0]["outcome_at"].isoformat()
    overlay["window_newest_outcome_at"] = retained[-1]["outcome_at"].isoformat()
    overlay["rebuilt_at"] = now.isoformat()
    return overlay


def build_runtime_states_from_history(
    signals: list[dict],
    *,
    now: datetime | None = None,
    allowed_keys: set[tuple[str, str]] | None = None,
    logger=None,
) -> tuple[dict, dict]:
    now = now or datetime.now(timezone.utc)
    state_logger = logger or globals()["logger"]
    grouped: dict[tuple[str, str], list[dict]] = {}
    skipped: dict[tuple[str, str], int] = {}

    for signal in signals:
        key = (signal["pair"], signal["timeframe"])
        if allowed_keys is not None and key not in allowed_keys:
            continue
        record, reason = signal_to_online_record(signal)
        if record is None:
            if reason != "unsupported_outcome":
                skipped[key] = skipped.get(key, 0) + 1
            continue
        grouped.setdefault(key, []).append(record)

    windows: dict[tuple[str, str], list[dict]] = {}
    overlays: dict[tuple[str, str], dict] = {}

    for key, records in grouped.items():
        retained = trim_retained_window(records, now=now)
        windows[key] = retained
        overlay_state = build_overlay_state_from_records(retained, now=now)
        if overlay_state is not None:
            overlays[key] = overlay_state

    for (pair, timeframe), count in skipped.items():
        state_logger.warning(
            "Skipped %d online-regime signals for %s:%s due to incomplete snapshot data",
            count,
            pair,
            timeframe,
        )

    return windows, overlays


def apply_resolved_signals_batch(
    signals: list[dict],
    retained_windows: dict[tuple[str, str], list[dict]],
    *,
    now: datetime | None = None,
    allowed_keys: set[tuple[str, str]] | None = None,
    logger=None,
) -> tuple[dict, dict]:
    now = now or datetime.now(timezone.utc)
    state_logger = logger or globals()["logger"]
    next_windows = {
        key: list(records)
        for key, records in retained_windows.items()
        if allowed_keys is None or key in allowed_keys
    }
    skipped: dict[tuple[str, str], int] = {}

    for signal in signals:
        key = (signal["pair"], signal["timeframe"])
        if allowed_keys is not None and key not in allowed_keys:
            continue
        record, reason = signal_to_online_record(signal)
        if record is None:
            if reason != "unsupported_outcome":
                skipped[key] = skipped.get(key, 0) + 1
            continue
        next_windows.setdefault(key, []).append(record)
        next_windows[key] = trim_retained_window(next_windows[key], now=now)

    next_overlays: dict[tuple[str, str], dict] = {}
    for key, records in next_windows.items():
        overlay_state = build_overlay_state_from_records(records, now=now)
        if overlay_state is not None:
            next_overlays[key] = overlay_state

    for (pair, timeframe), count in skipped.items():
        state_logger.warning(
            "Skipped %d online-regime signals for %s:%s due to incomplete snapshot data",
            count,
            pair,
            timeframe,
        )

    return next_windows, next_overlays


def clear_runtime_state_for_key(
    retained_windows: dict[tuple[str, str], list[dict]],
    overlays: dict[tuple[str, str], dict],
    key: tuple[str, str],
) -> None:
    retained_windows.pop(key, None)
    overlays.pop(key, None)


def _normalize_regime_row(row: dict[str, float]) -> dict[str, float]:
    clamped = {
        source: _clamp(value, EFFECTIVE_WEIGHT_FLOOR, EFFECTIVE_WEIGHT_CEILING)
        for source, value in row.items()
    }
    total = sum(clamped.values())
    if total <= 0:
        even = 1.0 / len(OUTER_KEYS)
        return {source: even for source in OUTER_KEYS}
    return {source: clamped[source] / total for source in OUTER_KEYS}


def resolve_effective_outer_weight_rows(regime_weights=None, overlay_state: dict | None = None) -> dict:
    baseline_rows = copy.deepcopy(get_outer_weight_table(regime_weights))
    if not overlay_state or overlay_state.get("eligible_count", 0) < MIN_WINDOW_SIGNALS:
        return baseline_rows

    effective = {}
    for regime in REGIMES:
        merged = {}
        for source in OUTER_KEYS:
            merged[source] = baseline_rows[regime][source] + overlay_state[regime][source]
        effective[regime] = _normalize_regime_row(merged)
    return effective


def resolve_effective_outer_weights(regime: dict, regime_weights=None, overlay_state: dict | None = None) -> dict:
    effective_rows = resolve_effective_outer_weight_rows(regime_weights, overlay_state)
    return blend_outer_weights(regime, outer_weights=effective_rows)
```

- [ ] **Step 5: Run the new unit/module test file**

Run:

```bash
cd backend
docker exec krypton-api-1 python -m pytest tests/engine/test_regime_online.py -v
```

Expected: PASS

- [ ] **Step 6: Commit the core module**

Run:

```bash
git add backend/app/engine/regime_online.py backend/tests/engine/test_regime_online.py
git commit -m "feat(engine): add regime online overlay core"
```

---

### Task 2: Route Outer-Weight Resolution Through the Online Helper

**Files:**
- Modify: `backend/app/engine/regime.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/engine/test_regime_pipeline.py`

- [ ] **Step 1: Add a wiring test for `run_pipeline()`**

Append to `backend/tests/engine/test_regime_pipeline.py`:

```python
from unittest.mock import patch


class TestPipelineWithOnlineOverlay:
    @pytest.mark.asyncio
    async def test_routes_outer_weight_resolution_through_online_helper(self):
        rw = MagicMock()
        for regime in ["trending", "ranging", "volatile", "steady"]:
            for source in ["tech", "flow", "onchain", "pattern", "liquidation", "confluence", "news"]:
                setattr(rw, f"{regime}_{source}_weight", 1.0 / 7.0)
            setattr(rw, f"{regime}_trend_cap", 30.0)
            setattr(rw, f"{regime}_mean_rev_cap", 25.0)
            setattr(rw, f"{regime}_squeeze_cap", 20.0)
            setattr(rw, f"{regime}_volume_cap", 25.0)

        app, _ = _make_app(regime_weights={("BTC-USDT-SWAP", "1h"): rw})
        app.state.regime_weight_overlays = {
            ("BTC-USDT-SWAP", "1h"): {
                "trending": {"tech": 0.01, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                "ranging": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                "volatile": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                "steady": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                "eligible_count": 20,
                "window_oldest_outcome_at": "2026-03-20T00:00:00+00:00",
                "window_newest_outcome_at": "2026-04-01T00:00:00+00:00",
                "rebuilt_at": "2026-04-01T00:00:00+00:00",
            }
        }
        app.state.regime_weight_signal_windows = {
            ("BTC-USDT-SWAP", "1h"): [{"id": i} for i in range(20)]
        }
        app.state.redis.lrange = AsyncMock(return_value=_raw_candles())
        app.state.redis.get = AsyncMock(return_value=None)

        candle = {
            "pair": "BTC-USDT-SWAP", "timeframe": "1h",
            "timestamp": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "open": 67000, "high": 67100, "low": 66900, "close": 67050,
            "volume": 100,
        }

        with patch("app.main.resolve_effective_outer_weights") as resolve_mock:
            resolve_mock.return_value = {
                "tech": 0.30,
                "flow": 0.15,
                "onchain": 0.15,
                "pattern": 0.10,
                "liquidation": 0.10,
                "confluence": 0.10,
                "news": 0.10,
            }
            await run_pipeline(app, candle)

        resolve_mock.assert_called_once()
        _, kwargs = resolve_mock.call_args
        assert kwargs["overlay_state"]["eligible_count"] == 20
```

- [ ] **Step 2: Run the new test and confirm it fails**

Run:

```bash
cd backend
docker exec krypton-api-1 python -m pytest tests/engine/test_regime_pipeline.py -k "online_helper" -v
```

Expected: FAIL because `run_pipeline()` still calls `blend_outer_weights()` directly and does not import `resolve_effective_outer_weights`

- [ ] **Step 3: Expose precomputed outer-weight tables in `regime.py`**

Update `backend/app/engine/regime.py`:

```python
"""Market regime detection and adaptive weight blending."""

import copy


REGIMES = ["trending", "ranging", "volatile", "steady"]
CAP_KEYS = ["trend_cap", "mean_rev_cap", "squeeze_cap", "volume_cap"]
OUTER_KEYS = ["tech", "flow", "onchain", "pattern", "liquidation", "confluence", "news"]


def get_outer_weight_table(regime_weights=None) -> dict:
    """Return per-regime outer weights from a DB row or defaults."""
    if regime_weights:
        return _extract_regime_dict(regime_weights, OUTER_KEYS, "_weight")
    return copy.deepcopy(DEFAULT_OUTER_WEIGHTS)


def blend_outer_weights(regime: dict, regime_weights=None, outer_weights: dict | None = None) -> dict:
    """Blend effective outer blend weights from regime mix."""
    outer = outer_weights if outer_weights is not None else get_outer_weight_table(regime_weights)
    return _blend(regime, outer, OUTER_KEYS)
```

- [ ] **Step 4: Use `resolve_effective_outer_weights()` inside `run_pipeline()`**

Update the imports near the top of `backend/app/main.py`:

```python
from app.engine.regime import smooth_regime_mix
from app.engine.regime_online import resolve_effective_outer_weights
```

Replace the regime-aware outer-weight block in `backend/app/main.py`:

```python
    # Regime-aware outer weight blending (smoothed to prevent single-candle flips)
    regime = tech_result.get("regime")
    if regime:
        regime = smooth_regime_mix(regime, app.state.smoothed_regime, pair, timeframe)

    overlay_state = getattr(app.state, "regime_weight_overlays", {}).get(rw_key)
    outer = resolve_effective_outer_weights(
        regime,
        regime_weights=regime_weights,
        overlay_state=overlay_state,
    )
```

- [ ] **Step 5: Initialize the new test-app state keys**

Update `_make_app()` in `backend/tests/engine/test_regime_pipeline.py`:

```python
    app.state.regime_weights = regime_weights or {}
    app.state.regime_weight_overlays = {}
    app.state.regime_weight_signal_windows = {}
    app.state.smoothed_regime = {}
```

- [ ] **Step 6: Run the targeted tests**

Run:

```bash
cd backend
docker exec krypton-api-1 python -m pytest tests/engine/test_regime_online.py tests/engine/test_regime_pipeline.py -v
```

Expected: PASS

- [ ] **Step 7: Commit the scoring-path integration**

Run:

```bash
git add backend/app/engine/regime.py backend/app/main.py backend/tests/engine/test_regime_pipeline.py
git commit -m "feat(engine): blend effective online regime weights"
```

---

### Task 3: Rebuild Runtime Online State on Startup and After Outcome Resolution

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/engine/test_regime_online.py`

- [ ] **Step 1: Add startup-helper and post-resolution wiring tests**

Append to `backend/tests/engine/test_regime_online.py`:

```python
import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI

from app.main import _active_regime_online_keys, check_pending_signals, rebuild_regime_online_state


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
    result.mappings.return_value.all.return_value = [{
        "id": idx + 1,
        "pair": "BTC-USDT-SWAP",
        "timeframe": "1h",
        "direction": "LONG",
        "outcome": "TP1_HIT",
        "outcome_at": datetime(2026, 4, 1, 12, 30, tzinfo=timezone.utc) - timedelta(minutes=idx),
        "raw_indicators": _complete_raw(tech_score=50.0, tech_confidence=1.0),
        "engine_snapshot": {"regime_mix": {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}},
    } for idx in range(MIN_WINDOW_SIGNALS)]

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
        engine_snapshot={"regime_mix": {"trending": 1.0, "ranging": 0.0, "volatile": 0.0, "steady": 0.0}},
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
    app.state.redis.lrange = AsyncMock(return_value=[
        json.dumps({
            "timestamp": "2026-04-01T12:30:00+00:00",
            "open": 50000.0,
            "high": 51100.0,
            "low": 49900.0,
            "close": 51050.0,
        })
    ])
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

    with patch("app.engine.outcome_resolver.resolve_signal_outcome", return_value={
        "outcome": "TP1_HIT",
        "outcome_at": resolved_at,
        "outcome_pnl_pct": 2.0,
        "outcome_duration_minutes": 90,
    }), patch("app.main.apply_resolved_signals_batch", return_value=(
        {("BTC-USDT-SWAP", "1h"): [{"id": idx} for idx in range(20)]},
        {("BTC-USDT-SWAP", "1h"): {
            "trending": {"tech": 0.01, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "ranging": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "volatile": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "steady": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "eligible_count": 20,
            "window_oldest_outcome_at": "2026-03-20T00:00:00+00:00",
            "window_newest_outcome_at": "2026-04-01T12:30:00+00:00",
            "rebuilt_at": "2026-04-01T12:31:00+00:00",
        }},
    )) as apply_mock, patch("app.main.reset_streak", new=AsyncMock()):
        await check_pending_signals(app)

    apply_mock.assert_called_once()
    assert app.state.regime_weight_overlays[("BTC-USDT-SWAP", "1h")]["eligible_count"] == 20
```

- [ ] **Step 2: Run the new wiring test and confirm it fails**

Run:

```bash
cd backend
docker exec krypton-api-1 python -m pytest tests/engine/test_regime_online.py -k "rebuild_regime_online_state or rebuilds_online_state_after_commit" -v
```

Expected: FAIL because `main.py` does not yet expose the startup helper or update the online runtime state using configured runtime keys

- [ ] **Step 3: Add extracted startup rebuild helpers and replay recent durable history after settings load**

Update the imports in `backend/app/main.py`:

```python
from app.engine.regime_online import (
    ONLINE_ELIGIBLE_OUTCOMES,
    WINDOW_DAYS,
    apply_resolved_signals_batch,
    build_runtime_states_from_history,
    resolve_effective_outer_weights,
)
```

Also add `tuple_` to the SQLAlchemy imports in `backend/app/main.py`.

Add these helpers near `check_pending_signals()` in `backend/app/main.py`:

```python
def _active_regime_online_keys(settings) -> set[tuple[str, str]]:
    return {
        (pair, timeframe)
        for pair in settings.pairs
        for timeframe in settings.timeframes
        if timeframe not in CONFLUENCE_ONLY_TIMEFRAMES
    }


async def rebuild_regime_online_state(app: FastAPI, *, now: datetime | None = None) -> None:
    app.state.regime_weight_overlays = {}
    app.state.regime_weight_signal_windows = {}

    runtime_keys = _active_regime_online_keys(app.state.settings)
    if not runtime_keys:
        return

    db = app.state.db
    now = now or datetime.now(timezone.utc)
    try:
        started = time.perf_counter()
        cutoff = now - timedelta(days=WINDOW_DAYS)
        async with db.session_factory() as session:
            result = await session.execute(
                select(
                    Signal.id,
                    Signal.pair,
                    Signal.timeframe,
                    Signal.direction,
                    Signal.outcome,
                    Signal.outcome_at,
                    Signal.raw_indicators,
                    Signal.engine_snapshot,
                )
                .where(Signal.outcome.in_(tuple(ONLINE_ELIGIBLE_OUTCOMES)))
                .where(Signal.outcome_at.isnot(None))
                .where(Signal.outcome_at >= cutoff)
                .where(tuple_(Signal.pair, Signal.timeframe).in_(sorted(runtime_keys)))
                .order_by(Signal.pair, Signal.timeframe, Signal.outcome_at, Signal.id)
            )
            recent_resolved = [dict(row) for row in result.mappings().all()]

        windows, overlays = build_runtime_states_from_history(
            recent_resolved,
            now=now,
            allowed_keys=runtime_keys,
            logger=logger,
        )
        app.state.regime_weight_signal_windows = windows
        app.state.regime_weight_overlays = overlays

        logger.info(
            "Rebuilt regime weight overlays for %d/%d pair-timeframe combos from %d signals in %.1fms",
            len(overlays),
            len(runtime_keys),
            len(recent_resolved),
            (time.perf_counter() - started) * 1000,
        )
    except Exception as e:
        logger.warning("Failed to rebuild regime weight overlays: %s", e)
        app.state.regime_weight_signal_windows = {}
        app.state.regime_weight_overlays = {}
```

Inside `lifespan()` in `backend/app/main.py`, immediately after `app.state.regime_weights` is loaded, initialize:

```python
    app.state.regime_weight_overlays = {}
    app.state.regime_weight_signal_windows = {}
```

Then, after PipelineSettings are loaded and patched onto `settings`, call:

```python
    await rebuild_regime_online_state(app)
```

This call must happen after settings load so the rebuild scope includes configured pair/timeframes that still use `DEFAULT_OUTER_WEIGHTS` because no `RegimeWeights` row exists.

- [ ] **Step 4: Rebuild the retained window and overlay after resolved outcomes commit**

In `check_pending_signals()` in `backend/app/main.py`, after the existing calibration-state update block and before the optimizer notification block, add:

```python
        try:
            resolved_signals = [
                {
                    "id": signal.id,
                    "pair": signal.pair,
                    "timeframe": signal.timeframe,
                    "direction": signal.direction,
                    "outcome": signal.outcome,
                    "outcome_at": signal.outcome_at,
                    "raw_indicators": signal.raw_indicators,
                    "engine_snapshot": signal.engine_snapshot,
                }
                for signal in pending
                if signal.outcome != "PENDING" and signal.outcome_at is not None
            ]
            if resolved_signals:
                current_windows = getattr(app.state, "regime_weight_signal_windows", {})
                next_windows, next_overlays = apply_resolved_signals_batch(
                    resolved_signals,
                    current_windows,
                    now=datetime.now(timezone.utc),
                    allowed_keys=_active_regime_online_keys(settings),
                    logger=logger,
                )
                app.state.regime_weight_signal_windows = next_windows
                app.state.regime_weight_overlays = next_overlays
                logger.info(
                    "Updated regime weight overlays for %d pair/timeframe combos after resolution batch",
                    len(next_overlays),
                )
        except Exception as e:
            logger.exception("Failed to update regime weight overlays after outcome resolution: %s", e)
```

- [ ] **Step 5: Initialize the runtime state on test apps**

Update `backend/tests/conftest.py`:

```python
    app.state.regime_weights = {}
    app.state.regime_weight_overlays = {}
    app.state.regime_weight_signal_windows = {}
    app.state.smoothed_regime = {}
```

- [ ] **Step 6: Run the targeted tests**

Run:

```bash
cd backend
docker exec krypton-api-1 python -m pytest tests/engine/test_regime_online.py tests/engine/test_regime_pipeline.py tests/api/test_engine_apply.py -v
```

Expected: PASS, including the direct startup-helper coverage

- [ ] **Step 7: Commit the startup/runtime rebuild integration**

Run:

```bash
git add backend/app/main.py backend/tests/conftest.py backend/tests/engine/test_regime_online.py
git commit -m "feat(engine): rebuild regime overlays from resolved signals"
```

---

### Task 4: Clear the Online Overlay When Baseline `RegimeWeights` Are Reloaded

**Files:**
- Modify: `backend/app/api/engine.py`
- Modify: `backend/tests/api/test_engine_apply.py`

- [ ] **Step 1: Add the failing API test for baseline-refresh clearing**

Append to `backend/tests/api/test_engine_apply.py`:

```python
@pytest.mark.asyncio
async def test_confirmed_regime_weight_update_clears_online_overlay_state(app, client):
    rw = MagicMock()
    rw.pair = "BTC-USDT-SWAP"
    rw.timeframe = "1h"
    rw.trending_tech_weight = 0.34

    ps = MagicMock()

    pipeline_result = MagicMock()
    pipeline_result.scalar_one_or_none.return_value = ps

    pair_row_result = MagicMock()
    pair_row_result.scalar_one_or_none.return_value = rw

    reload_result = MagicMock()
    reload_result.scalars.return_value.all.return_value = [rw]

    session = AsyncMock()
    session.__aenter__.return_value = session
    session.__aexit__.return_value = False
    session.execute = AsyncMock(side_effect=[pipeline_result, pair_row_result, reload_result])
    session.commit = AsyncMock()

    app.state.db.session_factory = MagicMock(return_value=session)
    app.state.regime_weights = {("BTC-USDT-SWAP", "1h"): rw}
    app.state.regime_weight_signal_windows = {
        ("BTC-USDT-SWAP", "1h"): [{"id": idx} for idx in range(20)]
    }
    app.state.regime_weight_overlays = {
        ("BTC-USDT-SWAP", "1h"): {
            "trending": {"tech": 0.01, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "ranging": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "volatile": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "steady": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
            "eligible_count": 20,
            "window_oldest_outcome_at": "2026-03-20T00:00:00+00:00",
            "window_newest_outcome_at": "2026-04-01T00:00:00+00:00",
            "rebuilt_at": "2026-04-01T00:00:01+00:00",
        }
    }

    resp = await client.post(
        "/api/engine/apply",
        cookies=COOKIES,
        json={
            "changes": {
                "regime_weights.BTC-USDT-SWAP.1h.trending_tech_weight": 0.40,
            },
            "confirm": True,
        },
    )

    assert resp.status_code == 200
    assert ("BTC-USDT-SWAP", "1h") not in app.state.regime_weight_signal_windows
    assert ("BTC-USDT-SWAP", "1h") not in app.state.regime_weight_overlays
```

- [ ] **Step 2: Run the API test and confirm it fails**

Run:

```bash
cd backend
docker exec krypton-api-1 python -m pytest tests/api/test_engine_apply.py -k "clears_online_overlay_state" -v
```

Expected: FAIL because `apply_parameters()` reloads `app.state.regime_weights` but does not clear the online overlay/window state

- [ ] **Step 3: Clear overlay/window state for touched baseline keys**

Update the imports near the top of `backend/app/api/engine.py`:

```python
from app.engine.regime_online import clear_runtime_state_for_key
```

Inside `apply_parameters()` in `backend/app/api/engine.py`, add a touched-key accumulator before the loop:

```python
            touched_regime_keys: set[tuple[str, str]] = set()

            for path, proposed in body.changes.items():
```

Inside the `elif path.startswith("regime_weights."):` branch, add:

```python
                        touched_regime_keys.add((pair, tf))
```

After the `app.state.regime_weights` reload block and before leaving the DB session, add:

```python
            if touched_regime_keys:
                overlays = getattr(app.state, "regime_weight_overlays", {})
                windows = getattr(app.state, "regime_weight_signal_windows", {})
                for key in touched_regime_keys:
                    clear_runtime_state_for_key(windows, overlays, key)
                    logger.info(
                        "Cleared regime weight overlay after baseline refresh for %s:%s",
                        key[0],
                        key[1],
                    )
```

- [ ] **Step 4: Run the targeted API tests**

Run:

```bash
cd backend
docker exec krypton-api-1 python -m pytest tests/api/test_engine_apply.py -v
```

Expected: PASS

- [ ] **Step 5: Commit the baseline-refresh clear behavior**

Run:

```bash
git add backend/app/api/engine.py backend/tests/api/test_engine_apply.py
git commit -m "feat(api): clear online regime overlay on baseline reload"
```

---

### Task 5: Final Verification

**Files:**
- Verify only

- [ ] **Step 1: Run the focused backend test slice**

Run:

```bash
cd backend
docker exec krypton-api-1 python -m pytest tests/engine/test_regime_online.py tests/engine/test_regime_pipeline.py tests/api/test_engine_apply.py -v
```

Expected: PASS

- [ ] **Step 2: Run the full backend suite**

Run:

```bash
cd backend
docker exec krypton-api-1 python -m pytest
```

Expected: PASS

- [ ] **Step 3: Restart the API and confirm replay rebuild logs**

Run:

```bash
cd backend
docker compose restart api
docker compose logs api --tail=80
```

Expected:
- A startup log line like `Loaded regime weights for`
- Either `Rebuilt regime weight overlays for` or a warning-free startup with zero overlays
- No traceback from `Failed to rebuild regime weight overlays`

- [ ] **Step 4: Re-run the baseline-refresh clearing API test after restart**

Run:

```bash
cd backend
docker exec krypton-api-1 python -m pytest tests/api/test_engine_apply.py -k "clears_online_overlay_state" -v
```

Expected: PASS

- [ ] **Step 5: Inspect startup replay cost and decide whether the query needs an index before calling the feature done**

Run:

```bash
cd backend
docker compose logs api --tail=80
```

Expected:
- The startup log should include `Rebuilt regime weight overlays for ... in ...ms`
- If replay remains fast on current data after SQL-side key filtering, stop here: v1 needs no schema change
- If replay is still slow or causes noticeable startup delay on current data, do not defer it to post-merge: add a small follow-up migration task in this branch for a composite `signals(pair, timeframe, outcome_at)` index and re-run verification before marking the feature complete
