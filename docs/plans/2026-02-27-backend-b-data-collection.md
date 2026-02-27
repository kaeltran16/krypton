# Backend Plan B: Data Collection (Phase 3, Tasks 6-7)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the OKX data collection layer — a WebSocket client for real-time candles, funding rates, and open interest, plus a REST poller for long/short ratio.

**Architecture:** Two async collectors feed data into callback handlers. The WS client maintains a persistent connection with auto-reconnect. The REST poller runs on a configurable interval.

**Tech Stack:** Python 3.11, websockets, httpx, pytest + pytest-asyncio

**Depends on:** Plan A (project structure, config)
**Unlocks:** Plan D (integration wiring)

---

## Phase 3: OKX Data Collector

### Task 6: OKX WebSocket client (candles + funding rate + open interest)

**Files:**
- Create: `backend/app/collector/__init__.py` (empty)
- Create: `backend/app/collector/ws_client.py`
- Create: `backend/tests/collector/__init__.py` (empty)
- Test: `backend/tests/collector/test_ws_client.py`

**Step 0: Add `websockets` dependency**

```bash
echo "websockets==16.0" >> backend/requirements.txt
cd backend && pip install websockets==16.0
```

**Step 1: Write the failing test**

```python
# backend/tests/collector/test_ws_client.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.collector.ws_client import (
    OKXWebSocketClient,
    parse_candle_message,
    parse_funding_rate_message,
    parse_open_interest_message,
)


# --- candle parsing ---

def test_parse_candle_message_confirmed():
    """Parse a confirmed candle close message from OKX."""
    raw = {
        "arg": {"channel": "candle15m", "instId": "BTC-USDT-SWAP"},
        "data": [
            ["1709042400000", "67000.5", "67200.0", "66900.0", "67100.0", "1234.56", "0", "0", "1"]
        ],
    }
    result = parse_candle_message(raw)
    assert result is not None
    assert result["pair"] == "BTC-USDT-SWAP"
    assert result["timeframe"] == "15m"
    assert result["open"] == 67000.5
    assert result["close"] == 67100.0
    assert result["confirmed"] is True


def test_parse_candle_message_returns_floats():
    """OHLCV values must be floats, not strings."""
    raw = {
        "arg": {"channel": "candle1H", "instId": "ETH-USDT-SWAP"},
        "data": [
            ["1709042400000", "3400.25", "3450.0", "3380.0", "3420.5", "5678.9", "0", "0", "1"]
        ],
    }
    result = parse_candle_message(raw)
    assert isinstance(result["open"], float)
    assert isinstance(result["high"], float)
    assert isinstance(result["low"], float)
    assert isinstance(result["close"], float)
    assert isinstance(result["volume"], float)


def test_parse_candle_message_unconfirmed():
    """Unconfirmed candle should return result with confirmed=False."""
    raw = {
        "arg": {"channel": "candle15m", "instId": "BTC-USDT-SWAP"},
        "data": [
            ["1709042400000", "67000.5", "67200.0", "66900.0", "67100.0", "1234.56", "0", "0", "0"]
        ],
    }
    result = parse_candle_message(raw)
    assert result is not None
    assert result["confirmed"] is False


def test_parse_candle_message_invalid():
    """Invalid message returns None."""
    result = parse_candle_message({"event": "subscribe"})
    assert result is None


# --- funding rate parsing ---

def test_parse_funding_rate_message():
    """Parse a funding rate push from OKX."""
    raw = {
        "arg": {"channel": "funding-rate", "instId": "BTC-USDT-SWAP"},
        "data": [
            {
                "fundingRate": "0.00015",
                "fundingTime": "1709049600000",
                "instId": "BTC-USDT-SWAP",
                "instType": "SWAP",
                "nextFundingRate": "0.00012",
                "nextFundingTime": "1709078400000",
            }
        ],
    }
    result = parse_funding_rate_message(raw)
    assert result is not None
    assert result["pair"] == "BTC-USDT-SWAP"
    assert result["funding_rate"] == 0.00015
    assert result["next_funding_rate"] == 0.00012


def test_parse_funding_rate_message_invalid():
    result = parse_funding_rate_message({"event": "subscribe"})
    assert result is None


# --- open interest parsing ---

def test_parse_open_interest_message():
    """Parse an open interest push from OKX."""
    raw = {
        "arg": {"channel": "open-interest", "instId": "BTC-USDT-SWAP"},
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "instType": "SWAP",
                "oi": "45000",
                "oiCcy": "45000",
                "ts": "1709042400000",
            }
        ],
    }
    result = parse_open_interest_message(raw)
    assert result is not None
    assert result["pair"] == "BTC-USDT-SWAP"
    assert result["open_interest"] == 45000.0


def test_parse_open_interest_message_invalid():
    result = parse_open_interest_message({"event": "subscribe"})
    assert result is None


# --- subscription building ---

def test_build_subscribe_args():
    """Build correct subscription args for pairs and timeframes."""
    client = OKXWebSocketClient(
        pairs=["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
        timeframes=["15m", "1h"],
    )
    args = client.build_subscribe_args()
    # 2 pairs * 2 timeframes (candles) + 2 pairs (funding-rate) + 2 pairs (open-interest) = 8
    assert len(args) == 8
    assert {"channel": "candle15m", "instId": "BTC-USDT-SWAP"} in args
    assert {"channel": "candle1H", "instId": "ETH-USDT-SWAP"} in args
    assert {"channel": "funding-rate", "instId": "BTC-USDT-SWAP"} in args
    assert {"channel": "open-interest", "instId": "ETH-USDT-SWAP"} in args


def test_timeframe_to_channel_mapping():
    """Timeframe strings map to OKX channel names."""
    client = OKXWebSocketClient(pairs=["BTC-USDT-SWAP"], timeframes=["15m", "1h", "4h"])
    args = client.build_subscribe_args()
    channels = {a["channel"] for a in args}
    assert channels == {"candle15m", "candle1H", "candle4H", "funding-rate", "open-interest"}
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/collector/test_ws_client.py -v
```

