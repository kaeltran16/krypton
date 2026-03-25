import pytest
from unittest.mock import AsyncMock, patch
from app.exchange.okx_client import OKXClient, _sign_request, parse_balance_response


def test_sign_request():
    """HMAC-SHA256 signing produces correct base64 output."""
    timestamp = "2024-01-01T00:00:00.000Z"
    method = "GET"
    path = "/api/v5/account/balance"
    body = ""
    secret = "test-secret"
    signature = _sign_request(timestamp, method, path, body, secret)
    assert isinstance(signature, str)
    assert len(signature) > 0


def test_parse_balance_response():
    raw = {
        "code": "0",
        "data": [{
            "totalEq": "10000.50",
            "upl": "150.25",
            "details": [{
                "ccy": "USDT",
                "availBal": "5000.00",
                "frozenBal": "2000.00",
                "eq": "7000.00",
            }],
        }],
    }
    result = parse_balance_response(raw)
    assert result["total_equity"] == 10000.50
    assert result["unrealized_pnl"] == 150.25
    assert len(result["currencies"]) == 1
    assert result["currencies"][0]["currency"] == "USDT"
    assert result["currencies"][0]["available"] == 5000.00


def test_parse_balance_response_error():
    raw = {"code": "50000", "msg": "error"}
    result = parse_balance_response(raw)
    assert result is None


def test_parse_positions_response():
    from app.exchange.okx_client import parse_positions_response
    raw = {
        "code": "0",
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "posSide": "long",
                "pos": "1",
                "avgPx": "65000",
                "markPx": "66000",
                "upl": "1000",
                "liqPx": "60000",
                "margin": "6500",
                "lever": "10",
            },
            {
                "instId": "ETH-USDT-SWAP",
                "posSide": "short",
                "pos": "0",
                "avgPx": "0",
                "markPx": "0",
                "upl": "0",
                "liqPx": "",
                "margin": "0",
                "lever": "0",
            },
        ],
    }
    result = parse_positions_response(raw)
    assert len(result) == 1
    assert result[0]["pair"] == "BTC-USDT-SWAP"
    assert result[0]["side"] == "long"
    assert result[0]["unrealized_pnl"] == 1000.0


def test_parse_positions_response_empty():
    from app.exchange.okx_client import parse_positions_response
    raw = {"code": "0", "data": []}
    assert parse_positions_response(raw) == []


def test_parse_order_response_success():
    from app.exchange.okx_client import parse_order_response
    raw = {
        "code": "0",
        "data": [{"ordId": "12345", "clOrdId": "abc"}],
    }
    result = parse_order_response(raw)
    assert result["success"] is True
    assert result["order_id"] == "12345"


def test_parse_order_response_error():
    from app.exchange.okx_client import parse_order_response
    raw = {
        "code": "51000",
        "msg": "Parameter error",
        "data": [{"sCode": "51000", "sMsg": "Invalid size"}],
    }
    result = parse_order_response(raw)
    assert result["success"] is False
    assert "Invalid size" in result["error"]


def test_parse_positions_response_with_ctime():
    from app.exchange.okx_client import parse_positions_response
    raw = {
        "code": "0",
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "posSide": "long",
                "pos": "1",
                "avgPx": "65000",
                "markPx": "66000",
                "upl": "1000",
                "liqPx": "60000",
                "margin": "6500",
                "lever": "10",
                "cTime": "1711468800000",
            },
        ],
    }
    result = parse_positions_response(raw)
    assert len(result) == 1
    assert result[0]["created_at"] is not None
    assert "2024-03-26" in result[0]["created_at"]


def test_parse_positions_response_missing_ctime():
    from app.exchange.okx_client import parse_positions_response
    raw = {
        "code": "0",
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "posSide": "long",
                "pos": "1",
                "avgPx": "65000",
                "markPx": "66000",
                "upl": "1000",
                "liqPx": "60000",
                "margin": "6500",
                "lever": "10",
            },
        ],
    }
    result = parse_positions_response(raw)
    assert len(result) == 1
    assert result[0]["created_at"] is None
