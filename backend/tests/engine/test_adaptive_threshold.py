from app.engine.optimizer import lookup_signal_threshold, sweep_threshold_1d


def test_threshold_specific_pair_regime():
    """Should return specific learned threshold when available."""
    thresholds = {
        ("BTC-USDT-SWAP", "trending"): 35,
        ("BTC-USDT-SWAP", None): 38,
    }
    result = lookup_signal_threshold("BTC-USDT-SWAP", "trending", thresholds, default=40)
    assert result == 35


def test_threshold_fallback_to_pair_level():
    """Should fall back to pair-level average when regime-specific not available."""
    thresholds = {
        ("BTC-USDT-SWAP", None): 38,
    }
    result = lookup_signal_threshold("BTC-USDT-SWAP", "ranging", thresholds, default=40)
    assert result == 38


def test_threshold_fallback_to_regime_level():
    """Should fall back to regime-level average when pair not available."""
    thresholds = {
        (None, "trending"): 36,
    }
    result = lookup_signal_threshold("WIF-USDT-SWAP", "trending", thresholds, default=40)
    assert result == 36


def test_threshold_fallback_to_global():
    """Should fall back to global default when nothing learned."""
    result = lookup_signal_threshold("WIF-USDT-SWAP", "volatile", {}, default=40)
    assert result == 40


def test_threshold_sweep_finds_optimal():
    """1D sweep should find threshold maximizing fitness."""
    def mock_fitness(threshold):
        return -abs(threshold - 45) / 100 + 0.5

    best, fitness = sweep_threshold_1d(mock_fitness, low=20, high=60, step=5)
    assert best == 45
    assert fitness > 0.4


def test_threshold_sweep_skips_insufficient_data():
    """Should return None when fewer than 10 resolved signals in bucket."""
    best, fitness = sweep_threshold_1d(None, low=20, high=60, step=5, signal_count=5, min_signals=10)
    assert best is None
