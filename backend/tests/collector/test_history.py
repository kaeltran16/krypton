import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.collector.history import (
    import_historical_candles,
    _upsert_candles,
    OKX_BAR_MAP,
)


def _make_okx_row(ts_ms: int, o=100, h=105, l=95, c=102, v=50):
    """Build a single OKX candle row [ts, o, h, l, c, vol, ...]."""
    return [str(ts_ms), str(o), str(h), str(l), str(c), str(v), "0", "0", "0"]


def _make_mock_response(rows, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"code": "0", "data": rows}
    return resp


class TestImportHistoricalCandles:

    @pytest.fixture
    def mock_db(self):
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        result = MagicMock()
        result.rowcount = 1
        session.execute = AsyncMock(return_value=result)
        session.commit = AsyncMock()

        db = MagicMock()
        db.session_factory.return_value = session
        return db

    @pytest.mark.asyncio
    async def test_imports_candles_and_returns_count(self, mock_db):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        rows = [_make_okx_row(now_ms - i * 900_000) for i in range(5)]

        with patch("app.collector.history.httpx.AsyncClient") as MockClient:
            client = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

            # First response has data, second is empty (end of pagination)
            client.get = AsyncMock(side_effect=[
                _make_mock_response(rows),
                _make_mock_response([]),
            ])

            result = await import_historical_candles(
                db=mock_db,
                pairs=["BTC-USDT-SWAP"],
                timeframes=["15m"],
                lookback_days=1,
            )

        assert result["total_imported"] == 5
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_unsupported_timeframe_returns_error(self, mock_db):
        result = await import_historical_candles(
            db=mock_db,
            pairs=["BTC-USDT-SWAP"],
            timeframes=["2m"],  # Not in OKX_BAR_MAP
            lookback_days=1,
        )
        assert result["total_imported"] == 0
        assert len(result["errors"]) == 1
        assert "Unsupported" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_pagination_walks_backwards(self, mock_db):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        cutoff_ms = now_ms - 2 * 86400_000  # 2 days ago

        # Page 1: recent candles (spaced 15m apart, doesn't cross 2-day cutoff)
        page1 = [_make_okx_row(now_ms - i * 900_000) for i in range(100)]
        # Page 2: older candles, past cutoff
        page2 = [_make_okx_row(cutoff_ms - i * 900_000) for i in range(50)]

        with patch("app.collector.history.httpx.AsyncClient") as MockClient:
            client = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
            client.get = AsyncMock(side_effect=[
                _make_mock_response(page1),
                _make_mock_response(page2),
            ])

            result = await import_historical_candles(
                db=mock_db,
                pairs=["BTC-USDT-SWAP"],
                timeframes=["15m"],
                lookback_days=2,
            )

        # Should have called get twice (pagination)
        assert client.get.call_count == 2
        assert result["total_imported"] == 150

    @pytest.mark.asyncio
    async def test_progress_callback_called(self, mock_db):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        rows = [_make_okx_row(now_ms - i * 900_000) for i in range(5)]

        progress_calls = []

        def on_progress(job_id, status):
            progress_calls.append(status)

        with patch("app.collector.history.httpx.AsyncClient") as MockClient:
            client = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
            client.get = AsyncMock(side_effect=[
                _make_mock_response(rows),
                _make_mock_response([]),
            ])

            await import_historical_candles(
                db=mock_db,
                pairs=["BTC-USDT-SWAP"],
                timeframes=["15m"],
                lookback_days=1,
                progress_callback=on_progress,
            )

        assert len(progress_calls) >= 1
        assert progress_calls[0]["status"] == "running"

    @pytest.mark.asyncio
    async def test_on_conflict_do_nothing(self, mock_db):
        """Existing candles should not be overwritten."""
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        rows = [_make_okx_row(now_ms)]

        # Simulate ON CONFLICT DO NOTHING — rowcount = 0
        session = mock_db.session_factory.return_value.__aenter__.return_value
        result_mock = MagicMock()
        result_mock.rowcount = 0
        session.execute = AsyncMock(return_value=result_mock)

        with patch("app.collector.history.httpx.AsyncClient") as MockClient:
            client = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
            client.get = AsyncMock(side_effect=[
                _make_mock_response(rows),
                _make_mock_response([]),
            ])

            result = await import_historical_candles(
                db=mock_db,
                pairs=["BTC-USDT-SWAP"],
                timeframes=["15m"],
                lookback_days=1,
            )

        # No new rows inserted
        assert result["total_imported"] == 0


class TestBarMap:
    def test_supported_timeframes(self):
        assert OKX_BAR_MAP["15m"] == "15m"
        assert OKX_BAR_MAP["1h"] == "1H"
        assert OKX_BAR_MAP["4h"] == "4H"
        assert OKX_BAR_MAP["1D"] == "1D"
