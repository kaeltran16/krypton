import asyncio
import bisect
import logging
import statistics
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import BacktestRun, Candle, PerformanceTrackerRow, Signal
from app.engine.outcome_resolver import resolve_signal_outcome

logger = logging.getLogger(__name__)

from app.engine.constants import LEVEL_DEFAULTS, PERFORMANCE_TRACKER

_atr = LEVEL_DEFAULTS["atr_defaults"]
DEFAULT_SL = _atr["sl"]
DEFAULT_TP1 = _atr["tp1"]
DEFAULT_TP2 = _atr["tp2"]

_opt = PERFORMANCE_TRACKER["optimization_params"]
MIN_SIGNALS = _opt["min_signals"]
WINDOW_SIZE = _opt["window_size"]
TRIGGER_INTERVAL = _opt["trigger_interval"]

_guard = PERFORMANCE_TRACKER["guardrails"]
SL_RANGE = tuple(_guard["sl_range"])
TP1_RANGE = tuple(_guard["tp1_range"])
TP2_RANGE = tuple(_guard["tp2_range"])
MAX_SL_ADJ = _guard["max_sl_adj"]
MAX_TP_ADJ = _guard["max_tp_adj"]


class PerformanceTracker:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self._tasks: set[asyncio.Task] = set()
        self._cache: dict[tuple[str, str], tuple[float, float, float]] = {}

    async def get_multipliers(self, pair: str, timeframe: str) -> tuple[float, float, float]:
        """Return learned (sl, tp1, tp2) multipliers from in-memory cache."""
        return self._cache.get((pair, timeframe), (DEFAULT_SL, DEFAULT_TP1, DEFAULT_TP2))

    async def reload_cache(self):
        """Refresh the in-memory cache from DB. Called after optimize/bootstrap."""
        async with self.session_factory() as session:
            result = await session.execute(select(PerformanceTrackerRow))
            rows = result.scalars().all()
            self._cache = {
                (r.pair, r.timeframe): (r.current_sl_atr, r.current_tp1_atr, r.current_tp2_atr)
                for r in rows
            }

    async def _get_resolved_count(self, session, pair: str, timeframe: str) -> int:
        """Count resolved signals excluding LLM-leveled ones (NULL treated as atr_default)."""
        result = await session.execute(
            select(func.count(Signal.id)).where(
                Signal.pair == pair,
                Signal.timeframe == timeframe,
                Signal.outcome != "PENDING",
                func.coalesce(
                    Signal.raw_indicators["levels_source"].astext, "atr_default"
                ) != "llm",
            )
        )
        return result.scalar_one()

    @staticmethod
    def compute_sortino(pnls: list[float]) -> float | None:
        """Compute Sortino ratio from a list of PnL percentages.

        Edge cases per spec:
        - All winners (no downside): return inf
        - Single loss: use abs(loss) as downside deviation
        - Empty: return None
        """
        if not pnls:
            return None
        downside = [p for p in pnls if p < 0]
        if not downside:
            return float("inf")
        mean_r = statistics.mean(pnls)
        downside_std = (
            statistics.stdev(downside) if len(downside) > 1 else abs(downside[0])
        )
        if downside_std == 0:
            return None
        return mean_r / downside_std

    @staticmethod
    def replay_signal(
        direction: str,
        entry: float,
        atr: float,
        sl_atr: float,
        tp1_atr: float,
        tp2_atr: float,
        candles: list[dict],
        created_at: datetime,
    ) -> dict | None:
        """Replay a signal with given ATR multipliers against candle data.

        Constructs price levels from multipliers, then delegates to
        resolve_signal_outcome for deterministic replay.
        Returns outcome dict or None if no level hit (expired).
        """
        sign = 1 if direction == "LONG" else -1
        signal_dict = {
            "direction": direction,
            "entry": entry,
            "stop_loss": entry - sign * sl_atr * atr,
            "take_profit_1": entry + sign * tp1_atr * atr,
            "take_profit_2": entry + sign * tp2_atr * atr,
            "created_at": created_at,
        }
        return resolve_signal_outcome(signal_dict, candles)

    @staticmethod
    def _apply_guardrails(old: float, new: float, bounds: tuple[float, float], max_adj: float) -> float:
        """Clamp new value to absolute bounds and max per-cycle adjustment."""
        clamped = max(bounds[0], min(new, bounds[1]))
        delta = clamped - old
        if abs(delta) > max_adj:
            clamped = old + max_adj * (1 if delta > 0 else -1)
        return round(clamped, 2)

    @staticmethod
    def _sweep_dimension(
        signals_data: list[dict],
        candles_map: dict[int, list[dict]],
        dimension: str,
        candidates: list[float],
    ) -> dict[float, float | None]:
        """Sweep one dimension across candidates, return {candidate: sortino}.

        For the swept dimension, computes candidate_base * strength * vol_factor.
        For other dimensions, uses stored effective values as-is.
        This intentionally evaluates "what if we changed X while keeping Y and Z
        exactly as deployed?" — the correct counterfactual for 1D optimization.
        """
        results: dict[float, float | None] = {}

        for candidate in candidates:
            pnls = []
            for idx, sig in enumerate(signals_data):
                candles = candles_map.get(idx, [])
                if not candles:
                    continue  # skip signals with no candle data

                # For the swept dimension: candidate * strength * vol
                # For other dimensions: use stored effective values
                if dimension == "sl":
                    sl = candidate * sig["sl_strength_factor"] * sig["vol_factor"]
                    tp1 = sig["effective_tp1_atr"]
                    tp2 = sig["effective_tp2_atr"]
                elif dimension == "tp1":
                    sl = sig["effective_sl_atr"]
                    tp1 = candidate * sig["tp_strength_factor"] * sig["vol_factor"]
                    tp2 = sig["effective_tp2_atr"]
                else:  # tp2
                    sl = sig["effective_sl_atr"]
                    tp1 = sig["effective_tp1_atr"]
                    tp2 = candidate * sig["tp_strength_factor"] * sig["vol_factor"]

                result = PerformanceTracker.replay_signal(
                    direction=sig["direction"],
                    entry=sig["entry"],
                    atr=sig["atr"],
                    sl_atr=sl, tp1_atr=tp1, tp2_atr=tp2,
                    candles=candles,
                    created_at=sig["created_at"],
                )
                if result is None:
                    continue  # no level hit (expired) — exclude from Sortino
                pnls.append(result["outcome_pnl_pct"])

            results[candidate] = PerformanceTracker.compute_sortino(pnls)

        return results

    def _gp_objective(self, params, signals, candles_map):
        """Objective function for GP optimizer. Returns value to minimize.

        signals: list of signal dicts (same schema as signals_data in optimize())
        candles_map: dict mapping signal index to candle list (same as optimize())
        """
        sl_atr, tp1_atr, tp2_atr = params

        if tp1_atr < sl_atr or tp2_atr < tp1_atr * 1.2:
            return 999.0

        pnls = []
        for idx, sig in enumerate(signals):
            candles = candles_map.get(idx, [])
            if not candles:
                continue
            # Apply per-signal strength/vol factors (same as sweep path)
            sl = sl_atr * sig["sl_strength_factor"] * sig["vol_factor"]
            tp1 = tp1_atr * sig["tp_strength_factor"] * sig["vol_factor"]
            tp2 = tp2_atr * sig["tp_strength_factor"] * sig["vol_factor"]
            result = self.replay_signal(
                direction=sig["direction"],
                entry=sig["entry"],
                atr=sig["atr"],
                sl_atr=sl,
                tp1_atr=tp1,
                tp2_atr=tp2,
                candles=candles,
                created_at=sig["created_at"],
            )
            if result is not None:
                pnls.append(result["outcome_pnl_pct"])

        sortino = self.compute_sortino(pnls)
        if sortino is None:
            return 0.0
        if sortino == float("inf"):
            return -999.0
        return -sortino

    def _gp_optimize(self, signals, candles_map, current_sl, current_tp1, current_tp2):
        """Run GP-based 3D joint optimization of SL/TP1/TP2 ATR multipliers.

        signals: list of signal dicts (same schema as signals_data in optimize())
        candles_map: dict mapping signal index to candle list (same as optimize())
        Returns (sl, tp1, tp2) tuple or None on failure (triggers sweep fallback).
        """
        try:
            from skopt import gp_minimize
            from skopt.space import Real
        except ImportError:
            logger.warning("scikit-optimize not installed, falling back to sweep")
            return None

        space = [
            Real(SL_RANGE[0], SL_RANGE[1], name="sl_atr"),
            Real(TP1_RANGE[0], TP1_RANGE[1], name="tp1_atr"),
            Real(TP2_RANGE[0], TP2_RANGE[1], name="tp2_atr"),
        ]

        def objective(params):
            return self._gp_objective(params, signals, candles_map)

        try:
            result = gp_minimize(
                func=objective,
                dimensions=space,
                x0=[current_sl, current_tp1, current_tp2],
                n_calls=40,
                n_initial_points=8,
                acq_func="EI",
                random_state=42,
            )
            best_sl, best_tp1, best_tp2 = result.x
            best_sortino = -result.fun if result.fun not in (0.0, -999.0) else 0.0
            logger.info(
                f"GP optimizer: best_sortino={best_sortino:.3f}, "
                f"params=({best_sl:.2f}, {best_tp1:.2f}, {best_tp2:.2f}), "
                f"n_calls={len(result.func_vals)}"
            )
            return best_sl, best_tp1, best_tp2
        except Exception as e:
            logger.error(f"GP optimization failed: {e}, falling back to sweep")
            return None

    async def optimize(self, pair: str, timeframe: str, dry_run: bool = False, settings=None):
        """Run 1D optimization for each multiplier dimension.

        Fetches the rolling window of resolved signals, batch-loads candles,
        validates data integrity, sweeps candidates, and applies guardrailed updates.
        When dry_run=True, returns proposed values without persisting.
        """
        async with self.session_factory() as session:
            # Fetch tracker row
            result = await session.execute(
                select(PerformanceTrackerRow).where(
                    PerformanceTrackerRow.pair == pair,
                    PerformanceTrackerRow.timeframe == timeframe,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return

            # Fetch last N resolved signals (excluding LLM)
            sig_result = await session.execute(
                select(Signal)
                .where(
                    Signal.pair == pair,
                    Signal.timeframe == timeframe,
                    Signal.outcome != "PENDING",
                    func.coalesce(
                        Signal.raw_indicators["levels_source"].astext, "atr_default"
                    ) != "llm",
                )
                .order_by(Signal.created_at.desc())
                .limit(WINDOW_SIZE)
            )
            signals = sig_result.scalars().all()

            if len(signals) < MIN_SIGNALS:
                return

            # Batch fetch candles for the entire time range
            min_created = min(s.created_at for s in signals)
            max_outcome = max(
                s.outcome_at for s in signals if s.outcome_at is not None
            )
            candle_result = await session.execute(
                select(Candle)
                .where(
                    Candle.pair == pair,
                    Candle.timeframe == timeframe,
                    Candle.timestamp > min_created,
                    Candle.timestamp <= max_outcome,
                )
                .order_by(Candle.timestamp)
            )
            all_candles = candle_result.scalars().all()

            # Pre-build sorted candle dicts + timestamp index for bisect slicing
            candle_dicts = [
                {"high": float(c.high), "low": float(c.low), "timestamp": c.timestamp}
                for c in all_candles
            ]
            candle_timestamps = [c["timestamp"] for c in candle_dicts]

            # Build per-signal candle lists + signal data dicts
            signals_data = []
            candles_map = {}
            valid_idx = 0

            for signal in signals:
                if signal.outcome_at is None:
                    continue

                indicators = signal.raw_indicators or {}
                atr = indicators.get("atr")
                if atr is None or atr == 0:
                    continue

                entry = float(signal.entry)

                # Bisect for O(log N) candle slicing instead of O(N) linear scan
                lo = bisect.bisect_right(candle_timestamps, signal.created_at)
                hi = bisect.bisect_right(candle_timestamps, signal.outcome_at)
                sig_candles = candle_dicts[lo:hi]

                # Data integrity check: replay with stored levels must match stored outcome.
                # If candles are incomplete, skip this signal.
                integrity_result = resolve_signal_outcome(
                    {
                        "direction": signal.direction,
                        "entry": entry,
                        "stop_loss": float(signal.stop_loss),
                        "take_profit_1": float(signal.take_profit_1),
                        "take_profit_2": float(signal.take_profit_2),
                        "created_at": signal.created_at,
                    },
                    sig_candles,
                )
                actual_outcome = signal.outcome
                replayed_outcome = integrity_result["outcome"] if integrity_result else "EXPIRED"
                if replayed_outcome != actual_outcome:
                    continue

                # Extract Phase 1 factors (legacy signals without them use 1.0)
                sl_strength = indicators.get("sl_strength_factor", 1.0)
                tp_strength = indicators.get("tp_strength_factor", 1.0)
                vol_factor = indicators.get("vol_factor", 1.0)

                # Effective multipliers: stored if available, else back-derive from prices
                effective_sl = indicators.get("effective_sl_atr")
                effective_tp1 = indicators.get("effective_tp1_atr")
                effective_tp2 = indicators.get("effective_tp2_atr")
                if effective_sl is None:
                    effective_sl = abs(entry - float(signal.stop_loss)) / atr
                    effective_tp1 = abs(float(signal.take_profit_1) - entry) / atr
                    effective_tp2 = abs(float(signal.take_profit_2) - entry) / atr

                signals_data.append({
                    "direction": signal.direction,
                    "entry": entry,
                    "atr": atr,
                    "effective_sl_atr": effective_sl,
                    "effective_tp1_atr": effective_tp1,
                    "effective_tp2_atr": effective_tp2,
                    "sl_strength_factor": sl_strength,
                    "tp_strength_factor": tp_strength,
                    "vol_factor": vol_factor,
                    "created_at": signal.created_at,
                    "outcome_at": signal.outcome_at,
                    "outcome": signal.outcome,
                })
                candles_map[valid_idx] = sig_candles
                valid_idx += 1

            if len(signals_data) < MIN_SIGNALS:
                logger.info(
                    "Optimization skipped for %s/%s: only %d valid signals (need %d)",
                    pair, timeframe, len(signals_data), MIN_SIGNALS,
                )
                return

            # Sweep each dimension independently
            # Include current value in candidates so sweep can select "keep current"
            sl_candidates = [round(x * 0.1, 1) for x in range(8, 26, 2)] + [2.5]  # 0.8 to 2.5
            tp1_candidates = [round(x * 0.1, 1) for x in range(10, 41, 5)]  # 1.0 to 4.0 step 0.5
            tp2_candidates = [round(x * 0.1, 1) for x in range(20, 61, 5)]  # 2.0 to 6.0 step 0.5

            current_sl = row.current_sl_atr
            current_tp1 = row.current_tp1_atr
            current_tp2 = row.current_tp2_atr

            # -- Try GP optimization if configured --
            gp_result = None
            if settings is not None and settings.atr_optimizer_mode == "gp":
                loop = asyncio.get_running_loop()
                gp_result = await loop.run_in_executor(
                    None, self._gp_optimize,
                    signals_data, candles_map, current_sl, current_tp1, current_tp2,
                )

            if gp_result is not None:
                gp_sl, gp_tp1, gp_tp2 = gp_result
                # Apply same guardrails as sweep path
                gp_sl = self._apply_guardrails(current_sl, gp_sl, SL_RANGE, MAX_SL_ADJ)
                gp_tp1 = self._apply_guardrails(current_tp1, gp_tp1, TP1_RANGE, MAX_TP_ADJ)
                gp_tp2 = self._apply_guardrails(current_tp2, gp_tp2, TP2_RANGE, MAX_TP_ADJ)

                adjustments = []
                if gp_sl != current_sl:
                    adjustments.append({"dimension": "sl", "old": current_sl, "new": gp_sl, "sortino": None, "clamped": gp_sl != gp_result[0]})
                if gp_tp1 != current_tp1:
                    adjustments.append({"dimension": "tp1", "old": current_tp1, "new": gp_tp1, "sortino": None, "clamped": gp_tp1 != gp_result[1]})
                if gp_tp2 != current_tp2:
                    adjustments.append({"dimension": "tp2", "old": current_tp2, "new": gp_tp2, "sortino": None, "clamped": gp_tp2 != gp_result[2]})
            else:
                adjustments = []

                for dim, candidates, current, bounds, max_adj in [
                    ("sl", sl_candidates, current_sl, SL_RANGE, MAX_SL_ADJ),
                    ("tp1", tp1_candidates, current_tp1, TP1_RANGE, MAX_TP_ADJ),
                    ("tp2", tp2_candidates, current_tp2, TP2_RANGE, MAX_TP_ADJ),
                ]:
                    # Ensure current value is in candidate list for fair comparison
                    current_rounded = round(current, 1)
                    if current_rounded not in candidates:
                        candidates = sorted(candidates + [current_rounded])

                    sweep_results = self._sweep_dimension(
                        signals_data, candles_map, dim, candidates,
                    )
                    # Find best candidate
                    scored = [(v, s) for v, s in sweep_results.items() if s is not None]
                    if not scored:
                        continue
                    best_val, best_sortino = max(scored, key=lambda x: x[1])
                    if round(best_val, 2) == round(current, 2):
                        continue
                    # Only apply if best candidate actually improves over current
                    current_sortino = sweep_results.get(current_rounded)
                    if current_sortino is not None and best_sortino <= current_sortino:
                        continue
                    new_val = self._apply_guardrails(current, best_val, bounds, max_adj)
                    if new_val != current:
                        adjustments.append({
                            "dimension": dim, "old": current, "new": new_val,
                            "sortino": best_sortino,
                            "clamped": new_val != best_val,
                        })

            if not adjustments:
                logger.info("Optimization for %s/%s: no changes", pair, timeframe)
                if dry_run:
                    return {
                        "sl_atr": row.current_sl_atr,
                        "tp1_atr": row.current_tp1_atr,
                        "tp2_atr": row.current_tp2_atr,
                        "signals_analyzed": len(signals_data),
                        "current_sortino": None,
                        "proposed_sortino": None,
                    }
                return

            # Compute proposed values
            best_sl = row.current_sl_atr
            best_tp1 = row.current_tp1_atr
            best_tp2 = row.current_tp2_atr
            best_sortino = None
            for adj in adjustments:
                if adj["dimension"] == "sl":
                    best_sl = adj["new"]
                elif adj["dimension"] == "tp1":
                    best_tp1 = adj["new"]
                elif adj["dimension"] == "tp2":
                    best_tp2 = adj["new"]
                best_sortino = adj["sortino"]

            if dry_run:
                # Compute current sortino for comparison
                current_pnls = []
                for idx, sig in enumerate(signals_data):
                    sig_candles = candles_map.get(idx, [])
                    if not sig_candles:
                        continue
                    result = self.replay_signal(
                        direction=sig["direction"], entry=sig["entry"], atr=sig["atr"],
                        sl_atr=sig["effective_sl_atr"], tp1_atr=sig["effective_tp1_atr"],
                        tp2_atr=sig["effective_tp2_atr"], candles=sig_candles,
                        created_at=sig["created_at"],
                    )
                    if result:
                        current_pnls.append(result["outcome_pnl_pct"])
                current_sortino = self.compute_sortino(current_pnls)
                return {
                    "sl_atr": best_sl,
                    "tp1_atr": best_tp1,
                    "tp2_atr": best_tp2,
                    "signals_analyzed": len(signals_data),
                    "current_sortino": current_sortino,
                    "proposed_sortino": best_sortino,
                }

        # Apply adjustments in a fresh session
        async with self.session_factory() as session:
            result = await session.execute(
                select(PerformanceTrackerRow).where(
                    PerformanceTrackerRow.pair == pair,
                    PerformanceTrackerRow.timeframe == timeframe,
                )
            )
            row = result.scalar_one()

            for adj in adjustments:
                if adj["dimension"] == "sl":
                    row.current_sl_atr = adj["new"]
                elif adj["dimension"] == "tp1":
                    row.current_tp1_atr = adj["new"]
                elif adj["dimension"] == "tp2":
                    row.current_tp2_atr = adj["new"]

            # Enforce R:R floor: tp1 >= sl * 1.0
            if row.current_tp1_atr < row.current_sl_atr:
                row.current_tp1_atr = row.current_sl_atr

            row.last_optimized_at = datetime.now(timezone.utc)
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()

            for adj in adjustments:
                logger.info(
                    "Tuning %s/%s %s: %.2f → %.2f (Sortino=%.3f%s)",
                    pair, timeframe, adj["dimension"].upper(),
                    adj["old"], adj["new"], adj["sortino"] if adj["sortino"] != float("inf") else 999,
                    " CLAMPED" if adj["clamped"] else "",
                )

            await self.reload_cache()

    async def check_optimization_triggers(self, session, resolved_pairs_timeframes: set[tuple[str, str]], settings=None):
        """After a batch of signals resolve, check if any buckets need optimization.

        Called once per check_pending_signals cycle (not per-signal) to avoid race conditions.
        Updates last_optimized_count and commits before scheduling async optimization.
        """
        for pair, timeframe in resolved_pairs_timeframes:
            count = await self._get_resolved_count(session, pair, timeframe)
            if count < MIN_SIGNALS:
                continue

            # Get or create tracker row
            result = await session.execute(
                select(PerformanceTrackerRow).where(
                    PerformanceTrackerRow.pair == pair,
                    PerformanceTrackerRow.timeframe == timeframe,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = PerformanceTrackerRow(pair=pair, timeframe=timeframe)
                session.add(row)
                await session.flush()

            if (count - row.last_optimized_count) >= TRIGGER_INTERVAL:
                row.last_optimized_count = count
                row.updated_at = datetime.now(timezone.utc)
                await session.commit()

                # Schedule optimization with reference tracking to prevent GC
                task = asyncio.create_task(self._optimize_safe(pair, timeframe, settings=settings))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _optimize_safe(self, pair: str, timeframe: str, settings=None):
        """Wrapper that catches and logs optimization failures."""
        try:
            await self.optimize(pair, timeframe, settings=settings)
        except Exception:
            logger.exception("Optimization failed for %s/%s", pair, timeframe)

    async def bootstrap_from_backtests(self):
        """Seed tracker rows from best completed backtests per pair/timeframe.

        Reads ATR multiplier config from the best completed backtest (by profit factor)
        for each unique pair/timeframe. Does not re-optimize — just copies starting values.
        Logs which pair/timeframes had no backtest data and were left at defaults.
        """
        async with self.session_factory() as session:
            # Get all completed backtests ordered by profit factor
            result = await session.execute(
                select(BacktestRun)
                .where(BacktestRun.status == "completed")
                .order_by(BacktestRun.created_at.desc())
            )
            runs = result.scalars().all()

            # Find best run per (pair, timeframe) by profit factor
            best_per_bucket: dict[tuple[str, str], BacktestRun] = {}
            for run in runs:
                pf = (run.results or {}).get("stats", {}).get("profit_factor") or 0
                for p in run.pairs:
                    key = (p, run.timeframe)
                    existing_pf = (
                        (best_per_bucket[key].results or {}).get("stats", {}).get("profit_factor") or 0
                        if key in best_per_bucket
                        else 0
                    )
                    if pf > existing_pf:
                        best_per_bucket[key] = run

            # Batch-fetch existing tracker rows to avoid N+1 queries
            existing_result = await session.execute(select(PerformanceTrackerRow))
            existing_keys = {
                (r.pair, r.timeframe) for r in existing_result.scalars().all()
            }

            seeded = []

            for (pair, timeframe), run in best_per_bucket.items():
                if (pair, timeframe) in existing_keys:
                    continue

                config = run.config or {}
                sl = config.get("sl_atr_multiplier", DEFAULT_SL)
                tp1 = config.get("tp1_atr_multiplier", DEFAULT_TP1)
                tp2 = config.get("tp2_atr_multiplier", DEFAULT_TP2)

                session.add(PerformanceTrackerRow(
                    pair=pair,
                    timeframe=timeframe,
                    current_sl_atr=sl,
                    current_tp1_atr=tp1,
                    current_tp2_atr=tp2,
                ))
                seeded.append(f"{pair}/{timeframe}")

            await session.commit()

            if seeded:
                logger.info("Bootstrap seeded tracker for: %s", ", ".join(seeded))
            else:
                logger.info("Bootstrap: no new pair/timeframe buckets to seed")

        await self.reload_cache()
