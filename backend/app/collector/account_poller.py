import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class AccountPoller:
    """Poll OKX account balance every 60s for portfolio alert evaluation."""

    def __init__(
        self,
        okx_client,
        redis,
        session_factory,
        manager,
        push_ctx: dict | None,
        evaluate_fn=None,
        interval: int = 60,
    ):
        self.okx_client = okx_client
        self.redis = redis
        self.session_factory = session_factory
        self.manager = manager
        self.push_ctx = push_ctx
        self._evaluate_fn = evaluate_fn
        self.interval = interval
        self._running = True

    def stop(self):
        self._running = False

    async def run(self):
        while self._running:
            try:
                await self._poll()
            except Exception as e:
                logger.error(f"Account poll failed: {e}")
            await asyncio.sleep(self.interval)

    async def _poll(self):
        if not self.okx_client:
            return

        # Fetch balance and positions in parallel
        balance, positions = await asyncio.gather(
            self.okx_client.get_balance(),
            self.okx_client.get_positions(),
            return_exceptions=True,
        )
        if isinstance(balance, Exception) or not balance:
            return
        if isinstance(positions, Exception):
            positions = []

        # Cache in Redis
        await self.redis.set(
            "account:balance", json.dumps(balance), ex=self.interval * 2
        )

        # Evaluate portfolio alerts
        if self._evaluate_fn:
            try:
                balance_data = {**balance, "positions": positions or []}
                await self._evaluate_fn(
                    balance_data, self.redis,
                    self.session_factory, self.manager, self.push_ctx,
                )
            except Exception as e:
                logger.debug(f"Portfolio alert evaluation error: {e}")

        # broadcast portfolio update to WS clients
        try:
            equity = balance["total_equity"]
            available = 0.0
            for c in balance.get("currencies", []):
                if c["currency"] == "USDT":
                    available = c["available"]
                    break
            used_margin = sum(p.get("margin", 0) for p in (positions or []))
            total_exposure = sum(
                abs(p.get("size", 0) * p.get("mark_price", 0))
                for p in (positions or [])
            )
            margin_utilization = (used_margin / equity * 100) if equity > 0 else 0

            await self.manager.broadcast_event({
                "type": "account_update",
                "total_equity": equity,
                "unrealized_pnl": balance["unrealized_pnl"],
                "available_balance": round(available, 2),
                "used_margin": round(used_margin, 2),
                "total_exposure": round(total_exposure, 2),
                "margin_utilization": round(margin_utilization, 1),
                "positions": positions or [],
            })
        except Exception as e:
            logger.debug(f"Portfolio broadcast failed: {e}")
