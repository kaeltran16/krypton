import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import run_pipeline


class TestMLPipelinePath:

    @pytest.fixture
    def mock_app(self):
        app = MagicMock()
        settings = MagicMock()
        settings.ml_enabled = True
        settings.ml_confidence_threshold = 0.65
        settings.ml_llm_threshold = 0.65
        settings.engine_signal_threshold = 30
        settings.engine_traditional_weight = 0.40
        settings.engine_flow_weight = 0.22
        settings.engine_onchain_weight = 0.23
        settings.engine_pattern_weight = 0.15
        settings.engine_llm_threshold = 30
        settings.engine_llm_timeout_seconds = 30
        settings.onchain_enabled = False
        settings.pairs = ["BTC-USDT-SWAP"]
        app.state.settings = settings
        app.state.order_flow = {"BTC-USDT-SWAP": {}}
        app.state.prompt_template = None
        app.state.manager = AsyncMock()
        app.state.db = MagicMock()
        app.state.db.session_factory = MagicMock(return_value=AsyncMock())
        app.state.okx_client = None

        # Mock Redis with 50 candles
        candles = []
        for i in range(50):
            candles.append(json.dumps({
                "open": 67000 + i * 10,
                "high": 67000 + i * 10 + 50,
                "low": 67000 + i * 10 - 30,
                "close": 67000 + i * 10 + 20,
                "volume": 100 + i,
            }))
        redis = AsyncMock()
        redis.lrange.return_value = candles
        app.state.redis = redis

        return app

    @pytest.fixture
    def mock_predictor(self):
        predictor = MagicMock()
        predictor.seq_len = 50
        predictor.flow_used = False
        predictor.predict.return_value = {
            "direction": "LONG",
            "confidence": 0.85,
            "sl_atr": 1.5,
            "tp1_atr": 2.0,
            "tp2_atr": 3.0,
        }
        return predictor

    @pytest.mark.asyncio
    async def test_ml_path_emits_signal(self, mock_app, mock_predictor):
        mock_app.state.ml_predictors = {"btc_usdt_swap": mock_predictor}

        candle = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "close": 67500}

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist:
            await run_pipeline(mock_app, candle)

            mock_predictor.predict.assert_called_once()
            mock_persist.assert_called_once()
            signal = mock_persist.call_args[0][1]
            assert signal["direction"] == "LONG"
            assert signal["pair"] == "BTC-USDT-SWAP"

    @pytest.mark.asyncio
    async def test_ml_path_low_confidence_no_signal(self, mock_app, mock_predictor):
        mock_predictor.predict.return_value["confidence"] = 0.40
        mock_app.state.ml_predictors = {"btc_usdt_swap": mock_predictor}

        candle = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "close": 67500}

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist:
            await run_pipeline(mock_app, candle)
            mock_persist.assert_not_called()

    @pytest.mark.asyncio
    async def test_ml_failure_falls_through_to_rule_based(self, mock_app, mock_predictor):
        mock_predictor.predict.side_effect = RuntimeError("model error")
        mock_app.state.ml_predictors = {"btc_usdt_swap": mock_predictor}

        candle = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "close": 67500}

        # Should not raise — falls through to rule-based path
        with patch("app.main.persist_signal", new_callable=AsyncMock):
            await run_pipeline(mock_app, candle)
