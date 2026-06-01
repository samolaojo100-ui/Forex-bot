import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from indicators import compute_indicators
from config import RISK_PERCENT, CRYPTO_PAIRS, DEFAULT_RR_RATIO, MIN_SIGNAL_SCORE

logger = logging.getLogger(__name__)


@dataclass
class TFSignal:
    tf: str
    direction: str          # BUY / SELL
    entry: float
    stop_loss: float
    take_profit: float
    sl_pips: float
    tp_pips: float
    lot_size: float
    score: float            # 0-5 score for this TF
    confirmed: list         # names of confirmed indicators
    rsi: float
    stoch: float
    macd: float
    adx: float
    agrees: bool            # agrees with overall direction


@dataclass
class Signal:
    pair: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    sl_pips: float
    tp_pips: float
    lot_size: float
    score: float            # 0–100 normalised score
    confidence: str
    tfs_agreed: int
    total_tfs: int
    tf_signals: list
    asset_type: str = "FOREX"
    risk_amount: float = 0.0


# ── helpers ──────────────────────────────────────────────────────────────────

def is_crypto(pair: str) -> bool:
    return pair in CRYPTO_PAIRS


def pip_size(pair: str) -> float:
    if is_crypto(pair):
        return 1.0
    return 0.01 if "JPY" in pair else 0.0001


def pips(pair: str, a: float, b: float) -> float:
    return round(abs(a - b) / pip_size(pair), 1)


def calc_lot_size(pair: str, sl_pips: float, balance: float) -> float:
    risk = balance * RISK_PERCENT / 100
    if is_crypto(pair):
        return round(risk / max(sl_pips, 1), 4)
    pv = 10 if "JPY" not in pair else 9.09
    return max(0.01, round(risk / (sl_pips * pv), 2))


def decimal_places(pair: str, close: float) -> int:
    if is_crypto(pair):
        return 2 if close > 10 else 5
    return 3 if "JPY" in pair else 5


# ── per-timeframe analysis ────────────────────────────────────────────────────

