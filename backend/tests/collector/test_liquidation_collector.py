from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
import pytest
from app.collector.liquidation import LiquidationCollector


@pytest.mark.asyncio
async def test_events_stored_after_poll():
    """Poll should store parsed events in the events dict."""
    mock_client = AsyncMock()
    mock_client.get_liquidation_orders.return_value = [
        {"bkPx": "50000", "sz": "100", "side": "buy", "ts": "0"},
    ]
    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"])
    await collector._poll()
    assert len(collector.events["BTC-USDT-SWAP"]) == 1
    assert collector.events["BTC-USDT-SWAP"][0]["price"] == 50000.0


@pytest.mark.asyncio
async def test_old_events_pruned():
    """Events older than 24h window should be pruned."""
    mock_client = AsyncMock()
    mock_client.get_liquidation_orders.return_value = []
    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"])
    # inject an old event
    old_ts = datetime.now(timezone.utc) - timedelta(hours=25)
    collector._events["BTC-USDT-SWAP"] = [
        {"price": 50000.0, "volume": 100.0, "timestamp": old_ts, "side": "buy"},
    ]
    await collector._poll()
    assert len(collector.events["BTC-USDT-SWAP"]) == 0


@pytest.mark.asyncio
async def test_pruning_runs_even_when_poll_fails():
    """Pruning should still happen if the API call for a pair fails."""
    mock_client = AsyncMock()
    mock_client.get_liquidation_orders.side_effect = Exception("API down")
    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"])
    old_ts = datetime.now(timezone.utc) - timedelta(hours=25)
    collector._events["BTC-USDT-SWAP"] = [
        {"price": 50000.0, "volume": 100.0, "timestamp": old_ts, "side": "buy"},
    ]
    await collector._poll()
    # old event should still be pruned despite poll failure
    assert len(collector.events["BTC-USDT-SWAP"]) == 0
