"""Tests for ML pipeline graceful fallback during feature mismatches."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import run_pipeline
from tests.test_pipeline_ml import _make_candle_list, _make_mock_app

CANDLE = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "open": 67400, "close": 67500}


class TestMLPredictionExceptionFallback:

    @pytest.mark.asyncio
    async def test_pipeline_continues_on_predict_exception(self):
        """Pipeline should continue without ML when predict() raises."""
        predictor = MagicMock()
        predictor.seq_len = 50
        predictor.flow_used = False
        predictor.regime_used = False
        predictor.btc_used = False
        predictor.predict.side_effect = RuntimeError("dimension mismatch")

        app = _make_mock_app(ml_predictors={"btc_usdt_swap": predictor})
        app.state.settings.engine_signal_threshold = 10

        with patch("app.main.persist_signal", new_callable=AsyncMock):
            await run_pipeline(app, CANDLE)

    @pytest.mark.asyncio
    async def test_pipeline_continues_on_set_available_features_exception(self):
        """Pipeline should continue if set_available_features raises."""
        predictor = MagicMock()
        predictor.seq_len = 50
        predictor.flow_used = False
        predictor.regime_used = False
        predictor.btc_used = False
        predictor.set_available_features.side_effect = TypeError("unexpected arg")
        predictor.predict.return_value = {
            "direction": "NEUTRAL", "confidence": 0.0,
            "sl_atr": 0.0, "tp1_atr": 0.0, "tp2_atr": 0.0,
        }

        app = _make_mock_app(ml_predictors={"btc_usdt_swap": predictor})
        app.state.settings.engine_signal_threshold = 10

        with patch("app.main.persist_signal", new_callable=AsyncMock):
            await run_pipeline(app, CANDLE)
