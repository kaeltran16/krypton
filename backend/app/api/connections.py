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
                    await ws.send_json({"type": "signal", "signal": signal})
                except Exception:
                    dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_candle(self, candle: dict):
        dead = []
        for ws, sub in list(self.connections.items()):
            if candle["pair"] in sub["pairs"] and candle["timeframe"] in sub["timeframes"]:
                try:
                    await ws.send_json({"type": "candle", "candle": candle})
                except Exception:
                    dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def _broadcast_to_all(self, payload: dict):
        """Broadcast a payload to all connected clients (no filtering)."""
        dead = []
        for ws in list(self.connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_news(self, alert: dict):
        """Broadcast a news_alert to all connected clients."""
        await self._broadcast_to_all(alert)

    async def broadcast_alert(self, alert: dict):
        """Broadcast an alert to all connected clients."""
        await self._broadcast_to_all(alert)

    async def broadcast_scores(self, scores: dict):
        """Broadcast pipeline score breakdown to all connected clients."""
        if not self.connections:
            return
        await self._broadcast_to_all({"type": "pipeline_scores", "scores": scores})
