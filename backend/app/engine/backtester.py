"""Backtesting strategy runner — replays historical candles through the scoring pipeline."""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from collections import deque
from types import SimpleNamespace

from app.engine.traditional import compute_technical_score, score_order_flow
from app.engine.patterns import detect_candlestick_patterns, compute_pattern_score
from app.engine.combiner import compute_preliminary_score, blend_with_ml, calculate_levels, scale_atr_multipliers
from app.engine.confluence import compute_confluence_score, TIMEFRAME_ANCESTORS
from app.engine.constants import PATTERN_STRENGTHS, PATTERN_BOOST_DEFAULTS, ORDER_FLOW, ORDER_FLOW_ASSET_SCALES
from app.engine.regime import blend_outer_weights

logger = logging.getLogger(__name__)

MIN_CANDLES = 70  # minimum candles for reliable indicators

_SIGMOID_KEYS = frozenset({
    "trend_strength_center", "trend_strength_steepness",
    "vol_expansion_center", "vol_expansion_steepness",
    "trend_score_steepness", "obv_slope_steepness",
    "volume_ratio_steepness",
    "mean_rev_rsi_steepness", "mean_rev_bb_pos_steepness",
    "squeeze_steepness", "mean_rev_blend_ratio",
})


def precompute_parent_indicators(parent_candles: list[dict]) -> tuple[list[str], list[dict]]:
    """Pre-compute enriched indicators for each parent candle.

    Returns (sorted_timestamps, indicators_list) for bisect lookup.
    Payload matches the enriched Redis cache shape used by live pipeline.
    """
    if len(parent_candles) < MIN_CANDLES:
        return [], []

    timestamps: list[str] = []
    indicators: list[dict] = []

    for i in range(MIN_CANDLES, len(parent_candles)):
        window = parent_candles[max(0, i - 199) : i + 1]
        df = pd.DataFrame(window)
        try:
            result = compute_technical_score(df)
            ts = parent_candles[i]["timestamp"]
            if isinstance(ts, datetime):
                ts = ts.isoformat()
            timestamps.append(ts)
            indicators.append({
                "trend_score": result["indicators"].get("trend_score", 0),
                "mean_rev_score": result["indicators"].get("mean_rev_score", 0),
                "trend_conviction": result["indicators"].get("trend_conviction", 0),
                "adx": result["indicators"]["adx"],
                "di_plus": result["indicators"]["di_plus"],
                "di_minus": result["indicators"]["di_minus"],
                "regime": result.get("regime", {}),
            })
        except Exception:
            continue

    return timestamps, indicators


def _lookup_parent_indicators(
    child_timestamp: str,
    parent_timestamps: list[str],
    parent_indicators: list[dict],
) -> dict | None:
    """Find the most recent parent snapshot at or before child_timestamp."""
    if not parent_timestamps:
        return None
    idx = bisect.bisect_right(parent_timestamps, child_timestamp) - 1
    if idx < 0:
        return None
    return parent_indicators[idx]


@dataclass
class BacktestConfig:
    # Backtester uses tech+pattern only (no flow/onchain), so weights differ from live pipeline
    signal_threshold: int = 40
    tech_weight: float = 0.75
    pattern_weight: float = 0.25
    enable_patterns: bool = True
    sl_atr_multiplier: float = 1.5
    tp1_atr_multiplier: float = 2.0
    tp2_atr_multiplier: float = 3.0
    risk_per_trade_pct: float = 1.0
    max_concurrent_positions: int = 3
    ml_confidence_threshold: float = 0.65  # minimum ML confidence to emit signal
    param_overrides: dict = field(default_factory=dict)
    flow_snapshots: list[dict] | None = None


@dataclass
class SimulatedTrade:
    pair: str
    direction: str
    entry_time: str
    entry_price: float
    sl: float
    tp1: float
    tp2: float
    score: int
    detected_patterns: list[dict] = field(default_factory=list)
    exit_time: str | None = None
    exit_price: float | None = None
    outcome: str = "OPEN"
    pnl_pct: float = 0.0
    duration_minutes: int = 0


