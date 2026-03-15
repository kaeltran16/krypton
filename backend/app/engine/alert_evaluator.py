import logging
from datetime import datetime, timedelta, timezone

from zoneinfo import ZoneInfo
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Alert, AlertHistory, AlertSettings

logger = logging.getLogger(__name__)


def check_price_condition(
    condition: str, threshold: float, prev_price: float | None, current_price: float | None
) -> bool:
    """Check if a price condition is met.

    For crosses_above/crosses_below: prev_price was below/above threshold, current_price is
    now above/below — a crossing event.
    For pct_move: threshold is the % threshold, prev_price is the base price,
    current_price is the current price.
    """
    if condition == "crosses_above":
        # Was below threshold, now at or above
        return (
            prev_price is not None
            and current_price is not None
            and prev_price < threshold
            and current_price >= threshold
        )
    elif condition == "crosses_below":
        return (
            prev_price is not None
            and current_price is not None
            and prev_price > threshold
            and current_price <= threshold
        )
    elif condition == "pct_move":
        if prev_price is None or current_price is None or prev_price == 0:
            return False
        pct_change = abs((current_price - prev_price) / prev_price) * 100
        return pct_change >= threshold
    return False


def check_indicator_condition(condition: str, threshold: float, value: float) -> bool:
    """Check gt/lt conditions for indicator alerts."""
    if condition == "gt":
        return value > threshold
    elif condition == "lt":
        return value < threshold
    return False


def check_signal_filters(filters: dict | None, signal: dict) -> bool:
    """Check if a signal matches all non-null filters."""
    if not filters:
        return True
    if filters.get("pair") and signal.get("pair") != filters["pair"]:
        return False
    if filters.get("direction") and signal.get("direction") != filters["direction"]:
        return False
    if filters.get("min_score") is not None:
        if abs(signal.get("final_score", 0)) < filters["min_score"]:
            return False
    if filters.get("timeframe") and signal.get("timeframe") != filters["timeframe"]:
        return False
    return True


def check_cooldown(last_triggered_at: datetime | None, cooldown_minutes: int) -> bool:
    """Return True if cooldown has expired (or never triggered)."""
    if last_triggered_at is None:
        return True
    elapsed = datetime.now(timezone.utc) - last_triggered_at
    return elapsed >= timedelta(minutes=cooldown_minutes)


def is_in_quiet_hours(
    now: datetime, enabled: bool, start: str, end: str, tz_name: str
) -> bool:
    """Check if current time falls within quiet hours."""
    if not enabled:
        return False
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        return False
    local_now = now.astimezone(tz)
    current_minutes = local_now.hour * 60 + local_now.minute
    start_h, start_m = map(int, start.split(":"))
    end_h, end_m = map(int, end.split(":"))
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m
    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes < end_minutes
    else:
        # Wraps midnight (e.g., 22:00 - 08:00)
        return current_minutes >= start_minutes or current_minutes < end_minutes


async def get_quiet_hours_settings(session_factory: async_sessionmaker) -> dict:
    """Load quiet hours settings from DB."""
    try:
        async with session_factory() as session:
            result = await session.execute(
                select(AlertSettings).where(AlertSettings.id == 1)
            )
            settings = result.scalar_one_or_none()
            if settings:
                return {
                    "enabled": settings.quiet_hours_enabled,
                    "start": settings.quiet_hours_start,
                    "end": settings.quiet_hours_end,
                    "tz": settings.quiet_hours_tz,
                }
    except Exception as e:
        logger.debug(f"Failed to load alert settings: {e}")
    return {"enabled": False, "start": "22:00", "end": "08:00", "tz": "UTC"}


