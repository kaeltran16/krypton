import pytest
from datetime import datetime, timezone, timedelta

from app.engine.cooldown import update_streak_on_sl, reset_streak, check_cooldown


PAIR = "BTC-USDT-SWAP"
TF = "1h"
DIR = "LONG"


class TestUpdateStreakOnSL:

    async def test_first_sl_sets_streak_to_1(self, fake_redis):
        ts = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts)
        key = f"cooldown:streak:{PAIR}:{TF}:{DIR}"
        assert fake_redis.store[key] == "1"

    async def test_second_sl_increments_to_2(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts2)
        key = f"cooldown:streak:{PAIR}:{TF}:{DIR}"
        assert fake_redis.store[key] == "2"

    async def test_timestamp_only_updates_if_newer(self, fake_redis):
        ts_new = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        ts_old = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts_new)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts_old)
        key = f"cooldown:last_sl:{PAIR}:{TF}:{DIR}"
        assert fake_redis.store[key] == ts_new.isoformat()
        # streak still increments even for out-of-order
        assert fake_redis.store[f"cooldown:streak:{PAIR}:{TF}:{DIR}"] == "2"


class TestResetStreak:

    async def test_reset_deletes_both_keys(self, fake_redis):
        ts = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts)
        await reset_streak(fake_redis, PAIR, TF, DIR)
        assert f"cooldown:streak:{PAIR}:{TF}:{DIR}" not in fake_redis.store
        assert f"cooldown:last_sl:{PAIR}:{TF}:{DIR}" not in fake_redis.store


class TestCheckCooldown:

    async def test_no_streak_returns_none(self, fake_redis):
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3)
        assert result is None

    async def test_streak_1_returns_none(self, fake_redis):
        ts = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts)
        now = datetime(2026, 3, 31, 12, 5, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is None

    async def test_streak_2_within_cooldown_returns_reason(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts2)
        # 1h tf, streak=2 -> cooldown=1 candle=3600s; check 30 min after last SL
        now = datetime(2026, 3, 31, 13, 30, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is not None
        assert "streak=2" in result
        assert "LONG" in result

    async def test_streak_2_after_cooldown_expires_returns_none(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts2)
        # 1h tf, streak=2 -> cooldown=1 candle=3600s; check 2h after last SL
        now = datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is None

    async def test_streak_4_caps_at_max_candles(self, fake_redis):
        base = datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc)
        for i in range(4):
            await update_streak_on_sl(fake_redis, PAIR, TF, DIR, base + timedelta(hours=i))
        # streak=4 -> cooldown = min(4-1, 3) = 3 candles = 10800s
        now = base + timedelta(hours=4)  # 4h after first, 1h after last SL
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is not None

    async def test_cooldown_max_zero_disables(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, TF, DIR, ts2)
        now = datetime(2026, 3, 31, 13, 5, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=0, now=now)
        assert result is None

    async def test_corrupted_timestamp_resets_and_returns_none(self, fake_redis):
        fake_redis.store[f"cooldown:streak:{PAIR}:{TF}:{DIR}"] = "3"
        fake_redis.store[f"cooldown:last_sl:{PAIR}:{TF}:{DIR}"] = "not-a-date"
        now = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is None
        assert f"cooldown:streak:{PAIR}:{TF}:{DIR}" not in fake_redis.store

    async def test_15m_timeframe_uses_900s_per_candle(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 12, 15, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, "15m", DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, "15m", DIR, ts2)
        # 15m tf, streak=2 -> cooldown=1 candle=900s; check 10 min after last SL
        now = datetime(2026, 3, 31, 12, 25, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, "15m", DIR, cooldown_max_candles=3, now=now)
        assert result is not None
        # check 16 min after last SL (past 900s)
        now_after = datetime(2026, 3, 31, 12, 31, tzinfo=timezone.utc)
        result_after = await check_cooldown(fake_redis, PAIR, "15m", DIR, cooldown_max_candles=3, now=now_after)
        assert result_after is None

    async def test_streak_exists_but_last_sl_missing_returns_none(self, fake_redis):
        # partial state: streak key exists but last_sl was evicted
        fake_redis.store[f"cooldown:streak:{PAIR}:{TF}:{DIR}"] = "3"
        now = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, TF, DIR, cooldown_max_candles=3, now=now)
        assert result is None

    async def test_unknown_timeframe_falls_back_to_3600s(self, fake_redis):
        ts1 = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 3, 31, 13, 0, tzinfo=timezone.utc)
        await update_streak_on_sl(fake_redis, PAIR, "12h", DIR, ts1)
        await update_streak_on_sl(fake_redis, PAIR, "12h", DIR, ts2)
        # unknown tf falls back to 3600s; streak=2 -> 1 candle = 3600s
        now = datetime(2026, 3, 31, 13, 30, tzinfo=timezone.utc)
        result = await check_cooldown(fake_redis, PAIR, "12h", DIR, cooldown_max_candles=3, now=now)
        assert result is not None
