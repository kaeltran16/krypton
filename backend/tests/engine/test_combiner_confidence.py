from app.engine.combiner import compute_preliminary_score, compute_confidence_tier


class TestConfidenceWeightedCombiner:
    def test_high_confidence_source_dominates(self):
        """Source with high confidence should get more weight."""
        # all equal weights, but tech has high confidence and others low
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

    def test_backward_compatible_defaults(self):
        """Default confidence values should produce same result as old behavior."""
        result = compute_preliminary_score(50, 30, 0.6, 0.4)
        # defaults are 0.5, so weights proportional: 0.6*0.5 : 0.4*0.5 = same ratio
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
        # baseline: tech=60, flow=40, no confluence
        baseline = compute_preliminary_score(
            60, 40, 0.5, 0.5,
            onchain_weight=0.0, pattern_weight=0.0,
            tech_confidence=0.8, flow_confidence=0.8,
            onchain_confidence=0.0, pattern_confidence=0.0,
        )
        # with confluence strongly bullish (+90), it should pull score up
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
        # avg_confidence should include confluence contribution
        assert with_confluence["avg_confidence"] > 0.0


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
