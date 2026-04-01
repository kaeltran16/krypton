"""Replay-derived online regime outer-weight adaptation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.engine.regime import DEFAULT_OUTER_WEIGHTS, OUTER_KEYS, REGIMES, blend_outer_weights

logger = logging.getLogger(__name__)

WINDOW_DAYS = 14
MIN_WINDOW_SIGNALS = 20
MAX_WINDOW_SIGNALS = 100
BASE_LR = 0.01
OVERLAY_DELTA_MIN = -0.12
OVERLAY_DELTA_MAX = 0.12
EFFECTIVE_WEIGHT_FLOOR = 0.02
EFFECTIVE_WEIGHT_CEILING = 0.50
ONLINE_ELIGIBLE_OUTCOMES = frozenset(
    {
        "TP1_HIT",
        "TP2_HIT",
        "TP1_TRAIL",
        "TP1_TP2",
        "SL_HIT",
        "EXPIRED",
    }
)
ONLINE_WIN_OUTCOMES = frozenset({"TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2"})


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _extract_outer_weight_table(regime_weights) -> dict[str, dict[str, float]]:
    if regime_weights is None:
        return {regime: dict(weights) for regime, weights in DEFAULT_OUTER_WEIGHTS.items()}

    return {
        regime: {
            source: float(
                getattr(
                    regime_weights,
                    f"{regime}_{source}_weight",
                    DEFAULT_OUTER_WEIGHTS[regime][source],
                )
            )
            for source in OUTER_KEYS
        }
        for regime in REGIMES
    }


def _normalize_regime_mix(regime_mix: dict | None) -> dict[str, float] | None:
    if not regime_mix:
        return None

    normalized = {regime: float(regime_mix.get(regime, 0.0) or 0.0) for regime in REGIMES}
    total = sum(normalized.values())
    if total <= 0:
        return None
    return {regime: value / total for regime, value in normalized.items()}


def _normalize_row_with_bounds(row: dict[str, float]) -> dict[str, float]:
    low = min(value - EFFECTIVE_WEIGHT_CEILING for value in row.values()) - 1.0
    high = max(value - EFFECTIVE_WEIGHT_FLOOR for value in row.values()) + 1.0

    for _ in range(80):
        mid = (low + high) / 2
        total = sum(
            _clamp(value - mid, EFFECTIVE_WEIGHT_FLOOR, EFFECTIVE_WEIGHT_CEILING)
            for value in row.values()
        )
        if abs(total - 1.0) < 1e-9:
            high = mid
            break
        if total > 1.0:
            low = mid
        else:
            high = mid

    return {
        source: _clamp(value - high, EFFECTIVE_WEIGHT_FLOOR, EFFECTIVE_WEIGHT_CEILING)
        for source, value in row.items()
    }


def _is_overlay_active(overlay_state: dict | None) -> bool:
    if not overlay_state:
        return False
    return int(overlay_state.get("eligible_count", 0) or 0) >= MIN_WINDOW_SIGNALS


def empty_overlay() -> dict:
    overlay = {regime: {source: 0.0 for source in OUTER_KEYS} for regime in REGIMES}
    overlay["eligible_count"] = 0
    overlay["window_oldest_outcome_at"] = None
    overlay["window_newest_outcome_at"] = None
    overlay["rebuilt_at"] = None
    return overlay


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

    outcome_at = _coerce_datetime(signal.get("outcome_at"))
    if outcome_at is None:
        return None, "missing_outcome_at"

    raw = signal.get("raw_indicators") or {}
    snapshot = signal.get("engine_snapshot") or {}
    regime_mix = _normalize_regime_mix(snapshot.get("regime_mix"))
    if regime_mix is None:
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

    return (
        {
            "id": int(signal["id"]),
            "pair": signal["pair"],
            "timeframe": signal["timeframe"],
            "direction": signal["direction"],
            "outcome": outcome,
            "outcome_at": outcome_at,
            "created_at": _coerce_datetime(signal.get("created_at")),
            "scores": scores,
            "confidences": confidences,
            "regime_mix": regime_mix,
        },
        None,
    )


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
    eligible = [
        record
        for record in records
        if (outcome_at := _coerce_datetime(record.get("outcome_at"))) is not None
        and outcome_at >= cutoff
    ]
    eligible.sort(key=lambda item: (_coerce_datetime(item["outcome_at"]), item["id"]))
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
    history: list[dict],
    *,
    now: datetime | None = None,
    allowed_keys: set[tuple[str, str]] | None = None,
    logger=None,
) -> tuple[dict[tuple[str, str], list[dict]], dict[tuple[str, str], dict]]:
    grouped: dict[tuple[str, str], list[dict]] = {}

    for signal in history:
        record, reason = signal_to_online_record(signal)
        if record is None:
            if logger is not None:
                logger.warning("Skipping online overlay signal: %s", reason)
            continue

        key = (record["pair"], record["timeframe"])
        if allowed_keys is not None and key not in allowed_keys:
            continue

        grouped.setdefault(key, []).append(record)

    windows = {}
    overlays = {}
    for key, records in grouped.items():
        retained = trim_retained_window(records, now=now)
        windows[key] = retained
        overlay_state = build_overlay_state_from_records(retained, now=now)
        if overlay_state is not None:
            overlays[key] = overlay_state
    return windows, overlays


def apply_resolved_signals_batch(
    history: list[dict],
    current_windows: dict[tuple[str, str], list[dict]],
    *,
    now: datetime | None = None,
    allowed_keys: set[tuple[str, str]] | None = None,
    logger=None,
) -> tuple[dict[tuple[str, str], list[dict]], dict[tuple[str, str], dict]]:
    windows = {key: list(records) for key, records in current_windows.items()}

    for signal in history:
        record, reason = signal_to_online_record(signal)
        if record is None:
            if logger is not None:
                logger.warning("Skipping online overlay signal batch item: %s", reason)
            continue

        key = (record["pair"], record["timeframe"])
        if allowed_keys is not None and key not in allowed_keys:
            continue

        windows.setdefault(key, []).append(record)

    overlays = {}
    for key, records in windows.items():
        retained = trim_retained_window(records, now=now)
        windows[key] = retained
        overlay_state = build_overlay_state_from_records(retained, now=now)
        if overlay_state is not None:
            overlays[key] = overlay_state
    return windows, overlays


def resolve_effective_outer_weight_rows(regime_weights, overlay_state: dict | None) -> dict[str, dict[str, float]]:
    baseline_rows = _extract_outer_weight_table(regime_weights)
    if not _is_overlay_active(overlay_state):
        return baseline_rows

    resolved = {}
    for regime in REGIMES:
        adjusted = {
            source: baseline_rows[regime][source] + float(overlay_state[regime][source])
            for source in OUTER_KEYS
        }
        resolved[regime] = _normalize_row_with_bounds(adjusted)
    return resolved


def resolve_effective_outer_weights(
    regime: dict,
    regime_weights=None,
    overlay_state: dict | None = None,
) -> dict[str, float]:
    if not _is_overlay_active(overlay_state):
        return blend_outer_weights(regime, regime_weights)

    rows = resolve_effective_outer_weight_rows(regime_weights, overlay_state)
    return {
        source: sum(regime[reg] * rows[reg][source] for reg in REGIMES)
        for source in OUTER_KEYS
    }


def clear_runtime_state_for_key(
    windows: dict[tuple[str, str], list[dict]],
    overlays: dict[tuple[str, str], dict],
    key: tuple[str, str],
) -> None:
    windows.pop(key, None)
    overlays.pop(key, None)