async def fire_alert(
    alert: Alert,
    trigger_value: float,
    session_factory: async_sessionmaker,
    manager,
    push_ctx: dict | None,
    redis=None,
):
    """Fire an alert: record history, broadcast WS, dispatch push, handle one-shot."""
    now = datetime.now(timezone.utc)

    # Check cooldown
    if not check_cooldown(alert.last_triggered_at, alert.cooldown_minutes):
        # Record silenced-by-cooldown in history
        async with session_factory() as session:
            session.add(AlertHistory(
                alert_id=alert.id,
                trigger_value=trigger_value,
                delivery_status="silenced_by_cooldown",
            ))
            await session.commit()
        return

    # Check quiet hours for non-critical alerts
    quiet = await get_quiet_hours_settings(session_factory)
    in_quiet = is_in_quiet_hours(now, quiet["enabled"], quiet["start"], quiet["end"], quiet["tz"])
    suppressed = in_quiet and alert.urgency != "critical"

    if suppressed:
        delivery_status = "silenced_by_quiet_hours"
    else:
        delivery_status = "delivered"

    # Record history
    async with session_factory() as session:
        session.add(AlertHistory(
            alert_id=alert.id,
            trigger_value=trigger_value,
            delivery_status=delivery_status,
        ))
        # Update alert last_triggered_at + one-shot deactivation
        stmt = (
            update(Alert)
            .where(Alert.id == alert.id)
            .values(
                last_triggered_at=now,
                **({"is_active": False} if alert.is_one_shot else {}),
            )
        )
        await session.execute(stmt)
        await session.commit()

    # Invalidate price alert Redis cache so cooldown/one-shot state is fresh
    if alert.type == "price" and redis:
        await redis.delete("alerts:price")

    # WebSocket broadcast (always, even during quiet hours — for in-app display)
    if manager:
        await manager.broadcast_alert({
            "type": "alert_triggered",
            "alert_id": alert.id,
            "label": alert.label,
            "trigger_value": trigger_value,
            "urgency": alert.urgency,
        })

    # Push dispatch (skip silent, skip if suppressed by quiet hours)
    if alert.urgency != "silent" and not suppressed and push_ctx:
        try:
            from app.push.alert_dispatch import dispatch_push_for_alert
            await dispatch_push_for_alert(
                session_factory=session_factory,
                alert_id=alert.id,
                label=alert.label,
                trigger_value=trigger_value,
                urgency=alert.urgency,
                vapid_private_key=push_ctx["vapid_private_key"],
                vapid_claims_email=push_ctx["vapid_claims_email"],
            )
        except Exception as e:
            logger.debug(f"Alert push dispatch failed: {e}")


async def evaluate_price_alerts(
    pair: str,
    current_price: float,
    redis,
    session_factory: async_sessionmaker,
    manager,
    push_ctx: dict | None,
):
    """Evaluate price alerts for a pair. Called at throttled 1/s cadence from ticker collector."""
    import json

    # Get previous price from Redis
    prev_price_raw = await redis.get(f"ticker_prev:{pair}")
    prev_price = float(prev_price_raw) if prev_price_raw else None

    # Load cached price alerts from Redis (invalidated on CRUD)
    cached = await redis.get("alerts:price")
    if cached:
        alert_dicts = json.loads(cached)
    else:
        # Cache miss — load from DB
        async with session_factory() as session:
            result = await session.execute(
                select(Alert).where(
                    Alert.type == "price",
                    Alert.is_active == True,
                )
            )
            alerts = result.scalars().all()
            alert_dicts = [
                {
                    "id": a.id, "pair": a.pair, "condition": a.condition,
                    "threshold": a.threshold, "secondary_threshold": a.secondary_threshold,
                    "urgency": a.urgency, "cooldown_minutes": a.cooldown_minutes,
                    "is_one_shot": a.is_one_shot, "label": a.label,
                    "last_triggered_at": a.last_triggered_at.isoformat() if a.last_triggered_at else None,
                }
                for a in alerts
            ]
            await redis.set("alerts:price", json.dumps(alert_dicts), ex=300)

    for ad in alert_dicts:
        if ad["pair"] and ad["pair"] != pair:
            continue

        triggered = False
        if ad["condition"] in ("crosses_above", "crosses_below"):
            triggered = check_price_condition(
                ad["condition"], ad["threshold"], prev_price, current_price
            )
        elif ad["condition"] == "pct_move":
            window_minutes = int(ad["secondary_threshold"] or 15)
            # Query Redis sorted set for snapshot price (with scores to avoid second call)
            min_ts = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
            snapshots = await redis.zrangebyscore(
                f"ticker_snapshots:{pair}", min_ts.timestamp(), "+inf", withscores=True
            )
            if snapshots:
                base_price = float(snapshots[0][0])
                oldest_ts = snapshots[0][1]
                coverage = (datetime.now(timezone.utc).timestamp() - oldest_ts) / (window_minutes * 60)
                if coverage >= 0.8:
                    triggered = check_price_condition("pct_move", ad["threshold"], base_price, current_price)

        if triggered:
            # Reconstruct a minimal Alert-like object for fire_alert
            async with session_factory() as session:
                result = await session.execute(select(Alert).where(Alert.id == ad["id"]))
                alert = result.scalar_one_or_none()
                if alert and alert.is_active:
                    await fire_alert(alert, current_price, session_factory, manager, push_ctx, redis=redis)

    # Store current price as prev for next evaluation
    await redis.set(f"ticker_prev:{pair}", str(current_price), ex=10)


