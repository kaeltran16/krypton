import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Coroutine

import httpx

logger = logging.getLogger(__name__)

OKX_REST_BASE = "https://www.okx.com"
LONG_SHORT_ENDPOINT = "/api/v5/rubik/stat/contracts/long-short-account-ratio"


def parse_long_short_response(raw: dict, pair: str) -> dict | None:
    if raw.get("code") != "0" or not raw.get("data"):
        return None
    row = raw["data"][0]
    return {
        "pair": pair,
        "timestamp": datetime.fromtimestamp(int(row["ts"]) / 1000, tz=timezone.utc),
        "long_short_ratio": float(row["longShortRatio"]),
    }


class OKXRestPoller:
    def __init__(
        self,
        pairs: list[str],
        interval_seconds: int = 300,
        on_data: Callable[[dict], Coroutine] | None = None,
    ):
        self.pairs = pairs
        self.interval_seconds = interval_seconds
        self.on_data = on_data
        self._running = False

    async def fetch_once(self):
        async with httpx.AsyncClient(base_url=OKX_REST_BASE, timeout=10) as client:
            for pair in self.pairs:
                try:
                    resp = await client.get(
                        LONG_SHORT_ENDPOINT,
                        params={"instId": pair, "period": "5m"},
                    )
                    resp.raise_for_status()
                    result = parse_long_short_response(resp.json(), pair)
                    if result and self.on_data:
                        await self.on_data(result)
                except Exception as e:
                    logger.error("Failed to fetch long/short for %s: %s", pair, e)

    async def run(self):
        self._running = True
        while self._running:
            await self.fetch_once()
            await asyncio.sleep(self.interval_seconds)

    def stop(self):
        self._running = False
