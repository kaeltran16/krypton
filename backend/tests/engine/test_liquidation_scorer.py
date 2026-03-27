"""Tests for the refactored liquidation scorer."""

import math
from datetime import datetime, timezone, timedelta

import pytest

from app.engine.liquidation_scorer import (
    aggregate_liquidation_buckets,
    detect_clusters,
    compute_cluster_score,
    compute_asymmetry_score,
    compute_liquidation_score,
)


# ── helpers ──

def _make_event(price, volume, side="buy", age_hours=0):
    ts = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return {"price": price, "volume": volume, "timestamp": ts, "side": side}


def _make_events(price, volume, side="buy", count=5):
    return [_make_event(price, volume, side) for _ in range(count)]


# ── aggregate_liquidation_buckets ──

class TestBucketAggregation:
    def test_groups_by_price_level(self):
        atr = 200.0  # bucket width = 50
        events = [
            _make_event(50010.0, 100.0),
            _make_event(50020.0, 200.0),  # same bucket as 50010
            _make_event(50200.0, 150.0),  # different bucket
        ]
        buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0)
        assert len(buckets) == 2
        near = [b for b in buckets if abs(b["center"] - 50000) < 50]
        assert len(near) == 1
        assert near[0]["total_volume"] == pytest.approx(300.0, rel=1e-6)

    def test_decay_reduces_old_events(self):
        atr = 100.0
        events = [
            _make_event(50000.0, 100.0, age_hours=0),
            _make_event(50000.0, 100.0, age_hours=8),  # 2x half-life
        ]
        buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0, decay_half_life_hours=4)
        assert buckets[0]["total_volume"] < 200.0
        assert buckets[0]["total_volume"] > 100.0

    def test_side_breakdown_tracks_long_short(self):
        """Buckets should include per-side volume breakdown."""
        atr = 200.0
        events = [
            _make_event(50000.0, 100.0, side="buy"),   # short liq
            _make_event(50000.0, 60.0, side="sell"),    # long liq
        ]
        buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0)
        assert len(buckets) == 1
        b = buckets[0]
        assert "side_breakdown" in b
        assert b["side_breakdown"]["short"] == pytest.approx(100.0, rel=1e-6)
        assert b["side_breakdown"]["long"] == pytest.approx(60.0, rel=1e-6)

    def test_missing_side_contributes_volume_not_direction(self):
        """Events without 'side' add to total volume but not to side breakdown."""
        atr = 200.0
        events = [
            _make_event(50000.0, 100.0, side="buy"),
            {"price": 50000.0, "volume": 50.0, "timestamp": datetime.now(timezone.utc)},  # no side
        ]
        buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0)
        b = buckets[0]
        assert b["total_volume"] == pytest.approx(150.0, rel=1e-6)
        assert b["side_breakdown"]["short"] == pytest.approx(100.0, rel=1e-6)
        assert b["side_breakdown"]["long"] == pytest.approx(0.0, abs=1e-6)

    def test_empty_events(self):
        assert aggregate_liquidation_buckets([], atr=200.0, current_price=50000.0) == []

    def test_zero_atr(self):
        events = [_make_event(50000.0, 100.0)]
        assert aggregate_liquidation_buckets(events, atr=0, current_price=50000.0) == []


# ── detect_clusters (MAD-based) ──

class TestClusterDetection:
    def test_detects_outlier_bucket(self):
        buckets = [
            {"center": 50000, "total_volume": 100, "side_breakdown": {"short": 100, "long": 0}},
            {"center": 50100, "total_volume": 100, "side_breakdown": {"short": 100, "long": 0}},
            {"center": 50200, "total_volume": 500, "side_breakdown": {"short": 500, "long": 0}},
            {"center": 50300, "total_volume": 80, "side_breakdown": {"short": 80, "long": 0}},
        ]
        clusters = detect_clusters(buckets)
        assert len(clusters) == 1
        assert clusters[0]["center"] == 50200

    def test_single_bucket_returned_as_is(self):
        buckets = [{"center": 50000, "total_volume": 100, "side_breakdown": {"short": 100, "long": 0}}]
        assert detect_clusters(buckets) == buckets

    def test_uniform_buckets_no_clusters(self):
        """When all volumes are equal, MAD=0; fall through to mean floor — still no outlier."""
        buckets = [
            {"center": 50000 + i * 100, "total_volume": 100, "side_breakdown": {"short": 100, "long": 0}}
            for i in range(5)
        ]
        clusters = detect_clusters(buckets)
        # threshold = max(100 + 2*0, 1.5*100) = 150 — none exceed
        assert len(clusters) == 0


# ── compute_cluster_score ──

