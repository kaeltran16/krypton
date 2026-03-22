import pytest
from app.engine.constants import PARAMETER_DESCRIPTIONS


def test_parameter_descriptions_structure():
    """Every description has required fields."""
    assert len(PARAMETER_DESCRIPTIONS) > 0
    for key, desc in PARAMETER_DESCRIPTIONS.items():
        assert "description" in desc, f"{key} missing description"
        assert "pipeline_stage" in desc, f"{key} missing pipeline_stage"
        assert "range" in desc, f"{key} missing range"
        assert isinstance(desc["description"], str)
        assert isinstance(desc["pipeline_stage"], str)
        assert isinstance(desc["range"], str)


def test_parameter_descriptions_coverage():
    """Descriptions cover key parameter groups."""
    keys = set(PARAMETER_DESCRIPTIONS.keys())
    # Spot-check a few from each group
    assert "signal_threshold" in keys or "signal" in keys
    assert "traditional_weight" in keys or "traditional" in keys
