import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock

from app.engine.traditional import compute_technical_score, compute_order_flow_score
from app.engine.combiner import compute_preliminary_score, compute_final_score, calculate_levels


def _make_candles(count: int = 80, base: float = 67000, trend: float = 10) -> list[dict]:
    """Generate synthetic uptrend candle data as list of dicts."""
    candles = []
    for i in range(count):
        o = base + i * trend
        candles.append({
            "open": o,
            "high": o + 50,
            "low": o - 30,
            "close": o + 20,
            "volume": 100 + i,
        })
    return candles


def test_full_pipeline_produces_signal():
    """End-to-end: candles + order flow -> preliminary score -> final score -> signal levels."""
    candles_data = _make_candles()
    df = pd.DataFrame(candles_data)

    tech_result = compute_technical_score(df)
    assert -100 <= tech_result["score"] <= 100

    flow_metrics = {
        "funding_rate": 0.0001,
        "open_interest_change_pct": 0.02,
        "long_short_ratio": 1.1,
    }
    flow_result = compute_order_flow_score(flow_metrics)
    assert -100 <= flow_result["score"] <= 100

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])["score"]

    # Simulate a positive LLM contribution (e.g., from factor scoring)
    final = compute_final_score(preliminary, 14)
    assert -100 <= final <= 100
    assert final > preliminary

    direction = "LONG" if final > 0 else "SHORT"
    atr = tech_result["indicators"]["atr"]
    levels = calculate_levels(direction, candles_data[-1]["close"], atr, llm_levels=None)
    assert "entry" in levels
    assert "stop_loss" in levels
    assert "take_profit_1" in levels
    assert "take_profit_2" in levels


def test_pipeline_without_llm():
    """Pipeline should work when LLM is skipped (preliminary below threshold)."""
    candles_data = _make_candles()
    df = pd.DataFrame(candles_data)

    tech_result = compute_technical_score(df)
    flow_result = compute_order_flow_score({})

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])["score"]
    final = compute_final_score(preliminary, 0)
    assert final == preliminary


def test_pipeline_with_empty_order_flow():
    """Pipeline should handle completely empty order flow gracefully."""
    candles_data = _make_candles()
    df = pd.DataFrame(candles_data)

    tech_result = compute_technical_score(df)
    flow_result = compute_order_flow_score({})
    assert flow_result["score"] == 0

    preliminary = compute_preliminary_score(
        tech_result["score"], flow_result["score"],
        tech_confidence=tech_result.get("confidence", 1.0),
        flow_confidence=flow_result.get("confidence", 0.0),
    )["score"]
    assert preliminary != 0


def test_pipeline_with_regime_and_flow_history():
    """Pipeline passes regime mix and flow history, signal includes diagnostic fields."""
    from types import SimpleNamespace

    candles_data = _make_candles()
    df = pd.DataFrame(candles_data)
    tech_result = compute_technical_score(df)

    flow_metrics = {
        "funding_rate": 0.0001,
        "open_interest_change_pct": 0.02,
        "long_short_ratio": 1.1,
        "price_direction": 1,
    }
    snapshots = [
        SimpleNamespace(funding_rate=0.00005, long_short_ratio=1.05, oi_change_pct=0.0)
        for _ in range(10)
    ]
    flow_result = compute_order_flow_score(
        flow_metrics,
        regime=tech_result["regime"],
        flow_history=snapshots,
    )
    assert -100 <= flow_result["score"] <= 100
    assert "contrarian_mult" in flow_result["details"]
    assert "final_mult" in flow_result["details"]
    assert flow_result["details"]["contrarian_mult"] <= 1.0

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])["score"]
    assert isinstance(preliminary, (int, float))


# --- order flow preloading ---

@pytest.mark.asyncio
async def test_order_flow_preloaded_from_db():
    """After lifespan init, order_flow should be seeded from latest snapshots."""
    from app.main import _seed_order_flow
    from app.db.models import OrderFlowSnapshot

    mock_snap = MagicMock(spec=OrderFlowSnapshot)
    mock_snap.pair = "BTC-USDT-SWAP"
    mock_snap.funding_rate = 0.0003
    mock_snap.open_interest = 150000.0
    mock_snap.long_short_ratio = 1.2

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_snap]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    order_flow = {}
    await _seed_order_flow(order_flow, mock_session)

    assert "BTC-USDT-SWAP" in order_flow
    assert order_flow["BTC-USDT-SWAP"]["funding_rate"] == 0.0003
    assert order_flow["BTC-USDT-SWAP"]["open_interest"] == 150000.0
    assert order_flow["BTC-USDT-SWAP"]["long_short_ratio"] == 1.2


@pytest.mark.asyncio
async def test_seed_order_flow_skips_null_fields():
    """Snapshot with NULL open_interest should not inject None into order_flow."""
    from app.main import _seed_order_flow
    from app.db.models import OrderFlowSnapshot

    mock_snap = MagicMock(spec=OrderFlowSnapshot)
    mock_snap.pair = "ETH-USDT-SWAP"
    mock_snap.funding_rate = 0.0001
    mock_snap.open_interest = None
    mock_snap.long_short_ratio = None

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_snap]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    order_flow = {}
    await _seed_order_flow(order_flow, mock_session)

    assert "ETH-USDT-SWAP" in order_flow
    assert order_flow["ETH-USDT-SWAP"]["funding_rate"] == 0.0001
    assert "open_interest" not in order_flow["ETH-USDT-SWAP"]
    assert "long_short_ratio" not in order_flow["ETH-USDT-SWAP"]
