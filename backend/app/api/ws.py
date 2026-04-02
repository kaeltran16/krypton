import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket

from app.api.auth import verify_ws_token

router = APIRouter()

logger = logging.getLogger(__name__)

DEFAULT_PAIRS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
DEFAULT_TIMEFRAMES = ["15m", "1h", "4h"]

_AUTH_TIMEOUT_S = 10


@router.websocket("/ws/signals")
async def signal_stream(websocket: WebSocket):
    await websocket.accept()

    # wait for auth message
    try:
        raw = await asyncio.wait_for(
            websocket.receive_json(), timeout=_AUTH_TIMEOUT_S
        )
    except Exception:
        await websocket.close(code=4001, reason="Auth timeout")
        return

    secret = websocket.app.state.settings.jwt_secret
    if raw.get("type") != "auth" or not verify_ws_token(
        raw.get("token", ""), secret
    ):
        await websocket.close(code=4001, reason="Invalid token")
        return

    manager = websocket.app.state.manager
    manager.connect_existing(websocket, DEFAULT_PAIRS, DEFAULT_TIMEFRAMES)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "subscribe":
                pairs = msg.get("pairs", DEFAULT_PAIRS)
                timeframes = msg.get("timeframes", DEFAULT_TIMEFRAMES)
                manager.update_subscription(websocket, pairs, timeframes)
    except Exception:
        manager.disconnect(websocket)
