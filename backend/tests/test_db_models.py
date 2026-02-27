from datetime import datetime, timezone
from decimal import Decimal

from app.db.models import Candle, Signal


def test_candle_model():
    candle = Candle(
        pair="BTC-USDT-SWAP",
        timeframe="15m",
        timestamp=datetime(2026, 2, 27, 14, 0, tzinfo=timezone.utc),
        open=Decimal("67000.5"),
        high=Decimal("67200.0"),
        low=Decimal("66900.0"),
        close=Decimal("67100.0"),
        volume=Decimal("1234.56"),
    )
    assert candle.pair == "BTC-USDT-SWAP"
    assert candle.timeframe == "15m"
    assert candle.close == Decimal("67100.0")


def test_signal_model():
    signal = Signal(
        pair="BTC-USDT-SWAP",
        timeframe="15m",
        direction="LONG",
        final_score=78,
        traditional_score=72,
        llm_opinion="confirm",
        llm_confidence="HIGH",
        explanation="Strong bullish setup.",
        entry=Decimal("67420"),
        stop_loss=Decimal("66890"),
        take_profit_1=Decimal("67950"),
        take_profit_2=Decimal("68480"),
        raw_indicators={"rsi": 32, "ema_9": 67100},
    )
    assert signal.direction == "LONG"
    assert signal.final_score == 78
    assert signal.raw_indicators["rsi"] == 32
