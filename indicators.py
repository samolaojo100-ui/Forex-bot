import pandas as pd
import numpy as np


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all 8 indicators on a OHLCV dataframe.
    Returns df with new columns added.
    """
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    # ── 1. RSI(14) ────────────────────────────────────────────────────
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ── 2. MACD(12,26,9) ─────────────────────────────────────────────
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"]        = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]

    # ── 3. Stochastic(9,6) ───────────────────────────────────────────
    low9  = low.rolling(9).min()
    high9 = high.rolling(9).max()
    df["stoch_k"] = 100 * (close - low9) / (high9 - low9).replace(0, np.nan)
    df["stoch_d"] = df["stoch_k"].rolling(6).mean()

    # ── 4. Bollinger Bands(20,2) ─────────────────────────────────────
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["bb_upper"] = bb_mid + 2 * bb_std
    df["bb_lower"] = bb_mid - 2 * bb_std
    df["bb_mid"]   = bb_mid
    bb_range       = (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
    df["bb_pct"]   = (close - df["bb_lower"]) / bb_range  # BB %B

    # ── 5. ATR(14) ───────────────────────────────────────────────────
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(com=13, adjust=False).mean()

    # ── 6. ADX(14) with +DI / -DI ───────────────────────────────────
    plus_dm  = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm[plus_dm < minus_dm]  = 0
    minus_dm[minus_dm < plus_dm] = 0

    atr14       = df["atr"]
    df["plus_di"]  = 100 * plus_dm.ewm(com=13, adjust=False).mean() / atr14.replace(0, np.nan)
    df["minus_di"] = 100 * minus_dm.ewm(com=13, adjust=False).mean() / atr14.replace(0, np.nan)
    dx = (df["plus_di"] - df["minus_di"]).abs() / (df["plus_di"] + df["minus_di"]).replace(0, np.nan) * 100
    df["adx"] = dx.ewm(com=13, adjust=False).mean()

    # ── 7. CCI(14) ───────────────────────────────────────────────────
    tp       = (high + low + close) / 3
    tp_mean  = tp.rolling(14).mean()
    tp_mad   = tp.rolling(14).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    df["cci"] = (tp - tp_mean) / (0.015 * tp_mad.replace(0, np.nan))

    # ── 8. Williams %R(14) ───────────────────────────────────────────
    high14    = high.rolling(14).max()
    low14     = low.rolling(14).min()
    df["williams_r"] = -100 * (high14 - close) / (high14 - low14).replace(0, np.nan)

    # ── EMAs for trend detection ──────────────────────────────────────
    df["ema9"]  = close.ewm(span=9,   adjust=False).mean()
    df["ema21"] = close.ewm(span=21,  adjust=False).mean()
    df["ema50"] = close.ewm(span=50,  adjust=False).mean()
    df["ema200"]= close.ewm(span=200, adjust=False).mean()

    return df.fillna(0)


def detect_candle_pattern(df: pd.DataFrame) -> str:
    """Detect basic candle patterns on the last 3 candles."""
    if len(df) < 3:
        return ""

    o  = df["open"].values
    h  = df["high"].values
    c  = df["close"].values
    l  = df["low"].values

    # Bullish engulfing
    if c[-2] < o[-2] and c[-1] > o[-1] and o[-1] < c[-2] and c[-1] > o[-2]:
        return "bullish_engulfing"

    # Bearish engulfing
    if c[-2] > o[-2] and c[-1] < o[-1] and o[-1] > c[-2] and c[-1] < o[-2]:
        return "bearish_engulfing"

    # Doji
    body = abs(c[-1] - o[-1])
    wick = h[-1] - l[-1]
    if wick > 0 and body / wick < 0.1:
        return "doji"

    # Three black crows
    if all(c[i] < o[i] for i in [-3, -2, -1]) and c[-1] < c[-2] < c[-3]:
        return "three_black_crows"

    # Three white soldiers
    if all(c[i] > o[i] for i in [-3, -2, -1]) and c[-1] > c[-2] > c[-3]:
        return "three_white_soldiers"

    # Hammer
    lower_wick = o[-1] - l[-1] if c[-1] >= o[-1] else c[-1] - l[-1]
    upper_wick = h[-1] - max(o[-1], c[-1])
    if lower_wick > 2 * body and upper_wick < body:
        return "hammer"

    # Shooting star
    if upper_wick > 2 * body and lower_wick < body:
        return "shooting_star"

    return ""


def support_resistance(df: pd.DataFrame):
    """Find recent swing high (resistance) and swing low (support)."""
    highs = df["high"].rolling(10).max()
    lows  = df["low"].rolling(10).min()
    return float(lows.iloc[-1]), float(highs.iloc[-1])
