"""LLM factor calibration: rolling-accuracy multipliers for factor weights."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.engine.risk import WIN_OUTCOMES

logger = logging.getLogger(__name__)

CALIBRATION_WINDOW_PAIR_MIN = 15
CALIBRATION_MIN_SAMPLES = 10
CALIBRATION_RAMP_LOW = 0.40
CALIBRATION_RAMP_HIGH = 0.55


def compute_multiplier(accuracy: float, *, floor: float = 0.5) -> float:
    """Smooth linear ramp: accuracy -> multiplier in [floor, 1.0]."""
    ramp_range = CALIBRATION_RAMP_HIGH - CALIBRATION_RAMP_LOW
    t = max(0.0, min(1.0, (accuracy - CALIBRATION_RAMP_LOW) / ramp_range))
    return t * (1.0 - floor) + floor


def apply_calibration(
    base_weights: dict[str, float],
    multipliers: dict[str, float],
) -> dict[str, float]:
    """Return base_weights scaled by per-factor multipliers."""
    return {k: v * multipliers.get(k, 1.0) for k, v in base_weights.items()}


@dataclass
class LLMCalibrationState:
    """In-memory calibration state rebuilt from DB on startup.

    Concurrency: multiplier dicts are rebuilt as a single tuple and
    assigned via one reference swap. The pipeline reads `_multipliers`
    atomically — it sees either the old or new tuple, never a mix.
    """

    window: int = 30
    floor: float = 0.5
    _records: list[dict] = field(default_factory=list)
    _signal_ids_ordered: list[int] = field(default_factory=list)
    _multipliers: tuple[dict[str, float], dict[str, dict[str, float]]] = field(
        default_factory=lambda: ({}, {})
    )

    def load_records(self, rows: list[dict]) -> None:
        """Bulk-load records from DB query results. Called once at startup."""
        self._records = list(rows)
        seen: dict[int, None] = {}
        for r in self._records:
            seen.setdefault(r["signal_id"], None)
        self._signal_ids_ordered = list(seen.keys())
        self._rebuild_multipliers()

    def record_outcomes(
        self,
        signal_id: int,
        pair: str,
        outcomes: list[dict],
    ) -> None:
        """Append new factor outcomes after signal resolution, trim window, rebuild."""
        self._append_outcomes(signal_id, pair, outcomes)
        self._trim_window()
        self._rebuild_multipliers()

    def record_outcomes_batch(
        self,
        batch: list[tuple[int, str, list[dict]]],
    ) -> None:
        """Append outcomes for multiple signals, then trim and rebuild once."""
        for signal_id, pair, outcomes in batch:
            self._append_outcomes(signal_id, pair, outcomes)
        self._trim_window()
        self._rebuild_multipliers()

    def _append_outcomes(self, signal_id: int, pair: str, outcomes: list[dict]) -> None:
        for o in outcomes:
            self._records.append({
                "signal_id": signal_id,
                "pair": pair,
                "factor_type": o["factor_type"],
                "direction": o["direction"],
                "strength": o["strength"],
                "correct": o["correct"],
                "resolved_at": o["resolved_at"],
            })
        if not self._signal_ids_ordered or self._signal_ids_ordered[-1] != signal_id:
            self._signal_ids_ordered.append(signal_id)

    def get_multipliers(self, pair: str) -> dict[str, float]:
        """Return factor_type -> multiplier dict for a pair.

        Uses per-pair accuracy where sufficient samples exist,
        falls back to global accuracy.
        """
        global_mults, pair_mults = self._multipliers
        result = dict(global_mults)
        result.update(pair_mults.get(pair, {}))
        return result

    def _trim_window(self) -> None:
        """Keep only records from the most recent `window` signals."""
        if len(self._signal_ids_ordered) <= self.window:
            return
        keep_ids = set(self._signal_ids_ordered[-self.window:])
        self._signal_ids_ordered = self._signal_ids_ordered[-self.window:]
        self._records = [r for r in self._records if r["signal_id"] in keep_ids]

    def _rebuild_multipliers(self) -> None:
        """Recompute global and per-pair multiplier dicts via atomic swap."""
        windowed = self._records

        global_counts: dict[str, list[bool]] = {}
        pair_counts: dict[str, dict[str, list[bool]]] = {}

        for r in windowed:
            global_counts.setdefault(r["factor_type"], []).append(r["correct"])
            pair_counts.setdefault(r["pair"], {}).setdefault(r["factor_type"], []).append(r["correct"])

        new_global: dict[str, float] = {}
        for ft, outcomes in global_counts.items():
            if len(outcomes) < CALIBRATION_MIN_SAMPLES:
                continue
            accuracy = sum(outcomes) / len(outcomes)
            new_global[ft] = compute_multiplier(accuracy, floor=self.floor)

        new_pair: dict[str, dict[str, float]] = {}
        for p, ft_map in pair_counts.items():
            for ft, outcomes in ft_map.items():
                if len(outcomes) < CALIBRATION_WINDOW_PAIR_MIN:
                    continue
                if ft not in new_global:
                    continue
                accuracy = sum(outcomes) / len(outcomes)
                new_pair.setdefault(p, {})[ft] = compute_multiplier(accuracy, floor=self.floor)

        # single atomic swap — readers see old or new, never mixed
        self._multipliers = (new_global, new_pair)

    def update_config(self, window: int | None = None, floor: float | None = None) -> None:
        """Update tunable params and rebuild multipliers."""
        changed = False
        if window is not None and window != self.window:
            self.window = window
            self._trim_window()
            changed = True
        if floor is not None and floor != self.floor:
            self.floor = floor
            changed = True
        if changed:
            self._rebuild_multipliers()


def compute_factor_correctness(
    factor_direction: str,
    signal_direction: str,
    outcome: str,
) -> bool:
    """Determine if an LLM factor's prediction was correct.

    Correct when:
    - Signal won AND factor is bullish on LONG / bearish on SHORT
    - Signal lost AND factor is bearish on LONG / bullish on SHORT
    """
    is_win = outcome in WIN_OUTCOMES
    agrees = (
        (signal_direction == "LONG" and factor_direction == "bullish")
        or (signal_direction == "SHORT" and factor_direction == "bearish")
    )
    return agrees if is_win else not agrees
