"""Tests for backtest API endpoints."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.backtest import router as backtest_router
from tests.conftest import make_test_jwt


def _mock_db(scalars_all=None, scalar_one=None, rowcount=0):
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = scalars_all or []
    mock_result.scalar_one_or_none.return_value = scalar_one
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
def bt_app():
    app = FastAPI()
    mock_settings = MagicMock()
    mock_settings.jwt_secret = "test-jwt-secret"
    app.state.settings = mock_settings
    app.state.db = _mock_db()
    app.state.manager = MagicMock()
    app.state.manager.broadcast_event = AsyncMock()
    app.state.import_jobs = {}
    app.state.backtest_cancel_flags = {}
    app.include_router(backtest_router)
    return app


# --- Auth tests ---

async def test_import_requires_auth(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post("/api/backtest/import", json={
            "pairs": ["BTC-USDT-SWAP"], "timeframes": ["15m"],
        })
    assert resp.status_code == 401


async def test_run_requires_auth(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post("/api/backtest/run", json={
            "pairs": ["BTC"], "timeframe": "15m",
            "date_from": "2025-01-01", "date_to": "2025-06-01",
        })
    assert resp.status_code == 401


async def test_list_runs_requires_auth(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.get("/api/backtest/runs")
    assert resp.status_code == 401


async def test_delete_requires_auth(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.delete("/api/backtest/runs/some-id")
    assert resp.status_code == 401


async def test_compare_requires_auth(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post("/api/backtest/compare", json={"run_ids": ["a", "b"]})
    assert resp.status_code == 401


# --- Import tests ---

async def test_trigger_import_returns_job_id(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post(
            "/api/backtest/import",
            json={"pairs": ["BTC-USDT-SWAP"], "timeframes": ["15m"], "lookback_days": 30},
            cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "running"


async def test_import_status_not_found(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.get("/api/backtest/import/nonexistent", cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 404


async def test_import_status_found(bt_app):
    bt_app.state.import_jobs["test-job"] = {
        "status": "completed", "total_imported": 100, "errors": [],
    }
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.get("/api/backtest/import/test-job", cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 200
    assert resp.json()["total_imported"] == 100


# --- Run tests ---

async def test_start_run_returns_run_id(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post(
            "/api/backtest/run",
            json={
                "pairs": ["BTC-USDT-SWAP"], "timeframe": "15m",
                "date_from": "2025-01-01", "date_to": "2025-06-01",
            },
            cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "running"


async def test_cancel_not_found(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post("/api/backtest/run/nonexistent/cancel", cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 404


async def test_cancel_sets_flag(bt_app):
    bt_app.state.backtest_cancel_flags["run-123"] = {"cancelled": False}
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post("/api/backtest/run/run-123/cancel", cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 200
    assert bt_app.state.backtest_cancel_flags["run-123"]["cancelled"] is True


async def test_list_runs(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.get("/api/backtest/runs", cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# --- Validation tests ---

async def test_import_invalid_lookback(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post(
            "/api/backtest/import",
            json={"pairs": ["BTC"], "timeframes": ["15m"], "lookback_days": 0},
            cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 422


async def test_run_threshold_too_high(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post(
            "/api/backtest/run",
            json={
                "pairs": ["BTC"], "timeframe": "15m",
                "date_from": "2025-01-01", "date_to": "2025-06-01",
                "signal_threshold": 200,
            },
            cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 422


async def test_compare_too_few(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post(
            "/api/backtest/compare",
            json={"run_ids": ["one"]},
            cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 422


async def test_compare_too_many(bt_app):
    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post(
            "/api/backtest/compare",
            json={"run_ids": ["a", "b", "c", "d", "e"]},
            cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 422


# --- 429 concurrent limit test ---

async def test_max_concurrent_runs_429(bt_app):
    """When max concurrent runs reached, return 429."""
    # Mock DB to return 2 running backtests
    mock_run1 = MagicMock()
    mock_run2 = MagicMock()
    bt_app.state.db = _mock_db(scalars_all=[mock_run1, mock_run2])

    async with AsyncClient(transport=ASGITransport(app=bt_app), base_url="http://test") as c:
        resp = await c.post(
            "/api/backtest/run",
            json={
                "pairs": ["BTC-USDT-SWAP"], "timeframe": "15m",
                "date_from": "2025-01-01", "date_to": "2025-06-01",
            },
            cookies={"krypton_token": make_test_jwt()},
        )
    assert resp.status_code == 429
