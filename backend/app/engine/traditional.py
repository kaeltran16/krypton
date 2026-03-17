import numpy as np
import pandas as pd

from app.engine.scoring import sigmoid_score, sigmoid_scale
from app.engine.regime import compute_regime_mix, blend_caps


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14):
    """Compute ADX, +DI, -DI."""
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    plus_dm = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)

    # Zero out the smaller DM
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0

    atr = _atr(high, low, close, length)

    plus_di = 100 * plus_dm.rolling(length).mean() / atr
    minus_di = 100 * minus_dm.rolling(length).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(length).mean()

    return adx, plus_di, minus_di


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()


def compute_technical_score(candles: pd.DataFrame, regime_weights=None) -> dict:
    """Compute technical analysis score using orthogonal indicator dimensions.

    Returns dict with 'score' (-100 to +100) and 'indicators' dict.
    Requires at least 70 candles for reliable indicators.
    """
    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]

    if len(df) < 70:
        raise ValueError(f"compute_technical_score requires at least 70 candles, got {len(df)}")

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    open_ = df["open"].astype(float)

    # === Compute indicators ===
    atr = _atr(high, low, close, 14)
    adx_series, plus_di, minus_di = _adx(high, low, close, 14)
    rsi = _rsi(close, 14)

    sma_20 = close.rolling(20).mean()
    std_20 = close.rolling(20).std()
    bb_upper = sma_20 + 2 * std_20
    bb_lower = sma_20 - 2 * std_20
    bb_width = bb_upper - bb_lower

    obv = _obv(close, volume)

    last = df.index[-1]

    # Extract last values
    adx_val = float(adx_series[last]) if pd.notna(adx_series[last]) else 0.0
    di_plus_val = float(plus_di[last]) if pd.notna(plus_di[last]) else 0.0
    di_minus_val = float(minus_di[last]) if pd.notna(minus_di[last]) else 0.0
    rsi_val = float(rsi[last]) if pd.notna(rsi[last]) else 50.0
    atr_val = float(atr[last]) if pd.notna(atr[last]) else 0.0

    bb_upper_val = float(bb_upper[last])
    bb_lower_val = float(bb_lower[last])
    bb_range = bb_upper_val - bb_lower_val
    bb_pos = (float(close[last]) - bb_lower_val) / bb_range if bb_range > 0 else 0.5

    # BB width percentile over last 50 values
    bb_widths = bb_width.dropna().values
    if len(bb_widths) >= 50:
        recent_widths = bb_widths[-50:]
        current_width = bb_widths[-1]
        bb_width_pct = float(np.sum(recent_widths < current_width) / len(recent_widths) * 100)
    else:
        bb_width_pct = 50.0

    # OBV slope (last 10 candles), normalized by average volume
    obv_vals = obv.values
    if len(obv_vals) >= 10:
        obv_recent = obv_vals[-10:]
        x = np.arange(10, dtype=float)
        obv_slope = float(np.polyfit(x, obv_recent, 1)[0])
    else:
        obv_slope = 0.0

    avg_volume = float(volume.rolling(20).mean().iloc[-1])
    obv_slope_norm = obv_slope / avg_volume if avg_volume > 0 else 0.0

    # Volume ratio
    vol_ratio = float(volume.iloc[-1]) / avg_volume if avg_volume > 0 else 1.0
    candle_direction = 1 if float(close.iloc[-1]) > float(open_.iloc[-1]) else -1

    # === Regime detection ===
    trend_strength = sigmoid_scale(adx_val, center=20, steepness=0.25)
    vol_expansion = sigmoid_scale(bb_width_pct, center=50, steepness=0.08)
    regime = compute_regime_mix(trend_strength, vol_expansion)
    caps = blend_caps(regime, regime_weights)

    # === Scoring (caps from regime-aware blending) ===
    # 1. Trend
    di_sign = 1 if di_plus_val > di_minus_val else -1
    trend_score = di_sign * sigmoid_scale(adx_val, center=15, steepness=0.30) * caps["trend_cap"]

    # 2. Mean reversion
    rsi_score = sigmoid_score(50 - rsi_val, center=0, steepness=0.25) * caps["mean_rev_cap"]

    # 3. Volatility & position (60/40 split)
    bb_pos_score = sigmoid_score(0.5 - bb_pos, center=0, steepness=10) * (caps["bb_vol_cap"] * 0.6)
    bb_pos_sign = 1 if bb_pos_score > 0 else (-1 if bb_pos_score < 0 else 0)
    bb_width_score = bb_pos_sign * sigmoid_score(50 - bb_width_pct, center=0, steepness=0.10) * (caps["bb_vol_cap"] * 0.4)

    # 4. Volume confirmation (60/40 split)
    obv_score = sigmoid_score(obv_slope_norm, center=0, steepness=4) * (caps["volume_cap"] * 0.6)
    vol_score = candle_direction * sigmoid_score(vol_ratio - 1, center=0, steepness=3.0) * (caps["volume_cap"] * 0.4)

    total = trend_score + rsi_score + bb_pos_score + bb_width_score + obv_score + vol_score
    score = max(min(round(total), 100), -100)

    indicators = {
        "adx": round(adx_val, 2),
        "di_plus": round(di_plus_val, 2),
        "di_minus": round(di_minus_val, 2),
        "rsi": round(rsi_val, 2),
        "bb_upper": round(bb_upper_val, 2),
        "bb_lower": round(bb_lower_val, 2),
        "bb_pos": round(bb_pos, 4),
        "bb_width_pct": round(bb_width_pct, 1),
        "obv_slope": round(obv_slope_norm, 4),
        "vol_ratio": round(vol_ratio, 4),
        "atr": round(atr_val, 4),
        "regime_trending": round(regime["trending"], 4),
        "regime_ranging": round(regime["ranging"], 4),
        "regime_volatile": round(regime["volatile"], 4),
    }

    return {"score": score, "indicators": indicators, "regime": regime, "caps": caps}


def compute_order_flow_score(metrics: dict) -> dict:
    """Compute order flow score from funding rate, OI changes, and L/S ratio.

    Returns dict with 'score' (-100 to +100) and 'details' dict.
    All keys are optional with safe defaults.
    """
    # Funding rate — contrarian (max ±35)
    funding = metrics.get("funding_rate", 0.0)
    funding_score = sigmoid_score(-funding, center=0, steepness=8000) * 35

    # OI change — direction-aware (max ±20)
    oi_change = metrics.get("open_interest_change_pct", 0.0)
    price_dir = metrics.get("price_direction", 0)
    if price_dir == 0:
        oi_score = 0.0
    else:
        oi_score = price_dir * sigmoid_score(oi_change, center=0, steepness=65) * 20

    # L/S ratio — contrarian (max ±35)
    ls = metrics.get("long_short_ratio", 1.0)
    ls_score = sigmoid_score(1.0 - ls, center=0, steepness=6) * 35

    total = funding_score + oi_score + ls_score
    score = max(min(round(total), 100), -100)

    return {"score": score, "details": metrics}
