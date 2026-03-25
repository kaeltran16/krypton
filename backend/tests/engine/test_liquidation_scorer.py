from datetime import datetime, timezone, timedelta
import pytest
from app.engine.liquidation_scorer import aggregate_liquidation_buckets, compute_liquidation_score


def test_bucket_aggregation_groups_by_price_level():
    """Liquidation events should be bucketed by price level (0.25 * ATR width)."""
    atr = 200.0  # bucket width = 50
    now = datetime.now(timezone.utc)
    events = [
        {"price": 50010.0, "volume": 100.0, "timestamp": now},
        {"price": 50020.0, "volume": 200.0, "timestamp": now},  # same bucket as 50010
        {"price": 50200.0, "volume": 150.0, "timestamp": now},  # different bucket
    ]
    buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0)
    # 50010 and 50020 should be in the same bucket (both round to idx=0, center=50000)
    assert len(buckets) == 2
    # Find the bucket containing 50010-50020
    near_bucket = [b for b in buckets if abs(b["center"] - 50000) < 50]
    assert len(near_bucket) == 1
    assert near_bucket[0]["total_volume"] == pytest.approx(300.0, rel=1e-6)


def test_bucket_decay_reduces_old_events():
    """Events older than half-life should have reduced weight."""
    atr = 100.0
    now = datetime.now(timezone.utc)
    events = [
        {"price": 50000.0, "volume": 100.0, "timestamp": now},
        {"price": 50000.0, "volume": 100.0, "timestamp": now - timedelta(hours=8)},  # 2x half-life
    ]
    buckets = aggregate_liquidation_buckets(events, atr=atr, current_price=50000.0, decay_half_life_hours=4)
    # Old event should be decayed to ~25% weight
    assert buckets[0]["total_volume"] < 200.0
    assert buckets[0]["total_volume"] > 100.0


def test_cluster_detection():
    """Buckets with volume > 2x median should be identified as clusters."""
    from app.engine.liquidation_scorer import detect_clusters

    buckets = [
        {"center": 50000, "total_volume": 100},
        {"center": 50100, "total_volume": 100},
        {"center": 50200, "total_volume": 500},  # cluster
        {"center": 50300, "total_volume": 80},
    ]
    clusters = detect_clusters(buckets, threshold_mult=2.0)
    assert len(clusters) == 1
    assert clusters[0]["center"] == 50200


def test_liquidation_score_near_cluster_boosts():
    """Price near a dense cluster should produce a directional score."""
    now = datetime.now(timezone.utc)
    events = [
        {"price": 50500.0, "volume": 1000.0, "timestamp": now},
        {"price": 50520.0, "volume": 800.0, "timestamp": now},
    ] + [
        {"price": 49000.0 + i * 10, "volume": 50.0, "timestamp": now}
        for i in range(20)  # background noise
    ]
    result = compute_liquidation_score(
        events=events, current_price=50400.0, atr=200.0,
    )
    assert isinstance(result, dict)
    assert "score" in result
    assert "confidence" in result
    assert "clusters" in result
    assert -100 <= result["score"] <= 100


def test_liquidation_score_no_events():
    """No events should return score=0, confidence=0."""
    result = compute_liquidation_score(events=[], current_price=50000.0, atr=200.0)
    assert result["score"] == 0
    assert result["confidence"] == 0.0


# --- depth modifier tests ---

def _make_events(price, volume, count=5):
    now = datetime.now(timezone.utc)
    return [{"price": price, "volume": volume, "timestamp": now, "side": "buy"} for _ in range(count)]


def test_depth_none_unchanged():
    events = _make_events(50200.0, 500.0)
    r1 = compute_liquidation_score(events, current_price=50000.0, atr=200.0)
    r2 = compute_liquidation_score(events, current_price=50000.0, atr=200.0, depth=None)
    assert r1["score"] == r2["score"]


def test_depth_thin_asks_amplifies_bullish_cluster():
    events = _make_events(50200.0, 500.0)
    thin_asks = {
        "bids": [(49900, 100), (49800, 100)],
        "asks": [(50100, 5), (50200, 3)],
    }
    r_no_depth = compute_liquidation_score(events, 50000.0, 200.0)
    r_thin = compute_liquidation_score(events, 50000.0, 200.0, depth=thin_asks)
    assert abs(r_thin["score"]) >= abs(r_no_depth["score"])


def test_depth_thick_asks_dampens_bullish_cluster():
    events = _make_events(50200.0, 500.0)
    thick_asks = {
        "bids": [(49900, 100), (49800, 100)],
        "asks": [(50100, 5000), (50200, 3000)],
    }
    r_no_depth = compute_liquidation_score(events, 50000.0, 200.0)
    r_thick = compute_liquidation_score(events, 50000.0, 200.0, depth=thick_asks)
    assert abs(r_thick["score"]) <= abs(r_no_depth["score"])


def test_depth_modifier_bounded():
    events = _make_events(50200.0, 500.0)
    extreme_depth = {
        "bids": [(49900, 1)],
        "asks": [(50100, 999999)],
    }
    result = compute_liquidation_score(events, 50000.0, 200.0, depth=extreme_depth)
    assert -100 <= result["score"] <= 100
