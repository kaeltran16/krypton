"""Anti-whipsaw cooldown: per-(pair, timeframe, direction) streak tracking."""

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TTL = 7 * 86400  # 7 days

_CANDLE_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400}


async def update_streak_on_sl(redis, pair: str, tf: str, direction: str, outcome_at: datetime):
    """Increment SL streak. Only update timestamp if newer than existing."""
    streak_key = f"cooldown:streak:{pair}:{tf}:{direction}"
    last_sl_key = f"cooldown:last_sl:{pair}:{tf}:{direction}"

    existing = await redis.get(last_sl_key)
    if existing and datetime.fromisoformat(existing) >= outcome_at:
        # out-of-order resolution: increment streak but keep newer timestamp
        await redis.incr(streak_key)
        await redis.expire(streak_key, _TTL)
        return

    pipe = redis.pipeline()
    pipe.incr(streak_key)
    pipe.set(last_sl_key, outcome_at.isoformat())
    pipe.expire(streak_key, _TTL)
    pipe.expire(last_sl_key, _TTL)
    await pipe.execute()


async def reset_streak(redis, pair: str, tf: str, direction: str):
    """Delete streak on win or expiry."""
    pipe = redis.pipeline()
    pipe.delete(f"cooldown:streak:{pair}:{tf}:{direction}")
    pipe.delete(f"cooldown:last_sl:{pair}:{tf}:{direction}")
    await pipe.execute()


async def check_cooldown(
    redis, pair: str, tf: str, direction: str,
    cooldown_max_candles: int, now: datetime | None = None,
) -> str | None:
    """Return suppression reason string if cooldown active, else None."""
    if cooldown_max_candles <= 0:
        return None

    streak_key = f"cooldown:streak:{pair}:{tf}:{direction}"
    last_sl_key = f"cooldown:last_sl:{pair}:{tf}:{direction}"
    streak_raw, last_sl_raw = await asyncio.gather(
        redis.get(streak_key), redis.get(last_sl_key),
    )
    if not streak_raw:
        return None

    streak = int(streak_raw)
    if streak < 2:
        return None

    cooldown = min(streak - 1, cooldown_max_candles)
    if not last_sl_raw:
        return None

    try:
        last_sl_dt = datetime.fromisoformat(last_sl_raw)
    except (ValueError, TypeError):
        logger.warning("Corrupted cooldown timestamp for %s:%s:%s, resetting", pair, tf, direction)
        await reset_streak(redis, pair, tf, direction)
        return None

    if now is None:
        now = datetime.now(timezone.utc)

    candle_seconds = _CANDLE_SECONDS.get(tf, 3600)
    elapsed = (now - last_sl_dt).total_seconds()
    remaining = cooldown * candle_seconds - elapsed
    if remaining > 0:
        return f"cooldown: streak={streak}, {remaining:.0f}s remaining ({direction} SL_HIT)"
    return None
