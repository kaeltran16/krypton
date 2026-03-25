import json
import pytest
from unittest.mock import AsyncMock

from app.collector.onchain import OnChainCollector


@pytest.mark.asyncio
async def test_addr_trend_pct_computed_from_history():
    """After _append_history stores active_addresses, addr_trend_pct should be set."""
    mock_redis = AsyncMock()

    history = [
        json.dumps({"v": 800000, "ts": "2026-03-25T00:00:00Z"}),
        json.dumps({"v": 850000, "ts": "2026-03-25T01:00:00Z"}),
        json.dumps({"v": 900000, "ts": "2026-03-25T02:00:00Z"}),
    ]

    async def _lrange_side_effect(key, start, end):
        if start == 0 and end == 0:
            return [history[0]]
        if start == -1 and end == -1:
            return [history[-1]]
        return history

    mock_redis.lrange = AsyncMock(side_effect=_lrange_side_effect)
    mock_redis.rpush = AsyncMock()
    mock_redis.ltrim = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.set = AsyncMock()

    collector = OnChainCollector(pairs=["BTC-USDT-SWAP"], redis=mock_redis)
    await collector._append_history("BTC-USDT-SWAP", "active_addresses", 900000)

    set_calls = [c for c in mock_redis.set.call_args_list if "addr_trend_pct" in str(c)]
    assert len(set_calls) >= 1

    # verify the stored value is (900000 - 800000) / 800000 = 0.125
    stored = json.loads(set_calls[0][0][1])
    assert abs(stored["value"] - 0.125) < 0.001


@pytest.mark.asyncio
async def test_addr_trend_pct_not_computed_for_other_metrics():
    """Non-active_addresses metrics should not trigger addr_trend_pct."""
    mock_redis = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.ltrim = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.set = AsyncMock()

    collector = OnChainCollector(pairs=["BTC-USDT-SWAP"], redis=mock_redis)
    await collector._append_history("BTC-USDT-SWAP", "whale_tx_count", 5)

    set_calls = [c for c in mock_redis.set.call_args_list if "addr_trend_pct" in str(c)]
    assert len(set_calls) == 0
