import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app.engine.confluence import (
    TIMEFRAME_CACHE_TTL, TIMEFRAME_PARENT,
    CONFLUENCE_ONLY_TIMEFRAMES, compute_confluence_score,
)
from app.main import run_pipeline


class TestHTFCacheKeyContract:
    @pytest.mark.asyncio
    async def test_cache_key_format_and_ttl(self):
        """Verify the key/TTL contract that run_pipeline must follow."""
        redis = AsyncMock()
        pair, timeframe = "BTC-USDT-SWAP", "1h"

        # Replicate the serialization run_pipeline uses
        indicators = {"adx": 28.5, "di_plus": 32.1, "di_minus": 18.7}
        htf_cache = json.dumps({
            "adx": indicators["adx"],
            "di_plus": indicators["di_plus"],
            "di_minus": indicators["di_minus"],
            "timestamp": "2025-01-01T01:00:00+00:00",
        })
        htf_key = f"htf_indicators:{pair}:{timeframe}"
        ttl = TIMEFRAME_CACHE_TTL[timeframe]
        await redis.set(htf_key, htf_cache, ex=ttl)

        redis.set.assert_called_once_with(htf_key, htf_cache, ex=7200)
        cached = json.loads(redis.set.call_args[0][1])
        assert cached["adx"] == 28.5
        assert cached["di_plus"] == 32.1
        assert cached["di_minus"] == 18.7


class TestHTFCacheReadPattern:
    @pytest.mark.asyncio
    async def test_child_reads_parent_cache_and_scores(self):
        """15m pipeline reads cached 1h indicators and produces non-zero confluence."""
        redis = AsyncMock()
        parent_data = json.dumps({"adx": 30, "di_plus": 28, "di_minus": 15})
        redis.get.return_value = parent_data

        pair, timeframe = "BTC-USDT-SWAP", "15m"
        parent_tf = TIMEFRAME_PARENT[timeframe]
        raw_parent = await redis.get(f"htf_indicators:{pair}:{parent_tf}")
        parent_indicators = json.loads(raw_parent)

        child_direction = 1  # child is bullish
        score = compute_confluence_score(child_direction, parent_indicators)

        # Parent is bullish (DI+ > DI-) and child is bullish → positive boost
        assert score > 0
        redis.get.assert_called_once_with(f"htf_indicators:{pair}:1h")

    @pytest.mark.asyncio
    async def test_cold_start_cache_miss_returns_zero(self):
        """No cache → confluence = 0, no crash."""
        redis = AsyncMock()
        redis.get.return_value = None

        raw_parent = await redis.get("htf_indicators:BTC-USDT-SWAP:1h")
        parent_indicators = json.loads(raw_parent) if raw_parent else None

        score = compute_confluence_score(1, parent_indicators)
        assert score == 0


class TestConfluenceOnlyTimeframes:
    def test_1d_is_confluence_only(self):
        """1D should be in CONFLUENCE_ONLY_TIMEFRAMES."""
        assert "1D" in CONFLUENCE_ONLY_TIMEFRAMES

    def test_signal_timeframes_are_not_confluence_only(self):
        """15m, 1h, 4h should emit signals normally."""
        for tf in ["15m", "1h", "4h"]:
            assert tf not in CONFLUENCE_ONLY_TIMEFRAMES

    def test_all_signal_timeframes_have_parents(self):
        """Every signal-emitting timeframe should have a parent for confluence."""
        for tf in ["15m", "1h", "4h"]:
            assert tf in TIMEFRAME_PARENT

    def test_cache_ttl_covers_all_timeframes(self):
        """Every timeframe (signal + confluence-only) should have a cache TTL."""
        all_tfs = set(TIMEFRAME_PARENT.keys()) | CONFLUENCE_ONLY_TIMEFRAMES
        for tf in all_tfs:
            assert tf in TIMEFRAME_CACHE_TTL


def _mock_db():
    mock_session = AsyncMock()
    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db, mock_session


class TestPipeline1DEarlyReturn:
    @pytest.mark.asyncio
    async def test_1d_caches_indicators_but_skips_signal_emission(self):
        """run_pipeline for 1D should write HTF cache then return without emitting."""
        app = FastAPI()
        app.state.settings = MagicMock()
        app.state.settings.engine_confluence_max_score = 15
        app.state.redis = AsyncMock()
        mock_db, mock_session = _mock_db()
        app.state.db = mock_db
        app.state.order_flow = {}
        app.state.prompt_template = ""
        app.state.manager = MagicMock()

        # 200 candles so we pass the minimum count check
        raw_candles = [
            json.dumps({
                "timestamp": f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00",
                "open": 67000 + i * 10, "high": 67100 + i * 10,
                "low": 66900 + i * 10, "close": 67050 + i * 10,
                "volume": 100,
            })
            for i in range(200)
        ]
        app.state.redis.lrange = AsyncMock(return_value=raw_candles)

        candle = {
            "pair": "BTC-USDT-SWAP", "timeframe": "1D",
            "timestamp": datetime(2026, 2, 27, tzinfo=timezone.utc),
            "open": 67000, "high": 67100, "low": 66900, "close": 67050,
            "volume": 100,
        }

        await run_pipeline(app, candle)

        # HTF cache should have been written (redis.set called)
        app.state.redis.set.assert_called_once()
        call_args = app.state.redis.set.call_args
        assert "htf_indicators:BTC-USDT-SWAP:1D" in call_args[0]

        # No signal should have been emitted
        app.state.manager.broadcast.assert_not_called()
        mock_session.add.assert_not_called()
