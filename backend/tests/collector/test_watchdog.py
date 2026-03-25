import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_watchdog_logs_warning_on_stale_data():
    from app.collector.watchdog import _check_once

    stale_result = {
        "candles": {"BTC-USDT-SWAP:15m": {"seconds_ago": 3000, "stale": True}},
        "order_flow": {},
        "onchain": {},
        "liquidation": {"seconds_ago": None, "stale": True},
    }

    with patch("app.collector.watchdog.compute_freshness", new_callable=AsyncMock, return_value=stale_result):
        with patch("app.collector.watchdog.logger") as mock_logger:
            app_state = MagicMock()
            await _check_once(app_state)
            mock_logger.warning.assert_called()


@pytest.mark.asyncio
async def test_watchdog_silent_when_fresh():
    from app.collector.watchdog import _check_once

    fresh_result = {
        "candles": {"BTC-USDT-SWAP:15m": {"seconds_ago": 60, "stale": False}},
        "order_flow": {"BTC-USDT-SWAP": {"seconds_ago": 30, "stale": False}},
        "onchain": {"BTC-USDT-SWAP": {"metrics_present": 2, "stale": False}},
        "liquidation": {"seconds_ago": 120, "stale": False},
    }

    with patch("app.collector.watchdog.compute_freshness", new_callable=AsyncMock, return_value=fresh_result):
        with patch("app.collector.watchdog.logger") as mock_logger:
            app_state = MagicMock()
            await _check_once(app_state)
            mock_logger.warning.assert_not_called()
