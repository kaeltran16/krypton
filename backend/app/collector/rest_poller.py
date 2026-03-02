import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Coroutine

import httpx

logger = logging.getLogger(__name__)

OKX_REST_BASE = "https://www.okx.com"
LONG_SHORT_ENDPOINT = "/api/v5/rubik/stat/contracts/long-short-account-ratio"


def _pair_to_ccy(pair: str) -> str:
    return pair.partition("-")[0] or pair


def _looks_like_millis_timestamp(value) -> bool:
    text = str(value)
    return text.isdigit() and len(text) >= 12


def _extract_long_short_fields(row) -> tuple[str, str] | None:
    if isinstance(row, dict):
        ts = row.get("ts")
        ratio = row.get("longShortRatio")
        if ts in (None, "") or ratio in (None, ""):
            return None
        return str(ts), str(ratio)

    if isinstance(row, list) and len(row) >= 2:
        first = str(row[0])
        second = str(row[1])
        if _looks_like_millis_timestamp(first):
            return first, second
        if _looks_like_millis_timestamp(second):
            return second, first

    return None


def parse_long_short_response(raw: dict, pair: str) -> dict | None:
    if raw.get("code") != "0" or not raw.get("data"):
        return None

    fields = _extract_long_short_fields(raw["data"][0])
    if not fields:
        return None

    ts, ratio = fields
    return {
        "pair": pair,
        "timestamp": datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc),
        "long_short_ratio": float(ratio),
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
                        params={"ccy": _pair_to_ccy(pair), "period": "5m"},
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


