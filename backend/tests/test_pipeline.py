import pandas as pd

from app.engine.traditional import compute_technical_score, compute_order_flow_score
from app.engine.combiner import compute_preliminary_score, compute_final_score, calculate_levels
from app.engine.llm import parse_llm_response


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

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])

    llm_json = '{"opinion": "confirm", "confidence": "HIGH", "explanation": "Strong setup.", "levels": null}'
    llm_response = parse_llm_response(llm_json)
    assert llm_response is not None

    final = compute_final_score(preliminary, llm_response)
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

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])
    final = compute_final_score(preliminary, llm_response=None)
    assert final == preliminary


def test_pipeline_with_empty_order_flow():
    """Pipeline should handle completely empty order flow gracefully."""
    candles_data = _make_candles()
    df = pd.DataFrame(candles_data)

    tech_result = compute_technical_score(df)
    flow_result = compute_order_flow_score({})
    assert flow_result["score"] == 0

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])
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
        SimpleNamespace(funding_rate=0.00005, long_short_ratio=1.05)
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

    preliminary = compute_preliminary_score(tech_result["score"], flow_result["score"])
    assert isinstance(preliminary, (int, float))
