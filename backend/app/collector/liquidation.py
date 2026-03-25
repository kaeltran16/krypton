"""Polls OKX liquidation endpoint every 5 minutes, maintains rolling 24h window."""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 300  # 5 minutes
WINDOW_HOURS = 24


class LiquidationCollector:
    def __init__(self, okx_client, pairs: list[str], redis=None):
        self._client = okx_client
        self._pairs = pairs
        self._events: dict[str, list[dict]] = {p: [] for p in pairs}
        self._redis = redis
        self._task = None
        self._last_poll_ts = None

    @property
    def events(self) -> dict[str, list[dict]]:
        return self._events

    async def load_from_redis(self):
        """Reload events from Redis on startup."""
        if not self._redis:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        for pair in self._pairs:
            try:
                raw_list = await self._redis.lrange(f"liq_events:{pair}", 0, -1)
                for raw in raw_list:
                    event = json.loads(raw)
                    event["timestamp"] = datetime.fromisoformat(event["timestamp"])
                    if event["timestamp"] > cutoff:
                        self._events[pair].append(event)
                logger.info("Loaded %d liquidation events for %s from Redis", len(self._events[pair]), pair)
            except Exception as e:
                logger.warning("Failed to load liquidation events for %s: %s", pair, e)

    async def start(self):
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _poll_loop(self):
        while True:
            try:
                await self._poll()
            except Exception as e:
                logger.warning("Liquidation poll error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _poll(self):
        self._last_poll_ts = time.time()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        for pair in self._pairs:
            try:
                raw = await self._client.get_liquidation_orders(pair)
                if raw:
                    new_events = []
                    for item in raw:
                        event = {
                            "price": float(item.get("bkPx", 0)),
                            "volume": float(item.get("sz", 0)),
                            "timestamp": datetime.now(timezone.utc),
                            "side": item.get("side", ""),
                        }
                        self._events[pair].append(event)
                        new_events.append(event)
                    await self._persist_events(pair, new_events)
            except Exception as e:
                logger.debug("Liquidation poll for %s failed: %s", pair, e)
            finally:
                self._events[pair] = [
                    e for e in self._events[pair] if e["timestamp"] > cutoff
                ]

    async def _persist_events(self, pair: str, events: list[dict]):
        if not self._redis or not events:
            return
        try:
            key = f"liq_events:{pair}"
            for event in events:
                data = {
                    "price": event["price"],
                    "volume": event["volume"],
                    "timestamp": event["timestamp"].isoformat(),
                    "side": event["side"],
                }
                await self._redis.rpush(key, json.dumps(data))
            await self._redis.expire(key, WINDOW_HOURS * 3600)
        except Exception as e:
            logger.debug("Failed to persist liquidation events: %s", e)
