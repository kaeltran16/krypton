import json
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


@pytest.mark.asyncio
async def test_events_persisted_to_redis():
    mock_client = AsyncMock()
    mock_client.get_liquidation_orders.return_value = [
        {"bkPx": "50000", "sz": "100", "side": "buy", "ts": "0"},
    ]
    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[])

    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"], redis=mock_redis)
    await collector._poll()

    mock_redis.rpush.assert_called()
    call_args = mock_redis.rpush.call_args
    assert call_args[0][0] == "liq_events:BTC-USDT-SWAP"
    event = json.loads(call_args[0][1])
    assert event["price"] == 50000.0


@pytest.mark.asyncio
async def test_events_reloaded_from_redis_on_init():
    mock_client = AsyncMock()
    now = datetime.now(timezone.utc)
    stored = json.dumps({
        "price": 49000.0, "volume": 200.0,
        "timestamp": now.isoformat(), "side": "sell",
    })
    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[stored])

    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"], redis=mock_redis)
    await collector.load_from_redis()

    assert len(collector.events["BTC-USDT-SWAP"]) == 1
    assert collector.events["BTC-USDT-SWAP"][0]["price"] == 49000.0


@pytest.mark.asyncio
async def test_old_events_not_reloaded_from_redis():
    mock_client = AsyncMock()
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    stored = json.dumps({
        "price": 49000.0, "volume": 200.0,
        "timestamp": old.isoformat(), "side": "sell",
    })
    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[stored])

    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"], redis=mock_redis)
    await collector.load_from_redis()

    assert len(collector.events["BTC-USDT-SWAP"]) == 0


@pytest.mark.asyncio
async def test_volume_normalized_by_batch_size():
    """Each event's volume should be divided by the number of events in the batch."""
    mock_client = AsyncMock()
    mock_client.get_liquidation_orders.return_value = [
        {"bkPx": "50000", "sz": "100", "side": "buy", "ts": "0"},
        {"bkPx": "50100", "sz": "200", "side": "sell", "ts": "0"},
    ]
    collector = LiquidationCollector(mock_client, ["BTC-USDT-SWAP"])
    await collector._poll()
    events = collector.events["BTC-USDT-SWAP"]
    assert len(events) == 2
    # batch had 2 events, so volumes should be halved
    assert events[0]["volume"] == pytest.approx(50.0)
    assert events[1]["volume"] == pytest.approx(100.0)
