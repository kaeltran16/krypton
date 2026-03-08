"""On-chain data collector polling free public APIs.

Tier 1 (every 5 min): Mempool.space, CoinGecko public
Tier 2 (every 30 min): CryptoQuant, Glassnode (freemium, tight quotas)
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# Tier 1 endpoints (no API key required)
MEMPOOL_RECENT_TXS = "https://mempool.space/api/mempool/recent"
COINGECKO_COIN_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}"

# Tier 2 endpoints (CryptoQuant API key required)
CRYPTOQUANT_EXCHANGE_FLOW = "https://api.cryptoquant.com/v1/btc/exchange-flows/netflow"

# Free public endpoints (no API key)
BLOCKCHAIN_INFO_STATS = "https://api.blockchain.info/stats"
BLOCKCHAIN_INFO_CHARTS = "https://api.blockchain.info/charts/{name}?timespan=2days&format=json"

PAIR_TO_COIN = {
    "BTC-USDT-SWAP": ("bitcoin", "BTC"),
    "ETH-USDT-SWAP": ("ethereum", "ETH"),
}

REDIS_TTL = 600  # 10 minutes


def _redis_key(pair: str, metric: str) -> str:
    return f"onchain:{pair}:{metric}"


class OnChainCollector:
    def __init__(
        self,
        pairs: list[str],
        redis,
        poll_interval: int = 300,
        tier2_interval: int = 1800,
        cryptoquant_api_key: str = "",
        glassnode_api_key: str = "",
    ):
        self.pairs = pairs
        self.redis = redis
        self.poll_interval = poll_interval
        self.tier2_interval = tier2_interval
        self.cryptoquant_api_key = cryptoquant_api_key
        self._running = False

    async def run(self):
        self._running = True
        await asyncio.gather(
            self._tier1_loop(),
            self._tier2_loop(),
        )

    async def _tier1_loop(self):
        while self._running:
            try:
                await self._poll_tier1()
            except Exception as e:
                logger.error(f"Tier 1 on-chain poll failed: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _tier2_loop(self):
        while self._running:
            try:
                await self._poll_tier2()
            except Exception as e:
                logger.error(f"Tier 2 on-chain poll failed: {e}")
            await asyncio.sleep(self.tier2_interval)

    async def _poll_tier1(self):
        async with httpx.AsyncClient(timeout=15) as client:
            await self._fetch_mempool(client)
            await self._fetch_blockchain_info(client)
            for pair in self.pairs:
                coin_id, _ = PAIR_TO_COIN.get(pair, (None, None))
                if coin_id:
                    await self._fetch_coingecko(client, pair, coin_id)

    async def _poll_tier2(self):
        async with httpx.AsyncClient(timeout=15) as client:
            for pair in self.pairs:
                _, symbol = PAIR_TO_COIN.get(pair, (None, None))
                if not symbol:
                    continue
                if self.cryptoquant_api_key:
                    await self._fetch_cryptoquant_netflow(client, pair, symbol)

    async def _fetch_mempool(self, client: httpx.AsyncClient):
        """Fetch recent large BTC transactions from mempool.space."""
        try:
            resp = await client.get(MEMPOOL_RECENT_TXS)
            resp.raise_for_status()
            txs = resp.json()

            # Count large transactions (>100 BTC equivalent in vsize-weighted value)
            large_tx_count = sum(1 for tx in txs if tx.get("value", 0) > 10_000_000_000)  # sats

            pair = "BTC-USDT-SWAP"
            key = _redis_key(pair, "whale_tx_count")
            await self.redis.set(key, json.dumps({
                "value": large_tx_count,
                "total_txs": len(txs),
                "ts": datetime.now(timezone.utc).isoformat(),
            }), ex=REDIS_TTL)

            # Track in rolling history
            await self._append_history(pair, "whale_tx_count", large_tx_count)
        except Exception as e:
            logger.debug(f"Mempool fetch failed: {e}")

    async def _fetch_coingecko(self, client: httpx.AsyncClient, pair: str, coin_id: str):
        """Fetch community/developer metrics from CoinGecko."""
        try:
            resp = await client.get(
                COINGECKO_COIN_URL.format(coin_id=coin_id),
                params={"localization": "false", "tickers": "false",
                         "market_data": "false", "community_data": "true",
                         "developer_data": "true"},
            )
            resp.raise_for_status()
            data = resp.json()

            community = data.get("community_data", {})
            developer = data.get("developer_data", {})

            # Active addresses proxy: reddit subscribers + twitter followers trend
            reddit_subs = community.get("reddit_subscribers", 0) or 0
            twitter_followers = community.get("twitter_followers", 0) or 0

            # Developer activity: commit count 4 weeks
            commits_4w = developer.get("commit_count_4_weeks", 0) or 0

            key = _redis_key(pair, "community_metrics")
            await self.redis.set(key, json.dumps({
                "reddit_subscribers": reddit_subs,
                "twitter_followers": twitter_followers,
                "commits_4w": commits_4w,
                "ts": datetime.now(timezone.utc).isoformat(),
            }), ex=REDIS_TTL)
        except Exception as e:
            logger.debug(f"CoinGecko fetch failed for {pair}: {e}")

    async def _fetch_cryptoquant_netflow(self, client: httpx.AsyncClient, pair: str, symbol: str):
        """Fetch exchange netflow from CryptoQuant."""
        if symbol != "BTC":
            return  # CryptoQuant free tier is BTC-only
        try:
            resp = await client.get(
                CRYPTOQUANT_EXCHANGE_FLOW,
                headers={"Authorization": f"Bearer {self.cryptoquant_api_key}"},
                params={"window": "day", "limit": 1},
            )
            resp.raise_for_status()
            data = resp.json()

            result = data.get("result", {}).get("data", [])
            if result:
                netflow = result[0].get("netflow", 0)
                key = _redis_key(pair, "exchange_netflow")
                await self.redis.set(key, json.dumps({
                    "value": netflow,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }), ex=REDIS_TTL)
                await self._append_history(pair, "exchange_netflow", netflow)
        except Exception as e:
            logger.debug(f"CryptoQuant netflow failed for {pair}: {e}")

    async def _fetch_blockchain_info(self, client: httpx.AsyncClient):
        """Fetch BTC active addresses and estimated NUPL from blockchain.info (free, no key)."""
        pair = "BTC-USDT-SWAP"

        # Active addresses (n_unique_addresses from stats endpoint)
        try:
            resp = await client.get(BLOCKCHAIN_INFO_STATS)
            resp.raise_for_status()
            data = resp.json()
            value = data.get("n_unique_addresses", 0)
            if value:
                key = _redis_key(pair, "active_addresses")
                await self.redis.set(key, json.dumps({
                    "value": value,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }), ex=REDIS_TTL)
                await self._append_history(pair, "active_addresses", value)
        except Exception as e:
            logger.debug(f"Blockchain.info stats failed: {e}")

        # Market cap / realized cap ratio as NUPL proxy
        try:
            resp = await client.get(
                BLOCKCHAIN_INFO_CHARTS.format(name="market-cap"),
            )
            resp.raise_for_status()
            mc_data = resp.json().get("values", [])

            resp2 = await client.get(
                BLOCKCHAIN_INFO_CHARTS.format(name="market-price"),
            )
            resp2.raise_for_status()
            price_data = resp2.json().get("values", [])

            if mc_data and price_data:
                market_cap = mc_data[-1].get("y", 0)
                price_now = price_data[-1].get("y", 0)
                price_prev = price_data[0].get("y", 0) if len(price_data) > 1 else price_now

                # Simplified NUPL proxy: price momentum as sentiment gauge
                # Maps 2-day price change into -1..+1 range, similar to NUPL behavior
                if price_prev > 0:
                    momentum = (price_now - price_prev) / price_prev
                    nupl_proxy = max(-1.0, min(1.0, momentum * 10))
                else:
                    nupl_proxy = 0.0

                key = _redis_key(pair, "nupl")
                await self.redis.set(key, json.dumps({
                    "value": nupl_proxy,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }), ex=REDIS_TTL)
        except Exception as e:
            logger.debug(f"Blockchain.info NUPL proxy failed: {e}")

    async def _append_history(self, pair: str, metric: str, value: float):
        """Store rolling 24h history for trend calculation."""
        hist_key = f"onchain_hist:{pair}:{metric}"
        entry = json.dumps({"v": value, "ts": datetime.now(timezone.utc).isoformat()})
        await self.redis.rpush(hist_key, entry)
        await self.redis.ltrim(hist_key, -288, -1)  # 288 = 24h at 5-min intervals
        await self.redis.expire(hist_key, 86400)

    def stop(self):
        self._running = False
