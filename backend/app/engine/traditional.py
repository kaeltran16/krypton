import math

import numpy as np
import pandas as pd

from app.engine.scoring import sigmoid_score, sigmoid_scale
from app.engine.regime import compute_regime_mix, blend_caps
from app.engine.constants import ORDER_FLOW, INDICATOR_PERIODS, MR_PRESSURE, VOL_MULTIPLIER, SIGMOID_PARAMS

_HTF_TIMEFRAMES = {"4h", "1D"}


def compute_mr_pressure(rsi: float, bb_pos: float, config: dict | None = None) -> float:
    """Measure mean-reversion indicator extremity (0.0-1.0).

    Multiplicative gate: BOTH RSI and BB position must be extreme.
    Symmetric for overbought and oversold.
    """
    cfg = config or MR_PRESSURE
    rsi_extremity = max(0, abs(rsi - 50) - cfg["rsi_offset"]) / cfg["rsi_range"]
    bb_extremity = max(0, abs(bb_pos - 0.5) - cfg["bb_offset"]) / cfg["bb_range"]
    return min(1.0, rsi_extremity * bb_extremity)


def compute_trend_conviction(
    close: float,
    ema_9: float,
    ema_21: float,
    ema_50: float,
    adx: float,
    di_direction: float,
    atr: float = 1.0,
) -> dict:
    """Compute trend conviction from EMA alignment, ADX strength, and price position.

    Returns dict with:
        conviction: 0.0 (no trend) to 1.0 (strong directional trend)
        direction: +1 (bullish) or -1 (bearish), from di_direction
    """
    direction = 1 if di_direction > 0 else -1

    # 1. Continuous EMA alignment: normalized distance between EMA pairs through sigmoid
    if atr > 0:
        ema_spread = (ema_9 - ema_21) / atr
    else:
        ema_spread = 0.0
    ema_alignment = sigmoid_scale(abs(ema_spread), center=0.5, steepness=2.0)
    # penalize conflicting EMA/DI direction
    spread_dir = 1 if ema_spread >= 0 else -1
    if spread_dir != direction:
        ema_alignment *= 0.3

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


