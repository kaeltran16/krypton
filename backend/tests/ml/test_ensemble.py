import pytest
from app.ml.ensemble import compute_ensemble_signal


class TestComputeEnsembleSignal:

    def test_ml_and_llm_agree_long(self):
        ml = {"direction": "LONG", "confidence": 0.85, "sl_atr": 1.3, "tp1_atr": 2.1, "tp2_atr": 3.4}
        llm = {"opinion": "confirm", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm)
        assert result["direction"] == "LONG"
        assert result["emit"] is True
        assert result["position_scale"] == 1.0

    def test_ml_and_llm_agree_short(self):
        ml = {"direction": "SHORT", "confidence": 0.75, "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0}
        llm = {"opinion": "confirm", "confidence": "MEDIUM"}
        result = compute_ensemble_signal(ml, llm)
        assert result["direction"] == "SHORT"
        assert result["emit"] is True

    def test_llm_caution_tightens_sl(self):
        ml = {"direction": "LONG", "confidence": 0.80, "sl_atr": 2.0, "tp1_atr": 3.0, "tp2_atr": 4.0}
        llm = {"opinion": "caution", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm)
        assert result["emit"] is True
        assert result["sl_atr"] < 2.0  # tightened
        assert result["position_scale"] < 1.0

    def test_llm_contradict_blocks(self):
        ml = {"direction": "LONG", "confidence": 0.90, "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0}
        llm = {"opinion": "contradict", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm)
        assert result["emit"] is False

    def test_ml_neutral_no_signal(self):
        ml = {"direction": "NEUTRAL", "confidence": 0.60, "sl_atr": 0, "tp1_atr": 0, "tp2_atr": 0}
        llm = {"opinion": "confirm", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm)
        assert result["emit"] is False

    def test_low_confidence_no_signal(self):
        ml = {"direction": "LONG", "confidence": 0.50, "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0}
        llm = {"opinion": "confirm", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm)
        assert result["emit"] is False

    def test_custom_min_confidence(self):
        ml = {"direction": "LONG", "confidence": 0.70, "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0}
        llm = {"opinion": "confirm", "confidence": "HIGH"}
        result = compute_ensemble_signal(ml, llm, min_confidence=0.80)
        assert result["emit"] is False
        result2 = compute_ensemble_signal(ml, llm, min_confidence=0.60)
        assert result2["emit"] is True

    def test_no_llm_response_still_works(self):
        ml = {"direction": "LONG", "confidence": 0.80, "sl_atr": 1.5, "tp1_atr": 2.0, "tp2_atr": 3.0}
        result = compute_ensemble_signal(ml, llm_response=None)
        # Without LLM confirmation, emit with reduced scale
        assert result["emit"] is True
        assert result["position_scale"] < 1.0
