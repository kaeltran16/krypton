import math

import numpy as np
import pandas as pd

from app.engine.scoring import sigmoid_score, sigmoid_scale
from app.engine.regime import compute_regime_mix, blend_caps

_HTF_TIMEFRAMES = {"4h", "1D"}


def compute_trend_conviction(
    close: float,
    ema_9: float,
    ema_21: float,
    ema_50: float,
    adx: float,
    di_plus: float,
    di_minus: float,
) -> dict:
    """Compute trend conviction from EMA alignment, ADX strength, and price position.

    Returns dict with:
        conviction: 0.0 (no trend) to 1.0 (strong directional trend)
        direction: +1 (bullish) or -1 (bearish), from DI+/DI-
    """
    direction = 1 if di_plus > di_minus else -1

    # 1. EMA alignment (direction-aware): full=1.0, partial=0.5, against/equal=0.0
    bullish_full = ema_9 > ema_21 > ema_50
    bearish_full = ema_9 < ema_21 < ema_50
    if bullish_full or bearish_full:
        ema_alignment = 1.0
    elif (direction == 1 and ema_9 > ema_21) or (direction == -1 and ema_9 < ema_21):
        ema_alignment = 0.5
    else:
        ema_alignment = 0.0

    # 2. ADX strength (reuses same sigmoid as regime detection)
    adx_strength = sigmoid_scale(adx, center=20, steepness=0.25)

    # 3. Price confirmation (direction-aware)
    above_all = close > ema_9 and close > ema_21 and close > ema_50
    below_all = close < ema_9 and close < ema_21 and close < ema_50
    if (direction == 1 and above_all) or (direction == -1 and below_all):
        price_confirm = 1.0
    else:
        price_confirm = 0.0

    conviction = (ema_alignment + adx_strength + price_confirm) / 3.0

    return {"conviction": conviction, "direction": direction}


def _find_swing_points(series: np.ndarray, order: int, mode: str) -> list[int]:
    """Find local minima or maxima indices in a series.

    Uses strict comparison: the center point must be strictly less/greater
    than all neighbors in the window. This prevents flat regions from
    producing spurious swing points.

    Args:
        series: 1D array of values.
        order: Number of points on each side to compare.
        mode: "min" for swing lows, "max" for swing highs.
    """
    indices = []
    for i in range(order, len(series) - order):
        left = series[i - order : i]
        right = series[i + 1 : i + order + 1]
        if mode == "min" and series[i] < left.min() and series[i] < right.min():
            indices.append(i)
        elif mode == "max" and series[i] > left.max() and series[i] > right.max():
            indices.append(i)
    return indices


def detect_divergence(
    close: pd.Series,
    rsi: pd.Series,
    lookback: int = 50,
    order: int = 3,
) -> float:
    """Detect RSI/price divergence over recent candles.

    Checks for both bullish divergence (price lower low + RSI higher low)
    and bearish divergence (price higher high + RSI lower high).
    Returns the stronger divergence if both are present.

    Args:
        close: Price close series.
        rsi: RSI series (same length as close).
        lookback: Number of recent candles to scan.
        order: Swing point detection window (points on each side).

    Returns:
        0.0 (no divergence) to 1.0 (strong divergence).
    """
    close_arr = close.values[-lookback:].astype(float)
    rsi_arr = rsi.values[-lookback:].astype(float)

    if len(close_arr) < 2 * order + 1:
        return 0.0

    best = 0.0

    # Check bullish divergence (swing lows)
    swing_lows = _find_swing_points(close_arr, order, "min")
    if len(swing_lows) >= 2:
        i1, i2 = swing_lows[-2], swing_lows[-1]
        price_lower = close_arr[i2] < close_arr[i1]
        rsi_higher = rsi_arr[i2] > rsi_arr[i1]
        if price_lower and rsi_higher:
            rsi_diff = rsi_arr[i2] - rsi_arr[i1]
            best = max(best, min(1.0, rsi_diff / 15.0))

    # Check bearish divergence (swing highs)
    swing_highs = _find_swing_points(close_arr, order, "max")
    if len(swing_highs) >= 2:
        i1, i2 = swing_highs[-2], swing_highs[-1]
        price_higher = close_arr[i2] > close_arr[i1]
        rsi_lower = rsi_arr[i2] < rsi_arr[i1]
        if price_higher and rsi_lower:
            rsi_diff = rsi_arr[i1] - rsi_arr[i2]
            best = max(best, min(1.0, rsi_diff / 15.0))

    return best


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