def compute_technical_score(candles: pd.DataFrame, regime_weights=None, scoring_params: dict | None = None, timeframe: str | None = None, overrides: dict | None = None) -> dict:
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

    bb_pct_window = INDICATOR_PERIODS["bb_width_percentile_window"]
    bb_widths = bb_width.dropna().values
    if len(bb_widths) >= bb_pct_window:
        recent_widths = bb_widths[-bb_pct_window:]
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

    di_sum = di_plus_val + di_minus_val
    di_spread = (di_plus_val - di_minus_val) / di_sum if di_sum > 0 else 0.0

    # === Scoring parameters (shape + blend) ===
    sp = scoring_params or {}

    di_direction = sigmoid_score(di_spread, center=0, steepness=sp.get("di_spread_steepness", SIGMOID_PARAMS["di_spread_steepness"]))

    tc = compute_trend_conviction(
        close=close_val,
        ema_9=ema_9_val, ema_21=ema_21_val, ema_50=ema_50_val,
        adx=adx_val, di_direction=di_direction,
        atr=atr_val,
    )
    trend_conviction = tc["conviction"]

    divergence = 0.0
    if timeframe in _HTF_TIMEFRAMES:
        divergence = detect_divergence(close, rsi, lookback=50, order=3)

    adx_center = getattr(regime_weights, "adx_center", 20.0) if regime_weights else 20.0
    trend_strength = sigmoid_scale(adx_val, center=sp.get("trend_strength_center", adx_center), steepness=sp.get("trend_strength_steepness", 0.25))
    vol_expansion = sigmoid_scale(bb_width_pct, center=sp.get("vol_expansion_center", 50), steepness=sp.get("vol_expansion_steepness", 0.08))
    regime = compute_regime_mix(trend_strength, vol_expansion)
    caps = blend_caps(regime, regime_weights)

    _mr_ovr = overrides.get("mr_pressure") if overrides else None
    mr = {**MR_PRESSURE, **_mr_ovr} if _mr_ovr else MR_PRESSURE
    _vol_ovr = overrides.get("vol_multiplier") if overrides else None
    vol = {**VOL_MULTIPLIER, **_vol_ovr} if _vol_ovr else VOL_MULTIPLIER

    mr_pressure_val = compute_mr_pressure(rsi_val, bb_pos, config=mr)
    if mr_pressure_val > 0:
        shift = mr_pressure_val * mr["max_cap_shift"]
        caps["mean_rev_cap"] += shift
        caps["trend_cap"] -= shift

    mr_rsi_steep = sp.get("mean_rev_rsi_steepness", 0.25)
    mr_bb_steep = sp.get("mean_rev_bb_pos_steepness", 10.0)
    sq_steep = sp.get("squeeze_steepness", 0.10)
    blend_ratio = sp.get("mean_rev_blend_ratio", 0.6)

    # === Scoring (caps from regime-aware blending) ===
    # 1. Trend
    trend_score = di_direction * sigmoid_scale(adx_val, center=15, steepness=sp.get("trend_score_steepness", 0.30)) * caps["trend_cap"]

    # 2. Unified mean reversion (RSI + BB position)
    rsi_raw = sigmoid_score(50 - rsi_val, center=0, steepness=mr_rsi_steep)
    bb_pos_raw = sigmoid_score(0.5 - bb_pos, center=0, steepness=mr_bb_steep)
    mean_rev_score = (blend_ratio * rsi_raw + (1 - blend_ratio) * bb_pos_raw) * caps["mean_rev_cap"]

    # 3. Squeeze / expansion
    directional_sum = trend_score + mean_rev_score
    directional_sign = 1 if directional_sum > 0 else (-1 if directional_sum < 0 else 0)
    squeeze_score = directional_sign * sigmoid_scale(50 - bb_width_pct, center=0, steepness=sq_steep) * caps["squeeze_cap"]

    # 4. Multiplicative volume confirmation
    directional = trend_score + mean_rev_score + squeeze_score

    if directional == 0:
        total = 0.0
    else:
        score_sign = 1 if directional > 0 else -1

        obv_dir = 1 if obv_slope_norm > 0 else -1
        obv_confirms = (obv_dir == score_sign)
        obv_strength = sigmoid_scale(abs(obv_slope_norm), center=0, steepness=sp.get("obv_slope_steepness", 4))

        candle_confirms = (candle_direction == score_sign)
        vol_strength = sigmoid_scale(vol_ratio - 1, center=0, steepness=sp.get("volume_ratio_steepness", 3))

        obv_w = vol["obv_weight"]
        vol_w = 1.0 - obv_w
        confirmation = (
            obv_w * (obv_strength if obv_confirms else 1 - obv_strength)
            + vol_w * (vol_strength if candle_confirms else 1 - vol_strength)
        )

        vol_mult_ceil = 1.0 + caps["volume_cap"] / 100
        vol_mult_floor = 2.0 - vol_mult_ceil
        vol_mult = vol_mult_floor + (vol_mult_ceil - vol_mult_floor) * confirmation
        total = directional * vol_mult

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
        "trend_score": round(trend_score, 2),
        "di_direction": round(di_direction, 4),
        "mean_rev_rsi_raw": round(rsi_raw, 4),
        "mean_rev_bb_pos_raw": round(bb_pos_raw, 4),
        "regime_trending": round(regime["trending"], 4),
        "regime_ranging": round(regime["ranging"], 4),
        "regime_volatile": round(regime["volatile"], 4),
        "regime_steady": round(regime["steady"], 4),
        "ema_9": round(ema_9_val, 2),
        "ema_21": round(ema_21_val, 2),
        "ema_50": round(ema_50_val, 2),
        "trend_conviction": round(trend_conviction, 2),
        "divergence": round(divergence, 2),
        "mr_pressure": round(mr_pressure_val, 4),
    }

    # confidence: directional — either strong trend or strong exhaustion can produce confidence
    indicator_conflict = 1.0 - abs(trend_score + mean_rev_score) / max(abs(trend_score) + abs(mean_rev_score), 1e-6)
    final_sign = 1 if total > 0 else (-1 if total < 0 else 0)

    trend_conf = trend_strength * 0.5 + trend_conviction * 0.5
    di_sign = 1 if di_direction > 0 else (-1 if di_direction < 0 else 0)
    if final_sign != 0 and di_sign != final_sign:
        trend_conf *= 0.2

    mr_conf = mr_pressure_val
    thesis_conf = max(trend_conf, mr_conf)
    confidence = thesis_conf * 0.8 + (1.0 - indicator_conflict) * 0.2
    confidence = max(0.0, min(1.0, confidence))

    return {"score": score, "indicators": indicators, "regime": regime, "caps": caps, "confidence": round(confidence, 4), "mr_pressure": round(mr_pressure_val, 4)}


