import pandas as pd
import numpy as np


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast=12, slow=26, signal=9):
    e_fast      = ema(series, fast)
    e_slow      = ema(series, slow)
    macd_line   = e_fast - e_slow
    signal_line = ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(series: pd.Series, period=20, std=2.0):
    mid   = series.rolling(period).mean()
    sigma = series.rolling(period).std()
    return mid + std * sigma, mid, mid - std * sigma


def stochastic(high, low, close, k_period=14, d_period=3):
    lowest  = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    k = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


def atr(high, low, close, period=14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def adx(high, low, close, period=14):
    up_move  = high.diff()
    dn_move  = -low.diff()
    plus_dm  = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
    atr_val  = atr(high, low, close, period)
    plus_di  = 100 * pd.Series(plus_dm, index=high.index).ewm(span=period, adjust=False).mean() / atr_val
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(span=period, adjust=False).mean() / atr_val
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.ewm(span=period, adjust=False).mean(), plus_di, minus_di


def support_resistance(df: pd.DataFrame, lookback=20):
    recent = df.tail(lookback)
    return recent["low"].min(), recent["high"].max()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df    = df.copy()
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    df["ema9"]   = ema(close, 9)
    df["ema21"]  = ema(close, 21)
    df["ema50"]  = ema(close, 50)
    df["ema200"] = ema(close, 200)

    df["rsi"] = rsi(close)

    df["macd"], df["macd_signal"], df["macd_hist"] = macd(close)

    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger_bands(close)

    df["stoch_k"], df["stoch_d"] = stochastic(high, low, close)

    df["atr"] = atr(high, low, close)

    df["adx"], df["plus_di"], df["minus_di"] = adx(high, low, close)

    df["vol_avg"]   = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg"].replace(0, np.nan)

    return df
