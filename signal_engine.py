# signal_engine.py
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
    take_profit: float       # main TP (TP2)
    tp1: float               # partial exit — 1:1 RR
    tp2: float               # main target — 1:2 RR
    tp3: float               # extended target — 1:3 RR
    invalidation: float      # structural invalidation beyond SL
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
    tp1: float = 0.0         # partial TP
    tp2: float = 0.0         # main TP
    tp3: float = 0.0         # extended TP
    stop_loss: float = 0.0
    invalidation: float = 0.0
    asset_type: str = "FOREX"
    risk_amount: float = 0.0
    sr_warning: str = ""


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
    """Sweet spot RSI scoring."""
    if direction == "BUY":
        if 40 <= rsi <= 65:  return  1.0
        if 65 < rsi <= 75:   return  0.3
        if rsi > 75:         return -0.5
        if 25 <= rsi < 40:   return  0.3
        if rsi < 25:         return -0.3
    else:
        if 35 <= rsi <= 60:  return  1.0
        if 25 <= rsi < 35:   return  0.3
        if rsi < 25:         return -0.5
        if 60 < rsi <= 75:   return  0.3
        if rsi > 75:         return -0.3
    return 0.0


def daily_trend(processed: dict):
    """Return BUY, SELL, or None from the 1day timeframe."""
    df = processed.get("1day")
    if df is None or len(df) < 2:
        return None
    row = df.iloc[-1]
    pts = sum([
        row["ema9"]  > row["ema21"],
        row["ema21"] > row["ema50"],
        row["macd"]  > row["macd_signal"],
        row["plus_di"] > row["minus_di"],
        row["rsi"] > 50,
    ])
    return "BUY" if pts >= 3 else "SELL"


def check_sr_proximity(entry: float, direction: str,
                        df: pd.DataFrame, threshold: float = 0.003) -> str:
    support, resistance = support_resistance(df)
    if direction == "BUY":
        if (resistance - entry) / entry < threshold:
            return f"⚠️ Near resistance ({resistance:.5f})"
    else:
        if (entry - support) / entry < threshold:
            return f"⚠️ Near support ({support:.5f})"
    return ""


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


def compute_tps(direction: str, entry: float, sl: float, pair: str, dec: int):
    """
    Compute TP1 (1:1), TP2 (1:2), TP3 (1:3) and invalidation from entry/SL.
    Invalidation is SL extended by 50% — the structural bail-out level.
    """
    sl_dist = abs(entry - sl)

    if direction == "BUY":
        tp1          = round(entry + sl_dist * 1.0, dec)
        tp2          = round(entry + sl_dist * 2.0, dec)
        tp3          = round(entry + sl_dist * 3.0, dec)
        invalidation = round(sl - sl_dist * 0.5,   dec)
    else:
        tp1          = round(entry - sl_dist * 1.0, dec)
        tp2          = round(entry - sl_dist * 2.0, dec)
        tp3          = round(entry - sl_dist * 3.0, dec)
        invalidation = round(sl + sl_dist * 0.5,   dec)

    return tp1, tp2, tp3, invalidation


def analyze_tf(df: pd.DataFrame, pair: str, tf: str,
               balance: float, overall_dir: str) -> TFSignal:
    row   = df.iloc[-1]
    close = row["close"]

    confirmed = []
    buy_pts   = 0

    # 1. EMA
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

    # 3. RSI sweet spot
    rsi             = row["rsi"]
    direction_guess = "BUY" if buy_pts > 0 else "SELL"
    rsi_pts         = rsi_score(rsi, direction_guess)
    buy_pts        += rsi_pts
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

    atr    = row["atr"]
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
    dec  = 2 if is_crypto(pair) and close > 10 else 5

    tp1, tp2, tp3, invalidation = compute_tps(direction, close, sl, pair, dec)

    return TFSignal(
        tf=tf, direction=direction,
        entry=round(close, dec),
        stop_loss=round(sl, dec),
        take_profit=tp2,
        tp1=tp1, tp2=tp2, tp3=tp3,
        invalidation=invalidation,
        sl_pips=sl_p, tp_pips=tp_p, lot_size=lot,
        indicators=ind_score, confirmed=confirmed,
        rsi=round(rsi, 2), stoch=round(k, 2),
        macd=round(row["macd"], 6),
        agrees=direction == overall_dir,
    )


