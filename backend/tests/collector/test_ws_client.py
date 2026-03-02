import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.collector.ws_client import (
    OKXWebSocketClient,
    parse_candle_message,
    parse_funding_rate_message,
    parse_open_interest_message,
)


# --- candle parsing ---

def test_parse_candle_message_confirmed():
    """Parse a confirmed candle close message from OKX."""
    raw = {
        "arg": {"channel": "candle15m", "instId": "BTC-USDT-SWAP"},
        "data": [
            ["1709042400000", "67000.5", "67200.0", "66900.0", "67100.0", "1234.56", "0", "0", "1"]
        ],
    }
    result = parse_candle_message(raw)
    assert result is not None
    assert result["pair"] == "BTC-USDT-SWAP"
    assert result["timeframe"] == "15m"
    assert result["open"] == 67000.5
    assert result["close"] == 67100.0
    assert result["confirmed"] is True


def test_parse_candle_message_returns_floats():
    """OHLCV values must be floats, not strings."""
    raw = {
        "arg": {"channel": "candle1H", "instId": "ETH-USDT-SWAP"},
        "data": [
            ["1709042400000", "3400.25", "3450.0", "3380.0", "3420.5", "5678.9", "0", "0", "1"]
        ],
    }
    result = parse_candle_message(raw)
    assert isinstance(result["open"], float)
    assert isinstance(result["high"], float)
    assert isinstance(result["low"], float)
    assert isinstance(result["close"], float)
    assert isinstance(result["volume"], float)


def test_parse_candle_message_unconfirmed():
    """Unconfirmed candle should return result with confirmed=False."""
    raw = {
        "arg": {"channel": "candle15m", "instId": "BTC-USDT-SWAP"},
        "data": [
            ["1709042400000", "67000.5", "67200.0", "66900.0", "67100.0", "1234.56", "0", "0", "0"]
        ],
    }
    result = parse_candle_message(raw)
    assert result is not None
    assert result["confirmed"] is False


def test_parse_candle_message_invalid():
    """Invalid message returns None."""
    result = parse_candle_message({"event": "subscribe"})
    assert result is None


# --- funding rate parsing ---

def test_parse_funding_rate_message():
    """Parse a funding rate push from OKX."""
    raw = {
        "arg": {"channel": "funding-rate", "instId": "BTC-USDT-SWAP"},
        "data": [
            {
                "fundingRate": "0.00015",
                "fundingTime": "1709049600000",
                "instId": "BTC-USDT-SWAP",
                "instType": "SWAP",
                "nextFundingRate": "0.00012",
                "nextFundingTime": "1709078400000",
            }
        ],
    }
    result = parse_funding_rate_message(raw)
    assert result is not None
    assert result["pair"] == "BTC-USDT-SWAP"
    assert result["funding_rate"] == 0.00015
    assert result["next_funding_rate"] == 0.00012


def test_parse_funding_rate_message_blank_next_rate():
    raw = {
        "arg": {"channel": "funding-rate", "instId": "BTC-USDT-SWAP"},
        "data": [
            {
                "fundingRate": "0.00015",
                "fundingTime": "1709049600000",
                "nextFundingRate": "",
            }
        ],
    }
    result = parse_funding_rate_message(raw)
    assert result is not None
    assert result["funding_rate"] == 0.00015
    assert result["next_funding_rate"] is None


def test_parse_funding_rate_message_invalid():
    result = parse_funding_rate_message({"event": "subscribe"})
    assert result is None


# --- open interest parsing ---

def test_parse_open_interest_message():
    """Parse an open interest push from OKX."""
    raw = {
        "arg": {"channel": "open-interest", "instId": "BTC-USDT-SWAP"},
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "instType": "SWAP",
                "oi": "45000",
                "oiCcy": "45000",
                "ts": "1709042400000",
            }
        ],
    }
    result = parse_open_interest_message(raw)
    assert result is not None
    assert result["pair"] == "BTC-USDT-SWAP"
    assert result["open_interest"] == 45000.0


def test_parse_open_interest_message_invalid():
    result = parse_open_interest_message({"event": "subscribe"})
    assert result is None


def test_parse_open_interest_message_blank_oi():
    raw = {
        "arg": {"channel": "open-interest", "instId": "BTC-USDT-SWAP"},
        "data": [
            {
                "oi": "",
                "ts": "1709042400000",
            }
        ],
    }
    result = parse_open_interest_message(raw)
    assert result is None


# --- subscription building ---

def test_build_candle_args():
    """Build correct candle subscription args for business endpoint."""
    client = OKXWebSocketClient(
        pairs=["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
        timeframes=["15m", "1h"],
    )
    args = client._build_candle_args()
    assert len(args) == 4
    assert {"channel": "candle15m", "instId": "BTC-USDT-SWAP"} in args
    assert {"channel": "candle1H", "instId": "ETH-USDT-SWAP"} in args


def test_build_public_args():
    """Build correct public subscription args for funding-rate and open-interest."""
    client = OKXWebSocketClient(
        pairs=["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
        timeframes=["15m", "1h"],
    )
    args = client._build_public_args()
    assert len(args) == 4
    assert {"channel": "funding-rate", "instId": "BTC-USDT-SWAP"} in args
    assert {"channel": "open-interest", "instId": "ETH-USDT-SWAP"} in args


def test_timeframe_to_channel_mapping():
    """Timeframe strings map to OKX channel names."""
    client = OKXWebSocketClient(pairs=["BTC-USDT-SWAP"], timeframes=["15m", "1h", "4h"])
    candle_args = client._build_candle_args()
    channels = {a["channel"] for a in candle_args}
    assert channels == {"candle15m", "candle1H", "candle4H"}