# --- Order flow contrarian bias constants ---
FUNDING_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["funding"]
OI_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["oi"]
LS_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["ls_ratio"]
CVD_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["cvd"]
FUNDING_MAX = ORDER_FLOW["max_scores"]["funding"]
OI_MAX = ORDER_FLOW["max_scores"]["oi"]
LS_MAX = ORDER_FLOW["max_scores"]["ls_ratio"]
CVD_MAX = ORDER_FLOW["max_scores"]["cvd"]
BOOK_MAX = ORDER_FLOW["max_scores"]["book"]
BOOK_STEEPNESS = ORDER_FLOW["sigmoid_steepnesses"]["book"]
FRESH_SECONDS = ORDER_FLOW["freshness_fresh_seconds"]
STALE_SECONDS = ORDER_FLOW["freshness_stale_seconds"]
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
    mr_pressure: float = 0.0,
    flow_age_seconds: float | None = None,
    asset_scale: float = 1.0,
) -> dict:
    """Compute order flow score from funding rate, OI changes, and L/S ratio.

    Returns dict with 'score' (-100 to +100) and 'details' dict.
    All keys are optional with safe defaults.

    Args:
        regime: Market regime mix from compute_technical_score().
            {"trending": float, "ranging": float, "volatile": float, "steady": float}
            None defaults to full contrarian (mult=1.0).
        flow_history: Recent OrderFlowSnapshot rows (oldest first).
            None or < 10 rows disables RoC override.
    """
    # regime-based contrarian scaling
    if regime is not None:
        trending = regime.get("trending", 0.0) + regime.get("steady", 0.0)
        contrarian_mult = 1.0 - (trending * (1.0 - TRENDING_FLOOR))
        contrarian_mult = max(TRENDING_FLOOR, min(1.0, contrarian_mult))
    else:
        contrarian_mult = 1.0

    if mr_pressure > 0:
        relaxed_floor = TRENDING_FLOOR + mr_pressure * (1.0 - TRENDING_FLOOR)
        contrarian_mult = max(contrarian_mult, relaxed_floor)

    # rate-of-change override from flow history
    roc_boost = 0.0
    funding_roc = 0.0
    ls_roc = 0.0
    oi_roc = 0.0
    max_roc = 0.0

    if flow_history and len(flow_history) >= TOTAL_SNAPSHOTS:
        baseline = flow_history[-TOTAL_SNAPSHOTS:-RECENT_WINDOW]
        recent = flow_history[-RECENT_WINDOW:]

        funding_roc, has_funding = _field_roc(baseline, recent, lambda s: s.funding_rate)
        ls_roc, has_ls = _field_roc(baseline, recent, lambda s: s.long_short_ratio)
        oi_roc, has_oi = _field_roc(baseline, recent, lambda s: s.oi_change_pct)

        if has_funding or has_ls or has_oi:
            ls_roc_scaled = ls_roc * LS_ROC_SCALE
            max_roc = max(abs(funding_roc), abs(ls_roc_scaled), abs(oi_roc))
            roc_boost = sigmoid_scale(max_roc, center=ROC_THRESHOLD, steepness=ROC_STEEPNESS)

    final_mult = contrarian_mult + roc_boost * (1.0 - contrarian_mult)

    effective_conviction = trend_conviction * (1.0 - mr_pressure)
    conviction_dampening = 1.0 - effective_conviction
    final_mult = min(final_mult, conviction_dampening)

    # Funding rate — contrarian, asset-scaled
    funding = metrics.get("funding_rate", 0.0)
    funding_steepness = FUNDING_STEEPNESS * asset_scale
    funding_score = sigmoid_score(-funding, center=0, steepness=funding_steepness) * FUNDING_MAX

    # OI change — direction-aware (max +/-20), NOT affected by regime/RoC
    oi_change = metrics.get("open_interest_change_pct", 0.0)
    price_dir = metrics.get("price_direction", 0)
    if price_dir == 0:
        oi_score = 0.0
    else:
        oi_score = price_dir * sigmoid_score(oi_change, center=0, steepness=OI_STEEPNESS) * OI_MAX

    # L/S ratio — contrarian, asset-scaled
    ls = metrics.get("long_short_ratio", 1.0)
    ls_steepness = LS_STEEPNESS * asset_scale
    ls_score = sigmoid_score(1.0 - ls, center=0, steepness=ls_steepness) * LS_MAX

    # CVD — directional, trend-based when history available (max +/-CVD_MAX)
    cvd_delta = metrics.get("cvd_delta")
    avg_vol = metrics.get("avg_candle_volume", 0)
    cvd_history = metrics.get("cvd_history")

    if cvd_history and len(cvd_history) >= 5 and avg_vol > 0:
        arr = np.array(cvd_history[-10:], dtype=float)
        x = np.arange(len(arr))
        slope = np.polynomial.polynomial.polyfit(x, arr, 1)[1]
        cvd_normalized = slope / avg_vol
        cvd_score = sigmoid_score(cvd_normalized, center=0, steepness=CVD_STEEPNESS) * CVD_MAX
    elif cvd_delta is not None and avg_vol > 0:
        cvd_normalized = cvd_delta / avg_vol
        cvd_score = sigmoid_score(cvd_normalized, center=0, steepness=CVD_STEEPNESS) * CVD_MAX
    else:
        cvd_score = 0.0

    # Book imbalance — directional, NOT contrarian (max +/-BOOK_MAX)
    book_imbalance = metrics.get("book_imbalance")
    if book_imbalance is not None:
        book_score = sigmoid_score(book_imbalance, center=0, steepness=BOOK_STEEPNESS) * BOOK_MAX
    else:
        book_score = 0.0

    total = (funding_score + oi_score + ls_score + cvd_score + book_score) * final_mult
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
        "cvd_score": round(cvd_score, 1),
        "book_score": round(book_score, 1),
        "contrarian_mult": round(contrarian_mult, 4),
        "roc_boost": round(roc_boost, 4),
        "final_mult": round(final_mult, 4),
        "funding_roc": round(funding_roc, 8),
        "ls_roc": round(ls_roc, 8),
        "oi_roc": round(oi_roc, 8),
        "max_roc": round(max_roc, 8),
        "trend_conviction": round(trend_conviction, 2),
        "asset_scale": round(asset_scale, 4),
    }

    # dynamic confidence: key-based presence detection
    inputs_present = sum([
        "funding_rate" in metrics,
        "open_interest_change_pct" in metrics and price_dir != 0,
        "long_short_ratio" in metrics,
        cvd_delta is not None and avg_vol > 0,
        book_imbalance is not None,
    ])
    sources_available = sum([
        "funding_rate" in metrics,
        "open_interest_change_pct" in metrics,
        "long_short_ratio" in metrics,
        cvd_delta is not None,
        book_imbalance is not None,
    ])
    flow_confidence = round(inputs_present / max(sources_available, 1), 4)

    # Freshness decay — penalize confidence for stale flow data
    freshness_decay = 0.0
    if flow_age_seconds is not None and flow_age_seconds > FRESH_SECONDS:
        freshness_decay = min(1.0, (flow_age_seconds - FRESH_SECONDS) / (STALE_SECONDS - FRESH_SECONDS))
        flow_confidence = round(flow_confidence * (1.0 - freshness_decay), 4)

    details["flow_age_seconds"] = round(flow_age_seconds, 1) if flow_age_seconds is not None else None
    details["freshness_decay"] = round(freshness_decay, 4)

    return {"score": score, "details": details, "confidence": flow_confidence}
