"""Tests for WebSocket news_alert broadcast."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.api.connections import ConnectionManager


@pytest.mark.asyncio
async def test_broadcast_news_to_all_clients():
    """News alerts are sent to all connected clients regardless of subscription."""
    manager = ConnectionManager()

    ws1 = AsyncMock()
    ws2 = AsyncMock()
    manager.connections[ws1] = {"pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}
    manager.connections[ws2] = {"pairs": ["ETH-USDT-SWAP"], "timeframes": ["4h"]}

    alert = {
        "type": "news_alert",
        "news": {
            "id": 1,
            "headline": "Fed holds rates",
            "impact": "high",
            "sentiment": "bullish",
            "affected_pairs": ["ALL"],
        },
    }

    await manager.broadcast_news(alert)

    ws1.send_json.assert_called_once_with(alert)
    ws2.send_json.assert_called_once_with(alert)


@pytest.mark.asyncio
async def test_broadcast_news_dead_client_removed():
    """Clients that fail to receive are disconnected."""
    manager = ConnectionManager()

    ws_good = AsyncMock()
    ws_dead = AsyncMock()
    ws_dead.send_json = AsyncMock(side_effect=Exception("connection closed"))

    manager.connections[ws_good] = {"pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}
    manager.connections[ws_dead] = {"pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}

    alert = {"type": "news_alert", "news": {"id": 1, "headline": "test"}}
    await manager.broadcast_news(alert)

    assert ws_good in manager.connections
    assert ws_dead not in manager.connections


@pytest.mark.asyncio
async def test_broadcast_news_no_clients():
    """No error when broadcasting to zero clients."""
    manager = ConnectionManager()
    alert = {"type": "news_alert", "news": {"id": 1, "headline": "test"}}
    await manager.broadcast_news(alert)  # Should not raise


@pytest.mark.asyncio
async def test_signal_broadcast_is_filtered():
    """Regular signal broadcast only goes to matching pair/tf — NOT all clients."""
    manager = ConnectionManager()

    ws_btc = AsyncMock()
    ws_eth = AsyncMock()
    manager.connections[ws_btc] = {"pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}
    manager.connections[ws_eth] = {"pairs": ["ETH-USDT-SWAP"], "timeframes": ["4h"]}

    signal = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "direction": "LONG", "final_score": 70}
    await manager.broadcast(signal)

    ws_btc.send_json.assert_called_once()
    ws_eth.send_json.assert_not_called()
