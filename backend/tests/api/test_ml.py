"""Tests for ML API endpoints."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.ml import router as ml_router

API_KEY = "test-key"
HEADERS = {"X-API-Key": API_KEY}


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
    mock_settings.krypton_api_key = API_KEY
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
    resp = await ml_client.get("/api/ml/status", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ml_enabled"] is False
    assert data["loaded_pairs"] == []


async def test_train_returns_job_id(ml_client):
    resp = await ml_client.post(
        "/api/ml/train",
        json={"timeframe": "1h", "epochs": 1},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "running"


async def test_train_status_not_found(ml_client):
    resp = await ml_client.get("/api/ml/train/nonexistent", headers=HEADERS)
    assert resp.status_code == 404


async def test_train_background_job_handles_no_data(ml_app, ml_client):
    """Verify background job completes with 'failed' status when no data."""
    import asyncio

    resp = await ml_client.post(
        "/api/ml/train",
        json={"timeframe": "1h", "epochs": 1},
        headers=HEADERS,
    )
    job_id = resp.json()["job_id"]

    # Wait for background task to finish
    await asyncio.sleep(0.5)

    resp = await ml_client.get(f"/api/ml/train/{job_id}", headers=HEADERS)
    data = resp.json()
    assert data["status"] == "failed"
    assert "No pair had enough data" in data.get("error", "")


async def test_train_accepts_seq_len_and_dropout(ml_client):
    resp = await ml_client.post(
        "/api/ml/train",
        json={"seq_len": 75, "dropout": 0.4},
        headers={"X-API-Key": "test-key"},
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
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