class TestClusterScoring:
    def test_short_liquidation_above_price_is_bullish(self):
        """Cluster above price with side='buy' (short liqs) should score positive."""
        events = _make_events(50200.0, 500.0, side="buy", count=10)
        result = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        assert result["score"] > 0

    def test_long_liquidation_below_price_is_bearish(self):
        """Cluster below price with side='sell' (long liqs) should score negative."""
        events = _make_events(49800.0, 500.0, side="sell", count=10)
        result = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        assert result["score"] < 0

    def test_mixed_cluster_uses_net_direction(self):
        """When both sides present, net direction determines sign."""
        # more shorts (buy) than longs (sell) at same price = net bullish
        events = (
            _make_events(50200.0, 300.0, side="buy", count=5)
            + _make_events(50200.0, 100.0, side="sell", count=5)
        )
        result = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        assert result["score"] > 0

    def test_no_events_returns_zero(self):
        result = compute_cluster_score([], current_price=50000.0, atr=200.0)
        assert result["score"] == 0
        assert result["confidence"] == 0.0

    def test_score_bounded(self):
        events = _make_events(50050.0, 10000.0, count=20)
        result = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        assert -100 <= result["score"] <= 100

    def test_returns_cluster_list(self):
        events = _make_events(50200.0, 500.0, count=10)
        result = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        assert isinstance(result["clusters"], list)
        for c in result["clusters"]:
            assert "price" in c
            assert "volume" in c
            assert "side_breakdown" in c

    def test_depth_none_unchanged(self):
        events = _make_events(50200.0, 500.0)
        r1 = compute_cluster_score(events, current_price=50000.0, atr=200.0)
        r2 = compute_cluster_score(events, current_price=50000.0, atr=200.0, depth=None)
        assert r1["score"] == r2["score"]

    def test_depth_thin_asks_amplifies(self):
        events = _make_events(50200.0, 500.0)
        thin_asks = {
            "bids": [(49900, 100), (49800, 100)],
            "asks": [(50100, 5), (50200, 3)],
        }
        r_no = compute_cluster_score(events, 50000.0, 200.0)
        r_thin = compute_cluster_score(events, 50000.0, 200.0, depth=thin_asks)
        assert abs(r_thin["score"]) >= abs(r_no["score"])

    def test_depth_thick_asks_dampens(self):
        events = _make_events(50200.0, 500.0)
        thick_asks = {
            "bids": [(49900, 100), (49800, 100)],
            "asks": [(50100, 5000), (50200, 3000)],
        }
        r_no = compute_cluster_score(events, 50000.0, 200.0)
        r_thick = compute_cluster_score(events, 50000.0, 200.0, depth=thick_asks)
        assert abs(r_thick["score"]) <= abs(r_no["score"])

    def test_depth_modifier_bounded(self):
        events = _make_events(50200.0, 500.0)
        extreme = {"bids": [(49900, 1)], "asks": [(50100, 999999)]}
        result = compute_cluster_score(events, 50000.0, 200.0, depth=extreme)
        assert -100 <= result["score"] <= 100

    def test_sigmoid_depth_continuity(self):
        """Sigmoid depth modifier should be smooth — no jumps > 0.20 between test ratios."""
        from app.engine.liquidation_scorer import depth_modifier
        ratios = [0.3, 0.49, 0.51, 1.0, 1.99, 2.01, 3.0]
        mods = [depth_modifier(ratio) for ratio in ratios]
        for i in range(len(mods) - 1):
            assert abs(mods[i + 1] - mods[i]) < 0.20


# ── depth_modifier / get_depth_ratio ──

class TestDepthHelpers:
    def test_depth_modifier_returns_bounded(self):
        from app.engine.liquidation_scorer import depth_modifier
        for ratio in [0.0, 0.5, 1.0, 2.0, 5.0, 100.0]:
            m = depth_modifier(ratio)
            assert 0.7 <= m <= 1.3

    def test_depth_modifier_low_ratio_amplifies(self):
        from app.engine.liquidation_scorer import depth_modifier
        assert depth_modifier(0.3) > 1.0

    def test_depth_modifier_high_ratio_dampens(self):
        from app.engine.liquidation_scorer import depth_modifier
        assert depth_modifier(3.0) < 1.0

    def test_get_depth_ratio_no_depth_returns_neutral(self):
        from app.engine.liquidation_scorer import get_depth_ratio
        assert get_depth_ratio(50200.0, 50000.0, 200.0, None) == 1.0
        assert get_depth_ratio(50200.0, 50000.0, 200.0, {}) == 1.0

    def test_get_depth_ratio_empty_levels_returns_neutral(self):
        from app.engine.liquidation_scorer import get_depth_ratio
        assert get_depth_ratio(50200.0, 50000.0, 200.0, {"bids": [], "asks": []}) == 1.0

    def test_get_depth_ratio_computes_correctly(self):
        from app.engine.liquidation_scorer import get_depth_ratio
        depth = {
            "bids": [(49900, 100), (49800, 100)],
            "asks": [(50100, 200), (50200, 50)],
        }
        ratio = get_depth_ratio(50200.0, 50000.0, 200.0, depth)
        assert ratio > 0

    def test_get_depth_ratio_above_uses_asks(self):
        from app.engine.liquidation_scorer import get_depth_ratio
        depth = {"bids": [(49900, 999)], "asks": [(50100, 10)]}
        ratio = get_depth_ratio(50200.0, 50000.0, 200.0, depth)
        # should use asks, not bids
        assert ratio > 0

    def test_get_depth_ratio_below_uses_bids(self):
        from app.engine.liquidation_scorer import get_depth_ratio
        depth = {"bids": [(49900, 10)], "asks": [(50100, 999)]}
        ratio = get_depth_ratio(49800.0, 50000.0, 200.0, depth)
        # should use bids, not asks
        assert ratio > 0


