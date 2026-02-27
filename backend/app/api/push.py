from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import delete

from app.db.models import PushSubscription

router = APIRouter(prefix="/api/push")


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: dict
    pairs: list[str]
    timeframes: list[str]
    threshold: int = 50


class UnsubscribeRequest(BaseModel):
    endpoint: str


@router.post("/subscribe")
async def subscribe(req: SubscribeRequest, request: Request):
    async with request.app.state.session_factory() as session:
        await session.execute(
            delete(PushSubscription).where(PushSubscription.endpoint == req.endpoint)
        )
        sub = PushSubscription(
            endpoint=req.endpoint,
            p256dh_key=req.keys["p256dh"],
            auth_key=req.keys["auth"],
            pairs=req.pairs,
            timeframes=req.timeframes,
            threshold=req.threshold,
        )
        session.add(sub)
        await session.commit()

    return {"status": "subscribed"}


@router.post("/unsubscribe")
async def unsubscribe(req: UnsubscribeRequest, request: Request):
    async with request.app.state.session_factory() as session:
        await session.execute(
            delete(PushSubscription).where(PushSubscription.endpoint == req.endpoint)
        )
        await session.commit()

    return {"status": "unsubscribed"}
