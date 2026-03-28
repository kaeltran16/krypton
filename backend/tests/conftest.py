import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from fastapi import FastAPI

from app.main import create_app

_TEST_JWT_SECRET = "test-jwt-secret"

os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("JWT_SECRET", _TEST_JWT_SECRET)
os.environ.setdefault("ALLOWED_EMAILS", "test@example.com")


def make_test_jwt(email: str = "test@example.com", user_id: str = "00000000-0000-0000-0000-000000000001"):
    payload = {"sub": user_id, "email": email, "exp": datetime.now(timezone.utc) + timedelta(days=1)}
    return pyjwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")


@asynccontextmanager
async def _test_lifespan(app: FastAPI):
    mock_settings = MagicMock()
    mock_settings.jwt_secret = _TEST_JWT_SECRET
    mock_settings.google_client_id = "test-client-id"
    mock_settings.allowed_emails = "test@example.com"
    mock_settings.pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    mock_settings.engine_traditional_weight = 0.40
    mock_settings.engine_flow_weight = 0.22
    mock_settings.engine_onchain_weight = 0.23
    mock_settings.engine_pattern_weight = 0.15
    mock_settings.engine_ml_weight = 0.25
    mock_settings.engine_ml_weight_min = 0.05
    mock_settings.engine_ml_weight_max = 0.30
    mock_settings.engine_signal_threshold = 40
    mock_settings.engine_llm_threshold = 40
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
    mock_settings.engine_confluence_level_weight_1 = 0.50
    mock_settings.engine_confluence_level_weight_2 = 0.30
    mock_settings.engine_confluence_trend_alignment_steepness = 0.30
    mock_settings.engine_confluence_adx_strength_center = 15.0
    mock_settings.engine_confluence_adx_conviction_ratio = 0.60
    mock_settings.engine_confluence_mr_penalty_factor = 0.50
    app.state.settings = mock_settings
    app.state.regime_weights = {}
    app.state.smoothed_regime = {}
    app.state.scoring_params = {
        "mean_rev_rsi_steepness": 0.25,
        "mean_rev_bb_pos_steepness": 10.0,
        "squeeze_steepness": 0.10,
        "mean_rev_blend_ratio": 0.6,
    }
    app.state.pattern_strength_overrides = None
    app.state.pattern_boost_overrides = None
    app.state.pipeline_settings_lock = asyncio.Lock()
    from app.engine.optimizer import OptimizerState
    app.state.optimizer = OptimizerState()
    app.state.active_signal_optimization = None
    app.state.manager = MagicMock()
    app.state.manager.broadcast = AsyncMock()
    app.state.start_time = 1000000.0
    app.state.last_pipeline_cycle = 1000000.0
    app.state.order_book = {}

    mock_db = MagicMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(side_effect=Exception("no real DB"))
    mock_db.session_factory = MagicMock(return_value=mock_session)
    app.state.db = mock_db
    yield


@pytest.fixture
async def app():
    a = create_app(lifespan_override=_test_lifespan)
    async with _test_lifespan(a):
        yield a


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def auth_cookies():
    token = make_test_jwt()
    return {"krypton_token": token}
