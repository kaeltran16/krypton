"""Backtesting strategy runner — replays historical candles through the scoring pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.engine.traditional import compute_technical_score
from app.engine.patterns import detect_candlestick_patterns, compute_pattern_score
from app.engine.combiner import compute_preliminary_score, calculate_levels

logger = logging.getLogger(__name__)

MIN_CANDLES = 50  # minimum candles for reliable indicators


@dataclass
class BacktestConfig:
    signal_threshold: int = 50
    tech_weight: float = 0.75
    pattern_weight: float = 0.25
    enable_ema: bool = True
    enable_macd: bool = True
    enable_rsi: bool = True
    enable_bb: bool = True
    enable_patterns: bool = True
    sl_atr_multiplier: float = 1.5
    tp1_atr_multiplier: float = 2.0
    tp2_atr_multiplier: float = 3.0
    risk_per_trade_pct: float = 1.0
    max_concurrent_positions: int = 3
    ml_confidence_threshold: float = 0.65  # minimum ML confidence to emit signal


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
) -> dict:
    """Run a backtest on historical candles for a single pair.

    Args:
        candles: Chronologically sorted list of candle dicts with
                 keys: timestamp, open, high, low, close, volume.
        pair: Instrument ID.
        config: Backtest parameters. Uses defaults if None.
        cancel_flag: Dict with key "cancelled" (bool) checked each iteration.

    Returns:
        Dict with trades list and aggregate stats.
    """
    if config is None:
        config = BacktestConfig()

    trades: list[SimulatedTrade] = []
    open_positions: list[SimulatedTrade] = []

    if len(candles) < MIN_CANDLES:
        return _build_results(trades, pair, config)

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

        if ml_predictor is not None:
            # ML scoring mode
            try:
                from app.ml.features import build_feature_matrix
                feature_matrix = build_feature_matrix(df)
                prediction = ml_predictor.predict(feature_matrix)

                if prediction["direction"] == "NEUTRAL" or prediction["confidence"] < config.ml_confidence_threshold:
                    continue

                direction = prediction["direction"]
                score = int(prediction["confidence"] * 100)
                if direction == "SHORT":
                    score = -score

                # Use compute_technical_score for ATR (same as rule-based path)
                try:
                    tech_result = compute_technical_score(df)
                    atr = tech_result["indicators"].get("atr", 0)
                except Exception:
                    continue
                if atr <= 0:
                    continue

                price = float(current["close"])
                if direction == "LONG":
                    sl = price - prediction["sl_atr"] * atr
                    tp1 = price + prediction["tp1_atr"] * atr
                    tp2 = price + prediction["tp2_atr"] * atr
                else:
                    sl = price + prediction["sl_atr"] * atr
                    tp1 = price - prediction["tp1_atr"] * atr
                    tp2 = price - prediction["tp2_atr"] * atr

                detected = []

            except Exception:
                continue
        else:
            # Rule-based scoring mode (existing logic)
            try:
                tech_result = compute_technical_score(df)
            except Exception:
                continue

            pat_score = 0
            detected = []
            if config.enable_patterns:
                try:
                    detected = detect_candlestick_patterns(df)
                    indicator_ctx = {**tech_result["indicators"], "close": float(df.iloc[-1]["close"])}
                    pat_score = compute_pattern_score(detected, indicator_ctx)
                except Exception:
                    pass

            score = compute_preliminary_score(
                technical_score=tech_result["score"],
                order_flow_score=0,
                tech_weight=config.tech_weight,
                flow_weight=0.0,
                onchain_score=0,
                onchain_weight=0.0,
                pattern_score=pat_score,
                pattern_weight=config.pattern_weight,
            )

            direction = "LONG" if score > 0 else "SHORT"

            if abs(score) < config.signal_threshold:
                continue

            atr = tech_result["indicators"].get("atr", 0)
            if atr <= 0:
                continue

            price = float(current["close"])
            if direction == "LONG":
                sl = price - config.sl_atr_multiplier * atr
                tp1 = price + config.tp1_atr_multiplier * atr
                tp2 = price + config.tp2_atr_multiplier * atr
            else:
                sl = price + config.sl_atr_multiplier * atr
                tp1 = price - config.tp1_atr_multiplier * atr
                tp2 = price - config.tp2_atr_multiplier * atr

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
