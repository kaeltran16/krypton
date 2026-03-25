import pytest
from unittest.mock import MagicMock


@pytest.mark.asyncio
async def test_depth_state_stored():
    """books5 data should be stored in app.state.order_book with correct structure."""
    from app.main import handle_depth

    app = MagicMock()
    app.state.order_book = {}

    await handle_depth(app, {
        "pair": "BTC-USDT-SWAP",
        "bids": [(67000.0, 10.0), (66990.0, 20.0)],
        "asks": [(67010.0, 15.0), (67020.0, 8.0)],
    })

    assert "BTC-USDT-SWAP" in app.state.order_book
    assert len(app.state.order_book["BTC-USDT-SWAP"]["bids"]) == 2
    assert len(app.state.order_book["BTC-USDT-SWAP"]["asks"]) == 2
    assert "_last_updated" in app.state.order_book["BTC-USDT-SWAP"]
