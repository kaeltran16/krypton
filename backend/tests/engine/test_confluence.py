"""Tests for multi-timeframe confluence scoring."""

import pytest

from app.engine.confluence import (
    compute_confluence_score,
    DEFAULT_LEVEL_WEIGHTS,
    MAX_POSSIBLE_LEVELS,
)


# ── helpers ──

def _make_parent(
    trend_score=0,
    mean_rev_score=0,
    adx=25,
    trend_conviction=0.5,
    regime=None,
):
    """Build a parent cache dict with sensible defaults."""
    return {
        "trend_score": trend_score,
        "mean_rev_score": mean_rev_score,
        "adx": adx,
        "trend_conviction": trend_conviction,
        "regime": regime or {"trending": 0.5, "ranging": 0.3, "volatile": 0.2},
    }


def _child(trend_score=0, mean_rev_score=0, trend_conviction=0.5):
    return {
        "trend_score": trend_score,
        "mean_rev_score": mean_rev_score,
        "trend_conviction": trend_conviction,
    }


# ── 1. no parents available (empty list) ──

def test_empty_parent_list_returns_zero():
    result = compute_confluence_score(_child(trend_score=50), [], "15m")
    assert result["score"] == 0 and result["confidence"] == 0.0


# ── 2. all None parents ──

def test_all_none_parents_returns_zero():
    result = compute_confluence_score(
        _child(trend_score=50), [None, None, None], "15m"
    )
    assert result["score"] == 0 and result["confidence"] == 0.0


# ── 3. no thesis (both sub-scores 0) ──

def test_no_thesis_returns_zero():
    parent = _make_parent(trend_score=40, adx=30)
    result = compute_confluence_score(
        _child(trend_score=0, mean_rev_score=0), [parent], "15m"
    )
    assert result["score"] == 0 and result["confidence"] == 0.0


# ── 4. trend thesis with aligned parent ──

def test_trend_aligned_parent_positive_score():
    """Child long trend, parent long trend with strong ADX -> positive score."""
    child = _child(trend_score=60, mean_rev_score=10)
    parent = _make_parent(trend_score=50, adx=35, trend_conviction=0.8)
    result = compute_confluence_score(child, [parent], "15m")
    assert result["score"] > 0
    assert result["confidence"] > 0


def test_trend_aligned_short_direction():
    """Both child and parent bearish -> positive score (aligned)."""
    child = _child(trend_score=-55, mean_rev_score=-10)
    parent = _make_parent(trend_score=-40, adx=30, trend_conviction=0.7)
    result = compute_confluence_score(child, [parent], "15m")
    assert result["score"] > 0


# ── 5. trend thesis with opposing parent ──

def test_trend_opposing_parent_negative_score():
    """Child long, parent short -> negative score."""
    child = _child(trend_score=60, mean_rev_score=10)
    parent = _make_parent(trend_score=-40, adx=35, trend_conviction=0.7)
    result = compute_confluence_score(child, [parent], "15m")
    assert result["score"] < 0


def test_trend_opposing_short_child():
    """Child short, parent long -> negative score."""
    child = _child(trend_score=-55, mean_rev_score=-10)
    parent = _make_parent(trend_score=40, adx=30, trend_conviction=0.6)
    result = compute_confluence_score(child, [parent], "15m")
    assert result["score"] < 0


# ── 6. mean-reversion thesis with ranging parent ──

def test_mr_ranging_parent_supports():
    """Child MR long, parent MR long in ranging regime -> positive score."""
    child = _child(trend_score=5, mean_rev_score=50)
    parent = _make_parent(
        mean_rev_score=30,
        trend_score=5,
        regime={"trending": 0.1, "ranging": 0.8, "volatile": 0.1},
    )
    result = compute_confluence_score(child, [parent], "15m")
    assert result["score"] > 0


def test_mr_ranging_parent_opposing_direction():
    """Child MR long, parent MR short in ranging regime -> negative score."""
    child = _child(trend_score=5, mean_rev_score=50)
    parent = _make_parent(
        mean_rev_score=-30,
        trend_score=5,
        regime={"trending": 0.1, "ranging": 0.8, "volatile": 0.1},
    )
    result = compute_confluence_score(child, [parent], "15m")
    assert result["score"] < 0


# ── 7. mean-reversion thesis with trending parent ──

