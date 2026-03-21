import json

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.api.auth import ALGORITHM
from app.api.connections import ConnectionManager

router = APIRouter()
manager = ConnectionManager()

DEFAULT_PAIRS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
DEFAULT_TIMEFRAMES = ["15m", "1h", "4h"]


@router.websocket("/ws/signals")
async def signal_stream(websocket: WebSocket, token: str | None = None):
    if not token:
        await websocket.accept()
        await websocket.close(code=4001, reason="Not authenticated")
        return
    try:
        jwt.decode(token, websocket.app.state.settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        await websocket.accept()
        await websocket.close(code=4001, reason="Invalid token")
        return

    await manager.connect(websocket, DEFAULT_PAIRS, DEFAULT_TIMEFRAMES)

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
    except WebSocketDisconnect:
        manager.disconnect(websocket)

