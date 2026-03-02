import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.lrange = AsyncMock(return_value=[
        json.dumps({"timestamp": 1700000000000, "open": 65000, "high": 65500, "low": 64800, "close": 65200, "volume": 100}),
        json.dumps({"timestamp": 1700000900000, "open": 65200, "high": 65300, "low": 65100, "close": 65250, "volume": 80}),
    ])
    return r


def test_parse_candles_from_redis(mock_redis):
    from app.api.candles import parse_redis_candles
    raw = [
        json.dumps({"timestamp": 1700000000000, "open": 65000, "high": 65500, "low": 64800, "close": 65200, "volume": 100}),
    ]
    result = parse_redis_candles(raw)
    assert len(result) == 1
    assert result[0]["open"] == 65000
    assert result[0]["close"] == 65200
