"""Tests for ML API endpoints."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.ml import router as ml_router
from tests.conftest import make_test_jwt

COOKIES = {"krypton_token": make_test_jwt()}


def _mock_db(scalars_all=None):
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    mock_db = MagicMock()

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    mock_db.session_factory = fake_session
    return mock_db


@pytest.fixture
def ml_app():
    app = FastAPI()
    mock_settings = MagicMock()
    mock_settings.jwt_secret = "test-jwt-secret"
    mock_settings.ml_enabled = False
    mock_settings.ml_checkpoint_dir = "/tmp/test_models"
    mock_settings.pairs = ["BTC-USDT-SWAP"]
    app.state.settings = mock_settings
    app.state.db = _mock_db()
    app.state.ml_predictors = {}
    app.include_router(ml_router)
    return app


@pytest.fixture
async def ml_client(ml_app):
    async with AsyncClient(
        transport=ASGITransport(app=ml_app), base_url="http://test"
    ) as ac:
        yield ac


async def test_status_returns_disabled_by_default(ml_client):
    resp = await ml_client.get("/api/ml/status", cookies=COOKIES)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ml_enabled"] is False
    assert data["loaded_pairs"] == []


async def test_train_returns_job_id(ml_client):
    resp = await ml_client.post(
        "/api/ml/train",
        json={"timeframe": "1h", "epochs": 1},
        cookies=COOKIES,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "running"


async def test_train_status_not_found(ml_client):
    resp = await ml_client.get("/api/ml/train/nonexistent", cookies=COOKIES)
    assert resp.status_code == 404


async def test_train_background_job_handles_no_data(ml_app, ml_client):
    """Verify background job completes with 'failed' status when no data."""
    import asyncio

    resp = await ml_client.post(
        "/api/ml/train",
        json={"timeframe": "1h", "epochs": 1},
        cookies=COOKIES,
    )
    job_id = resp.json()["job_id"]

    # Wait for background task to finish
    await asyncio.sleep(0.5)

    resp = await ml_client.get(f"/api/ml/train/{job_id}", cookies=COOKIES)
    data = resp.json()
    assert data["status"] == "failed"
    assert "No pair had enough data" in data.get("error", "")


async def test_train_accepts_seq_len_and_dropout(ml_client):
    resp = await ml_client.post(
        "/api/ml/train",
        json={"seq_len": 75, "dropout": 0.4},
        cookies={"krypton_token": make_test_jwt()},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data


async def test_cancel_training(ml_app, ml_client):
    """Test cancelling a running job."""
    from app.api.ml import _get_train_jobs
    train_jobs = _get_train_jobs(ml_app)
    train_jobs["test_cancel"] = {"status": "running", "task": AsyncMock()}

    resp = await ml_client.post(
        "/api/ml/train/test_cancel/cancel",
        cookies=COOKIES,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


async def test_data_readiness_returns_per_pair_counts(ml_app, ml_client):
    """GET /api/ml/data-readiness?timeframe=1h returns candle counts per pair."""
    from unittest.mock import MagicMock, AsyncMock
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone

    # Mock DB to return aggregate results
    mock_session = AsyncMock()
    mock_row_btc = MagicMock()
    mock_row_btc.pair = "BTC-USDT-SWAP"
    mock_row_btc.count = 8760
    mock_row_btc.oldest = datetime(2025, 3, 22, tzinfo=timezone.utc)

    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row_btc]
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    ml_app.state.db.session_factory = fake_session

    resp = await ml_client.get("/api/ml/data-readiness?timeframe=1h", cookies=COOKIES)
    assert resp.status_code == 200
    data = resp.json()
    assert "BTC-USDT-SWAP" in data
    assert data["BTC-USDT-SWAP"]["count"] == 8760
    assert data["BTC-USDT-SWAP"]["sufficient"] is True


async def test_data_readiness_requires_timeframe(ml_client):
    """GET /api/ml/data-readiness without timeframe returns 422."""
    resp = await ml_client.get("/api/ml/data-readiness", cookies=COOKIES)
    assert resp.status_code == 422
