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
