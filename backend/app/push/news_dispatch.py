import asyncio
import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import PushSubscription

logger = logging.getLogger(__name__)


async def dispatch_push_for_news(
    session_factory: async_sessionmaker,
    news: dict,
    vapid_private_key: str,
    vapid_claims_email: str,
):
    """Send Web Push for a high-impact news alert to all subscribers."""
    if not vapid_private_key:
        return

    async with session_factory() as session:
        result = await session.execute(select(PushSubscription))
        subscriptions = result.scalars().all()

    impact = news.get("impact", "")
    headline = news.get("headline", "News alert")
    sentiment = news.get("sentiment", "")

    payload = json.dumps({
        "title": f"[{impact.upper()}] News Alert",
        "body": f"{headline} ({sentiment})",
        "url": "/news",
    })

    for sub in subscriptions:
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
                },
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": vapid_claims_email},
            )
        except WebPushException as e:
            logger.warning("News push failed for %s: %s", sub.endpoint, e)
