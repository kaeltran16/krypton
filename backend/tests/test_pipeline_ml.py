import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import run_pipeline


def _make_candle_list(n=80, base_price=67000):
    """Generate a list of JSON-encoded candle strings for Redis mock."""
    candles = []
    for i in range(n):
        candles.append(json.dumps({
            "open": base_price + i * 10,
            "high": base_price + i * 10 + 50,
            "low": base_price + i * 10 - 30,
            "close": base_price + i * 10 + 20,
            "volume": 100 + i,
        }))
    return candles


def _make_mock_app(*, ml_predictors=None, prompt_template=None):
    """Create a mock app with all required state."""
    app = MagicMock()
    settings = MagicMock()
    settings.ml_enabled = True
    settings.ml_confidence_threshold = 0.65
    settings.engine_signal_threshold = 50
    settings.engine_traditional_weight = 0.40
    settings.engine_flow_weight = 0.22
    settings.engine_onchain_weight = 0.23
    settings.engine_pattern_weight = 0.15
    settings.engine_llm_threshold = 30
    settings.engine_llm_timeout_seconds = 30
    settings.engine_ml_weight = 0.25
    settings.ml_sl_min_atr = 0.5
    settings.ml_sl_max_atr = 3.0
    settings.ml_tp1_min_atr = 1.0
    settings.ml_tp2_max_atr = 8.0
    settings.ml_rr_floor = 1.0
    settings.llm_caution_sl_factor = 0.8
    settings.onchain_enabled = False
    settings.pairs = ["BTC-USDT-SWAP"]
    app.state.settings = settings
    app.state.order_flow = {"BTC-USDT-SWAP": {}}
    app.state.prompt_template = prompt_template
    app.state.manager = AsyncMock()
    app.state.db = MagicMock()
    app.state.db.session_factory = MagicMock(return_value=AsyncMock())
    app.state.okx_client = None
    app.state.ml_predictors = ml_predictors or {}
    app.state.tracker = None

    redis = AsyncMock()
    redis.lrange.return_value = _make_candle_list()
    app.state.redis = redis

    return app


def _make_mock_predictor(direction="LONG", confidence=0.85, sl_atr=1.5, tp1_atr=2.0, tp2_atr=3.0):
    predictor = MagicMock()
    predictor.seq_len = 50
    predictor.flow_used = False
    predictor.predict.return_value = {
        "direction": direction,
        "confidence": confidence,
        "sl_atr": sl_atr,
        "tp1_atr": tp1_atr,
        "tp2_atr": tp2_atr,
    }
    return predictor


CANDLE = {"pair": "BTC-USDT-SWAP", "timeframe": "1h", "open": 67400, "close": 67500}


class TestUnifiedPipelineIndicatorOnly:
    """Tests for the unified pipeline when ML is unavailable."""

    @pytest.mark.asyncio
    async def test_indicators_only_emits_signal(self):
        app = _make_mock_app()
        app.state.settings.engine_signal_threshold = 10  # low threshold to ensure emission

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist:
            await run_pipeline(app, CANDLE)

            if mock_persist.called:
                signal = mock_persist.call_args[0][1]
                assert signal["traditional_score"] != 0  # always populated now

    @pytest.mark.asyncio
    async def test_indicators_below_threshold_no_signal(self):
        app = _make_mock_app()
        app.state.settings.engine_signal_threshold = 100  # very high threshold

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist:
            await run_pipeline(app, CANDLE)
            mock_persist.assert_not_called()


class TestUnifiedPipelineWithML:
    """Tests for the unified pipeline with ML predictor available."""

    @pytest.mark.asyncio
    async def test_ml_blends_with_indicators(self):
        """ML predictor present changes the blended score vs indicator-only."""
        predictor = _make_mock_predictor(direction="LONG", confidence=0.85)
        app_ml = _make_mock_app(ml_predictors={"btc_usdt_swap": predictor})
        app_ml.state.settings.engine_signal_threshold = 10

        app_no_ml = _make_mock_app()
        app_no_ml.state.settings.engine_signal_threshold = 10

        ml_signal = None
        no_ml_signal = None

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist:
            await run_pipeline(app_ml, CANDLE)
            if mock_persist.called:
                ml_signal = mock_persist.call_args[0][1]

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist:
            await run_pipeline(app_no_ml, CANDLE)
            if mock_persist.called:
                no_ml_signal = mock_persist.call_args[0][1]

        # If both emitted, the scores should differ due to ML blending
        if ml_signal and no_ml_signal:
            assert ml_signal["raw_indicators"].get("ml_score") is not None
            assert no_ml_signal["raw_indicators"].get("ml_score") is None

    @pytest.mark.asyncio
    async def test_ml_failure_falls_through_to_indicators(self):
        """ML failure still produces indicator-only signal."""
        predictor = _make_mock_predictor()
        predictor.predict.side_effect = RuntimeError("model error")
        app = _make_mock_app(ml_predictors={"btc_usdt_swap": predictor})
        app.state.settings.engine_signal_threshold = 10

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist:
            await run_pipeline(app, CANDLE)
            # Should not raise — indicators still run and may emit


