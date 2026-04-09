"""Tests for ML API endpoints."""
import json
import os
import tempfile
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.ml import router as ml_router
from tests.conftest import make_test_jwt

COOKIES = {"krypton_token": make_test_jwt()}


def _mock_db(scalars_all=None, rowcount=0):
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    mock_result.rowcount = rowcount
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

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


async def test_training_history_requires_auth(ml_app):
    async with AsyncClient(
        transport=ASGITransport(app=ml_app), base_url="http://test"
    ) as c:
        resp = await c.get("/api/ml/train/history")
    assert resp.status_code == 401


async def test_training_history_returns_empty_list(ml_client):
    resp = await ml_client.get("/api/ml/train/history", cookies=COOKIES)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_training_history_returns_runs(ml_app, ml_client):
    from datetime import datetime, timezone

    mock_run = MagicMock()
    mock_run.job_id = "20260323_140000"
    mock_run.status = "completed"
    mock_run.preset_label = "Balanced"
    mock_run.params = {"timeframe": "1h", "epochs": 100}
    mock_run.result = {"BTC-USDT-SWAP": {"best_val_loss": 0.68}}
    mock_run.error = None
    mock_run.pairs_trained = ["BTC-USDT-SWAP"]
    mock_run.duration_seconds = 120.5
    mock_run.total_candles = 8760
    mock_run.created_at = datetime(2026, 3, 23, 14, 0, 0, tzinfo=timezone.utc)
    mock_run.completed_at = datetime(2026, 3, 23, 14, 2, 0, tzinfo=timezone.utc)

    ml_app.state.db = _mock_db(scalars_all=[mock_run])

    resp = await ml_client.get("/api/ml/train/history", cookies=COOKIES)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["job_id"] == "20260323_140000"
    assert data[0]["status"] == "completed"
    assert data[0]["preset_label"] == "Balanced"
    assert data[0]["duration_seconds"] == 120.5


async def test_delete_training_run_requires_auth(ml_app):
    async with AsyncClient(
        transport=ASGITransport(app=ml_app), base_url="http://test"
    ) as c:
        resp = await c.delete("/api/ml/train/history/some-id")
    assert resp.status_code == 401


async def test_delete_training_run_not_found(ml_app, ml_client):
    ml_app.state.db = _mock_db(rowcount=0)
    resp = await ml_client.delete(
        "/api/ml/train/history/nonexistent", cookies=COOKIES
    )
    assert resp.status_code == 404


async def test_delete_training_run_success(ml_app, ml_client):
    ml_app.state.db = _mock_db(rowcount=1)
    resp = await ml_client.delete(
        "/api/ml/train/history/20260323_140000", cookies=COOKIES
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted": "20260323_140000"}


async def test_train_persists_run_to_db(ml_app, ml_client):
    """start_training should insert an MLTrainingRun row."""
    add_calls = []
    original_mock_db = _mock_db()

    @asynccontextmanager
    async def tracking_session():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.rowcount = 0
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock(side_effect=lambda obj: add_calls.append(obj))
        yield mock_session

    original_mock_db.session_factory = tracking_session
    ml_app.state.db = original_mock_db

    resp = await ml_client.post(
        "/api/ml/train",
        json={
            "timeframe": "1h",
            "lookback_days": 365,
            "epochs": 50,
            "preset_label": "Quick Test",
        },
        cookies=COOKIES,
    )
    assert resp.status_code == 200
    assert len(add_calls) == 1
    from app.db.models import MLTrainingRun
    assert isinstance(add_calls[0], MLTrainingRun)
    assert add_calls[0].preset_label == "Quick Test"
    assert add_calls[0].status == "running"


def test_reload_predictors_passes_drift_settings(ml_app):
    """_reload_predictors should pass drift config values to predictor constructors."""
    import torch
    from app.api.ml import _reload_predictors
    from app.ml.model import SignalLSTM

    settings = ml_app.state.settings
    settings.drift_psi_moderate = 0.15
    settings.drift_psi_severe = 0.30
    settings.drift_penalty_moderate = 0.2
    settings.drift_penalty_severe = 0.5

    # Create a real temporary ensemble checkpoint
    with tempfile.TemporaryDirectory() as tmpdir:
        pair_dir = os.path.join(tmpdir, "BTC-USDT-SWAP")
        os.makedirs(pair_dir)

        input_size = 10
        model = SignalLSTM(input_size=input_size, hidden_size=16, num_layers=1, dropout=0.0)
        for i in range(3):
            torch.save(model.state_dict(), os.path.join(pair_dir, f"ensemble_{i}.pt"))

        config = {
            "n_members": 3,
            "input_size": input_size,
            "hidden_size": 16,
            "num_layers": 1,
            "dropout": 0.0,
            "seq_len": 10,
            "model_version": "v2",
            "feature_names": [f"f{j}" for j in range(input_size)],
            "members": [
                {"index": i, "trained_at": "2026-03-31T12:00:00", "val_loss": 0.4,
                 "data_range": [0.0, 1.0]}
                for i in range(3)
            ],
        }
        with open(os.path.join(pair_dir, "ensemble_config.json"), "w") as f:
            json.dump(config, f)

        settings.ml_checkpoint_dir = tmpdir
        _reload_predictors(ml_app, settings)

        predictor = ml_app.state.ml_predictors.get("BTC-USDT-SWAP")
        assert predictor is not None
        assert predictor._drift_config.psi_moderate == 0.15
        assert predictor._drift_config.psi_severe == 0.30
        assert predictor._drift_config.penalty_moderate == 0.2
        assert predictor._drift_config.penalty_severe == 0.5