async def evaluate_signal_alerts(
    signal_data: dict,
    session_factory: async_sessionmaker,
    manager,
    push_ctx: dict | None,
):
    """Evaluate signal alerts when a new signal is emitted."""
    async with session_factory() as session:
        result = await session.execute(
            select(Alert).where(Alert.type == "signal", Alert.is_active == True)
        )
        alerts = result.scalars().all()

    for alert in alerts:
        if check_signal_filters(alert.filters, signal_data):
            await fire_alert(
                alert, abs(signal_data.get("final_score", 0)),
                session_factory, manager, push_ctx,
            )


async def evaluate_indicator_alerts(
    pair: str,
    timeframe: str,
    indicators: dict,
    session_factory: async_sessionmaker,
    manager,
    push_ctx: dict | None,
):
    """Evaluate indicator alerts after technical scoring completes."""
    # Explicit mapping: alert condition -> (indicator dict key, comparison operator)
    CONDITION_TO_INDICATOR: dict[str, tuple[str, str]] = {
        "rsi_above": ("rsi", "gt"),
        "rsi_below": ("rsi", "lt"),
        "adx_above": ("adx", "gt"),
        "bb_width_percentile_above": ("bb_width_pct", "gt"),
        "bb_width_percentile_below": ("bb_width_pct", "lt"),
        "funding_rate_above": ("funding_rate", "gt"),
        "funding_rate_below": ("funding_rate", "lt"),
        # Also support bare gt/lt for programmatic use
        "gt": (None, "gt"),
        "lt": (None, "lt"),
    }

    async with session_factory() as session:
        result = await session.execute(
            select(Alert).where(Alert.type == "indicator", Alert.is_active == True)
        )
        alerts = result.scalars().all()

    for alert in alerts:
        # Timeframe filter
        if alert.timeframe and alert.timeframe != timeframe:
            continue
        if alert.pair and alert.pair != pair:
            continue

        mapping = CONDITION_TO_INDICATOR.get(alert.condition or "")
        if not mapping:
            continue
        ind_key, cond = mapping
        # For bare gt/lt, ind_key is None — skip (requires specific indicator condition)
        if ind_key is None:
            continue
        value = indicators.get(ind_key)
        if value is not None:
            if check_indicator_condition(cond, alert.threshold, value):
                await fire_alert(alert, value, session_factory, manager, push_ctx)


async def evaluate_portfolio_alerts(
    balance_data: dict,
    redis,
    session_factory: async_sessionmaker,
    manager,
    push_ctx: dict | None,
):
    """Evaluate portfolio alerts on each account balance poll."""
    equity = balance_data.get("total_equity", 0)

    async with session_factory() as session:
        result = await session.execute(
            select(Alert).where(Alert.type == "portfolio", Alert.is_active == True)
        )
        alerts = result.scalars().all()

    for alert in alerts:
        if alert.condition == "drawdown_pct":
            # Track peak in Redis, fallback to alert.peak_value
            peak_key = f"portfolio_peak:{alert.id}"
            peak_raw = await redis.get(peak_key)
            peak = float(peak_raw) if peak_raw else (alert.peak_value or equity)

            if equity > peak:
                peak = equity
                await redis.set(peak_key, str(peak), ex=86400 * 7)
                # Persist to DB
                async with session_factory() as session:
                    from sqlalchemy import update as sa_update
                    await session.execute(
                        sa_update(Alert).where(Alert.id == alert.id).values(peak_value=peak)
                    )
                    await session.commit()

            if peak > 0:
                drawdown_pct = ((peak - equity) / peak) * 100
                if drawdown_pct >= alert.threshold:
                    await fire_alert(alert, drawdown_pct, session_factory, manager, push_ctx, redis=redis)

        elif alert.condition == "pnl_crosses":
            pnl = balance_data.get("unrealized_pnl", 0)
            if alert.threshold >= 0 and pnl >= alert.threshold:
                await fire_alert(alert, pnl, session_factory, manager, push_ctx, redis=redis)
            elif alert.threshold < 0 and pnl <= alert.threshold:
                await fire_alert(alert, pnl, session_factory, manager, push_ctx, redis=redis)

        elif alert.condition == "position_loss_pct":
            positions = balance_data.get("positions", [])
            for pos in positions:
                pos_pnl_pct = pos.get("unrealized_pnl_pct", 0)
                if pos_pnl_pct <= -abs(alert.threshold):
                    await fire_alert(alert, pos_pnl_pct, session_factory, manager, push_ctx, redis=redis)
                    break  # Only fire once per evaluation


async def cleanup_alert_history(session_factory: async_sessionmaker, retention_days: int = 30):
    """Delete alert history older than retention_days. Run daily."""
    from sqlalchemy import delete
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    async with session_factory() as session:
        await session.execute(
            delete(AlertHistory).where(AlertHistory.triggered_at < cutoff)
        )
        await session.commit()
    logger.info(f"Cleaned up alert history older than {retention_days} days")
