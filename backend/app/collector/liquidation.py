"""Polls OKX liquidation endpoint every 5 minutes, maintains rolling 24h window."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 300  # 5 minutes
WINDOW_HOURS = 24


class LiquidationCollector:
    def __init__(self, okx_client, pairs: list[str]):
        self._client = okx_client
        self._pairs = pairs
        self._events: dict[str, list[dict]] = {p: [] for p in pairs}
        self._task = None

    @property
    def events(self) -> dict[str, list[dict]]:
        return self._events

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
        cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        for pair in self._pairs:
            try:
                raw = await self._client.get_liquidation_orders(pair)
                if raw:
                    for item in raw:
                        self._events[pair].append({
                            "price": float(item.get("bkPx", 0)),
                            "volume": float(item.get("sz", 0)),
                            "timestamp": datetime.now(timezone.utc),
                            "side": item.get("side", ""),
                        })
            except Exception as e:
                logger.debug("Liquidation poll for %s failed: %s", pair, e)
            finally:
                # Always prune old events, even if the API call failed,
                # to prevent unbounded memory growth
                self._events[pair] = [
                    e for e in self._events[pair] if e["timestamp"] > cutoff
                ]
