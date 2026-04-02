import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.auth import create_ws_token
from app.api.connections import ConnectionManager
from tests.conftest import make_test_jwt

JWT_SECRET = "test-secret-key"


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
    from app.api.auth import create_ws_token

    with TestClient(app) as client:
        with client.websocket_connect("/ws/signals") as ws:
            token = create_ws_token(app.state.settings.jwt_secret)
            ws.send_json({"type": "auth", "token": token})
            ws.send_text('{"type": "subscribe", "pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}')


def test_websocket_handles_malformed_json(app):
    from starlette.testclient import TestClient
    from app.api.auth import create_ws_token

    with TestClient(app) as client:
        with client.websocket_connect("/ws/signals") as ws:
            token = create_ws_token(app.state.settings.jwt_secret)
            ws.send_json({"type": "auth", "token": token})
            ws.send_text("not-json")
            ws.send_text('{"type": "subscribe", "pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}')


@pytest.mark.asyncio
async def test_ws_message_auth_accepted():
    """Client sends auth message after connect, gets registered."""
    from app.api.ws import signal_stream

    ws = AsyncMock()
    ws.app = MagicMock()
    ws.app.state.settings.jwt_secret = JWT_SECRET
    ws.app.state.manager = MagicMock()
    ws.app.state.manager.connect_existing = MagicMock()

    token = create_ws_token(JWT_SECRET)
    ws.receive_json = AsyncMock(return_value={"type": "auth", "token": token})
    # after auth, simulate immediate disconnect
    ws.receive_text = AsyncMock(side_effect=Exception("disconnect"))

    await signal_stream(ws)

    ws.accept.assert_awaited_once()
    ws.app.state.manager.connect_existing.assert_called_once()


@pytest.mark.asyncio
async def test_ws_message_auth_rejected_bad_token():
    """Client sends invalid token, connection closed with 4001."""
    from app.api.ws import signal_stream

    ws = AsyncMock()
    ws.app = MagicMock()
    ws.app.state.settings.jwt_secret = JWT_SECRET

    ws.receive_json = AsyncMock(return_value={"type": "auth", "token": "bad.token.here"})

    await signal_stream(ws)

    ws.close.assert_awaited_once()
    assert ws.close.call_args.kwargs.get("code") == 4001 or ws.close.call_args[1].get("code") == 4001


@pytest.mark.asyncio
async def test_ws_message_auth_timeout():
    """Client doesn't send auth within timeout, connection closed."""
    from app.api.ws import signal_stream, _AUTH_TIMEOUT_S

    ws = AsyncMock()
    ws.app = MagicMock()
    ws.app.state.settings.jwt_secret = JWT_SECRET

    async def slow_receive():
        await asyncio.sleep(_AUTH_TIMEOUT_S + 1)

    ws.receive_json = AsyncMock(side_effect=slow_receive)

    await signal_stream(ws)

    ws.close.assert_awaited_once()
