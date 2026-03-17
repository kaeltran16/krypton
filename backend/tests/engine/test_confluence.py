import pytest

from app.engine.confluence import compute_confluence_score


class TestConfluenceNoneParent:
    def test_none_returns_zero(self):
        assert compute_confluence_score(1, None) == 0

    def test_none_negative_direction(self):
        assert compute_confluence_score(-1, None) == 0


class TestConfluenceEqualDI:
    def test_equal_di_returns_zero(self):
        indicators = {"adx": 30, "di_plus": 25, "di_minus": 25}
        assert compute_confluence_score(1, indicators) == 0


class TestConfluenceAligned:
    def test_strong_trend_aligned(self):
        """ADX 40 + aligned → near max score."""
        score = compute_confluence_score(1, {"adx": 40, "di_plus": 30, "di_minus": 10})
        assert 13 <= score <= 15

    def test_moderate_trend_aligned(self):
        """ADX 25 + aligned → high score (sigmoid saturates quickly)."""
        score = compute_confluence_score(1, {"adx": 25, "di_plus": 30, "di_minus": 10})
        assert 12 <= score <= 15

    def test_weak_trend_aligned(self):
        """ADX 10 + aligned → small score."""
        score = compute_confluence_score(1, {"adx": 10, "di_plus": 30, "di_minus": 10})
        assert 1 <= score <= 5


class TestConfluenceConflicting:
    def test_strong_trend_conflicting(self):
        """ADX 40 + conflicting → near negative max."""
        score = compute_confluence_score(-1, {"adx": 40, "di_plus": 30, "di_minus": 10})
        assert -15 <= score <= -13

    def test_weak_trend_conflicting(self):
        """ADX 10 + conflicting → small negative."""
        score = compute_confluence_score(-1, {"adx": 10, "di_plus": 30, "di_minus": 10})
        assert -5 <= score <= -1


class TestConfluenceClamping:
    def test_clamped_to_custom_max(self):
        score = compute_confluence_score(1, {"adx": 100, "di_plus": 50, "di_minus": 5}, max_score=10)
        assert score <= 10

    def test_clamped_to_custom_neg_max(self):
        score = compute_confluence_score(-1, {"adx": 100, "di_plus": 50, "di_minus": 5}, max_score=10)
        assert score >= -10


class TestConfluenceShortParent:
    def test_short_child_aligned_with_short_parent(self):
        """Child SHORT, parent SHORT (DI- > DI+) → positive boost."""
        score = compute_confluence_score(-1, {"adx": 35, "di_plus": 10, "di_minus": 30})
        assert score > 10

    def test_long_child_conflicting_with_short_parent(self):
        """Child LONG, parent SHORT → negative penalty."""
        score = compute_confluence_score(1, {"adx": 35, "di_plus": 10, "di_minus": 30})
        assert score < -10
