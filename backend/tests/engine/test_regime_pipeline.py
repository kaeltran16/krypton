# backend/tests/engine/test_regime_pipeline.py
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
    app.state.settings.engine_confluence_level_weight_1 = 0.50
    app.state.settings.engine_confluence_level_weight_2 = 0.30
    app.state.settings.engine_confluence_trend_alignment_steepness = 0.30
    app.state.settings.engine_confluence_adx_strength_center = 15.0
    app.state.settings.engine_confluence_adx_conviction_ratio = 0.60
    app.state.settings.engine_confluence_mr_penalty_factor = 0.50
    app.state.settings.engine_signal_threshold = 40
    app.state.settings.engine_llm_threshold = 40
    app.state.settings.engine_mr_llm_trigger = 0.30
    app.state.settings.engine_ml_weight_min = 0.05
    app.state.settings.engine_ml_weight_max = 0.30
    app.state.settings.ml_confidence_threshold = 0.65
    app.state.settings.onchain_enabled = False
    app.state.settings.ml_sl_min_atr = 0.5
    app.state.settings.ml_sl_max_atr = 3.0
    app.state.settings.ml_tp1_min_atr = 1.0
    app.state.settings.ml_tp2_max_atr = 8.0
    app.state.settings.ml_rr_floor = 1.0
    app.state.settings.vapid_private_key = ""
    app.state.settings.vapid_claims_email = ""
    app.state.settings.news_llm_context_window_minutes = 30
    app.state.settings.openrouter_api_key = ""
    app.state.settings.engine_cooldown_max_candles = 3
    app.state.settings.pairs = ["BTC-USDT-SWAP"]
    app.state.settings.timeframes = ["1h"]

    # Core infrastructure
    app.state.redis = AsyncMock()
    mock_db, mock_session = _mock_db()
    app.state.db = mock_db
    app.state.order_flow = {}
    app.state.order_book = {}
    app.state.prompt_template = ""

    # WebSocket manager
    app.state.manager = MagicMock()
    app.state.manager.broadcast = AsyncMock()
    app.state.manager.broadcast_candle = AsyncMock()
    app.state.manager.broadcast_scores = AsyncMock()

    # Regime weights (the feature under test)
    app.state.regime_weights = regime_weights or {}
    app.state.regime_weight_overlays = {}
    app.state.regime_weight_signal_windows = {}
    app.state.smoothed_regime = {}

    # Pipeline task tracking
    app.state.pipeline_tasks = set()

    # CVD state
    app.state.cvd = {}

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


class TestPipelineWithOnlineOverlay:
    @pytest.mark.asyncio
    async def test_routes_outer_weight_resolution_through_online_helper(self):
        rw = MagicMock()
        rw.adx_center = 20.0
        for regime in ["trending", "ranging", "volatile", "steady"]:
            for source in ["tech", "flow", "onchain", "pattern", "liquidation", "confluence", "news"]:
                setattr(rw, f"{regime}_{source}_weight", 1.0 / 7.0)
            setattr(rw, f"{regime}_trend_cap", 30.0)
            setattr(rw, f"{regime}_mean_rev_cap", 25.0)
            setattr(rw, f"{regime}_squeeze_cap", 20.0)
            setattr(rw, f"{regime}_volume_cap", 25.0)

        app, _ = _make_app(regime_weights={("BTC-USDT-SWAP", "1h"): rw})
        app.state.regime_weight_overlays = {
            ("BTC-USDT-SWAP", "1h"): {
                "trending": {"tech": 0.01, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                "ranging": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                "volatile": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                "steady": {"tech": 0.0, "flow": 0.0, "onchain": 0.0, "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0, "news": 0.0},
                "eligible_count": 20,
                "window_oldest_outcome_at": "2026-03-20T00:00:00+00:00",
                "window_newest_outcome_at": "2026-04-01T00:00:00+00:00",
                "rebuilt_at": "2026-04-01T00:00:00+00:00",
            }
        }
        app.state.regime_weight_signal_windows = {
            ("BTC-USDT-SWAP", "1h"): [{"id": i} for i in range(20)]
        }
        app.state.redis.lrange = AsyncMock(return_value=_raw_candles())
        app.state.redis.get = AsyncMock(return_value=None)

        candle = {
            "pair": "BTC-USDT-SWAP", "timeframe": "1h",
            "timestamp": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "open": 67000, "high": 67100, "low": 66900, "close": 67050,
            "volume": 100,
        }

        with patch("app.main.resolve_effective_outer_weights") as resolve_mock:
            resolve_mock.return_value = {
                "tech": 0.30,
                "flow": 0.15,
                "onchain": 0.15,
                "pattern": 0.10,
                "liquidation": 0.10,
                "confluence": 0.10,
                "news": 0.10,
            }
            await run_pipeline(app, candle)

        resolve_mock.assert_called_once()
        _, kwargs = resolve_mock.call_args
        assert kwargs["overlay_state"]["eligible_count"] == 20
