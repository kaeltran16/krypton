import numpy as np
import pandas as pd
import pytest

from app.ml.labels import generate_targets, TargetConfig


def _make_candles_df(n=500, base=67000):
    """Candles with a mix of flat and trending periods."""
    from datetime import datetime, timedelta, timezone
    rng = np.random.default_rng(42)
    data = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        noise = rng.uniform(-50, 50)
        trend = 20 * np.sin(2 * np.pi * i / 100)
        c = base + trend + noise
        data.append({
            "timestamp": (start + timedelta(hours=i)).isoformat(),
            "open": c - 5, "high": c + 30, "low": c - 30, "close": c, "volume": 100,
        })
    return pd.DataFrame(data)


class TestGenerateTargets:

    def test_output_shapes(self):
        df = _make_candles_df(500)
        cfg = TargetConfig(horizon=48)
        fwd, sl, tp1, tp2, valid = generate_targets(df, cfg)
        assert fwd.shape == (500,)
        assert sl.shape == (500,)
        assert valid.shape == (500,)

    def test_last_horizon_candles_invalid(self):
        df = _make_candles_df(200)
        cfg = TargetConfig(horizon=48)
        _, _, _, _, valid = generate_targets(df, cfg)
        assert not valid[-48:].any()
        assert valid[:100].any()

    def test_atr_normalization(self):
        df = _make_candles_df(500)
        cfg = TargetConfig(horizon=48)
        fwd, _, _, _, valid = generate_targets(df, cfg)
        valid_fwd = fwd[valid]
        assert valid_fwd.std() > 0.1
        assert valid_fwd.std() < 20

    def test_zero_atr_skipped(self):
        df = _make_candles_df(200)
        for col in ["open", "high", "low", "close"]:
            df.loc[:13, col] = 67000.0
        cfg = TargetConfig(horizon=48)
        _, _, _, _, valid = generate_targets(df, cfg)
        assert not valid[:14].any()

    def test_sltp_only_for_significant_moves(self):
        df = _make_candles_df(500)
        cfg = TargetConfig(horizon=48, noise_floor=0.3)
        fwd, sl, tp1, tp2, valid = generate_targets(df, cfg)
        small_moves = valid & (np.abs(fwd) < 0.3)
        if small_moves.any():
            assert (sl[small_moves] == 0).all()
            assert (tp1[small_moves] == 0).all()
