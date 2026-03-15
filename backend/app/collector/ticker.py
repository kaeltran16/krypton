import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import websockets

logger = logging.getLogger(__name__)

OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"


class TickerCollector:
    """Subscribe to OKX ticker channel for live prices.

    Caches latest price in Redis, samples snapshots for pct_move alerts,
    and invokes price alert evaluation at throttled 1/s/pair cadence.
    """

    def __init__(
        self,
        pairs: list[str],
        redis,
        session_factory,
        manager,
        push_ctx: dict | None,
        evaluate_fn=None,
    ):
        self.pairs = pairs
        self.redis = redis
        self.session_factory = session_factory
        self.manager = manager
        self.push_ctx = push_ctx
        self._evaluate_fn = evaluate_fn
        self._running = True
        self._reconnect = False
        self._last_eval: dict[str, float] = {}  # pair -> last evaluation timestamp
        self._last_snapshot: dict[str, float] = {}  # pair -> last snapshot timestamp

    def stop(self):
        self._running = False

    def request_reconnect(self):
        """Signal the collector to reconnect with updated pairs."""
        self._reconnect = True

    async def run(self):
        """Connect to OKX public WS and subscribe to ticker channels."""
        backoff = 1
        while self._running:
            try:
                self._reconnect = False
                async with websockets.connect(OKX_WS_PUBLIC, ping_interval=20) as ws:
                    backoff = 1
                    # Subscribe to tickers for all pairs
                    sub_msg = {
                        "op": "subscribe",
                        "args": [{"channel": "tickers", "instId": p} for p in self.pairs],
                    }
                    await ws.send(json.dumps(sub_msg))
                    logger.info("Ticker collector connected for %d pairs", len(self.pairs))

                    async for raw in ws:
                        if not self._running or self._reconnect:
                            break
                        try:
                            msg = json.loads(raw)
                            await self._handle_message(msg)
                        except Exception as e:
                            logger.debug(f"Ticker message error: {e}")

                    if self._reconnect:
                        logger.info("Ticker collector reconnecting for pairs change")

            except Exception as e:
                if not self._running:
                    break
                logger.warning(f"Ticker WS error: {e}, reconnecting in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _handle_message(self, msg: dict):
        data = msg.get("data")
        if not data:
            return

        for tick in data:
            pair = tick.get("instId")
            last_price = tick.get("last")
            if not pair or not last_price:
                continue

            price = float(last_price)
            now = time.monotonic()

            # Cache latest price in Redis
            await self.redis.set(f"ticker:{pair}", str(price), ex=30)

            # Sample snapshot once per minute for pct_move alerts
            last_snap = self._last_snapshot.get(pair, 0)
            if now - last_snap >= 60:
                self._last_snapshot[pair] = now
                ts = datetime.now(timezone.utc).timestamp()
                await self.redis.zadd(f"ticker_snapshots:{pair}", {str(price): ts})
                # Trim snapshots older than 90 minutes
                cutoff = ts - (90 * 60)
                await self.redis.zremrangebyscore(f"ticker_snapshots:{pair}", "-inf", cutoff)

            # Throttle alert evaluation to 1/s per pair
            last_eval = self._last_eval.get(pair, 0)
            if now - last_eval >= 1.0 and self._evaluate_fn:
                self._last_eval[pair] = now
                try:
                    await self._evaluate_fn(
                        pair, price, self.redis,
                        self.session_factory, self.manager, self.push_ctx,
                    )
                except Exception as e:
                    logger.debug(f"Price alert evaluation error for {pair}: {e}")
