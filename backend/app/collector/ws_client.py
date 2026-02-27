import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Callable, Coroutine

import websockets

logger = logging.getLogger(__name__)

OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"

TIMEFRAME_CHANNEL_MAP = {
    "15m": "candle15m",
    "1h": "candle1H",
    "4h": "candle4H",
}

CHANNEL_TIMEFRAME_MAP = {v: k for k, v in TIMEFRAME_CHANNEL_MAP.items()}


def parse_candle_message(msg: dict) -> dict | None:
    """Parse an OKX candle WebSocket message. Returns parsed dict or None."""
    arg = msg.get("arg")
    data = msg.get("data")
    if not arg or not data:
        return None

    channel = arg.get("channel", "")
    if not channel.startswith("candle"):
        return None

    timeframe = CHANNEL_TIMEFRAME_MAP.get(channel)
    if not timeframe:
        return None

    row = data[0]
    return {
        "pair": arg["instId"],
        "timeframe": timeframe,
        "timestamp": datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
        "confirmed": row[8] == "1",
    }


def parse_funding_rate_message(msg: dict) -> dict | None:
    """Parse an OKX funding rate WebSocket message."""
    arg = msg.get("arg")
    data = msg.get("data")
    if not arg or not data:
        return None

    if arg.get("channel") != "funding-rate":
        return None

    row = data[0]
    return {
        "pair": arg["instId"],
        "funding_rate": float(row["fundingRate"]),
        "next_funding_rate": float(row["nextFundingRate"]),
        "funding_time": datetime.fromtimestamp(int(row["fundingTime"]) / 1000, tz=timezone.utc),
    }


def parse_open_interest_message(msg: dict) -> dict | None:
    """Parse an OKX open interest WebSocket message."""
    arg = msg.get("arg")
    data = msg.get("data")
    if not arg or not data:
        return None

    if arg.get("channel") != "open-interest":
        return None

    row = data[0]
    return {
        "pair": arg["instId"],
        "open_interest": float(row["oi"]),
        "timestamp": datetime.fromtimestamp(int(row["ts"]) / 1000, tz=timezone.utc),
    }


class OKXWebSocketClient:
    def __init__(
        self,
        pairs: list[str],
        timeframes: list[str],
        on_candle: Callable[[dict], Coroutine] | None = None,
        on_funding_rate: Callable[[dict], Coroutine] | None = None,
        on_open_interest: Callable[[dict], Coroutine] | None = None,
    ):
        self.pairs = pairs
        self.timeframes = timeframes
        self.on_candle = on_candle
        self.on_funding_rate = on_funding_rate
        self.on_open_interest = on_open_interest
        self._ws = None
        self._running = False

    def build_subscribe_args(self) -> list[dict]:
        args = []
        for pair in self.pairs:
            for tf in self.timeframes:
                channel = TIMEFRAME_CHANNEL_MAP.get(tf)
                if channel:
                    args.append({"channel": channel, "instId": pair})
            args.append({"channel": "funding-rate", "instId": pair})
            args.append({"channel": "open-interest", "instId": pair})
        return args

    async def connect(self):
        self._running = True
        backoff = 1
        while self._running:
            try:
                async with websockets.connect(OKX_WS_PUBLIC) as ws:
                    self._ws = ws
                    backoff = 1
                    await self._subscribe(ws)
                    await self._listen(ws)
            except (websockets.ConnectionClosed, ConnectionError, OSError) as e:
                logger.warning("OKX WS disconnected: %s. Reconnecting in %ds...", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _subscribe(self, ws):
        subscribe_args = self.build_subscribe_args()
        msg = {"op": "subscribe", "args": subscribe_args}
        await ws.send(json.dumps(msg))
        logger.info("Subscribed to %d channels", len(subscribe_args))

    async def _listen(self, ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Received malformed JSON, skipping")
                continue

            try:
                candle = parse_candle_message(msg)
                if candle and self.on_candle:
                    if candle["confirmed"]:
                        await self.on_candle(candle)
                    else:
                        logger.debug("Unconfirmed candle for %s %s, skipping", candle["pair"], candle["timeframe"])
                    continue

                funding = parse_funding_rate_message(msg)
                if funding and self.on_funding_rate:
                    await self.on_funding_rate(funding)
                    continue

                oi = parse_open_interest_message(msg)
                if oi and self.on_open_interest:
                    await self.on_open_interest(oi)
            except (KeyError, ValueError) as e:
                logger.warning("Failed to parse message: %s", e)

    async def stop(self):
        self._running = False
        if self._ws:
            await self._ws.close()
