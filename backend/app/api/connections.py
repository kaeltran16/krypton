import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.connections: dict[WebSocket, dict] = {}

    async def connect(self, ws: WebSocket, pairs: list[str], timeframes: list[str]):
        await ws.accept()
        self.connections[ws] = {"pairs": pairs, "timeframes": timeframes}
        logger.info(f"Client connected. Total: {len(self.connections)}")

    def disconnect(self, ws: WebSocket):
        self.connections.pop(ws, None)
        logger.info(f"Client disconnected. Total: {len(self.connections)}")

    def update_subscription(self, ws: WebSocket, pairs: list[str], timeframes: list[str]):
        if ws in self.connections:
            self.connections[ws] = {"pairs": pairs, "timeframes": timeframes}

    async def broadcast(self, signal: dict):
        dead = []
        for ws, sub in list(self.connections.items()):
            if signal["pair"] in sub["pairs"] and signal["timeframe"] in sub["timeframes"]:
                try:
                    await ws.send_json({"type": "signal", "data": signal})
                except Exception:
                    dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
