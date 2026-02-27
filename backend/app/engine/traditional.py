import numpy as np
import pandas as pd


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = _ema(series, 12)
    ema26 = _ema(series, 26)
    macd_line = ema12 - ema26
    signal_line = _ema(macd_line, 9)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()


def compute_technical_score(candles: pd.DataFrame) -> dict:
    """
    Compute technical analysis score from OHLCV candle data.
    Returns dict with 'score' (-100 to +100) and 'indicators' dict.
    Requires at least 50 candles for reliable indicators.
    """
    df = candles.copy()
    df.columns = [c.lower() for c in df.columns]

    df["ema_9"] = _ema(df["close"], 9)
    df["ema_21"] = _ema(df["close"], 21)
    df["ema_50"] = _ema(df["close"], 50)

    macd_line, macd_signal, macd_hist = _macd(df["close"])
    df["macd"] = macd_line
    df["macd_signal"] = macd_signal
    df["macd_hist"] = macd_hist

    df["rsi"] = _rsi(df["close"], 14)

    sma_20 = df["close"].rolling(20).mean()
    std_20 = df["close"].rolling(20).std()
    df["bb_upper"] = sma_20 + 2 * std_20
    df["bb_lower"] = sma_20 - 2 * std_20

    df["atr"] = _atr(df["high"], df["low"], df["close"], 14)

    last = df.iloc[-1]
    score = 0.0

    # EMA trend (max +/- 30)
    if last["ema_9"] > last["ema_21"] > last["ema_50"]:
        score += 30
    elif last["ema_9"] < last["ema_21"] < last["ema_50"]:
        score -= 30
    else:
        ema_diff = (last["ema_9"] - last["ema_21"]) / last["close"] * 1000
        score += max(min(ema_diff * 10, 15), -15)

    # MACD (max +/- 25)
    if last["macd_hist"] > 0:
        score += min(abs(last["macd_hist"]) / last["close"] * 10000, 25)
    else:
        score -= min(abs(last["macd_hist"]) / last["close"] * 10000, 25)

    # RSI (max +/- 25)
    rsi = last["rsi"]
    if rsi < 30:
        score += 25
    elif rsi < 40:
        score += 10
    elif rsi > 70:
        score -= 25
    elif rsi > 60:
        score -= 10

    # Bollinger Band position (max +/- 20)
    bb_range = last["bb_upper"] - last["bb_lower"]
    if bb_range > 0:
        bb_pos = (last["close"] - last["bb_lower"]) / bb_range
        if bb_pos < 0.2:
            score += 20
        elif bb_pos > 0.8:
            score -= 20

    score = max(min(round(score), 100), -100)

    indicators = {
        "ema_9": float(last["ema_9"]),
        "ema_21": float(last["ema_21"]),
        "ema_50": float(last["ema_50"]) if pd.notna(last["ema_50"]) else None,
        "macd": float(last["macd"]),
        "macd_signal": float(last["macd_signal"]),
        "macd_hist": float(last["macd_hist"]),
        "rsi": float(last["rsi"]),
        "bb_upper": float(last["bb_upper"]),
        "bb_lower": float(last["bb_lower"]),
        "atr": float(last["atr"]),
    }

    return {"score": score, "indicators": indicators}


def compute_order_flow_score(metrics: dict) -> dict:
    """
    Compute order flow score from funding rate, OI changes, and L/S ratio.
    Returns dict with 'score' (-100 to +100) and 'details' dict.
    All keys are optional with safe defaults.
    """
    score = 0.0

    # funding rate analysis (max +/- 35)
    funding = metrics.get("funding_rate", 0.0)
    if funding > 0.0005:
        score -= 35
    elif funding > 0.0001:
        score -= 15
    elif funding < -0.0005:
        score += 35
    elif funding < -0.0001:
        score += 15

    # open interest change (max +/- 15)
    oi_change = metrics.get("open_interest_change_pct", 0.0)
    if oi_change > 0.05:
        score += 15
    elif oi_change < -0.05:
        score -= 15

    # long/short ratio (max +/- 35)
    ls = metrics.get("long_short_ratio", 1.0)
    if ls > 2.0:
        score -= 35
    elif ls > 1.5:
        score -= 15
    elif ls < 0.5:
        score += 35
    elif ls < 0.7:
        score += 15

    score = max(min(round(score), 100), -100)

    return {"score": score, "details": metrics}
