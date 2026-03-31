import pytest
from datetime import datetime, timezone, timedelta

from app.engine.cooldown import update_streak_on_sl, reset_streak, check_cooldown


PAIR = "BTC-USDT-SWAP"
TF = "1h"


class TestOutcomeStreakFlow:
    """Tests the full lifecycle: SL builds streak, win resets it, cooldown activates."""

    async def test_sl_sl_triggers_cooldown_then_win_resets(self, fake_redis):
        # 2 consecutive SL hits build streak
        t1 = datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 3, 31, 11, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, "LONG", t1)
        await update_streak_on_sl(fake_redis, PAIR, TF, "LONG", t2)

        # cooldown active 5min after last SL
        now = t2 + timedelta(minutes=5)
        reason = await check_cooldown(fake_redis, PAIR, TF, "LONG", cooldown_max_candles=3, now=now)
        assert reason is not None

        # win resets streak
        await reset_streak(fake_redis, PAIR, TF, "LONG")
        reason = await check_cooldown(fake_redis, PAIR, TF, "LONG", cooldown_max_candles=3, now=now)
        assert reason is None

    async def test_independent_directions(self, fake_redis):
        t1 = datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 3, 31, 11, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, "LONG", t1)
        await update_streak_on_sl(fake_redis, PAIR, TF, "LONG", t2)

        now = t2 + timedelta(minutes=5)
        # LONG is under cooldown
        assert await check_cooldown(fake_redis, PAIR, TF, "LONG", cooldown_max_candles=3, now=now) is not None
        # SHORT is free
        assert await check_cooldown(fake_redis, PAIR, TF, "SHORT", cooldown_max_candles=3, now=now) is None
