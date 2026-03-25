import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_candle_stale_when_old():
    from app.collector.freshness import compute_freshness

    old_ts = time.time() - 2400  # 40 min ago
    candle_json = json.dumps({"timestamp": old_ts})

    mock_redis = AsyncMock()
    mock_redis.lindex = AsyncMock(return_value=candle_json)
    mock_redis.exists = AsyncMock(return_value=1)

    app_state = MagicMock()
    app_state.redis = mock_redis
    app_state.settings = MagicMock()
    app_state.settings.pairs = ["BTC-USDT-SWAP"]
    app_state.settings.timeframes = ["15m"]
    app_state.order_flow = {"BTC-USDT-SWAP": {"_last_updated": time.time()}}
    app_state.liquidation_collector = MagicMock()
    app_state.liquidation_collector._last_poll_ts = time.time()

    result = await compute_freshness(app_state)

    btc_candle = result["candles"].get("BTC-USDT-SWAP:15m", {})
    assert btc_candle.get("stale") is True


@pytest.mark.asyncio
async def test_all_fresh():
    from app.collector.freshness import compute_freshness

    now = time.time()
    candle_json = json.dumps({"timestamp": now - 60})

    mock_redis = AsyncMock()
    mock_redis.lindex = AsyncMock(return_value=candle_json)
    mock_redis.exists = AsyncMock(return_value=1)

    app_state = MagicMock()
    app_state.redis = mock_redis
    app_state.settings = MagicMock()
    app_state.settings.pairs = ["BTC-USDT-SWAP"]
    app_state.settings.timeframes = ["15m"]
    app_state.order_flow = {"BTC-USDT-SWAP": {"_last_updated": now}}
    app_state.liquidation_collector = MagicMock()
    app_state.liquidation_collector._last_poll_ts = now

    result = await compute_freshness(app_state)

    btc_candle = result["candles"].get("BTC-USDT-SWAP:15m", {})
    assert btc_candle.get("stale") is False
