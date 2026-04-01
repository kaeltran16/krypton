"""Tests for ML training WebSocket endpoint and JWT auth."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from starlette.testclient import TestClient

from tests.conftest import _TEST_JWT_SECRET, make_test_jwt


def _make_ws_token(secret: str = _TEST_JWT_SECRET, expired: bool = False) -> str:
    exp = datetime.now(timezone.utc) + (timedelta(seconds=-10) if expired else timedelta(minutes=5))
    return pyjwt.encode({"purpose": "ws", "exp": exp}, secret, algorithm="HS256")


class TestWSToken:
    def test_create_ws_token_returns_valid_jwt(self):
        from app.api.auth import create_ws_token, ALGORITHM
        token = create_ws_token(_TEST_JWT_SECRET)
        payload = pyjwt.decode(token, _TEST_JWT_SECRET, algorithms=[ALGORITHM])
        assert payload["purpose"] == "ws"
        assert payload["exp"] > time.time()

    def test_create_ws_token_expires_in_5_minutes(self):
        from app.api.auth import create_ws_token, ALGORITHM
        token = create_ws_token(_TEST_JWT_SECRET)
        payload = pyjwt.decode(token, _TEST_JWT_SECRET, algorithms=[ALGORITHM])
        # Should expire within 5 minutes (300s), not 30 days
        assert payload["exp"] - time.time() < 310

    def test_verify_ws_token_accepts_valid(self):
        from app.api.auth import create_ws_token, verify_ws_token
        token = create_ws_token(_TEST_JWT_SECRET)
        assert verify_ws_token(token, _TEST_JWT_SECRET) is True

    def test_verify_ws_token_rejects_expired(self):
        from app.api.auth import verify_ws_token
        token = _make_ws_token(expired=True)
        assert verify_ws_token(token, _TEST_JWT_SECRET) is False

    def test_verify_ws_token_rejects_wrong_secret(self):
        from app.api.auth import verify_ws_token
        token = _make_ws_token(secret="wrong-secret")
        assert verify_ws_token(token, _TEST_JWT_SECRET) is False

    def test_verify_ws_token_rejects_missing_purpose(self):
        from app.api.auth import verify_ws_token
        token = pyjwt.encode(
            {"exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            _TEST_JWT_SECRET,
            algorithm="HS256",
        )
        assert verify_ws_token(token, _TEST_JWT_SECRET) is False


@pytest.fixture
def ws_token_app():
    from fastapi import FastAPI
    from app.api.auth import router as auth_router
    app = FastAPI()
    app.state.settings = MagicMock()
    app.state.settings.jwt_secret = _TEST_JWT_SECRET
    mock_db = MagicMock()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_db.session_factory = MagicMock(return_value=mock_session)
    app.state.db = mock_db
    app.include_router(auth_router)
    return app


class TestWSTokenEndpoint:
    @pytest.mark.asyncio
    async def test_ws_token_endpoint_requires_auth(self, ws_token_app):
        from httpx import AsyncClient, ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=ws_token_app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/auth/ws-token")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_ws_token_endpoint_returns_token(self, ws_token_app):
        from httpx import AsyncClient, ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=ws_token_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/auth/ws-token",
                cookies={"krypton_token": make_test_jwt()},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "token" in data
            # Verify the returned token is a valid WS token
            from app.api.auth import verify_ws_token
            assert verify_ws_token(data["token"], _TEST_JWT_SECRET) is True


from app.api.ml import _get_train_jobs


def _init_ml_ws(app, job_id: str = "test_job", status: str = "running"):
    """Set up a mock training job and WS connection store."""
    train_jobs = _get_train_jobs(app)
    train_jobs[job_id] = {"status": status, "progress": {}}
    if not hasattr(app.state, "ml_ws_connections"):
        app.state.ml_ws_connections = {}
    app.state.ml_ws_connections[job_id] = {
        "clients": [],
        "loss_history": {},
    }


@pytest.fixture
def ml_ws_app():
    from fastapi import FastAPI
    from app.api.ws_ml import router as ws_ml_router
    from app.api.auth import router as auth_router
    app = FastAPI()
    app.state.settings = MagicMock()
    app.state.settings.jwt_secret = _TEST_JWT_SECRET
    app.state.ml_ws_connections = {}
    app.include_router(ws_ml_router)
    app.include_router(auth_router)
    return app


class TestMLWebSocket:
    def test_rejects_missing_auth(self, ml_ws_app):
        _init_ml_ws(ml_ws_app)
        with TestClient(ml_ws_app) as client:
            with client.websocket_connect("/ws/ml-training/test_job") as ws:
                # Send no auth message — server should timeout or reject
                ws.send_json({"type": "not_auth"})
                # Server should close with 4001
                try:
                    ws.receive_json()
                    pytest.fail("Should have been closed")
                except Exception:
                    pass

    def test_rejects_invalid_token(self, ml_ws_app):
        _init_ml_ws(ml_ws_app)
        with TestClient(ml_ws_app) as client:
            with client.websocket_connect("/ws/ml-training/test_job") as ws:
                ws.send_json({"type": "auth", "token": "invalid"})
                try:
                    ws.receive_json()
                    pytest.fail("Should have been closed")
                except Exception:
                    pass

    def test_rejects_expired_token(self, ml_ws_app):
        _init_ml_ws(ml_ws_app)
        expired_token = _make_ws_token(expired=True)
        with TestClient(ml_ws_app) as client:
            with client.websocket_connect("/ws/ml-training/test_job") as ws:
                ws.send_json({"type": "auth", "token": expired_token})
                try:
                    ws.receive_json()
                    pytest.fail("Should have been closed")
                except Exception:
                    pass

    def test_accepts_valid_token_and_sends_snapshot(self, ml_ws_app):
        _init_ml_ws(ml_ws_app)
        token = _make_ws_token()
        with TestClient(ml_ws_app) as client:
            with client.websocket_connect("/ws/ml-training/test_job") as ws:
                ws.send_json({"type": "auth", "token": token})
                msg = ws.receive_json()
                assert msg["type"] == "snapshot"
                assert msg["status"] == "running"
                assert msg["progress"] == {}
                assert msg["loss_history"] == {}

    def test_snapshot_includes_accumulated_history(self, ml_ws_app):
        _init_ml_ws(ml_ws_app)
        # Pre-populate loss history (simulates late join)
        ml_ws_app.state.ml_ws_connections["test_job"]["loss_history"] = {
            "BTC-USDT-SWAP": [
                {"epoch": 1, "train_loss": 0.9, "val_loss": 0.95},
                {"epoch": 2, "train_loss": 0.8, "val_loss": 0.85},
            ]
        }
        train_jobs = _get_train_jobs(ml_ws_app)
        train_jobs["test_job"]["progress"] = {
            "BTC-USDT-SWAP": {"epoch": 2, "total_epochs": 100, "train_loss": 0.8, "val_loss": 0.85}
        }
        token = _make_ws_token()
        with TestClient(ml_ws_app) as client:
            with client.websocket_connect("/ws/ml-training/test_job") as ws:
                ws.send_json({"type": "auth", "token": token})
                msg = ws.receive_json()
                assert msg["type"] == "snapshot"
                assert len(msg["loss_history"]["BTC-USDT-SWAP"]) == 2
                assert msg["progress"]["BTC-USDT-SWAP"]["epoch"] == 2

    def test_client_added_to_connections(self, ml_ws_app):
        _init_ml_ws(ml_ws_app)
        token = _make_ws_token()
        with TestClient(ml_ws_app) as client:
            with client.websocket_connect("/ws/ml-training/test_job") as ws:
                ws.send_json({"type": "auth", "token": token})
                ws.receive_json()  # snapshot
                assert len(ml_ws_app.state.ml_ws_connections["test_job"]["clients"]) == 1

    def test_unknown_job_closes_connection(self, ml_ws_app):
        # No job set up — job_id doesn't exist
        token = _make_ws_token()
        with TestClient(ml_ws_app) as client:
            with client.websocket_connect("/ws/ml-training/nonexistent") as ws:
                ws.send_json({"type": "auth", "token": token})
                try:
                    ws.receive_json()
                    pytest.fail("Should have been closed")
                except Exception:
                    pass


class TestBroadcastWiring:
    @pytest.mark.asyncio
    async def test_ml_ws_connections_initialized_on_job_start(self, ws_token_app):
        """Starting training should create an entry in ml_ws_connections."""
        from httpx import AsyncClient, ASGITransport

        ws_token_app.state.ml_ws_connections = {}
        # Mock DB so training endpoint works
        mock_db = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_db.session_factory = MagicMock(return_value=mock_session)
        ws_token_app.state.db = mock_db
        ws_token_app.state.settings.pairs = ["BTC-USDT-SWAP"]
        ws_token_app.state.settings.ml_checkpoint_dir = "/tmp/ml"
        ws_token_app.state.ml_predictors = {}

        from app.api.ml import router as ml_router
        ws_token_app.include_router(ml_router)

        async with AsyncClient(
            transport=ASGITransport(app=ws_token_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/ml/train",
                json={"epochs": 5},
                cookies={"krypton_token": make_test_jwt()},
            )
            assert resp.status_code == 200
            job_id = resp.json()["job_id"]
            assert job_id in ws_token_app.state.ml_ws_connections
            entry = ws_token_app.state.ml_ws_connections[job_id]
            assert entry["clients"] == []
            assert entry["loss_history"] == {}


class TestBroadcastFunction:
    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_clients(self):
        from app.api.ws_ml import broadcast_ml_event
        app = MagicMock()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        app.state.ml_ws_connections = {
            "job1": {"clients": [ws1, ws2], "loss_history": {}},
        }
        event = {"type": "epoch_update", "pair": "BTC", "epoch": 1}
        await broadcast_ml_event(app, "job1", event)
        ws1.send_json.assert_called_once_with(event)
        ws2.send_json.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_clients(self):
        from app.api.ws_ml import broadcast_ml_event
        app = MagicMock()
        ws_alive = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_json.side_effect = Exception("disconnected")
        app.state.ml_ws_connections = {
            "job1": {"clients": [ws_alive, ws_dead], "loss_history": {}},
        }
        await broadcast_ml_event(app, "job1", {"type": "test"})
        ws_alive.send_json.assert_called_once()
        assert ws_dead not in app.state.ml_ws_connections["job1"]["clients"]

    @pytest.mark.asyncio
    async def test_broadcast_noop_for_unknown_job(self):
        from app.api.ws_ml import broadcast_ml_event
        app = MagicMock()
        app.state.ml_ws_connections = {}
        # Should not raise
        await broadcast_ml_event(app, "nonexistent", {"type": "test"})

    @pytest.mark.asyncio
    async def test_close_connections_closes_clients_and_defers_cleanup(self):
        from app.api.ws_ml import close_ml_connections
        app = MagicMock()
        ws = AsyncMock()
        app.state.ml_ws_connections = {
            "job1": {"clients": [ws], "loss_history": {}},
        }
        # Patch loop.call_later to capture the deferred cleanup
        mock_loop = MagicMock()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("asyncio.get_running_loop", lambda: mock_loop)
            await close_ml_connections(app, "job1")
        ws.close.assert_called_once()
        # Entry still exists (deferred cleanup), but clients list is cleared
        assert "job1" in app.state.ml_ws_connections
        assert app.state.ml_ws_connections["job1"]["clients"] == []
        # Deferred cleanup was scheduled
        mock_loop.call_later.assert_called_once()
