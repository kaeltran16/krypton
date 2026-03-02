from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.connections import ConnectionManager


@pytest.mark.asyncio
async def test_connection_manager_broadcast_matching():
    """Manager should broadcast signal to clients subscribed to matching pair/timeframe."""
    manager = ConnectionManager()

    mock_ws = AsyncMock()
    manager.connections[mock_ws] = {"pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}

    signal = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "direction": "LONG", "final_score": 75}
    await manager.broadcast(signal)

    mock_ws.send_json.assert_called_once_with({"type": "signal", "signal": signal})


@pytest.mark.asyncio
async def test_connection_manager_skips_non_matching():
    """Manager should skip clients not subscribed to the signal's pair/timeframe."""
    manager = ConnectionManager()

    mock_ws = AsyncMock()
    manager.connections[mock_ws] = {"pairs": ["ETH-USDT-SWAP"], "timeframes": ["1h"]}

    signal = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "direction": "LONG", "final_score": 75}
    await manager.broadcast(signal)

    mock_ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_connection_manager_removes_dead_connection():
    """Manager should remove connections that fail on send."""
    manager = ConnectionManager()

    mock_ws_good = AsyncMock()
    mock_ws_dead = AsyncMock()
    mock_ws_dead.send_json.side_effect = Exception("Connection closed")

    sub = {"pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}
    manager.connections[mock_ws_good] = sub
    manager.connections[mock_ws_dead] = sub

    signal = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "direction": "LONG", "final_score": 75}
    await manager.broadcast(signal)

    assert mock_ws_dead not in manager.connections
    assert mock_ws_good in manager.connections


@pytest.mark.asyncio
async def test_update_subscription():
    """Manager should update subscription for existing connection."""
    manager = ConnectionManager()

    mock_ws = AsyncMock()
    manager.connections[mock_ws] = {"pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}

    manager.update_subscription(mock_ws, ["ETH-USDT-SWAP"], ["4h"])

    assert manager.connections[mock_ws] == {"pairs": ["ETH-USDT-SWAP"], "timeframes": ["4h"]}


def test_websocket_connects_and_receives_subscription(app):
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        with client.websocket_connect("/ws/signals?api_key=test-key") as ws:
            ws.send_text('{"type": "subscribe", "pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}')


def test_websocket_handles_malformed_json(app):
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        with client.websocket_connect("/ws/signals?api_key=test-key") as ws:
            ws.send_text("not-json")
            ws.send_text('{"type": "subscribe", "pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}')


def test_websocket_accepts_header_api_key(app):
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        with client.websocket_connect("/ws/signals", headers={"X-API-Key": "test-key"}) as ws:
            ws.send_text('{"type": "subscribe", "pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}')

