import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.api.connections import ConnectionManager

router = APIRouter()
manager = ConnectionManager()

DEFAULT_PAIRS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
DEFAULT_TIMEFRAMES = ["15m", "1h", "4h"]


@router.websocket("/ws/signals")
async def signal_stream(websocket: WebSocket, api_key: str | None = None):
    settings = websocket.app.state.settings
    client_key = api_key or websocket.headers.get("x-api-key")
    if client_key != settings.krypton_api_key:
        await websocket.accept()
        await websocket.close(code=4001, reason="Invalid API key")
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