def analyze_tf(df: pd.DataFrame, pair: str, tf: str, balance: float, overall_dir: str) -> TFSignal:
    row = df.iloc[-1]
    close = float(row["close"])
    ps = pip_size(pair)
    confirmed = []
    score = 0.0  # 0 – 5

    # 1. EMA trend alignment (max 1 pt)
    if row["ema9"] > row["ema21"] > row["ema50"]:
        score += 1.0
        confirmed.append("EMA bullish")
    elif row["ema9"] < row["ema21"] < row["ema50"]:
        score += 1.0
        confirmed.append("EMA bearish")
    elif row["ema9"] > row["ema21"]:
        score += 0.4
        confirmed.append("EMA partial")

    # 2. MACD (max 1 pt)
    if row["macd"] > row["macd_signal"] and row["macd_hist"] > 0:
        score += 1.0
        confirmed.append("MACD bullish")
    elif row["macd"] < row["macd_signal"] and row["macd_hist"] < 0:
        score += 1.0
        confirmed.append("MACD bearish")
    elif abs(row["macd_hist"]) > 0:
        score += 0.4
        confirmed.append("MACD partial")

    # 3. RSI — FIX: RSI > 50 = bullish momentum, RSI < 50 = bearish (was inverted before)
    rsi = float(row["rsi"])
    if overall_dir == "BUY":
        if 50 < rsi < 70:           # bullish but not overbought
            score += 1.0
            confirmed.append(f"RSI {rsi:.0f} bullish")
        elif rsi >= 70:             # overbought — partial
            score += 0.3
        elif rsi > 45:
            score += 0.5
    else:  # SELL
        if 30 < rsi < 50:           # bearish but not oversold
            score += 1.0
            confirmed.append(f"RSI {rsi:.0f} bearish")
        elif rsi <= 30:             # oversold — partial
            score += 0.3
        elif rsi < 55:
            score += 0.5

    # 4. Stochastic (max 1 pt)
    k = float(row["stoch_k"])
    d = float(row["stoch_d"])
    if overall_dir == "BUY":
        if k > d and k < 80:
            score += 1.0
            confirmed.append(f"Stoch {k:.0f} bullish")
        elif k > d:
            score += 0.4
    else:
        if k < d and k > 20:
            score += 1.0
            confirmed.append(f"Stoch {k:.0f} bearish")
        elif k < d:
            score += 0.4

    # 5. ADX strength (max 1 pt) — direction-agnostic trend strength
    adx_val = float(row["adx"]) if not np.isnan(row["adx"]) else 0
    plus_di = float(row["plus_di"]) if not np.isnan(row["plus_di"]) else 0
    minus_di = float(row["minus_di"]) if not np.isnan(row["minus_di"]) else 0
    if adx_val >= 25:
        score += 1.0
        confirmed.append(f"ADX {adx_val:.0f} strong")
    elif adx_val >= 18:
        score += 0.5

    # Direction for this TF (based on which DI is dominant + MACD)
    buy_votes = sum([
        row["ema9"] > row["ema21"],
        row["macd"] > row["macd_signal"],
        rsi > 50,
        k > d,
        plus_di > minus_di,
    ])
    tf_direction = "BUY" if buy_votes >= 3 else "SELL"

    # SL / TP from ATR
    atr = float(row["atr"]) if not np.isnan(row["atr"]) else close * 0.001
    min_sl = close * 0.003 if is_crypto(pair) else (0.0015 if "JPY" not in pair else 0.15)
    sl_dist = max(1.5 * atr, min_sl)

    if tf_direction == "BUY":
        sl = close - sl_dist
        tp = close + sl_dist * DEFAULT_RR_RATIO
    else:
        sl = close + sl_dist
        tp = close - sl_dist * DEFAULT_RR_RATIO

    sl_p = pips(pair, close, sl)
    tp_p = pips(pair, close, tp)
    lot = calc_lot_size(pair, max(sl_p, 0.1), balance)
    dec = decimal_places(pair, close)

    return TFSignal(
        tf=tf,
        direction=tf_direction,
        entry=round(close, dec),
        stop_loss=round(sl, dec),
        take_profit=round(tp, dec),
        sl_pips=sl_p,
        tp_pips=tp_p,
        lot_size=lot,
        score=round(score, 2),
        confirmed=confirmed,
        rsi=round(rsi, 2),
        stoch=round(k, 2),
        macd=round(float(row["macd"]), 6),
        adx=round(adx_val, 1),
        agrees=(tf_direction == overall_dir),
    )


# ── overall direction ─────────────────────────────────────────────────────────

def overall_direction(processed: dict) -> str:
    """
    FIX: was passing raw tf_data instead of processed (indicator) data.
    Now correctly uses the processed dataframes.
    """
    buy_votes = 0
    for tf, df in processed.items():
        row = df.iloc[-1]
        pts = sum([
            row["ema9"] > row["ema21"],
            row["macd"] > row["macd_signal"],
            float(row["rsi"]) > 50,          # FIX: > 50 = bullish
            row["stoch_k"] > row["stoch_d"],
            row["plus_di"] > row["minus_di"],
        ])
        if pts >= 3:
            buy_votes += 1
    return "BUY" if buy_votes >= len(processed) / 2 else "SELL"


# ── main pair analysis ────────────────────────────────────────────────────────

