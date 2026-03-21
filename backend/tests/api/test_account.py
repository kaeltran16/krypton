import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from tests.conftest import make_test_jwt


@pytest.fixture
def mock_okx_client():
    client = AsyncMock()
    client.get_balance = AsyncMock(return_value={
        "total_equity": 10000.50,
        "unrealized_pnl": 150.25,
        "currencies": [{"currency": "USDT", "available": 5000.0, "frozen": 2000.0, "equity": 7000.0}],
    })
    client.get_positions = AsyncMock(return_value=[
        {"pair": "BTC-USDT-SWAP", "side": "long", "size": 1.0, "avg_price": 65000.0,
         "mark_price": 66000.0, "unrealized_pnl": 1000.0, "liquidation_price": 60000.0,
         "margin": 6500.0, "leverage": "10"},
    ])
    client.place_order = AsyncMock(return_value={
        "success": True, "order_id": "12345", "client_order_id": "abc",
    })
    return client


@pytest.fixture
def app_with_okx(mock_okx_client):
    from app.main import create_app
    app = create_app()
    app.state.okx_client = mock_okx_client
    app.state.settings = MagicMock()
    app.state.settings.jwt_secret = "test-jwt-secret"
    return app


@pytest.fixture
def app_without_okx():
    from app.main import create_app
    app = create_app()
    app.state.okx_client = None
    app.state.settings = MagicMock()
    app.state.settings.jwt_secret = "test-jwt-secret"
    return app


def test_get_balance(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.get("/api/account/balance", cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 200
    assert resp.json()["total_equity"] == 10000.50


def test_get_balance_no_okx(app_without_okx):
    client = TestClient(app_without_okx)
    resp = client.get("/api/account/balance", cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 503


def test_get_positions(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.get("/api/account/positions", cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["pair"] == "BTC-USDT-SWAP"


def test_place_order_success(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/order", json={
        "pair": "BTC-USDT-SWAP", "side": "buy", "size": "1",
    }, cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_place_order_invalid_side(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/order", json={
        "pair": "BTC-USDT-SWAP", "side": "invalid", "size": "1",
    }, cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 422


def test_place_order_invalid_size(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/order", json={
        "pair": "BTC-USDT-SWAP", "side": "buy", "size": "abc",
    }, cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 422


def test_place_order_negative_size(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/order", json={
        "pair": "BTC-USDT-SWAP", "side": "buy", "size": "-1",
    }, cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 422


def test_place_order_no_okx(app_without_okx):
    client = TestClient(app_without_okx)
    resp = client.post("/api/account/order", json={
        "pair": "BTC-USDT-SWAP", "side": "buy", "size": "1",
    }, cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 503
