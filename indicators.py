import pandas as pd
import numpy as np

# ─────────────────────────────────────────────────────────────
#  Individual indicator functions
# ─────────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series,
         fast: int = 12, slow: int = 26, signal: int = 9
         ) -> tuple[pd.Series, pd.Series, pd.Series]:
    e_fast   = ema(series, fast)
    e_slow   = ema(series, slow)
    macd_line   = e_fast - e_slow
    signal_line = ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(series: pd.Series, period: int = 20, std: float = 2.0
                    ) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid   = series.rolling(period).mean()
    sigma = series.rolling(period).std()
    upper = mid + std * sigma
    lower = mid - std * sigma
    return upper, mid, lower


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_period: int = 14, d_period: int = 3
               ) -> tuple[pd.Series, pd.Series]:
    lowest  = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    k = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up_move   = high.diff()
    down_move = -low.diff()
    plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    atr_val   = atr(high, low, close, period)
    plus_di   = 100 * pd.Series(plus_dm).ewm(span=period, adjust=False).mean() / atr_val
    minus_di  = 100 * pd.Series(minus_dm).ewm(span=period, adjust=False).mean() / atr_val
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.ewm(span=period, adjust=False).mean(), plus_di, minus_di


def support_resistance(df: pd.DataFrame, lookback: int = 20) -> tuple[float, float]:
    """Simple pivot-based S/R."""
    recent = df.tail(lookback)
    support    = recent["low"].min()
    resistance = recent["high"].max()
    return support, resistance


# ─────────────────────────────────────────────────────────────
#  Full indicator suite applied to a single DataFrame
# ─────────────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close, high, low = df["close"], df["high"], df["low"]

    # EMAs
    df["ema9"]   = ema(close, 9)
    df["ema21"]  = ema(close, 21)
    df["ema50"]  = ema(close, 50)
    df["ema200"] = ema(close, 200)

    # RSI
    df["rsi"] = rsi(close)

    # MACD
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(close)

    # Bollinger Bands
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger_bands(close)

    # Stochastic
    df["stoch_k"], df["stoch_d"] = stochastic(high, low, close)

    # ATR
    df["atr"] = atr(high, low, close)

    # ADX
    df["adx"], df["plus_di"], df["minus_di"] = adx(high, low, close)

    # Volume ratio
    df["vol_avg"] = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / df["vol_avg"].replace(0, np.nan)

    return df
