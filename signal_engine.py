import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from indicators import compute_indicators, support_resistance
from config import RISK_PERCENT, CRYPTO_PAIRS, DEFAULT_RR_RATIO

logger = logging.getLogger(__name__)

@dataclass
class TFSignal:
    tf: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    sl_pips: float
    tp_pips: float
    lot_size: float
    indicators: int
    confirmed: list
    rsi: float
    stoch: float
    macd: float
    agrees: bool

@dataclass
class Signal:
    pair: str
    direction: str
    entry: float
    score: int
    confidence: str
    tfs_agreed: int
    total_tfs: int
    tf_signals: list
    asset_type: str = "FOREX"
    risk_amount: float = 0.0
    sr_warning: str = ""  # NEW: shows if entry is near S/R

def is_crypto(pair: str) -> bool:
    return pair in CRYPTO_PAIRS

def pip_size(pair: str) -> float:
    if is_crypto(pair): return 1.0
    return 0.01 if "JPY" in pair else 0.0001

def pips(pair: str, a: float, b: float) -> float:
    return round(abs(a - b) / pip_size(pair), 1)

def lot_size(pair: str, sl_pips: float, balance: float) -> float:
    risk = balance * RISK_PERCENT / 100
    if is_crypto(pair):
        return round(risk / max(sl_pips, 1), 4)
    pv = 10 if "JPY" not in pair else 9.09
    return max(0.01, round(risk / (sl_pips * pv), 2))

def rsi_score(rsi: float, direction: str) -> float:
    """
    RSI sweet spot scoring — rewards entries in healthy momentum zone,
    penalises overextended/exhausted readings.
    BUY sweet spot: 40–65 (momentum building, not exhausted)
    SELL sweet spot: 35–60
    """
    if direction == "BUY":
        if 40 <= rsi <= 65:   return 1.0   # sweet spot
        if 65 < rsi <= 75:    return 0.3   # getting stretched
        if rsi > 75:          return -0.5  # overbought exhaustion
        if 25 <= rsi < 40:    return 0.3   # oversold but may not bounce yet
        if rsi < 25:          return -0.3  # deeply oversold, snap risk
        return 0.0
    else:  # SELL
        if 35 <= rsi <= 60:   return 1.0
        if 25 <= rsi < 35:    return 0.3
        if rsi < 25:          return -0.5  # oversold exhaustion
        if 60 < rsi <= 75:    return 0.3
        if rsi > 75:          return -0.3
        return 0.0

def daily_trend(processed: dict) -> str | None:
    """
    Extract the 1day timeframe direction as the trend gate.
    Returns 'BUY', 'SELL', or None if no daily data available.
    """
    df = processed.get("1day")
    if df is None or len(df) < 2:
        return None
    row = df.iloc[-1]
    pts = sum([
        row["ema9"] > row["ema21"],
        row["ema21"] > row["ema50"],
        row["macd"] > row["macd_signal"],
        row["plus_di"] > row["minus_di"],
        row["rsi"] > 50,
    ])
    return "BUY" if pts >= 3 else "SELL"

def check_sr_proximity(entry: float, direction: str, df: pd.DataFrame, threshold: float = 0.003) -> str:
    """
    Check if entry is dangerously close to a recent swing high (for BUY)
    or swing low (for SELL). threshold = 0.3% of price by default.
    Returns a warning string, or empty string if clear.
    """
    support, resistance = support_resistance(df)
    if direction == "BUY":
        distance = (resistance - entry) / entry
        if distance < threshold:
            return f"⚠️ Near resistance ({resistance:.5f})"
    else:
        distance = (entry - support) / entry
        if distance < threshold:
            return f"⚠️ Near support ({support:.5f})"
    return ""

