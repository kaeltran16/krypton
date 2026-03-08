"""News & events collector.

Polls API sources (CryptoPanic, CoinGecko news) and RSS feeds on a
configurable interval. Deduplicates, scores via LLM, persists to Postgres,
and triggers alerts for high-impact news.
"""
import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone, timedelta

import feedparser
import httpx
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import NewsEvent

logger = logging.getLogger(__name__)

CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/"
COINGECKO_NEWS_URL = "https://api.coingecko.com/api/v3/news"


def normalize_headline(headline: str) -> str:
    """Normalize headline for fingerprinting: lowercase, strip punctuation/whitespace."""
    text = headline.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def fingerprint_headline(headline: str) -> str:
    """SHA-256 of normalized headline for dedup."""
    return hashlib.sha256(normalize_headline(headline).encode()).hexdigest()


def is_relevant(headline: str, pairs: list[str], keywords: list[str]) -> bool:
    """Check if headline mentions a tracked pair symbol or macro keyword."""
    text = headline.lower()
    # Check pair symbols (e.g. BTC, ETH from BTC-USDT-SWAP)
    for pair in pairs:
        symbol = pair.split("-")[0].lower()
        if symbol in text:
            return True
    # Check macro keywords
    for kw in keywords:
        if kw.lower() in text:
            return True
    return False


def extract_affected_pairs(headline: str, pairs: list[str], keywords: list[str]) -> list[str]:
    """Determine which pairs a headline affects."""
    text = headline.lower()
    affected = []
    for pair in pairs:
        symbol = pair.split("-")[0].lower()
        if symbol in text:
            affected.append(symbol.upper())
    # If no specific pair matched but macro keyword hit, it affects ALL
    if not affected:
        for kw in keywords:
            if kw.lower() in text:
                return ["ALL"]
    return affected or ["ALL"]