def analyze_pair(pair: str, tf_data: dict, account_balance: float):
    try:
        processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicator error: {e}")
        return None

    # FIX: pass processed (not tf_data) to overall_direction
    o_dir = overall_direction(processed)

    tf_sigs = []
    for tf, df in processed.items():
        try:
            tfs = analyze_tf(df, pair, tf, account_balance, o_dir)
            tf_sigs.append(tfs)
        except Exception as e:
            logger.warning(f"{pair} {tf} analyze error: {e}")

    if not tf_sigs:
        return None

    agreed = sum(1 for t in tf_sigs if t.agrees)
    raw_score = sum(t.score for t in tf_sigs)
    max_score = len(tf_sigs) * 5.0
    # Normalise to 0-10 scale
    normalised = round((raw_score / max_score) * 10, 1) if max_score > 0 else 0

    # FIX: filter on normalised score, not raw total_ind
    if normalised < MIN_SIGNAL_SCORE:
        return None
    if agreed < max(1, len(tf_sigs) // 2):
        return None

    conf_pct = agreed / len(tf_sigs)
    if conf_pct >= 0.8:
        confidence = "VERY HIGH ⭐⭐⭐"
    elif conf_pct >= 0.6:
        confidence = "HIGH ⭐⭐"
    elif conf_pct >= 0.4:
        confidence = "MEDIUM ⭐"
    else:
        confidence = "LOW"

    # Use 1h as reference TF for entry/SL/TP; fall back to first
    main_tf = next((t for t in tf_sigs if t.tf == "1h"), tf_sigs[0])
    risk_usd = round(account_balance * RISK_PERCENT / 100, 2)

    return Signal(
        pair=pair,
        direction=o_dir,
        entry=main_tf.entry,
        stop_loss=main_tf.stop_loss,
        take_profit=main_tf.take_profit,
        sl_pips=main_tf.sl_pips,
        tp_pips=main_tf.tp_pips,
        lot_size=main_tf.lot_size,
        score=normalised,
        confidence=confidence,
        tfs_agreed=agreed,
        total_tfs=len(tf_sigs),
        tf_signals=tf_sigs,
        asset_type="CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount=risk_usd,
    )


def scan_all_pairs(data_map: dict, account_balance: float, crypto_only: bool = False) -> list:
    signals = []
    for pair, tfs in data_map.items():
        if crypto_only and not is_crypto(pair):
            continue
        try:
            sig = analyze_pair(pair, tfs, account_balance)
            if sig:
                signals.append(sig)
        except Exception as e:
            logger.warning(f"{pair} scan error: {e}")
    signals.sort(key=lambda s: s.score, reverse=True)
    return signals


def force_analyze_pair(pair: str, tf_data: dict, account_balance: float):
    """Force a signal even with low score (used for crypto always-on signals)."""
    try:
        processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicator error: {e}")
        return None

    o_dir = overall_direction(processed)
    tf_sigs = []
    for tf, df in processed.items():
        try:
            tf_sigs.append(analyze_tf(df, pair, tf, account_balance, o_dir))
        except Exception as e:
            logger.warning(f"{pair} {tf} error: {e}")

    if not tf_sigs:
        return None

    agreed = sum(1 for t in tf_sigs if t.agrees)
    raw_score = sum(t.score for t in tf_sigs)
    max_score = len(tf_sigs) * 5.0
    normalised = round((raw_score / max_score) * 10, 1) if max_score > 0 else 0
    conf_pct = agreed / len(tf_sigs)

    if conf_pct >= 0.8:
        confidence = "VERY HIGH ⭐⭐⭐"
    elif conf_pct >= 0.6:
        confidence = "HIGH ⭐⭐"
    elif conf_pct >= 0.4:
        confidence = "MEDIUM ⭐"
    else:
        confidence = "LOW"

    main_tf = next((t for t in tf_sigs if t.tf == "1h"), tf_sigs[0])
    risk_usd = round(account_balance * RISK_PERCENT / 100, 2)

    return Signal(
        pair=pair,
        direction=o_dir,
        entry=main_tf.entry,
        stop_loss=main_tf.stop_loss,
        take_profit=main_tf.take_profit,
        sl_pips=main_tf.sl_pips,
        tp_pips=main_tf.tp_pips,
        lot_size=main_tf.lot_size,
        score=normalised,
        confidence=confidence,
        tfs_agreed=agreed,
        total_tfs=len(tf_sigs),
        tf_signals=tf_sigs,
        asset_type="CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount=risk_usd,
    )
