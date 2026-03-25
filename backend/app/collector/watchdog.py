"""Background data freshness watchdog -- logs warnings when sources go stale."""

import asyncio
import logging

from app.collector.freshness import compute_freshness

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30


async def _check_once(app_state):
    report = await compute_freshness(app_state)

    for key, info in report.get("candles", {}).items():
        if info.get("stale"):
            logger.warning("Candle data stale: %s (age=%s)", key, info.get("seconds_ago"))

    for pair, info in report.get("order_flow", {}).items():
        if info.get("stale"):
            logger.warning("Order flow stale: %s (age=%s)", pair, info.get("seconds_ago"))

    for pair, info in report.get("onchain", {}).items():
        if info.get("stale"):
            logger.warning("On-chain data stale: %s (present=%s/%s)", pair, info.get("metrics_present"), info.get("metrics_total"))

    liq = report.get("liquidation", {})
    if isinstance(liq, dict) and liq.get("stale"):
        logger.warning("Liquidation data stale (age=%s)", liq.get("seconds_ago"))


async def run_watchdog(app_state):
    """Background loop checking data freshness every 30 seconds."""
    while True:
        try:
            await _check_once(app_state)
        except Exception as e:
            logger.error("Watchdog check failed: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)