def analyze_tf(df: pd.DataFrame, pair: str, tf: str, balance: float, overall_dir: str) -> TFSignal:
    row = df.iloc[-1]
    close = row["close"]
    ps = pip_size(pair)

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

    # 3. RSI — sweet spot scoring (CHANGED)
    rsi = row["rsi"]
    direction_guess = "BUY" if buy_pts > 0 else "SELL"
    rsi_pts = rsi_score(rsi, direction_guess)
    buy_pts += rsi_pts
    if rsi_pts > 0: confirmed.append("RSI")

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
    lot = lot_size(pair, max(sl_p, 0.1), balance)
    dec = 2 if is_crypto(pair) and close > 10 else 5

    return TFSignal(
        tf=tf, direction=direction,
        entry=round(close, dec),
        stop_loss=round(sl, dec),
        take_profit=round(tp, dec),
        sl_pips=sl_p, tp_pips=tp_p, lot_size=lot,
        indicators=ind_score, confirmed=confirmed,
        rsi=round(rsi, 2), stoch=round(k, 2),
        macd=round(row["macd"], 6),
        agrees=direction == overall_dir,
    )

def overall_direction(tf_data: dict, processed: dict) -> str:
    buy = 0
    for tf, df in processed.items():
        row = df.iloc[-1]
        pts = sum([
            row["ema9"] > row["ema21"],
            row["macd"] > row["macd_signal"],
            row["rsi"] < 50,
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

    # ── GATE 1: Daily trend must agree ──────────────────────────────
    d_trend = daily_trend(processed)
    o_dir = overall_direction(tf_data, processed)
    if d_trend is not None and d_trend != o_dir:
        logger.debug(f"{pair} blocked — daily trend {d_trend} vs signal {o_dir}")
        return None

    tf_sigs = []
    total_ind = 0
    for tf, df in processed.items():
        tfs = analyze_tf(df, pair, tf, account_balance, o_dir)
        tf_sigs.append(tfs)
        total_ind += tfs.indicators

    agreed = sum(1 for t in tf_sigs if t.agrees)
    score = total_ind

    if score < 6:
        return None
    if agreed < 2:
        return None

    conf_pct = agreed / len(tf_sigs)
    if conf_pct >= 0.8:   confidence = "VERY HIGH"
    elif conf_pct >= 0.6: confidence = "HIGH"
    elif conf_pct >= 0.4: confidence = "MEDIUM"
    else:                 confidence = "LOW"

    main_tf = next((t for t in tf_sigs if t.tf == "1h"), tf_sigs[0])
    risk_usd = round(account_balance * RISK_PERCENT / 100, 2)

    # ── GATE 2: S/R proximity check ─────────────────────────────────
    sr_ref_df = processed.get("1h") or processed.get("4h") or list(processed.values())[-1]
    sr_warning = check_sr_proximity(main_tf.entry, o_dir, sr_ref_df)

    # Downgrade score if too close to S/R (not a hard block, but penalises)
    if sr_warning:
        score = max(0, score - 3)
        if score < 6:
            logger.debug(f"{pair} dropped below threshold after S/R penalty")
            return None

    return Signal(
        pair=pair, direction=o_dir,
        entry=main_tf.entry, score=score,
        confidence=confidence,
        tfs_agreed=agreed, total_tfs=len(tf_sigs),
        tf_signals=tf_sigs,
        asset_type="CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount=risk_usd,
        sr_warning=sr_warning,
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
    """Force a signal for crypto even with low score — skips daily gate."""
    try:
        processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicator error: {e}")
        return None

    o_dir = overall_direction(tf_data, processed)
    tf_sigs = []
    total_ind = 0
    for tf, df in processed.items():
        tfs = analyze_tf(df, pair, tf, account_balance, o_dir)
        tf_sigs.append(tfs)
        total_ind += tfs.indicators

    agreed = sum(1 for t in tf_sigs if t.agrees)
    score = total_ind
    conf_pct = agreed / len(tf_sigs)
    if conf_pct >= 0.8:   confidence = "VERY HIGH"
    elif conf_pct >= 0.6: confidence = "HIGH"
    elif conf_pct >= 0.4: confidence = "MEDIUM"
    else:                 confidence = "LOW"

    main_tf = next((t for t in tf_sigs if t.tf == "1h"), tf_sigs[0])
    risk_usd = round(account_balance * RISK_PERCENT / 100, 2)

    return Signal(
        pair=pair, direction=o_dir,
        entry=main_tf.entry, score=score,
        confidence=confidence,
        tfs_agreed=agreed, total_tfs=len(tf_sigs),
        tf_signals=tf_sigs,
        asset_type="CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount=risk_usd,
        sr_warning="",
    )