def compute_technical_score(candles: pd.DataFrame, regime_weights=None, scoring_params: dict | None = None, timeframe: str | None = None) -> dict:
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

    # EMAs for structure-aware level placement
    ema_9 = close.ewm(span=9, adjust=False).mean()
    ema_21 = close.ewm(span=21, adjust=False).mean()
    ema_50 = close.ewm(span=50, adjust=False).mean()

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

    ema_9_val = float(ema_9[last])
    ema_21_val = float(ema_21[last])
    ema_50_val = float(ema_50[last])
    close_val = float(close[last])

    tc = compute_trend_conviction(
        close=close_val,
        ema_9=ema_9_val, ema_21=ema_21_val, ema_50=ema_50_val,
        adx=adx_val, di_plus=di_plus_val, di_minus=di_minus_val,
    )
    trend_conviction = tc["conviction"]

    divergence = 0.0
    if timeframe in _HTF_TIMEFRAMES:
        divergence = detect_divergence(close, rsi, lookback=50, order=3)

    mr_suppression = max(1.0 - trend_conviction, divergence)

    trend_strength = sigmoid_scale(adx_val, center=20, steepness=0.25)
    vol_expansion = sigmoid_scale(bb_width_pct, center=50, steepness=0.08)
    regime = compute_regime_mix(trend_strength, vol_expansion)
    caps = blend_caps(regime, regime_weights)

    # === Scoring parameters (shape + blend) ===
    sp = scoring_params or {}
    mr_rsi_steep = sp.get("mean_rev_rsi_steepness", 0.25)
    mr_bb_steep = sp.get("mean_rev_bb_pos_steepness", 10.0)
    sq_steep = sp.get("squeeze_steepness", 0.10)
    blend_ratio = sp.get("mean_rev_blend_ratio", 0.6)

    # === Scoring (caps from regime-aware blending) ===
    # 1. Trend
    di_sign = 1 if di_plus_val > di_minus_val else -1
    trend_score = di_sign * sigmoid_scale(adx_val, center=15, steepness=0.30) * caps["trend_cap"]

    # 2. Unified mean reversion (RSI + BB position)
    rsi_raw = sigmoid_score(50 - rsi_val, center=0, steepness=mr_rsi_steep)
    bb_pos_raw = sigmoid_score(0.5 - bb_pos, center=0, steepness=mr_bb_steep)
    mean_rev_score = (blend_ratio * rsi_raw + (1 - blend_ratio) * bb_pos_raw) * caps["mean_rev_cap"]

    # 3. Squeeze / expansion
    mean_rev_sign = 1 if mean_rev_score > 0 else (-1 if mean_rev_score < 0 else 0)
    squeeze_score = mean_rev_sign * sigmoid_scale(50 - bb_width_pct, center=0, steepness=sq_steep) * caps["squeeze_cap"]

    mean_rev_score = mean_rev_score * mr_suppression
    squeeze_score = squeeze_score * mr_suppression

    # 4. Volume confirmation (60/40 split)
    obv_score = sigmoid_score(obv_slope_norm, center=0, steepness=4) * (caps["volume_cap"] * 0.6)
    vol_score = candle_direction * sigmoid_score(vol_ratio - 1, center=0, steepness=3.0) * (caps["volume_cap"] * 0.4)

    total = trend_score + mean_rev_score + squeeze_score + obv_score + vol_score
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
        "mean_rev_score": round(mean_rev_score, 2),
        "squeeze_score": round(squeeze_score, 2),
        "mean_rev_rsi_raw": round(rsi_raw, 4),
        "mean_rev_bb_pos_raw": round(bb_pos_raw, 4),
        "regime_trending": round(regime["trending"], 4),
        "regime_ranging": round(regime["ranging"], 4),
        "regime_volatile": round(regime["volatile"], 4),
        "ema_9": round(ema_9_val, 2),
        "ema_21": round(ema_21_val, 2),
        "ema_50": round(ema_50_val, 2),
        "trend_conviction": round(trend_conviction, 2),
        "mr_suppression": round(mr_suppression, 2),
        "divergence": round(divergence, 2),
    }

    return {"score": score, "indicators": indicators, "regime": regime, "caps": caps}


# --- Order flow contrarian bias constants ---
from app.engine.constants import ORDER_FLOW

TRENDING_FLOOR = ORDER_FLOW["trending_floor"]
RECENT_WINDOW = ORDER_FLOW["recent_window"]
BASELINE_WINDOW = ORDER_FLOW["baseline_window"]
TOTAL_SNAPSHOTS = RECENT_WINDOW + BASELINE_WINDOW
ROC_THRESHOLD = ORDER_FLOW["roc_threshold"]
ROC_STEEPNESS = ORDER_FLOW["roc_steepness"]
LS_ROC_SCALE = ORDER_FLOW["ls_roc_scale"]