Expected: FAIL — `ImportError`

**Step 3: Implement ws_client.py**

```python
# backend/app/collector/ws_client.py
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
```

**Step 4: Run tests**

```bash
cd backend && python -m pytest tests/collector/test_ws_client.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/app/collector/__init__.py backend/app/collector/ws_client.py backend/tests/collector/__init__.py backend/tests/collector/test_ws_client.py
git commit -m "feat: add OKX WebSocket client with candle, funding rate, and open interest parsing"
```

---

### Task 7: REST poller for long/short ratio

**Files:**
- Create: `backend/app/collector/rest_poller.py`
- Test: `backend/tests/collector/test_rest_poller.py`

**Step 1: Write the failing test**

```python
# backend/tests/collector/test_rest_poller.py
from unittest.mock import AsyncMock, patch

from app.collector.rest_poller import OKXRestPoller, parse_long_short_response


def test_parse_long_short_response_valid():
    """Parse valid long/short ratio response."""
    raw = {
        "code": "0",
        "data": [
            {"ts": "1709042400000", "longShortRatio": "1.25"}
        ],
    }
    result = parse_long_short_response(raw, "BTC-USDT-SWAP")
    assert result is not None
    assert result["pair"] == "BTC-USDT-SWAP"
    assert result["long_short_ratio"] == 1.25


def test_parse_long_short_response_invalid():
    """Invalid response returns None."""
    result = parse_long_short_response({"code": "1"}, "BTC-USDT-SWAP")
    assert result is None


async def test_poller_fetches_for_all_pairs():
    """Poller should fetch long/short ratio for each configured pair."""
    poller = OKXRestPoller(
        pairs=["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
        interval_seconds=300,
    )
    mock_callback = AsyncMock()
    poller.on_data = mock_callback

    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "code": "0",
        "data": [{"ts": "1709042400000", "longShortRatio": "1.5"}],
    }
    mock_response.raise_for_status = lambda: None

    with patch("app.collector.rest_poller.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        await poller.fetch_once()

    assert mock_callback.call_count == 2
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/collector/test_rest_poller.py -v
```

Expected: FAIL — `ImportError`

**Step 3: Implement rest_poller.py**

```python
# backend/app/collector/rest_poller.py
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
```

**Step 4: Run tests**

```bash
cd backend && python -m pytest tests/collector/test_rest_poller.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/app/collector/rest_poller.py backend/tests/collector/test_rest_poller.py
git commit -m "feat: add OKX REST poller for long/short ratio"
```
