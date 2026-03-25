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


def test_get_algo_orders(app_with_okx, mock_okx_client):
    mock_okx_client.get_algo_orders_pending = AsyncMock(return_value=[
        {"algo_id": "algo1", "pair": "BTC-USDT-SWAP", "side": "sell",
         "tp_trigger_price": 70000.0, "sl_trigger_price": 60000.0,
         "size": "1", "status": "live"},
    ])
    client = TestClient(app_with_okx)
    resp = client.get("/api/account/algo-orders?pair=BTC-USDT-SWAP",
                       cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["algo_id"] == "algo1"


def test_amend_algo_success(app_with_okx, mock_okx_client):
    mock_okx_client.get_algo_orders_pending = AsyncMock(return_value=[
        {"algo_id": "algo1", "pair": "BTC-USDT-SWAP", "side": "sell",
         "tp_trigger_price": 70000.0, "sl_trigger_price": 60000.0,
         "size": "1", "status": "live"},
    ])
    mock_okx_client.cancel_algo_order = AsyncMock(return_value={"success": True})
    mock_okx_client.place_algo_order = AsyncMock(return_value={"success": True, "algo_id": "algo2"})
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/amend-algo", json={
        "pair": "BTC-USDT-SWAP", "side": "buy", "size": "1",
        "sl_price": "59000", "tp_price": "72000",
    }, cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["algo_id"] == "algo2"


def test_amend_algo_cancel_fails(app_with_okx, mock_okx_client):
    mock_okx_client.get_algo_orders_pending = AsyncMock(return_value=[
        {"algo_id": "algo1", "pair": "BTC-USDT-SWAP", "side": "sell",
         "tp_trigger_price": 70000.0, "sl_trigger_price": 60000.0,
         "size": "1", "status": "live"},
    ])
    mock_okx_client.cancel_algo_order = AsyncMock(return_value={"success": False, "error": "Cancel failed"})
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/amend-algo", json={
        "pair": "BTC-USDT-SWAP", "side": "buy", "size": "1",
        "sl_price": "59000",
    }, cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 400


def test_amend_algo_placement_fails_returns_sl_tp_removed(app_with_okx, mock_okx_client):
    mock_okx_client.get_algo_orders_pending = AsyncMock(return_value=[
        {"algo_id": "algo1", "pair": "BTC-USDT-SWAP", "side": "sell",
         "tp_trigger_price": 70000.0, "sl_trigger_price": 60000.0,
         "size": "1", "status": "live"},
    ])
    mock_okx_client.cancel_algo_order = AsyncMock(return_value={"success": True})
    mock_okx_client.place_algo_order = AsyncMock(return_value={"success": False, "error": "Placement failed"})
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/amend-algo", json={
        "pair": "BTC-USDT-SWAP", "side": "buy", "size": "1",
        "sl_price": "59000",
    }, cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["sl_tp_removed"] is True


def test_partial_close(app_with_okx, mock_okx_client):
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/partial-close", json={
        "pair": "BTC-USDT-SWAP", "pos_side": "long", "size": "0.5",
    }, cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # Verify place_order was called with correct closing side and pos_side
    call_kwargs = mock_okx_client.place_order.call_args
    assert call_kwargs.kwargs["side"] == "sell"
    assert call_kwargs.kwargs["pos_side"] == "long"


def test_partial_close_invalid_pos_side(app_with_okx):
    client = TestClient(app_with_okx)
    resp = client.post("/api/account/partial-close", json={
        "pair": "BTC-USDT-SWAP", "pos_side": "invalid", "size": "0.5",
    }, cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 422


def test_get_funding_costs(app_with_okx, mock_okx_client):
    mock_okx_client.get_funding_costs = AsyncMock(return_value=[
        {"pair": "BTC-USDT-SWAP", "pnl": -0.05, "fee": 0, "ts": 1711468800000},
        {"pair": "BTC-USDT-SWAP", "pnl": -0.03, "fee": 0, "ts": 1711472400000},
    ])
    client = TestClient(app_with_okx)
    resp = client.get("/api/account/funding-costs?pair=BTC-USDT-SWAP",
                       cookies={"krypton_token": make_test_jwt()})
    assert resp.status_code == 200
    data = resp.json()
    assert data["pair"] == "BTC-USDT-SWAP"
    assert data["total_funding"] == -0.08
