import pytest
from app.engine.combiner import compute_preliminary_score, compute_confidence_tier
from app.engine.constants import CONVICTION_FLOOR


class TestConfidenceWeightedCombiner:
    def test_high_confidence_source_dominates(self):
        """Source with high confidence should get more weight."""
        result_equal = compute_preliminary_score(
            50, 0, 0.5, 0.5,
            tech_confidence=0.5, flow_confidence=0.5,
        )
        result_tech_dominant = compute_preliminary_score(
            50, 0, 0.5, 0.5,
            tech_confidence=1.0, flow_confidence=0.1,
        )
        assert result_tech_dominant["score"] > result_equal["score"]

    def test_zero_confidence_zeroes_weight(self):
        """Source with 0 confidence should have no influence."""
        result = compute_preliminary_score(
            100, -100, 0.5, 0.5,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_confidence=1.0, flow_confidence=0.0,
            onchain_confidence=0.0, pattern_confidence=0.0,
        )
        assert result["score"] == 100

    def test_backward_compatible_with_confidence(self):
        """Confidence params still produce valid results."""
        result = compute_preliminary_score(
            50, 30, 0.6, 0.4,
            tech_confidence=0.8, flow_confidence=0.6,
        )
        assert isinstance(result["score"], int)
        assert -100 <= result["score"] <= 100

    def test_avg_confidence_returned(self):
        """Result includes avg_confidence for tier computation."""
        result = compute_preliminary_score(
            50, 30, 0.5, 0.5,
            tech_confidence=0.8, flow_confidence=0.6,
        )
        assert 0.0 <= result["avg_confidence"] <= 1.0

    def test_confluence_participates_in_blending(self):
        """Confluence as 6th source contributes when weight and confidence are set."""
        baseline = compute_preliminary_score(
            60, 40, 0.5, 0.5,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_confidence=0.8, flow_confidence=0.8,
            onchain_confidence=0.0, pattern_confidence=0.0,
        )
        with_confluence = compute_preliminary_score(
            60, 40, 0.4, 0.4,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_confidence=0.8, flow_confidence=0.8,
            onchain_confidence=0.0, pattern_confidence=0.0,
            confluence_score=90,
            confluence_weight=0.2,
            confluence_confidence=0.9,
        )
        assert with_confluence["score"] > baseline["score"]
        assert with_confluence["avg_confidence"] > 0.0


class TestAvgConfidenceEffectiveWeights:
    """Validates effective-weight avg_confidence contract."""

    def test_avg_confidence_uses_effective_weights(self):
        """High-confidence source should dominate avg_confidence."""
        result = compute_preliminary_score(
            100, 0, 0.5, 0.5,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_confidence=0.9, flow_confidence=0.1,
        )
        # Tech effective weight = 0.5*0.9 = 0.45, flow = 0.5*0.1 = 0.05
        # Normalized: tech_ew = 0.9, flow_ew = 0.1
        # avg_confidence = 0.9*0.9 + 0.1*0.1 = 0.82
        assert result["avg_confidence"] > 0.8

    def test_avg_confidence_zero_confidence_excluded(self):
        """Source with 0 confidence should not drag avg_confidence down."""
        result = compute_preliminary_score(
            100, 0, 0.5, 0.5,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_confidence=0.9, flow_confidence=0.0,
        )
        # Only tech contributes: ew_tech=1.0, avg = 0.9*1.0 = 0.9
        assert result["avg_confidence"] == pytest.approx(0.9, abs=0.01)

    def test_avg_confidence_all_zero_returns_zero(self):
        """All zero confidence returns avg_confidence=0."""
        result = compute_preliminary_score(
            100, 50, 0.5, 0.5,
            tech_confidence=0.0, flow_confidence=0.0,
            onchain_confidence=0.0, pattern_confidence=0.0,
        )
        assert result["avg_confidence"] == 0.0


class TestAvailabilityConviction:
    def test_availability_gates_weight(self):
        """Source with availability=0 should not contribute regardless of conviction."""
        result = compute_preliminary_score(
            technical_score=100, order_flow_score=-100,
            tech_weight=0.5, flow_weight=0.5,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=1.0, tech_conviction=0.8,
            flow_availability=0.0, flow_conviction=1.0,
        )
        assert result["score"] == pytest.approx(100 * (CONVICTION_FLOOR + (1 - CONVICTION_FLOOR) * 0.8), abs=2)

    def test_conviction_scales_score(self):
        """Low conviction reduces score magnitude via floor."""
        high_conv = compute_preliminary_score(
            technical_score=100, order_flow_score=0,
            tech_weight=1.0, flow_weight=0.0,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=1.0, tech_conviction=1.0,
        )
        low_conv = compute_preliminary_score(
            technical_score=100, order_flow_score=0,
            tech_weight=1.0, flow_weight=0.0,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=1.0, tech_conviction=0.0,
        )
        # conviction=1.0 -> scale=1.0, conviction=0.0 -> scale=CONVICTION_FLOOR
        assert high_conv["score"] == 100
        assert low_conv["score"] == pytest.approx(100 * CONVICTION_FLOOR, abs=2)

    def test_backward_compat_confidence_still_works(self):
        """Legacy confidence param still works (mapped to availability)."""
        result = compute_preliminary_score(
            technical_score=80, order_flow_score=60,
            tech_weight=0.6, flow_weight=0.4,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_confidence=0.9, flow_confidence=0.5,
        )
        assert isinstance(result["score"], int)


