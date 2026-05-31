import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from indicators import compute_indicators
from config import RISK_PERCENT, CRYPTO_PAIRS, DEFAULT_RR_RATIO

logger = logging.getLogger(__name__)


@dataclass
class TFSignal:
    tf:          str
    direction:   str        # BUY / SELL
    entry:       float
    stop_loss:   float
    take_profit: float
    sl_pips:     float
    tp_pips:     float
    lot_size:    float
    indicators:  int        # how many of 5 confirmed
    confirmed:   list       # names of confirmed indicators
    rsi:         float
    stoch:       float
    macd:        float
    agrees:      bool       # agrees with overall direction


@dataclass
class Signal:
    pair:         str
    direction:    str
    entry:        float
    score:        int       # sum of TF scores (max 25)
    confidence:   str
    tfs_agreed:   int       # how many TFs agree
    total_tfs:    int
    tf_signals:   list      # list of TFSignal
    asset_type:   str = "FOREX"
    risk_amount:  float = 0.0


def is_crypto(pair: str) -> bool:
    return pair in CRYPTO_PAIRS


def pip_size(pair: str) -> float:
    if is_crypto(pair): return 1.0
    return 0.01 if "JPY" in pair else 0.0001


def pips(pair: str, a: float, b: float) -> float:
    return round(abs(a - b) / pip_size(pair), 1)


def lot_size(pair: str, sl_pips: float, balance: float) -> float:
    risk  = balance * RISK_PERCENT / 100
    if is_crypto(pair):
        return round(risk / max(sl_pips, 1), 4)
    pv = 10 if "JPY" not in pair else 9.09
    return max(0.01, round(risk / (sl_pips * pv), 2))


def analyze_tf(df: pd.DataFrame, pair: str, tf: str, balance: float, overall_dir: str) -> TFSignal:
    row   = df.iloc[-1]
    close = row["close"]
    ps    = pip_size(pair)

    confirmed = []
    buy_pts = 0

    # 1. EMA trend
    if row["ema9"] > row["ema21"] > row["ema50"]:
        buy_pts += 1; confirmed.append("EMA")
    elif row["ema9"] < row["ema21"] < row["ema50"]:
        buy_pts -= 1
    else:
        if row["ema9"] > row["ema21"]: buy_pts += 0.5

    # 2. MACD
    if row["macd"] > row["macd_signal"] and row["macd_hist"] > 0:
        buy_pts += 1; confirmed.append("MACD")
    elif row["macd"] < row["macd_signal"] and row["macd_hist"] < 0:
        buy_pts -= 1
    elif row["macd_hist"] > 0:
        buy_pts += 0.3; confirmed.append("MACD")

    # 3. RSI
    rsi = row["rsi"]
    if rsi < 50:
        buy_pts += 0.5; confirmed.append("RSI")
    elif rsi > 50:
        buy_pts -= 0.5

    # 4. Stochastic
    k = row["stoch_k"]
    if k > row["stoch_d"]:
        buy_pts += 0.5; confirmed.append("Stochastic")
    else:
        buy_pts -= 0.5

    # 5. Bollinger
    if close < row["bb_mid"]:
        buy_pts += 0.5; confirmed.append("Bollinger")
    else:
        buy_pts -= 0.3

    direction = "BUY" if buy_pts > 0 else "SELL"
    ind_score = min(len(confirmed), 5)

    # Per-TF SL/TP based on ATR
    atr = row["atr"]
    min_sl = close * 0.003 if is_crypto(pair) else (0.0010 if "JPY" not in pair else 0.10)

    if direction == "BUY":
        sl = close - max(1.2 * atr, min_sl)
        tp = close + max(1.2 * atr, min_sl) * DEFAULT_RR_RATIO
    else:
        sl = close + max(1.2 * atr, min_sl)
        tp = close - max(1.2 * atr, min_sl) * DEFAULT_RR_RATIO

    sl_p = pips(pair, close, sl)
    tp_p = pips(pair, close, tp)
    lot  = lot_size(pair, max(sl_p, 0.1), balance)

    # Precision
    dec = 2 if is_crypto(pair) and close > 10 else 5

    return TFSignal(
        tf          = tf,
        direction   = direction,
        entry       = round(close, dec),
        stop_loss   = round(sl, dec),
        take_profit = round(tp, dec),
        sl_pips     = sl_p,
        tp_pips     = tp_p,
        lot_size    = lot,
        indicators  = ind_score,
        confirmed   = confirmed,
        rsi         = round(rsi, 2),
        stoch       = round(k, 2),
        macd        = round(row["macd"], 6),
        agrees      = direction == overall_dir,
    )