def test_mr_trending_parent_opposes():
    """Child MR long, parent strongly trending in same direction -> penalty."""
    child = _child(trend_score=5, mean_rev_score=50)
    parent = _make_parent(
        mean_rev_score=5,
        trend_score=40,
        regime={"trending": 0.9, "ranging": 0.05, "volatile": 0.05},
    )
    result = compute_confluence_score(child, [parent], "15m")
    # trending parent opposes mean-reversion: sign(child_mr=+) * sign(parent_trend=+) = +1
    # trend_opposition = 0.9 * 1 = 0.9, ranging_support ~ 0
    # raw = 0 - 0.5 * 0.9 = -0.45 -> negative
    assert result["score"] < 0


def test_mr_trending_parent_opposite_direction_helps():
    """Child MR long, parent trending short -> trend opposition is negative (helps MR)."""
    child = _child(trend_score=5, mean_rev_score=50)
    parent = _make_parent(
        mean_rev_score=5,
        trend_score=-40,
        regime={"trending": 0.9, "ranging": 0.05, "volatile": 0.05},
    )
    result = compute_confluence_score(child, [parent], "15m")
    # sign(child_mr=+) * sign(parent_trend=-) = -1
    # trend_opposition = 0.9 * (-1) = -0.9
    # raw = ~0 - 0.5 * (-0.9) = +0.45 -> positive
    assert result["score"] > 0


# ── 8. multi-level: 3 parents for 15m -> full confidence ──

def test_multi_level_full_parents_15m():
    """15m has max 3 levels; all present -> higher confidence than single parent."""
    child = _child(trend_score=60, mean_rev_score=10)
    parents = [
        _make_parent(trend_score=50, adx=30, trend_conviction=0.8),
        _make_parent(trend_score=45, adx=25, trend_conviction=0.7),
        _make_parent(trend_score=40, adx=20, trend_conviction=0.6),
    ]
    result = compute_confluence_score(child, parents, "15m")
    assert result["score"] > 0
    # 3/3 levels available, avg conviction = (0.8+0.7+0.6)/3 = 0.7
    assert result["confidence"] == pytest.approx(0.7, abs=0.01)


# ── 9. multi-level: 1 of 3 available -> lower confidence ──

def test_multi_level_partial_parents_lower_confidence():
    """Only 1 of 3 parents available -> confidence scales down."""
    child = _child(trend_score=60, mean_rev_score=10)
    single = [_make_parent(trend_score=50, adx=30, trend_conviction=0.9)]
    full = [
        _make_parent(trend_score=50, adx=30, trend_conviction=0.9),
        _make_parent(trend_score=45, adx=25, trend_conviction=0.9),
        _make_parent(trend_score=40, adx=20, trend_conviction=0.9),
    ]
    result_single = compute_confluence_score(child, single, "15m")
    result_full = compute_confluence_score(child, full, "15m")
    assert result_single["confidence"] < result_full["confidence"]
    # 1/3 * 0.9 = 0.3
    assert result_single["confidence"] == pytest.approx(0.3, abs=0.01)


def test_multi_level_middle_none():
    """Immediate and great-grandparent present, grandparent None."""
    child = _child(trend_score=60, mean_rev_score=10)
    parents = [
        _make_parent(trend_score=50, adx=30, trend_conviction=0.8),
        None,
        _make_parent(trend_score=40, adx=20, trend_conviction=0.6),
    ]
    result = compute_confluence_score(child, parents, "15m")
    assert result["score"] > 0
    # 2/3 levels, avg conviction = (0.8+0.6)/2 = 0.7
    assert result["confidence"] == pytest.approx(2 / 3 * 0.7, abs=0.01)


# ── 10. level weight renormalization when parents missing ──

def test_weight_renormalization_single_parent():
    """With 1 parent, its weight is renormalized to 1.0 regardless of level_weight config."""
    child = _child(trend_score=60, mean_rev_score=10)
    parent = _make_parent(trend_score=50, adx=35, trend_conviction=0.8)

    # single parent at index 0 (weight 0.5) renormalized to 1.0
    result_single = compute_confluence_score(child, [parent], "15m")

    # same parent duplicated at all levels for comparison
    result_all = compute_confluence_score(child, [parent, parent, parent], "15m")

    # with identical parents, score should be the same (all alignments equal)
    assert result_single["score"] == result_all["score"]


def test_weight_renormalization_skipped_level():
    """When index 1 (grandparent) is None, weights 0 and 2 renormalize."""
    child = _child(trend_score=60, mean_rev_score=10)
    parent_imm = _make_parent(trend_score=50, adx=30, trend_conviction=0.8)
    parent_ggp = _make_parent(trend_score=-20, adx=25, trend_conviction=0.5)

    result = compute_confluence_score(
        child, [parent_imm, None, parent_ggp], "15m"
    )
    # weights used: [0.5, 0.2], total=0.7
    # immediate aligned (positive), great-grandparent opposing (negative)
    # score reflects weighted blend, not raw average
    assert result["score"] != 0


