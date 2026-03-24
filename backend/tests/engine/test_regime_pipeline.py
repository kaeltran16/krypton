# backend/tests/engine/test_regime_pipeline.py
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app.main import run_pipeline


def _mock_db():
    mock_session = AsyncMock()
    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db, mock_session


def _make_app(regime_weights=None):
    """Build a minimal FastAPI app with all app.state attributes run_pipeline() accesses."""
    app = FastAPI()

    # Settings
    app.state.settings = MagicMock()
    app.state.settings.engine_confluence_max_score = 15
    app.state.settings.engine_signal_threshold = 40
    app.state.settings.engine_llm_threshold = 20
    app.state.settings.engine_ml_weight = 0.25
    app.state.settings.ml_confidence_threshold = 0.65
    app.state.settings.onchain_enabled = False
    app.state.settings.vapid_private_key = ""
    app.state.settings.vapid_claims_email = ""
    app.state.settings.news_llm_context_window_minutes = 30
    app.state.settings.openrouter_api_key = ""
    app.state.settings.pairs = ["BTC-USDT-SWAP"]
    app.state.settings.timeframes = ["1h"]

    # Core infrastructure
    app.state.redis = AsyncMock()
    mock_db, mock_session = _mock_db()
    app.state.db = mock_db
    app.state.order_flow = {}
    app.state.prompt_template = ""

    # WebSocket manager
    app.state.manager = MagicMock()
    app.state.manager.broadcast = AsyncMock()
    app.state.manager.broadcast_candle = AsyncMock()

    # Regime weights (the feature under test)
    app.state.regime_weights = regime_weights or {}
    app.state.smoothed_regime = {}

    # Pipeline task tracking
    app.state.pipeline_tasks = set()

    # Optional subsystems
    app.state.ml_predictors = {}
    app.state.tracker = None
    app.state.okx_client = None

    return app, mock_session


def _raw_candles(n=200):
    return [
        json.dumps({
            "timestamp": f"2026-01-{(i % 28) + 1:02d}T{(i % 24):02d}:00:00+00:00",
            "open": 67000 + i * 10, "high": 67100 + i * 10,
            "low": 66900 + i * 10, "close": 67050 + i * 10,
            "volume": 100,
        })
        for i in range(n)
    ]


class TestPipelineWithoutRegimeWeights:
    @pytest.mark.asyncio
    async def test_runs_with_empty_regime_weights(self):
        """Pipeline with no learned regime weights should use defaults."""
        app, _ = _make_app()
        app.state.redis.lrange = AsyncMock(return_value=_raw_candles())
        app.state.redis.get = AsyncMock(return_value=None)

        candle = {
            "pair": "BTC-USDT-SWAP", "timeframe": "1h",
            "timestamp": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "open": 67000, "high": 67100, "low": 66900, "close": 67050,
            "volume": 100,
        }
        # Should not raise
        await run_pipeline(app, candle)


class TestPipelineWithRegimeWeights:
    @pytest.mark.asyncio
    async def test_runs_with_learned_regime_weights(self):
        """Pipeline with learned regime weights should use them."""
        rw = MagicMock()
        for regime in ["trending", "ranging", "volatile"]:
            setattr(rw, f"{regime}_trend_cap", 30.0)
            setattr(rw, f"{regime}_mean_rev_cap", 25.0)
            setattr(rw, f"{regime}_squeeze_cap", 25.0)
            setattr(rw, f"{regime}_volume_cap", 20.0)
            setattr(rw, f"{regime}_tech_weight", 0.40)
            setattr(rw, f"{regime}_flow_weight", 0.20)
            setattr(rw, f"{regime}_onchain_weight", 0.20)
            setattr(rw, f"{regime}_pattern_weight", 0.20)

        app, _ = _make_app(regime_weights={("BTC-USDT-SWAP", "1h"): rw})
        app.state.redis.lrange = AsyncMock(return_value=_raw_candles())
        app.state.redis.get = AsyncMock(return_value=None)

        candle = {
            "pair": "BTC-USDT-SWAP", "timeframe": "1h",
            "timestamp": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "open": 67000, "high": 67100, "low": 66900, "close": 67050,
            "volume": 100,
        }
        # Should not raise
        await run_pipeline(app, candle)
