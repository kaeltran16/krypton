import asyncio
import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import PushSubscription

logger = logging.getLogger(__name__)


async def dispatch_push_for_alert(
    session_factory: async_sessionmaker,
    alert_id: str,
    label: str,
    trigger_value: float,
    urgency: str,
    vapid_private_key: str,
    vapid_claims_email: str,
):
    """Send Web Push for an alert to all subscribers.

    Unlike signal push, alert push does NOT filter by pair/timeframe/threshold —
    the alert definition itself is the filter.
    """
    if not vapid_private_key:
        return

    async with session_factory() as session:
        result = await session.execute(select(PushSubscription))
        subscriptions = result.scalars().all()

    payload = json.dumps({
        "type": "alert",
        "alert_id": alert_id,
        "label": label,
        "trigger_value": trigger_value,
        "urgency": urgency,
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
            logger.warning("Alert push failed for %s: %s", sub.endpoint, e)
