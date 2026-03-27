import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app.engine.confluence import (
    TIMEFRAME_CACHE_TTL, TIMEFRAME_PARENT, TIMEFRAME_ANCESTORS,
    CONFLUENCE_ONLY_TIMEFRAMES, compute_confluence_score,
)
from app.main import run_pipeline


def _make_enriched_cache(
    trend_score=30, mean_rev_score=-10, trend_conviction=0.7,
    adx=28.5, di_plus=32.1, di_minus=18.7,
    regime=None, timestamp="2025-01-01T01:00:00+00:00",
):
    """Build an enriched HTF cache payload matching the live pipeline shape."""
    return {
        "trend_score": trend_score,
        "mean_rev_score": mean_rev_score,
        "trend_conviction": trend_conviction,
        "adx": adx,
        "di_plus": di_plus,
        "di_minus": di_minus,
        "regime": regime or {"trending": 0.6, "ranging": 0.3, "volatile": 0.1},
        "timestamp": timestamp,
    }


class TestHTFCacheKeyContract:
    @pytest.mark.asyncio
    async def test_cache_key_format_and_ttl(self):
        """Verify the key/TTL contract that run_pipeline must follow."""
        redis = AsyncMock()
        pair, timeframe = "BTC-USDT-SWAP", "1h"

        htf_cache = json.dumps(_make_enriched_cache())
        htf_key = f"htf_indicators:{pair}:{timeframe}"
        ttl = TIMEFRAME_CACHE_TTL[timeframe]
        await redis.set(htf_key, htf_cache, ex=ttl)

        redis.set.assert_called_once_with(htf_key, htf_cache, ex=7200)
        cached = json.loads(redis.set.call_args[0][1])
        assert cached["adx"] == 28.5
        assert cached["di_plus"] == 32.1
        assert cached["di_minus"] == 18.7
        assert cached["trend_score"] == 30
        assert cached["mean_rev_score"] == -10
        assert cached["trend_conviction"] == 0.7
        assert "regime" in cached
        assert cached["regime"]["trending"] == 0.6

    @pytest.mark.asyncio
    async def test_enriched_cache_has_all_required_fields(self):
        """Every enriched cache payload must contain all fields used by confluence scorer."""
        cached = _make_enriched_cache()
        required = {"trend_score", "mean_rev_score", "trend_conviction",
                     "adx", "di_plus", "di_minus", "regime", "timestamp"}
        assert required == set(cached.keys())


class TestHTFCacheReadPattern:
    @pytest.mark.asyncio
    async def test_child_reads_parent_cache_and_scores(self):
        """15m pipeline reads cached ancestor indicators and produces non-zero confluence."""
        redis = AsyncMock()
        parent_data = json.dumps(_make_enriched_cache(
            trend_score=40, adx=30, di_plus=28, di_minus=15, trend_conviction=0.8,
        ))
        redis.get.return_value = parent_data

        pair, timeframe = "BTC-USDT-SWAP", "15m"
        ancestors = TIMEFRAME_ANCESTORS[timeframe]

        # read all ancestor caches
        parent_cache_list = []
        for anc_tf in ancestors:
            raw = await redis.get(f"htf_indicators:{pair}:{anc_tf}")
            parent_cache_list.append(json.loads(raw) if raw else None)

        child_indicators = {"trend_score": 50, "mean_rev_score": -5, "trend_conviction": 0.6}
        result = compute_confluence_score(child_indicators, parent_cache_list, timeframe)

        # parent has bullish trend and child has bullish trend => positive score
        assert result["score"] > 0
        assert "confidence" in result

    @pytest.mark.asyncio
    async def test_cold_start_cache_miss_returns_zero(self):
        """No cache => confluence score=0, no crash."""
        redis = AsyncMock()
        redis.get.return_value = None

        pair, timeframe = "BTC-USDT-SWAP", "15m"
        ancestors = TIMEFRAME_ANCESTORS[timeframe]

        parent_cache_list = []
        for anc_tf in ancestors:
            raw = await redis.get(f"htf_indicators:{pair}:{anc_tf}")
            parent_cache_list.append(json.loads(raw) if raw else None)

        child_indicators = {"trend_score": 50, "mean_rev_score": -5, "trend_conviction": 0.6}
        result = compute_confluence_score(child_indicators, parent_cache_list, timeframe)
        assert result["score"] == 0
        assert result["confidence"] == 0.0


class TestConfluenceOnlyTimeframes:
    def test_1d_is_confluence_only(self):
        """1D should be in CONFLUENCE_ONLY_TIMEFRAMES."""
        assert "1D" in CONFLUENCE_ONLY_TIMEFRAMES

    def test_signal_timeframes_are_not_confluence_only(self):
        """15m, 1h, 4h should emit signals normally."""
        for tf in ["15m", "1h", "4h"]:
            assert tf not in CONFLUENCE_ONLY_TIMEFRAMES

    def test_all_signal_timeframes_have_ancestors(self):
        """Every signal-emitting timeframe should have ancestors for confluence."""
        for tf in ["15m", "1h", "4h"]:
            assert tf in TIMEFRAME_ANCESTORS
            assert len(TIMEFRAME_ANCESTORS[tf]) > 0

    def test_all_signal_timeframes_have_parents(self):
        """Every signal-emitting timeframe should have a parent for confluence."""
        for tf in ["15m", "1h", "4h"]:
            assert tf in TIMEFRAME_PARENT

    def test_cache_ttl_covers_all_timeframes(self):
        """Every timeframe (signal + confluence-only) should have a cache TTL."""
        all_tfs = set(TIMEFRAME_PARENT.keys()) | CONFLUENCE_ONLY_TIMEFRAMES
        for tf in all_tfs:
            assert tf in TIMEFRAME_CACHE_TTL

    def test_ancestors_are_ordered_by_proximity(self):
        """Ancestors should be ordered: immediate parent first, then grandparent, etc."""
        assert TIMEFRAME_ANCESTORS["15m"] == ["1h", "4h", "1D"]
        assert TIMEFRAME_ANCESTORS["1h"] == ["4h", "1D"]
        assert TIMEFRAME_ANCESTORS["4h"] == ["1D"]


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
        app.state.settings.engine_confluence_level_weight_1 = 0.50
        app.state.settings.engine_confluence_level_weight_2 = 0.30
        app.state.settings.engine_confluence_trend_alignment_steepness = 0.30
        app.state.settings.engine_confluence_adx_strength_center = 15.0
        app.state.settings.engine_confluence_adx_conviction_ratio = 0.60
        app.state.settings.engine_confluence_mr_penalty_factor = 0.50
        app.state.redis = AsyncMock()
        mock_db, mock_session = _mock_db()
        app.state.db = mock_db
        app.state.order_flow = {}
        app.state.prompt_template = ""
        app.state.manager = MagicMock()
        app.state.regime_weights = {}

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

        # verify enriched payload was cached
        cached = json.loads(call_args[0][1])
        assert "trend_score" in cached
        assert "mean_rev_score" in cached
        assert "trend_conviction" in cached
        assert "adx" in cached
        assert "di_plus" in cached
        assert "di_minus" in cached
        assert "regime" in cached

        # No signal should have been emitted
        app.state.manager.broadcast.assert_not_called()
        mock_session.add.assert_not_called()