async def analyze_pair(pair: str, tf_data: dict, account_balance: float):
    from news_filter import check_news_block

    try:
        processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicator error: {e}")
        return None

    no_trade_reasons = []

    # Gate 1 — News
    news_blocked, news_reason = await check_news_block(pair)
    if news_blocked:
        no_trade_reasons.append(news_reason)

    # Gate 2 — Daily trend
    d_trend = daily_trend(processed)
    o_dir   = overall_direction(tf_data, processed)
    if d_trend is not None and d_trend != o_dir:
        no_trade_reasons.append(
            f"📉 Daily trend {d_trend} conflicts with signal {o_dir}"
        )

    tf_sigs   = []
    total_ind = 0
    for tf, df in processed.items():
        tfs = analyze_tf(df, pair, tf, account_balance, o_dir)
        tf_sigs.append(tfs)
        total_ind += tfs.indicators

    agreed = sum(1 for t in tf_sigs if t.agrees)
    score  = total_ind

    # Gate 3 — Score
    if score < 6:
        no_trade_reasons.append(f"📊 Score too low ({score}/25)")

    # Gate 4 — MTF alignment
    if agreed < 2:
        no_trade_reasons.append(f"🔀 MTF alignment weak ({agreed}/{len(tf_sigs)} TFs)")

    # Gate 5 — S/R proximity
    main_tf    = next((t for t in tf_sigs if t.tf == "1h"), tf_sigs[0])
    sr_ref_df  = processed.get("1h") or processed.get("4h") or list(processed.values())[-1]
    sr_warning = check_sr_proximity(main_tf.entry, o_dir, sr_ref_df)
    if sr_warning:
        score = max(0, score - 3)
        if score < 6:
            no_trade_reasons.append(f"🧱 Too close to structure — {sr_warning}")

    if no_trade_reasons:
        return {
            "no_trade":   True,
            "pair":       pair,
            "direction":  o_dir,
            "reasons":    no_trade_reasons,
            "conviction": round((agreed / len(tf_sigs)) * 100),
        }

    conf_pct = agreed / len(tf_sigs)
    if conf_pct >= 0.8:   confidence = "VERY HIGH"
    elif conf_pct >= 0.6: confidence = "HIGH"
    elif conf_pct >= 0.4: confidence = "MEDIUM"
    else:                 confidence = "LOW"

    risk_usd = round(account_balance * RISK_PERCENT / 100, 2)
    dec      = 2 if is_crypto(pair) and main_tf.entry > 10 else 5

    return Signal(
        pair=pair, direction=o_dir,
        entry=main_tf.entry, score=score,
        confidence=confidence,
        tfs_agreed=agreed, total_tfs=len(tf_sigs),
        tf_signals=tf_sigs,
        tp1=main_tf.tp1,
        tp2=main_tf.tp2,
        tp3=main_tf.tp3,
        stop_loss=main_tf.stop_loss,
        invalidation=main_tf.invalidation,
        asset_type="CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount=risk_usd,
        sr_warning=sr_warning,
    )


async def scan_all_pairs(data_map: dict, account_balance: float,
                          crypto_only: bool = False) -> list:
    signals = []
    for pair, tfs in data_map.items():
        if crypto_only and not is_crypto(pair): continue
        try:
            result = await analyze_pair(pair, tfs, account_balance)
            if result and not isinstance(result, dict):
                signals.append(result)
        except Exception as e:
            logger.warning(f"{pair} error: {e}")
    signals.sort(key=lambda s: s.score, reverse=True)
    return signals


async def force_analyze_pair(pair: str, tf_data: dict, account_balance: float):
    """Forces a signal for crypto — skips all gates."""
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

    if conf_pct >= 0.8:   confidence = "VERY HIGH"
    elif conf_pct >= 0.6: confidence = "HIGH"
    elif conf_pct >= 0.4: confidence = "MEDIUM"
    else:                 confidence = "LOW"

    main_tf  = next((t for t in tf_sigs if t.tf == "1h"), tf_sigs[0])
    risk_usd = round(account_balance * RISK_PERCENT / 100, 2)

    return Signal(
        pair=pair, direction=o_dir,
        entry=main_tf.entry, score=score,
        confidence=confidence,
        tfs_agreed=agreed, total_tfs=len(tf_sigs),
        tf_signals=tf_sigs,
        tp1=main_tf.tp1,
        tp2=main_tf.tp2,
        tp3=main_tf.tp3,
        stop_loss=main_tf.stop_loss,
        invalidation=main_tf.invalidation,
        asset_type="CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount=risk_usd,
        sr_warning="",
    )