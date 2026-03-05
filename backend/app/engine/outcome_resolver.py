from datetime import datetime, timezone


def resolve_signal_outcome(signal: dict, candles: list[dict]) -> dict | None:
    """Check if signal hit TP1, TP2, or SL based on candle data.

    Returns outcome dict if resolved, None if still pending.
    """
    direction = signal["direction"]
    entry = signal["entry"]
    sl = signal["stop_loss"]
    tp1 = signal["take_profit_1"]
    tp2 = signal["take_profit_2"]
    created_at = signal["created_at"]

    for candle in candles:
        high = candle["high"]
        low = candle["low"]
        ts = candle["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        if direction == "LONG":
            # Check SL first (worst case)
            if low <= sl:
                pnl_pct = (sl - entry) / entry * 100
                return _result("SL_HIT", sl, pnl_pct, created_at, ts)
            if high >= tp2:
                pnl_pct = (tp2 - entry) / entry * 100
                return _result("TP2_HIT", tp2, pnl_pct, created_at, ts)
            if high >= tp1:
                pnl_pct = (tp1 - entry) / entry * 100
                return _result("TP1_HIT", tp1, pnl_pct, created_at, ts)
        else:  # SHORT
            if high >= sl:
                pnl_pct = (entry - sl) / entry * 100
                return _result("SL_HIT", sl, pnl_pct, created_at, ts)
            if low <= tp2:
                pnl_pct = (entry - tp2) / entry * 100
                return _result("TP2_HIT", tp2, pnl_pct, created_at, ts)
            if low <= tp1:
                pnl_pct = (entry - tp1) / entry * 100
                return _result("TP1_HIT", tp1, pnl_pct, created_at, ts)

    return None


def _result(outcome: str, price: float, pnl_pct: float, created_at: datetime, resolved_at: datetime) -> dict:
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
