import asyncio
import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import PushSubscription

logger = logging.getLogger(__name__)


async def dispatch_push_for_signal(
    session_factory: async_sessionmaker,
    signal: dict,
    vapid_private_key: str,
    vapid_claims_email: str,
):
    if not vapid_private_key:
        return

    async with session_factory() as session:
        result = await session.execute(select(PushSubscription))
        subscriptions = result.scalars().all()

    for sub in subscriptions:
        if signal["pair"] not in sub.pairs:
            continue
        if signal["timeframe"] not in sub.timeframes:
            continue
        if abs(signal["final_score"]) < sub.threshold:
            continue

        payload = json.dumps({
            "title": f"{signal['direction']} {signal['pair']}",
            "body": f"Score: {signal['final_score']} | {signal['timeframe']}",
            "url": "/",
        })

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
            logger.warning("Push failed for %s: %s", sub.endpoint, e)
