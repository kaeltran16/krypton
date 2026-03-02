from unittest.mock import AsyncMock, MagicMock, patch

from app.collector.rest_poller import OKXRestPoller, parse_long_short_response


def test_parse_long_short_response_valid():
    """Parse valid long/short ratio response."""
    raw = {
        "code": "0",
        "data": [
            {"ts": "1709042400000", "longShortRatio": "1.25"}
        ],
    }
    result = parse_long_short_response(raw, "BTC-USDT-SWAP")
    assert result is not None
    assert result["pair"] == "BTC-USDT-SWAP"
    assert result["long_short_ratio"] == 1.25


def test_parse_long_short_response_array_row():
    raw = {
        "code": "0",
        "data": [
            ["1709042400000", "1.25"]
        ],
    }
    result = parse_long_short_response(raw, "BTC-USDT-SWAP")
    assert result is not None
    assert result["long_short_ratio"] == 1.25


def test_parse_long_short_response_invalid():
    """Invalid response returns None."""
    result = parse_long_short_response({"code": "1"}, "BTC-USDT-SWAP")
    assert result is None


async def test_poller_fetches_for_all_pairs():
    """Poller should fetch long/short ratio for each configured pair."""
    poller = OKXRestPoller(
        pairs=["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
        interval_seconds=300,
    )
    mock_callback = AsyncMock()
    poller.on_data = mock_callback

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "code": "0",
        "data": [["1709042400000", "1.5"]],
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    # httpx.AsyncClient() returns an object used as `async with ... as client:`
    # Use a simple async context manager to avoid AsyncMock __aenter__ issues
    class FakeClientCM:
        async def __aenter__(self):
            return mock_client

        async def __aexit__(self, *args):
            pass

    with patch("app.collector.rest_poller.httpx.AsyncClient", return_value=FakeClientCM()):
        await poller.fetch_once()

    assert mock_callback.call_count == 2
    assert mock_client.get.await_count == 2
    first_call = mock_client.get.await_args_list[0]
    second_call = mock_client.get.await_args_list[1]
    assert first_call.kwargs["params"] == {"ccy": "BTC", "period": "5m"}
    assert second_call.kwargs["params"] == {"ccy": "ETH", "period": "5m"}