def run_backtest(
    candles: list[dict],
    pair: str,
    config: BacktestConfig | None = None,
    cancel_flag: dict | None = None,
    ml_predictor=None,
    parent_candles: list[dict] | None = None,
    regime_weights=None,
    timeframe: str = "15m",
    parent_candles_by_tf: dict[str, list[dict]] | None = None,
) -> dict:
    """Run a backtest on historical candles for a single pair.

    Args:
        candles: Chronologically sorted list of candle dicts with
                 keys: timestamp, open, high, low, close, volume.
        pair: Instrument ID.
        config: Backtest parameters. Uses defaults if None.
        cancel_flag: Dict with key "cancelled" (bool) checked each iteration.
        parent_candles: Legacy single-parent candles (immediate parent only).
        parent_candles_by_tf: Multi-level parent candles keyed by timeframe.

    Returns:
        Dict with trades list and aggregate stats.
    """
    if config is None:
        config = BacktestConfig()

    # Pre-compute parent TF indicators for multi-level confluence scoring
    ancestors = TIMEFRAME_ANCESTORS.get(timeframe, [])
    precomputed: dict[str, tuple[list[str], list[dict]]] = {}

    if parent_candles_by_tf:
        for tf, pcandles in parent_candles_by_tf.items():
            precomputed[tf] = precompute_parent_indicators(pcandles)
    elif parent_candles:
        # Legacy single-parent backward compat
        immediate_parent = ancestors[0] if ancestors else None
        if immediate_parent:
            precomputed[immediate_parent] = precompute_parent_indicators(parent_candles)

    # ── Flow snapshot lookup ──
    _flow_ts: list[datetime] | None = None
    _flow_snaps: list[dict] | None = None
    _flow_maxlen = ORDER_FLOW["recent_window"] + ORDER_FLOW["baseline_window"]
    _flow_deque: deque = deque(maxlen=_flow_maxlen)
    _flow_ns_deque: deque = deque(maxlen=_flow_maxlen)
    _flow_asset_scale = ORDER_FLOW_ASSET_SCALES.get(pair, 1.0)

    if config.flow_snapshots:
        sorted_snaps = sorted(config.flow_snapshots, key=lambda s: s["timestamp"])
        _flow_ts = [s["timestamp"] for s in sorted_snaps]
        _flow_snaps = sorted_snaps

    # Estimate candle interval for drift tolerance
    _candle_interval_s = 900.0  # default 15m
    if len(candles) >= 2 and "timestamp" in candles[0] and "timestamp" in candles[1]:
        t0, t1 = candles[0]["timestamp"], candles[1]["timestamp"]
        if isinstance(t0, str):
            t0 = datetime.fromisoformat(t0)
        if isinstance(t1, str):
            t1 = datetime.fromisoformat(t1)
        _candle_interval_s = max((t1 - t0).total_seconds(), 60.0)

    trades: list[SimulatedTrade] = []
    open_positions: list[SimulatedTrade] = []

    if len(candles) < MIN_CANDLES:
        return _build_results(trades, pair, config)

    scoring_params: dict | None = None
    strength_overrides: dict | None = None
    boost_overrides: dict | None = None
    remaining_overrides: dict | None = None
    if config.param_overrides:
        _sp, _so, _bo, _ro = {}, {}, {}, {}
        for k, v in config.param_overrides.items():
            if k in _SIGMOID_KEYS:
                _sp[k] = v
            elif k in PATTERN_STRENGTHS:
                _so[k] = v
            elif k in PATTERN_BOOST_DEFAULTS:
                _bo[k] = v
            else:
                _ro[k] = v
        scoring_params = _sp or None
        strength_overrides = _so or None
        boost_overrides = _bo or None
        remaining_overrides = _ro or None

    for i in range(MIN_CANDLES, len(candles)):
        # Check cancellation
        if cancel_flag and cancel_flag.get("cancelled"):
            break

        window = candles[max(0, i - 199) : i + 1]
        current = candles[i]

        # Resolve open positions against current candle
        _resolve_positions(open_positions, current, trades)

        # Score current candle
        df = pd.DataFrame(window)

        # ── Rule-based scoring (always runs) ──
        try:
            tech_result = compute_technical_score(
                df, regime_weights=regime_weights,
                scoring_params=scoring_params,
                overrides=remaining_overrides,
            )
        except Exception:
            continue

        # Confluence scoring (multi-level, independent source)
        confluence_result = {"score": 0, "confidence": 0.0}
        if precomputed and ancestors:
            ts = current["timestamp"]
            if isinstance(ts, datetime):
                ts = ts.isoformat()
            parent_cache_list = []
            for anc_tf in ancestors:
                pc = precomputed.get(anc_tf)
                if pc:
                    parent_cache_list.append(_lookup_parent_indicators(ts, pc[0], pc[1]))
                else:
                    parent_cache_list.append(None)
            child_indicators = {
                "trend_score": tech_result["indicators"].get("trend_score", 0),
                "mean_rev_score": tech_result["indicators"].get("mean_rev_score", 0),
                "trend_conviction": tech_result["indicators"].get("trend_conviction", 0),
            }
            confluence_result = compute_confluence_score(
                child_indicators, parent_cache_list, timeframe=timeframe,
            )
        conf_score = confluence_result["score"]
        conf_confidence = confluence_result["confidence"]

        pat_score = 0
        detected = []
        if config.enable_patterns:
            try:
                detected = detect_candlestick_patterns(df)
                indicator_ctx = {**tech_result["indicators"], "close": float(df.iloc[-1]["close"])}
                pat_score = compute_pattern_score(
                    detected, indicator_ctx,
                    strength_overrides=strength_overrides,
                    boost_overrides=boost_overrides,
                )["score"]
            except Exception:
                pass

        # ── Flow scoring (when snapshots provided) ──
        flow_score = 0
        flow_confidence = 0.0
        if _flow_ts is not None:
            candle_ts = current["timestamp"]
            if isinstance(candle_ts, str):
                candle_ts = datetime.fromisoformat(candle_ts)
            idx = bisect.bisect_right(_flow_ts, candle_ts) - 1
            if idx >= 0:
                snap = _flow_snaps[idx]
                drift = (candle_ts - snap["timestamp"]).total_seconds()
                if drift <= 2 * _candle_interval_s:
                    _flow_deque.append(snap)
                    _flow_ns_deque.append(SimpleNamespace(**snap))
                    flow_result = score_order_flow(
                        metrics=snap,
                        regime=tech_result.get("regime"),
                        flow_history=list(_flow_ns_deque),
                        trend_conviction=tech_result["indicators"].get("trend_conviction", 0),
                        mr_pressure=tech_result["indicators"].get("mean_rev_score", 0),
                        flow_age_seconds=drift,
                        asset_scale=_flow_asset_scale,
                    )
                    flow_score = flow_result["score"]
                    flow_confidence = flow_result["confidence"]

        # Outer weights: use regime-blended when regime_weights provided,
        # otherwise preserve config defaults for backward compatibility
        conf_available = conf_confidence > 0
        flow_available = flow_score != 0 or flow_confidence > 0
        if regime_weights is not None:
            regime = tech_result.get("regime")
            outer = blend_outer_weights(regime, regime_weights)
            bt_tech_w = outer["tech"]
            bt_pattern_w = outer["pattern"]
            bt_conf_w = outer.get("confluence", 0.0) if conf_available else 0.0
            bt_flow_w = outer.get("flow", 0.0) if flow_available else 0.0
            bt_total = bt_tech_w + bt_pattern_w + bt_conf_w + bt_flow_w
            if bt_total > 0:
                bt_tech_w /= bt_total
                bt_pattern_w /= bt_total
                bt_conf_w /= bt_total
                bt_flow_w /= bt_total
        else:
            bt_tech_w = config.tech_weight
            bt_pattern_w = config.pattern_weight
            bt_conf_w = 0.0
            bt_flow_w = 0.0

        indicator_preliminary = compute_preliminary_score(
            technical_score=tech_result["score"],
            order_flow_score=flow_score,
            tech_weight=bt_tech_w,
            flow_weight=bt_flow_w,
            flow_confidence=flow_confidence,
            onchain_score=0,
            onchain_weight=0.0,
            pattern_score=pat_score,
            pattern_weight=bt_pattern_w,
            confluence_score=conf_score,
            confluence_weight=bt_conf_w,
            confluence_confidence=conf_confidence,
        )["score"]

        # ── Optional ML blending ──
        ml_score = None
        ml_confidence = None
        if ml_predictor is not None:
            try:
                from app.ml.features import build_feature_matrix
                feature_matrix = build_feature_matrix(df)
                prediction = ml_predictor.predict(feature_matrix)
                ml_confidence = prediction["confidence"]
                if prediction["direction"] != "NEUTRAL":
                    ml_score = ml_confidence * 100
                    if prediction["direction"] == "SHORT":
                        ml_score = -ml_score
            except Exception:
                pass

        score = blend_with_ml(
            indicator_preliminary, ml_score, ml_confidence,
            ml_confidence_threshold=config.ml_confidence_threshold,
        )

        direction = "LONG" if score > 0 else "SHORT"

        if abs(score) < config.signal_threshold:
            continue

        atr = tech_result["indicators"].get("atr", 0)
        if atr <= 0:
            continue

        price = float(current["close"])
        bb_width_pct = tech_result["indicators"].get("bb_width_pct", 50.0)

        # Phase 1: apply signal strength + volatility scaling to config multipliers
        # Phase 2 learned multipliers are NOT used in backtests — backtests use
        # whatever ATR multipliers are passed in the request config
        scaled = scale_atr_multipliers(
            score=score, bb_width_pct=bb_width_pct,
            sl_base=config.sl_atr_multiplier,
            tp1_base=config.tp1_atr_multiplier,
            tp2_base=config.tp2_atr_multiplier,
            signal_threshold=config.signal_threshold,
        )

        if direction == "LONG":
            sl = price - scaled["sl_atr"] * atr
            tp1 = price + scaled["tp1_atr"] * atr
            tp2 = price + scaled["tp2_atr"] * atr
        else:
            sl = price + scaled["sl_atr"] * atr
            tp1 = price - scaled["tp1_atr"] * atr
            tp2 = price - scaled["tp2_atr"] * atr

        # Enforce max concurrent positions
        if len(open_positions) >= config.max_concurrent_positions:
            continue

        ts = current["timestamp"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()

        trade = SimulatedTrade(
            pair=pair,
            direction=direction,
            entry_time=ts,
            entry_price=price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            score=score,
            detected_patterns=[p for p in detected if p["bias"] != "neutral"],
        )
        open_positions.append(trade)

    # Close remaining open positions at last candle
    if candles:
        last = candles[-1]
        for pos in open_positions:
            _close_trade(pos, last, "EXPIRED")
            trades.append(pos)
        open_positions.clear()

    return _build_results(trades, pair, config)


def _resolve_positions(
    open_positions: list[SimulatedTrade],
    candle: dict,
    closed_trades: list[SimulatedTrade],
):
    """Check open positions for SL/TP hits on the current candle."""
    high = float(candle["high"])
    low = float(candle["low"])

    still_open = []
    for pos in open_positions:
        hit = False

        if pos.direction == "LONG":
            if low <= pos.sl:
                _close_trade(pos, candle, "SL_HIT", exit_price=pos.sl)
                hit = True
            elif high >= pos.tp2:
                _close_trade(pos, candle, "TP2_HIT", exit_price=pos.tp2)
                hit = True
            elif high >= pos.tp1:
                _close_trade(pos, candle, "TP1_HIT", exit_price=pos.tp1)
                hit = True
        else:  # SHORT
            if high >= pos.sl:
                _close_trade(pos, candle, "SL_HIT", exit_price=pos.sl)
                hit = True
            elif low <= pos.tp2:
                _close_trade(pos, candle, "TP2_HIT", exit_price=pos.tp2)
                hit = True
            elif low <= pos.tp1:
                _close_trade(pos, candle, "TP1_HIT", exit_price=pos.tp1)
                hit = True

        if hit:
            closed_trades.append(pos)
        else:
            still_open.append(pos)

    open_positions.clear()
    open_positions.extend(still_open)


def _close_trade(
    trade: SimulatedTrade,
    candle: dict,
    outcome: str,
    exit_price: float | None = None,
):
    """Close a simulated trade with outcome and P&L calculation."""
    ts = candle["timestamp"]
    if isinstance(ts, datetime):
        ts = ts.isoformat()

    trade.exit_time = ts
    trade.outcome = outcome

    if exit_price is not None:
        trade.exit_price = exit_price
    else:
        trade.exit_price = float(candle["close"])

    if trade.entry_price > 0:
        if trade.direction == "LONG":
            trade.pnl_pct = round((trade.exit_price - trade.entry_price) / trade.entry_price * 100, 4)
        else:
            trade.pnl_pct = round((trade.entry_price - trade.exit_price) / trade.entry_price * 100, 4)

    # Duration
    try:
        entry_dt = datetime.fromisoformat(trade.entry_time)
        exit_dt = datetime.fromisoformat(trade.exit_time)
        trade.duration_minutes = int((exit_dt - entry_dt).total_seconds() / 60)
    except Exception:
        trade.duration_minutes = 0


def _build_results(
    trades: list[SimulatedTrade],
    pair: str,
    config: BacktestConfig,
) -> dict:
    """Compute aggregate stats from completed trades."""
    trade_dicts = [_trade_to_dict(t) for t in trades]

    if not trades:
        return {
            "trades": [],
            "stats": _empty_stats(),
        }

    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    total = len(trades)
    win_rate = round(len(wins) / total * 100, 2) if total else 0

    pnls = [t.pnl_pct for t in trades]
    net_pnl = round(sum(pnls), 4)
    avg_pnl = round(net_pnl / total, 4) if total else 0

    # Average R:R (winners only)
    avg_rr = 0.0
    if wins:
        avg_win = sum(t.pnl_pct for t in wins) / len(wins)
        avg_loss = abs(sum(t.pnl_pct for t in losses) / len(losses)) if losses else 1.0
        avg_rr = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0

    # Max drawdown
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cumulative += t.pnl_pct
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    max_dd = round(max_dd, 4)

    # Profit factor
    gross_profit = sum(t.pnl_pct for t in wins) if wins else 0
    gross_loss = abs(sum(t.pnl_pct for t in losses)) if losses else 0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    # Sharpe ratio (simplified: using trade returns)
    sharpe = None
    if total >= 7:
        import statistics
        mean_r = statistics.mean(pnls)
        std_r = statistics.stdev(pnls) if len(pnls) > 1 else 0
        sharpe = round(mean_r / std_r, 2) if std_r > 0 else None

    # Sortino ratio
    sortino = None
    if total >= 7:
        downside = [p for p in pnls if p < 0]
        if downside:
            import statistics
            downside_std = statistics.stdev(downside) if len(downside) > 1 else abs(downside[0])
            mean_r = statistics.mean(pnls)
            sortino = round(mean_r / downside_std, 2) if downside_std > 0 else None

    # Best/worst trade
    best = max(trades, key=lambda t: t.pnl_pct)
    worst = min(trades, key=lambda t: t.pnl_pct)

    # Avg duration
    avg_duration = round(sum(t.duration_minutes for t in trades) / total) if total else 0

    # Win rate by direction
    longs = [t for t in trades if t.direction == "LONG"]
    shorts = [t for t in trades if t.direction == "SHORT"]
    by_direction = {
        "LONG": {
            "total": len(longs),
            "wins": len([t for t in longs if t.pnl_pct > 0]),
            "win_rate": round(len([t for t in longs if t.pnl_pct > 0]) / len(longs) * 100, 2) if longs else 0,
        },
        "SHORT": {
            "total": len(shorts),
            "wins": len([t for t in shorts if t.pnl_pct > 0]),
            "win_rate": round(len([t for t in shorts if t.pnl_pct > 0]) / len(shorts) * 100, 2) if shorts else 0,
        },
    }

    # Monthly P&L breakdown
    monthly_pnl: dict[str, float] = {}
    for t in trades:
        try:
            month = t.entry_time[:7]  # "YYYY-MM"
            monthly_pnl[month] = round(monthly_pnl.get(month, 0) + t.pnl_pct, 4)
        except Exception:
            pass

    # Equity curve
    equity_curve = []
    cumulative = 0.0
    for t in trades:
        cumulative += t.pnl_pct
        equity_curve.append({"time": t.entry_time, "cumulative_pnl": round(cumulative, 4)})

    stats = {
        "total_trades": total,
        "win_rate": win_rate,
        "net_pnl": net_pnl,
        "avg_pnl": avg_pnl,
        "avg_rr": avg_rr,
        "max_drawdown": max_dd,
        "profit_factor": profit_factor,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "best_trade": {"pnl_pct": best.pnl_pct, "pair": best.pair, "direction": best.direction},
        "worst_trade": {"pnl_pct": worst.pnl_pct, "pair": worst.pair, "direction": worst.direction},
        "avg_duration_minutes": avg_duration,
        "by_direction": by_direction,
        "monthly_pnl": monthly_pnl,
        "equity_curve": equity_curve,
    }

    return {"trades": trade_dicts, "stats": stats}


def _trade_to_dict(trade: SimulatedTrade) -> dict:
    return {
        "pair": trade.pair,
        "direction": trade.direction,
        "entry_time": trade.entry_time,
        "exit_time": trade.exit_time,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "sl": trade.sl,
        "tp1": trade.tp1,
        "tp2": trade.tp2,
        "outcome": trade.outcome,
        "pnl_pct": trade.pnl_pct,
        "score": trade.score,
        "detected_patterns": [p["name"] for p in trade.detected_patterns],
        "duration_minutes": trade.duration_minutes,
    }


def _empty_stats() -> dict:
    return {
        "total_trades": 0,
        "win_rate": 0,
        "net_pnl": 0,
        "avg_pnl": 0,
        "avg_rr": 0,
        "max_drawdown": 0,
        "profit_factor": None,
        "sharpe_ratio": None,
        "sortino_ratio": None,
        "best_trade": None,
        "worst_trade": None,
        "avg_duration_minutes": 0,
        "by_direction": {"LONG": {"total": 0, "wins": 0, "win_rate": 0}, "SHORT": {"total": 0, "wins": 0, "win_rate": 0}},
        "monthly_pnl": {},
        "equity_curve": [],
    }