def _is_finite(v) -> bool:
    return v is not None and math.isfinite(v)


def _field_roc(baseline, recent, accessor):
    """Compute rate-of-change between baseline and recent windows for a given field."""
    b = [accessor(s) for s in baseline if _is_finite(accessor(s))]
    r = [accessor(s) for s in recent if _is_finite(accessor(s))]
    if b and r:
        return sum(r) / len(r) - sum(b) / len(b), True
    return 0.0, False


def compute_order_flow_score(
    metrics: dict,
    regime: dict | None = None,
    flow_history: list | None = None,
    trend_conviction: float = 0.0,
) -> dict:
    """Compute order flow score from funding rate, OI changes, and L/S ratio.

    Returns dict with 'score' (-100 to +100) and 'details' dict.
    All keys are optional with safe defaults.

    Args:
        regime: Market regime mix from compute_technical_score().
            {"trending": float, "ranging": float, "volatile": float}
            None defaults to full contrarian (mult=1.0).
        flow_history: Recent OrderFlowSnapshot rows (oldest first).
            None or < 10 rows disables RoC override.
    """
    # regime-based contrarian scaling
    if regime is not None:
        trending = regime.get("trending", 0.0)
        contrarian_mult = 1.0 - (trending * (1.0 - TRENDING_FLOOR))
        contrarian_mult = max(TRENDING_FLOOR, min(1.0, contrarian_mult))
    else:
        contrarian_mult = 1.0

    # rate-of-change override from flow history
    roc_boost = 0.0
    funding_roc = 0.0
    ls_roc = 0.0
    max_roc = 0.0

    if flow_history and len(flow_history) >= TOTAL_SNAPSHOTS:
        baseline = flow_history[-TOTAL_SNAPSHOTS:-RECENT_WINDOW]
        recent = flow_history[-RECENT_WINDOW:]

        funding_roc, has_funding = _field_roc(baseline, recent, lambda s: s.funding_rate)
        ls_roc, has_ls = _field_roc(baseline, recent, lambda s: s.long_short_ratio)

        if has_funding or has_ls:
            ls_roc_scaled = ls_roc * LS_ROC_SCALE
            max_roc = max(abs(funding_roc), abs(ls_roc_scaled))
            roc_boost = sigmoid_scale(max_roc, center=ROC_THRESHOLD, steepness=ROC_STEEPNESS)

    final_mult = contrarian_mult + roc_boost * (1.0 - contrarian_mult)

    conviction_dampening = 1.0 - trend_conviction
    final_mult = final_mult * conviction_dampening

    # Funding rate — contrarian (max +/-35)
    funding = metrics.get("funding_rate", 0.0)
    funding_score = sigmoid_score(-funding, center=0, steepness=8000) * 35 * final_mult

    # OI change — direction-aware (max +/-20), NOT affected by regime/RoC
    oi_change = metrics.get("open_interest_change_pct", 0.0)
    price_dir = metrics.get("price_direction", 0)
    if price_dir == 0:
        oi_score = 0.0
    else:
        oi_score = price_dir * sigmoid_score(oi_change, center=0, steepness=65) * 20

    # L/S ratio — contrarian (max +/-35)
    ls = metrics.get("long_short_ratio", 1.0)
    ls_score = sigmoid_score(1.0 - ls, center=0, steepness=6) * 35 * final_mult

    total = funding_score + oi_score + ls_score
    score = max(min(round(total), 100), -100)

    details = {
        "funding_rate": metrics.get("funding_rate", 0.0),
        "open_interest": metrics.get("open_interest"),
        "open_interest_change_pct": metrics.get("open_interest_change_pct", 0.0),
        "long_short_ratio": metrics.get("long_short_ratio", 1.0),
        "price_direction": metrics.get("price_direction", 0),
        "funding_score": round(funding_score, 1),
        "oi_score": round(oi_score, 1),
        "ls_score": round(ls_score, 1),
        "contrarian_mult": round(contrarian_mult, 4),
        "roc_boost": round(roc_boost, 4),
        "final_mult": round(final_mult, 4),
        "funding_roc": round(funding_roc, 8),
        "ls_roc": round(ls_roc, 8),
        "max_roc": round(max_roc, 8),
        "trend_conviction": round(trend_conviction, 2),
    }

    return {"score": score, "details": details}