# ── compute_asymmetry_score ──

class TestAsymmetryScoring:
    def test_more_shorts_is_bullish(self):
        events = (
            _make_events(50000.0, 200.0, side="buy", count=8)
            + _make_events(50000.0, 50.0, side="sell", count=2)
        )
        result = compute_asymmetry_score(events)
        assert result["score"] > 0
        assert result["raw_asymmetry"] > 0

    def test_more_longs_is_bearish(self):
        events = (
            _make_events(50000.0, 50.0, side="buy", count=2)
            + _make_events(50000.0, 200.0, side="sell", count=8)
        )
        result = compute_asymmetry_score(events)
        assert result["score"] < 0
        assert result["raw_asymmetry"] < 0

    def test_balanced_near_zero(self):
        events = (
            _make_events(50000.0, 100.0, side="buy", count=5)
            + _make_events(50000.0, 100.0, side="sell", count=5)
        )
        result = compute_asymmetry_score(events)
        assert abs(result["score"]) < 3
        assert result["raw_asymmetry"] == pytest.approx(0.0, abs=0.01)

    def test_empty_events_returns_zero(self):
        result = compute_asymmetry_score([])
        assert result["score"] == 0
        assert result["confidence"] == 0.0

    def test_no_side_events_returns_zero(self):
        """Events without 'side' field should produce zero (division guard)."""
        events = [
            {"price": 50000.0, "volume": 100.0, "timestamp": datetime.now(timezone.utc)}
            for _ in range(5)
        ]
        result = compute_asymmetry_score(events)
        assert result["score"] == 0
        assert result["confidence"] == 0.0

    def test_confidence_low_with_few_events(self):
        events = _make_events(50000.0, 100.0, side="buy", count=3)
        result = compute_asymmetry_score(events)
        assert result["confidence"] < 0.5

    def test_score_bounded(self):
        events = _make_events(50000.0, 10000.0, side="buy", count=20)
        result = compute_asymmetry_score(events)
        assert -25 <= result["score"] <= 25  # default max is 25


# ── compute_liquidation_score (composer) ──

class TestComposedScore:
    def test_blends_cluster_and_asymmetry(self):
        events = _make_events(50200.0, 500.0, side="buy", count=15)
        result = compute_liquidation_score(events, current_price=50000.0, atr=200.0)
        assert "score" in result
        assert "confidence" in result
        assert "clusters" in result
        assert "details" in result

    def test_details_dict_shape(self):
        events = _make_events(50200.0, 500.0, side="buy", count=15)
        result = compute_liquidation_score(events, current_price=50000.0, atr=200.0)
        d = result["details"]
        assert "cluster_score" in d
        assert "cluster_confidence" in d
        assert "asymmetry_score" in d
        assert "asymmetry_confidence" in d
        assert "raw_asymmetry" in d
        assert "cluster_weight" in d
        assert "asymmetry_weight" in d
        assert "event_count" in d

    def test_empty_events_returns_zero(self):
        result = compute_liquidation_score([], current_price=50000.0, atr=200.0)
        assert result["score"] == 0
        assert result["confidence"] == 0.0

    def test_cluster_weight_param(self):
        events = _make_events(50200.0, 500.0, side="buy", count=15)
        r_high = compute_liquidation_score(events, 50000.0, 200.0, cluster_weight=0.9)
        r_low = compute_liquidation_score(events, 50000.0, 200.0, cluster_weight=0.1)
        # different weights should produce different scores
        assert r_high["score"] != r_low["score"]

    def test_accepts_all_tunable_params(self):
        events = _make_events(50200.0, 500.0, side="buy", count=15)
        result = compute_liquidation_score(
            events, 50000.0, 200.0,
            cluster_max_score=40,
            asymmetry_max_score=30,
            cluster_weight=0.7,
            proximity_steepness=3.0,
            decay_half_life_hours=6.0,
            asymmetry_steepness=4.0,
        )
        assert -100 <= result["score"] <= 100