# ── 11. timeframe="4h" with 1 ancestor -> max_possible_levels=1 ──

def test_4h_timeframe_single_ancestor():
    """4h only has 1D as ancestor -> max_possible_levels=1."""
    assert MAX_POSSIBLE_LEVELS["4h"] == 1

    child = _child(trend_score=55, mean_rev_score=10)
    parent = _make_parent(trend_score=45, adx=30, trend_conviction=0.9)
    result = compute_confluence_score(child, [parent], "4h")
    assert result["score"] > 0
    # 1/1 levels, conviction 0.9
    assert result["confidence"] == pytest.approx(0.9, abs=0.01)


def test_4h_extra_parents_ignored():
    """4h should only use 1 parent even if more are passed."""
    child = _child(trend_score=55, mean_rev_score=10)
    parents = [
        _make_parent(trend_score=45, adx=30, trend_conviction=0.9),
        _make_parent(trend_score=-45, adx=30, trend_conviction=0.9),
    ]
    result_one = compute_confluence_score(child, [parents[0]], "4h")
    result_two = compute_confluence_score(child, parents, "4h")
    assert result_one == result_two


# ── edge cases ──

def test_unknown_timeframe_returns_zero():
    """Timeframe not in TIMEFRAME_ANCESTORS -> max_levels=0 -> zero."""
    child = _child(trend_score=50)
    parent = _make_parent(trend_score=40, adx=30)
    result = compute_confluence_score(child, [parent], "5m")
    assert result["score"] == 0 and result["confidence"] == 0.0


def test_1d_timeframe_returns_zero():
    """1D has no ancestors -> not in MAX_POSSIBLE_LEVELS -> zero."""
    child = _child(trend_score=50)
    parent = _make_parent(trend_score=40, adx=30)
    result = compute_confluence_score(child, [parent], "1D")
    assert result["score"] == 0 and result["confidence"] == 0.0


def test_score_clamped_to_100():
    """Score cannot exceed +/- 100 even with extreme inputs."""
    child = _child(trend_score=100, mean_rev_score=0)
    parent = _make_parent(trend_score=100, adx=100, trend_conviction=1.0)
    result = compute_confluence_score(child, [parent], "4h")
    assert -100 <= result["score"] <= 100


def test_custom_level_weights():
    """Override level weights via kwargs."""
    child = _child(trend_score=60, mean_rev_score=10)
    parents = [
        _make_parent(trend_score=50, adx=30, trend_conviction=0.8),
        _make_parent(trend_score=-40, adx=30, trend_conviction=0.8),
    ]
    # heavy immediate weight -> score dominated by aligned first parent
    result_heavy = compute_confluence_score(
        child, parents, "1h", level_weight_1=0.9, level_weight_2=0.1
    )
    # equal weights -> opposing second parent pulls score down more
    result_equal = compute_confluence_score(
        child, parents, "1h", level_weight_1=0.5, level_weight_2=0.5
    )
    assert result_heavy["score"] > result_equal["score"]


def test_confidence_zero_when_parent_missing_regime_for_mr():
    """MR thesis with parent missing regime dict uses defaults (all 0)."""
    child = _child(trend_score=5, mean_rev_score=50)
    parent = {"trend_score": 10, "mean_rev_score": 30, "adx": 20, "trend_conviction": 0.5}
    result = compute_confluence_score(child, [parent], "15m")
    # parent has no "regime" key -> defaults to empty dict -> ranging=0, trending=0
    # ranging_support = 0, trend_opposition = 0 -> alignment = 0 -> score = 0
    assert result["score"] == 0


def test_1h_timeframe_max_two_levels():
    """1h has ancestors [4h, 1D] -> max 2 levels."""
    assert MAX_POSSIBLE_LEVELS["1h"] == 2

    child = _child(trend_score=60, mean_rev_score=10)
    parents = [
        _make_parent(trend_score=50, adx=30, trend_conviction=0.8),
        _make_parent(trend_score=45, adx=25, trend_conviction=0.6),
    ]
    result = compute_confluence_score(child, parents, "1h")
    assert result["score"] > 0
    # 2/2 levels, avg conviction = 0.7
    assert result["confidence"] == pytest.approx(0.7, abs=0.01)
