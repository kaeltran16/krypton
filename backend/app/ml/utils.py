"""Shared ML utilities used by both training (api/ml.py) and inference (main.py)."""

import logging
from datetime import datetime

import numpy as np
import pandas as pd

from app.engine.scoring import sigmoid_scale
from app.engine.regime import compute_regime_mix
from app.engine.traditional import compute_trend_conviction

logger = logging.getLogger(__name__)

TF_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1D": 1440}

SCORE_SCALE = 40  # ±2.5 ATR saturates at ±100

NEUTRAL_RESULT = {
    "direction": "NEUTRAL",
    "ml_score": 0.0,
    "confidence": 0.0,
    "sl_atr": 0.0,
    "tp1_atr": 0.0,
    "tp2_atr": 0.0,
}


def regression_result(mean_return: float, mean_reg: np.ndarray) -> dict:
    """Build prediction result dict from regression output."""
    direction = "LONG" if mean_return > 0 else ("SHORT" if mean_return < 0 else "NEUTRAL")
    ml_score = float(np.clip(mean_return * SCORE_SCALE, -100, 100))
    return {
        "direction": direction,
        "ml_score": ml_score,
        "sl_atr": float(mean_reg[0]),
        "tp1_atr": float(mean_reg[1]),
        "tp2_atr": float(mean_reg[2]),
    }


def sigmoid_confidence(mean_return: float, uncertainty: float) -> float:
    """Compute confidence via sigmoid(|prediction| / uncertainty - 1)."""
    uncertainty = max(uncertainty, 1e-6)
    return 1.0 / (1.0 + np.exp(-(abs(mean_return) / uncertainty - 1.0)))


class FeatureMapper:
    """Shared feature mapping logic for predictors."""

    def __init__(self, input_size: int, expected_features: list[str]):
        self.input_size = input_size
        self._expected_features = expected_features
        self._feature_map = None
        self._available_features = None
        self._n_missing_features = 0
        self._n_expected_features = 0
        self._out_idx = None
        self._in_idx = None

    def set_available_features(self, names: list[str]):
        if names == self._available_features:
            return
        self._available_features = names
        expected = self._expected_features
        if not expected:
            self._feature_map = None
            self._n_missing_features = 0
            self._n_expected_features = 0
            return
        available_idx = {name: i for i, name in enumerate(names)}
        raw_map = []
        missing = []
        for name in expected:
            idx = available_idx.get(name, -1)
            raw_map.append(idx)
            if idx == -1:
                missing.append(name)
        self._n_missing_features = len(missing)
        self._n_expected_features = len(expected)
        if missing:
            logger.warning("Missing features (filled with 0): %s", missing)
        out_idx = np.array([i for i, c in enumerate(raw_map) if c >= 0], dtype=np.intp)
        in_idx = np.array([c for c in raw_map if c >= 0], dtype=np.intp)
        valid = out_idx < self.input_size
        self._out_idx = out_idx[valid]
        self._in_idx = in_idx[valid]
        self._feature_map = raw_map

    def map_features(self, features: np.ndarray) -> np.ndarray:
        if self._feature_map is None:
            if features.shape[1] > self.input_size:
                return features[:, :self.input_size]
            return features
        n_rows = features.shape[0]
        mapped = np.zeros((n_rows, self.input_size), dtype=np.float32)
        mapped[:, self._out_idx] = features[:, self._in_idx]
        return mapped


def directional_accuracy(predictions: np.ndarray, targets: np.ndarray) -> float:
    """Fraction of predictions with matching sign to targets.

    Samples where target is near-zero (|target| < 1e-6) are excluded.
    """
    mask = np.abs(targets) > 1e-6
    if not mask.any():
        return 0.0
    pred_sign = np.sign(predictions[mask])
    target_sign = np.sign(targets[mask])
    return float((pred_sign == target_sign).mean())


def bucket_timestamp(ts: datetime, timeframe: str) -> datetime:
    """Bucket a timestamp to the nearest candle boundary for a given timeframe."""
    minutes = TF_MINUTES.get(timeframe, 60)
    ts = ts.replace(second=0, microsecond=0)
    if minutes >= 1440:
        return ts.replace(hour=0, minute=0)
    if minutes >= 60:
        hours = minutes // 60
        return ts.replace(minute=0, hour=(ts.hour // hours) * hours)
    return ts.replace(minute=(ts.minute // minutes) * minutes)


def compute_per_candle_regime(candles_df) -> tuple[list[dict], list[float]]:
    """Compute regime mix and trend conviction for each candle in the DataFrame."""
    df = candles_df.copy()
    df.columns = [c.lower() for c in df.columns]
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)

    n = len(df)

    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    prev_high = high.shift(1)
    prev_low = low.shift(1)
    plus_dm = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()

    plus_di = 100 * plus_dm.rolling(14).mean() / atr14
    minus_di = 100 * minus_dm.rolling(14).mean() / atr14
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(14).mean()

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_width = 4 * std20

    # Pre-compute non-NaN BB width values once to avoid O(n^2) re-slicing
    bb_vals = bb_width.dropna().values
    bb_valid_indices = bb_width.dropna().index

    regime_list = []
    conviction_list = []

    for i in range(n):
        adx_val = float(adx.iloc[i]) if pd.notna(adx.iloc[i]) else 0.0
        di_p = float(plus_di.iloc[i]) if pd.notna(plus_di.iloc[i]) else 0.0
        di_m = float(minus_di.iloc[i]) if pd.notna(minus_di.iloc[i]) else 0.0

        # BB width percentile over last 50 valid values up to this candle
        valid_up_to = np.searchsorted(bb_valid_indices, i, side="right")
        if valid_up_to >= 50:
            recent = bb_vals[valid_up_to - 50:valid_up_to]
            bb_pct = float(np.sum(recent < recent[-1]) / len(recent) * 100)
        else:
            bb_pct = 50.0

        trend_strength = sigmoid_scale(adx_val, center=20, steepness=0.25)
        vol_expansion = sigmoid_scale(bb_pct, center=50, steepness=0.08)
        regime = compute_regime_mix(trend_strength, vol_expansion)
        regime_list.append(regime)

        tc = compute_trend_conviction(
            close=float(close.iloc[i]),
            ema_9=float(ema9.iloc[i]),
            ema_21=float(ema21.iloc[i]),
            ema_50=float(ema50.iloc[i]),
            adx=adx_val,
            di_direction=di_p - di_m,
        )
        conviction_list.append(tc["conviction"])

    return regime_list, conviction_list