async def is_url_duplicate(session, url: str) -> bool:
    """Pass 1: exact URL match."""
    result = await session.execute(
        select(NewsEvent.id).where(NewsEvent.url == url).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def is_headline_duplicate(session, headline: str, threshold: float = 85.0) -> bool:
    """Pass 2: fuzzy headline match against last 6 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    result = await session.execute(
        select(NewsEvent.headline)
        .where(NewsEvent.created_at >= cutoff)
        .order_by(NewsEvent.created_at.desc())
        .limit(200)
    )
    recent_headlines = [row[0] for row in result.all()]
    normalized = normalize_headline(headline)
    for existing in recent_headlines:
        ratio = fuzz.ratio(normalized, normalize_headline(existing))
        if ratio > threshold:
            return True
    return False


async def score_headlines_with_llm(
    headlines: list[dict],
    api_key: str,
    model: str,
    timeout: int = 30,
) -> list[dict]:
    """Batch score up to 10 headlines via LLM.

    Returns list of dicts with keys: impact, sentiment, summary, affected_pairs.
    """
    if not api_key or not headlines:
        return [{}] * len(headlines)

    numbered = "\n".join(
        f"{i+1}. [{h.get('source', '?')}] {h['headline']}"
        for i, h in enumerate(headlines)
    )

    prompt = f"""Score these news headlines for crypto market impact.
For each headline, respond with a JSON array where each element has:
- "impact": "high" | "medium" | "low"
- "sentiment": "bullish" | "bearish" | "neutral"
- "summary": one-sentence explanation of market relevance

Headlines:
{numbered}

Respond ONLY with the JSON array, no other text."""

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 1500,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

            # Parse JSON from possible markdown code block
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            scores = json.loads(content)
            if isinstance(scores, list) and len(scores) == len(headlines):
                return scores
    except Exception as e:
        logger.error(f"LLM headline scoring failed: {e}")

    return [{}] * len(headlines)


class NewsCollector:
    def __init__(
        self,
        pairs: list[str],
        db,
        redis,
        ws_manager,
        poll_interval: int = 150,
        cryptopanic_api_key: str = "",
        news_api_key: str = "",
        openrouter_api_key: str = "",
        openrouter_model: str = "anthropic/claude-3.5-sonnet",
        relevance_keywords: list[str] | None = None,
        rss_feeds: list[dict] | None = None,
        llm_daily_budget: int = 200,
        high_impact_push_enabled: bool = True,
        vapid_private_key: str = "",
        vapid_claims_email: str = "",
    ):
        self.pairs = pairs
        self.db = db
        self.redis = redis
        self.ws_manager = ws_manager
        self.poll_interval = poll_interval
        self.cryptopanic_api_key = cryptopanic_api_key
        self.news_api_key = news_api_key
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_model = openrouter_model
        self.relevance_keywords = relevance_keywords or []
        self.rss_feeds = rss_feeds or []
        self.llm_daily_budget = llm_daily_budget
        self.high_impact_push_enabled = high_impact_push_enabled
        self.vapid_private_key = vapid_private_key
        self.vapid_claims_email = vapid_claims_email
        self._running = False
        self._llm_calls_today = 0
        self._budget_reset_date = datetime.now(timezone.utc).date()

    def _check_budget(self):
        """Reset daily LLM call counter at midnight UTC."""
        today = datetime.now(timezone.utc).date()
        if today != self._budget_reset_date:
            self._llm_calls_today = 0
            self._budget_reset_date = today

    async def run(self):
        self._running = True
        # Validate RSS feeds on startup
        await self._validate_feeds()
        while self._running:
            try:
                await self._poll_cycle()
            except Exception as e:
                logger.error(f"News poll cycle failed: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _validate_feeds(self):
        """Log warnings for unreachable RSS feeds on startup."""
        async with httpx.AsyncClient(timeout=10) as client:
            for feed in self.rss_feeds:
                url = feed.get("url", "")
                try:
                    resp = await client.head(url)
                    if resp.status_code >= 400:
                        logger.warning(f"RSS feed unreachable ({resp.status_code}): {url}")
                except Exception as e:
                    logger.warning(f"RSS feed unreachable: {url} — {e}")

    async def _poll_cycle(self):
        """Single poll cycle: gather headlines, dedup, score, persist."""
        raw_headlines = []

        # Gather from all sources
        async with httpx.AsyncClient(timeout=15) as client:
            raw_headlines.extend(await self._fetch_cryptopanic(client))
            raw_headlines.extend(await self._fetch_rss())

        # Filter for relevance
        relevant = [
            h for h in raw_headlines
            if is_relevant(h["headline"], self.pairs, self.relevance_keywords)
        ]

        if not relevant:
            return

        # Dedup and persist
        to_score = []
        async with self.db.session_factory() as session:
            for h in relevant:
                # Pass 1: URL dedup
                if await is_url_duplicate(session, h["url"]):
                    continue
                # Pass 2: fuzzy headline dedup
                if await is_headline_duplicate(session, h["headline"]):
                    continue

                h["affected_pairs"] = extract_affected_pairs(
                    h["headline"], self.pairs, self.relevance_keywords,
                )
                h["fingerprint"] = fingerprint_headline(h["headline"])
                to_score.append(h)

        if not to_score:
            return

        # LLM scoring in batches of 10
        self._check_budget()
        scored = []
        for i in range(0, len(to_score), 10):
            batch = to_score[i:i+10]
            if self._llm_calls_today < self.llm_daily_budget:
                llm_results = await score_headlines_with_llm(
                    batch, self.openrouter_api_key, self.openrouter_model,
                )
                self._llm_calls_today += 1
                for h, llm in zip(batch, llm_results):
                    h["impact"] = llm.get("impact")
                    h["sentiment"] = llm.get("sentiment")
                    h["llm_summary"] = llm.get("summary")
            # else: headlines stored without scoring
            scored.extend(batch)

        # Persist to DB and alert
        async with self.db.session_factory() as session:
            for h in scored:
                try:
                    stmt = pg_insert(NewsEvent).values(
                        headline=h["headline"],
                        source=h["source"],
                        url=h["url"],
                        fingerprint=h["fingerprint"],
                        category=h.get("category", "crypto"),
                        impact=h.get("impact"),
                        sentiment=h.get("sentiment"),
                        affected_pairs=h.get("affected_pairs", []),
                        llm_summary=h.get("llm_summary"),
                        published_at=h.get("published_at", datetime.now(timezone.utc)),
                    ).on_conflict_do_nothing(constraint="uq_news_url")
                    result = await session.execute(stmt)
                    await session.flush()

                    # Alert for high impact
                    if h.get("impact") == "high" and result.rowcount > 0:
                        # Get the inserted row ID
                        row = await session.execute(
                            select(NewsEvent).where(NewsEvent.url == h["url"])
                        )
                        news_event = row.scalar_one_or_none()
                        if news_event and news_event.alerted_at is None:
                            await self._broadcast_alert(news_event)
                            news_event.alerted_at = datetime.now(timezone.utc)
                except Exception as e:
                    logger.error(f"Failed to persist news: {h.get('headline', '?')}: {e}")

            await session.commit()

    async def _fetch_cryptopanic(self, client: httpx.AsyncClient) -> list[dict]:
        """Fetch from CryptoPanic API."""
        if not self.cryptopanic_api_key:
            return []
        try:
            resp = await client.get(
                CRYPTOPANIC_URL,
                params={"auth_token": self.cryptopanic_api_key, "public": "true"},
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for post in data.get("results", []):
                published = post.get("published_at", "")
                try:
                    pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pub_dt = datetime.now(timezone.utc)
                results.append({
                    "headline": post.get("title", ""),
                    "source": "cryptopanic",
                    "url": post.get("url", ""),
                    "category": "crypto",
                    "published_at": pub_dt,
                })
            return results
        except Exception as e:
            logger.debug(f"CryptoPanic fetch failed: {e}")
            return []

    async def _fetch_rss(self) -> list[dict]:
        """Fetch and parse all configured RSS feeds."""
        results = []
        for feed_config in self.rss_feeds:
            url = feed_config.get("url", "")
            category = feed_config.get("category", "macro")
            try:
                parsed = await asyncio.to_thread(feedparser.parse, url)
                for entry in parsed.entries[:20]:  # Limit per feed
                    pub_dt = datetime.now(timezone.utc)
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        from calendar import timegm
                        pub_dt = datetime.fromtimestamp(
                            timegm(entry.published_parsed), tz=timezone.utc,
                        )

                    results.append({
                        "headline": entry.get("title", ""),
                        "source": f"rss_{_feed_name(url)}",
                        "url": entry.get("link", url),
                        "category": category,
                        "published_at": pub_dt,
                    })
            except Exception as e:
                logger.debug(f"RSS fetch failed for {url}: {e}")
        return results

    async def _broadcast_alert(self, news_event: NewsEvent):
        """Send news_alert via WebSocket + Web Push for high-impact news."""
        alert = {
            "type": "news_alert",
            "news": {
                "id": news_event.id,
                "headline": news_event.headline,
                "source": news_event.source,
                "category": news_event.category,
                "impact": news_event.impact,
                "sentiment": news_event.sentiment,
                "affected_pairs": news_event.affected_pairs,
                "llm_summary": news_event.llm_summary,
                "published_at": news_event.published_at.isoformat()
                if news_event.published_at else None,
            },
        }
        try:
            await self.ws_manager.broadcast_news(alert)
        except Exception as e:
            logger.error(f"News WS broadcast failed: {e}")

        # Web Push
        if self.high_impact_push_enabled and self.vapid_private_key:
            try:
                from app.push.news_dispatch import dispatch_push_for_news
                await dispatch_push_for_news(
                    session_factory=self.db.session_factory,
                    news=alert["news"],
                    vapid_private_key=self.vapid_private_key,
                    vapid_claims_email=self.vapid_claims_email,
                )
            except Exception as e:
                logger.error(f"News push dispatch failed: {e}")

    def stop(self):
        self._running = False


def _feed_name(url: str) -> str:
    """Extract a short name from RSS feed URL for the source field."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname or "unknown"
    # Strip www. prefix
    if host.startswith("www."):
        host = host[4:]
    # Take first part of domain
    return host.split(".")[0]