def overall_direction(tf_data: dict, processed: dict) -> str:
    buy = 0
    for tf, df in processed.items():
        row = df.iloc[-1]
        pts = sum([
            row["ema9"] > row["ema21"],
            row["macd"] > row["macd_signal"],
            row["rsi"]  < 50,
            row["stoch_k"] > row["stoch_d"],
            row["plus_di"] > row["minus_di"],
        ])
        if pts >= 3: buy += 1
    return "BUY" if buy >= len(processed) / 2 else "SELL"


def analyze_pair(pair: str, tf_data: dict, account_balance: float):
    try:
        processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicator error: {e}")
        return None

    o_dir     = overall_direction(tf_data, processed)
    tf_sigs   = []
    total_ind = 0

    for tf, df in processed.items():
        tfs = analyze_tf(df, pair, tf, account_balance, o_dir)
        tf_sigs.append(tfs)
        total_ind += tfs.indicators

    agreed    = sum(1 for t in tf_sigs if t.agrees)
    score     = total_ind   # max 25 (5 TFs × 5 indicators)

    if score < 6:
        return None

    if agreed < 2:
        return None

    conf_pct = agreed / len(tf_sigs)
    if conf_pct >= 0.8:    confidence = "VERY HIGH"
    elif conf_pct >= 0.6:  confidence = "HIGH"
    elif conf_pct >= 0.4:  confidence = "MEDIUM"
    else:                  confidence = "LOW"

    # Use entry from 1h as the main entry
    main_tf   = next((t for t in tf_sigs if t.tf == "1h"), tf_sigs[0])
    risk_usd  = round(account_balance * RISK_PERCENT / 100, 2)

    return Signal(
        pair        = pair,
        direction   = o_dir,
        entry       = main_tf.entry,
        score       = score,
        confidence  = confidence,
        tfs_agreed  = agreed,
        total_tfs   = len(tf_sigs),
        tf_signals  = tf_sigs,
        asset_type  = "CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount = risk_usd,
    )


def scan_all_pairs(data_map: dict, account_balance: float, crypto_only: bool = False) -> list:
    signals = []
    for pair, tfs in data_map.items():
        if crypto_only and not is_crypto(pair): continue
        try:
            sig = analyze_pair(pair, tfs, account_balance)
            if sig: signals.append(sig)
        except Exception as e:
            logger.warning(f"{pair} error: {e}")
    signals.sort(key=lambda s: s.score, reverse=True)
    return signals


def force_analyze_pair(pair: str, tf_data: dict, account_balance: float):
    """
    Like analyze_pair but forces a signal even with low score.
    Used to always show best available crypto signals.
    """
    try:
        processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicator error: {e}")
        return None

    o_dir     = overall_direction(tf_data, processed)
    tf_sigs   = []
    total_ind = 0

    for tf, df in processed.items():
        tfs = analyze_tf(df, pair, tf, account_balance, o_dir)
        tf_sigs.append(tfs)
        total_ind += tfs.indicators

    agreed   = sum(1 for t in tf_sigs if t.agrees)
    score    = total_ind

    conf_pct = agreed / len(tf_sigs)
    if conf_pct >= 0.8:    confidence = "VERY HIGH"
    elif conf_pct >= 0.6:  confidence = "HIGH"
    elif conf_pct >= 0.4:  confidence = "MEDIUM"
    else:                  confidence = "LOW"

    main_tf  = next((t for t in tf_sigs if t.tf == "1h"), tf_sigs[0])
    risk_usd = round(account_balance * RISK_PERCENT / 100, 2)

    return Signal(
        pair        = pair,
        direction   = o_dir,
        entry       = main_tf.entry,
        score       = score,
        confidence  = confidence,
        tfs_agreed  = agreed,
        total_tfs   = len(tf_sigs),
        tf_signals  = tf_sigs,
        asset_type  = "CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount = risk_usd,
    )