class TestRawOuterWeights:
    def test_unavailable_source_excluded_via_zero_confidence(self):
        """Source with confidence=0 has zero effective weight even with nonzero base weight."""
        result = compute_preliminary_score(
            technical_score=80, order_flow_score=60,
            tech_weight=0.40, flow_weight=0.22,
            onchain_score=50, onchain_weight=0.23,
            pattern_score=40, pattern_weight=0.15,
            tech_confidence=0.9, flow_confidence=0.0,
            onchain_confidence=0.7, pattern_confidence=0.6,
        )
        # flow has confidence=0 so ew_flow=0, flow_score shouldn't contribute
        result_no_flow = compute_preliminary_score(
            technical_score=80, order_flow_score=0,
            tech_weight=0.40, flow_weight=0.0,
            onchain_score=50, onchain_weight=0.23,
            pattern_score=40, pattern_weight=0.15,
            tech_confidence=0.9, flow_confidence=0.0,
            onchain_confidence=0.7, pattern_confidence=0.6,
        )
        assert result["score"] == result_no_flow["score"]


class TestPipelineWiring:
    """Verify availability/conviction extraction logic used in main.py and backtester."""

    def test_scorer_output_with_availability_passes_through(self):
        """Scorer returning availability/conviction should produce correct combiner input."""
        tech_result = {"score": 80, "availability": 1.0, "conviction": 0.7, "confidence": 0.7}
        flow_result = {"score": 40, "availability": 0.6, "conviction": 0.5, "confidence": 0.3}

        tech_avail = tech_result.get("availability", tech_result.get("confidence", 0.0))
        tech_conv = tech_result.get("conviction", 1.0)
        flow_avail = flow_result.get("availability", flow_result.get("confidence", 0.0))
        flow_conv = flow_result.get("conviction", 1.0)

        result = compute_preliminary_score(
            technical_score=80, order_flow_score=40,
            tech_weight=0.6, flow_weight=0.4,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=tech_avail, tech_conviction=tech_conv,
            flow_availability=flow_avail, flow_conviction=flow_conv,
        )
        assert isinstance(result["score"], int)
        assert result["score"] != 0

    def test_scorer_output_legacy_confidence_fallback(self):
        """Scorer without availability/conviction falls back to confidence correctly."""
        legacy_result = {"score": 60, "confidence": 0.8}

        avail = legacy_result.get("availability", legacy_result.get("confidence", 0.0))
        conv = legacy_result.get("conviction", 1.0)

        assert avail == 0.8
        assert conv == 1.0

    def test_pruned_source_zeroed(self):
        """Pruned source gets availability=0, excluding it from blend."""
        pruned = {"flow"}
        avail_vars = {"tech": 1.0, "flow": 0.6, "onchain": 0.0,
                      "pattern": 0.0, "liquidation": 0.0, "confluence": 0.0}
        for src in pruned:
            if src in avail_vars:
                avail_vars[src] = 0.0

        result = compute_preliminary_score(
            technical_score=80, order_flow_score=60,
            tech_weight=0.5, flow_weight=0.5,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=avail_vars["tech"], tech_conviction=0.8,
            flow_availability=avail_vars["flow"], flow_conviction=0.9,
        )
        tech_only = compute_preliminary_score(
            technical_score=80, order_flow_score=0,
            tech_weight=1.0, flow_weight=0.0,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_availability=1.0, tech_conviction=0.8,
        )
        assert result["score"] == tech_only["score"]


class TestConfidenceTier:
    def test_high_tier(self):
        assert compute_confidence_tier(0.8) == "high"

    def test_medium_tier(self):
        assert compute_confidence_tier(0.5) == "medium"

    def test_low_tier(self):
        assert compute_confidence_tier(0.1) == "low"

    def test_boundary_high(self):
        assert compute_confidence_tier(0.7) == "high"

    def test_boundary_medium(self):
        assert compute_confidence_tier(0.4) == "medium"
