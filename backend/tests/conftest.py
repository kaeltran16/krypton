import asyncio
import os
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from fastapi import FastAPI

from app.main import create_app

os.environ.setdefault("KRYPTON_API_KEY", "test-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")


@asynccontextmanager
async def _test_lifespan(app: FastAPI):
    mock_settings = MagicMock()
    mock_settings.krypton_api_key = "test-key"
    mock_settings.pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    mock_settings.engine_traditional_weight = 0.40
    mock_settings.engine_flow_weight = 0.22
    mock_settings.engine_onchain_weight = 0.23
    mock_settings.engine_pattern_weight = 0.15
    mock_settings.engine_ml_weight = 0.25
    mock_settings.engine_signal_threshold = 40
    mock_settings.engine_llm_threshold = 20
    mock_settings.ml_confidence_threshold = 0.65
    mock_settings.llm_factor_weights = {
        "support_proximity": 6.0, "resistance_proximity": 6.0,
        "level_breakout": 8.0, "htf_alignment": 7.0,
        "rsi_divergence": 7.0, "volume_divergence": 6.0,
        "macd_divergence": 6.0, "volume_exhaustion": 5.0,
        "funding_extreme": 5.0, "crowded_positioning": 5.0,
        "pattern_confirmation": 5.0, "news_catalyst": 7.0,
    }
    mock_settings.llm_factor_total_cap = 35.0
    mock_settings.engine_confluence_max_score = 15
    app.state.settings = mock_settings
    app.state.regime_weights = {}
    app.state.scoring_params = {
        "mean_rev_rsi_steepness": 0.25,
        "mean_rev_bb_pos_steepness": 10.0,
        "squeeze_steepness": 0.10,
        "mean_rev_blend_ratio": 0.6,
    }
    app.state.pipeline_settings_lock = asyncio.Lock()

    mock_db = MagicMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(side_effect=Exception("no real DB"))
    mock_db.session_factory = MagicMock(return_value=mock_session)
    app.state.db = mock_db
    yield


@pytest.fixture
def app():
    return create_app(lifespan_override=_test_lifespan)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