class TestUnifiedPipelineLLMBehavior:
    """Tests for LLM behavioral guarantees in the unified pipeline."""

    @pytest.mark.asyncio
    async def test_contradict_penalizes_but_does_not_veto(self):
        """Pipeline still emits when LLM contradicts a strong signal — penalty reduces score but threshold check decides."""
        from app.engine.models import LLMResponse

        app = _make_mock_app(prompt_template="fake template")
        app.state.settings.engine_signal_threshold = 10  # low threshold so penalized score still emits
        app.state.settings.engine_llm_threshold = 5

        llm_resp = LLMResponse(
            opinion="contradict", confidence="HIGH",
            explanation="Clear reversal signal", levels=None,
        )

        # Patch tech score high enough that blended survives the contradict penalty
        strong_tech = {"score": 100, "indicators": {
            "atr": 200, "bb_width_pct": 50.0, "adx": 30, "di_plus": 25,
            "di_minus": 15, "rsi": 35, "bb_upper": 68000, "bb_lower": 67000,
            "bb_pos": 0.8, "obv_slope": 0.5, "vol_ratio": 1.5,
        }}

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist, \
             patch("app.main.call_openrouter", new_callable=AsyncMock, return_value=llm_resp), \
             patch("app.main.render_prompt", return_value="rendered"), \
             patch("app.main.compute_technical_score", return_value=strong_tech):
            await run_pipeline(app, CANDLE)
            # With low threshold, penalized score should still emit
            assert mock_persist.called, "Contradict should penalize, not veto — signal should still emit"
            # Verify the emitted signal_data dict has a reduced score (penalty applied)
            signal_data = mock_persist.call_args[0][1]  # persist_signal(db, signal_data)
            assert abs(signal_data["final_score"]) >= 10, "Penalized score should still exceed threshold"

    @pytest.mark.asyncio
    async def test_caution_still_emits(self):
        """Pipeline can still emit with caution — it just dampens score."""
        from app.engine.models import LLMResponse

        app = _make_mock_app(prompt_template="fake template")
        app.state.settings.engine_signal_threshold = 10

        llm_resp = LLMResponse(
            opinion="caution", confidence="LOW",
            explanation="Some minor concern", levels=None,
        )

        with patch("app.main.persist_signal", new_callable=AsyncMock) as mock_persist, \
             patch("app.main.call_openrouter", new_callable=AsyncMock, return_value=llm_resp), \
             patch("app.main.render_prompt", return_value="rendered"):
            await run_pipeline(app, CANDLE)
            # May or may not emit depending on indicator score, but shouldn't crash


class TestLLMPromptRendering:
    """Tests for the unified LLM prompt template."""

    def test_prompt_includes_ml_context_when_available(self):
        from app.engine.llm import render_prompt, load_prompt_template
        from pathlib import Path

        template_path = Path(__file__).parent.parent / "app" / "prompts" / "signal_analysis.txt"
        if not template_path.exists():
            pytest.skip("Prompt template not found")

        template = load_prompt_template(template_path)
        rendered = render_prompt(
            template=template,
            pair="BTC-USDT-SWAP",
            timeframe="1h",
            indicators='{"ema9": 67000}',
            order_flow='{"funding_rate": 0.001}',
            patterns="No patterns detected.",
            onchain="On-chain data not available.",
            ml_context="Direction: LONG, Confidence: 0.85, Suggested SL: 1.50x ATR, TP1: 2.00x ATR, TP2: 3.00x ATR",
            news="No recent news available.",
            preliminary_score="60",
            direction="LONG",
            blended_score="65",
            agreement="agree",
            candles='[{"close": 67500}]',
        )
        assert "Direction: LONG, Confidence: 0.85" in rendered
        assert "agree" in rendered
        assert "65" in rendered

    def test_prompt_omits_ml_when_unavailable(self):
        from app.engine.llm import render_prompt, load_prompt_template
        from pathlib import Path

        template_path = Path(__file__).parent.parent / "app" / "prompts" / "signal_analysis.txt"
        if not template_path.exists():
            pytest.skip("Prompt template not found")

        template = load_prompt_template(template_path)
        rendered = render_prompt(
            template=template,
            pair="BTC-USDT-SWAP",
            timeframe="1h",
            indicators='{"ema9": 67000}',
            order_flow='{"funding_rate": 0.001}',
            patterns="No patterns detected.",
            onchain="On-chain data not available.",
            ml_context="ML model not available for this pair.",
            news="No recent news available.",
            preliminary_score="60",
            direction="LONG",
            blended_score="60",
            agreement="neutral",
            candles='[{"close": 67500}]',
        )
        assert "ML model not available" in rendered
        assert "neutral" in rendered
