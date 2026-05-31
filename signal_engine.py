import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from indicators import compute_indicators, support_resistance
from config import (
    RSI_OVERSOLD, RSI_OVERBOUGHT, VOLUME_MULTIPLIER,
    MIN_SL_PIPS, MAX_SL_PIPS, DEFAULT_RR_RATIO,
    RISK_PERCENT, MIN_SIGNAL_SCORE, CRYPTO_PAIRS,
)

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    pair:        str
    direction:   str
    entry:       float
    stop_loss:   float
    take_profit: float
    lot_size:    float
    sl_pips:     float
    tp_pips:     float
    rr_ratio:    float
    score:       float
    risk_amount: float
    asset_type:  str = "FOREX"   # FOREX or CRYPTO
    reasons:     list[str] = field(default_factory=list)
    timeframes:  list[str] = field(default_factory=list)
    confidence:  str = ""


def is_crypto(pair: str) -> bool:
    return pair in CRYPTO_PAIRS


def pip_size(pair: str) -> float:
    if is_crypto(pair):
        # For crypto, 1 "pip" = $1 move (we use dollar-based SL/TP)
        return 1.0
    return 0.01 if "JPY" in pair else 0.0001


def pips_between(pair: str, a: float, b: float) -> float:
    return abs(a - b) / pip_size(pair)


def calculate_lot_size(pair: str, sl_pips: float, account_balance: float) -> tuple[float, float]:
    risk_amount = account_balance * RISK_PERCENT / 100
    if is_crypto(pair):
        # For crypto: lot = risk / sl_in_dollars (sl_pips = dollar move)
        lot = risk_amount / max(sl_pips, 1)
        lot = round(lot, 4)
        lot = max(0.0001, min(lot, 10.0))
    else:
        pip_val = 10 if "JPY" not in pair else 9.09
        lot = risk_amount / (sl_pips * pip_val)
        lot = max(0.01, round(lot, 2))
        lot = min(lot, 100.0)
    return lot, round(risk_amount, 2)


def get_sl_tp_limits(pair: str) -> tuple[float, float]:
    """Return (min_sl, max_sl) appropriate for the asset."""
    if is_crypto(pair):
        entry_approx = {
            "BTC/USD": 60000, "ETH/USD": 3000, "BNB/USD": 400,
            "SOL/USD": 150,   "XRP/USD": 0.5,  "ADA/USD": 0.4,
            "AVAX/USD": 35,   "DOGE/USD": 0.15,"MATIC/USD": 0.8,
            "DOT/USD": 7,     "LTC/USD": 80,   "LINK/USD": 15,
        }.get(pair, 100)
        min_sl = entry_approx * 0.005   # 0.5% minimum
        max_sl = entry_approx * 0.05    # 5% maximum
        return min_sl, max_sl
    return MIN_SL_PIPS, MAX_SL_PIPS


def determine_direction(df: pd.DataFrame) -> str | None:
    row = df.iloc[-1]
    bull = sum([
        row["ema9"]    > row["ema21"],
        row["macd"]    > row["macd_signal"],
        row["rsi"]     < 55,
        row["stoch_k"] > row["stoch_d"],
        row["plus_di"] > row["minus_di"],
    ])
    if bull >= 4: return "BUY"
    if bull <= 1: return "SELL"
    return None


def score_timeframe(df: pd.DataFrame, direction: str) -> tuple[float, list[str]]:
    score, reasons = 0, []
    row    = df.iloc[-1]
    is_buy = direction == "BUY"

    ema_bull = row["ema9"] > row["ema21"] > row["ema50"]
    ema_bear = row["ema9"] < row["ema21"] < row["ema50"]
    if (is_buy and ema_bull) or (not is_buy and ema_bear):
        score += 2; reasons.append("✅ EMA fully aligned")
    elif (is_buy and row["ema9"] > row["ema21"]) or (not is_buy and row["ema9"] < row["ema21"]):
        score += 1; reasons.append("⚠️ Partial EMA alignment")

    macd_bull = row["macd"] > row["macd_signal"] and row["macd_hist"] > 0
    macd_bear = row["macd"] < row["macd_signal"] and row["macd_hist"] < 0
    if (is_buy and macd_bull) or (not is_buy and macd_bear):
        score += 2; reasons.append("✅ MACD confirms direction")
    elif (is_buy and row["macd_hist"] > 0) or (not is_buy and row["macd_hist"] < 0):
        score += 1; reasons.append("⚠️ MACD histogram only")

    rsi = row["rsi"]
    if is_buy and RSI_OVERSOLD < rsi < 60:
        score += 1; reasons.append(f"✅ RSI {rsi:.1f} bullish zone")
    elif not is_buy and 40 < rsi < RSI_OVERBOUGHT:
        score += 1; reasons.append(f"✅ RSI {rsi:.1f} bearish zone")
    elif is_buy and rsi <= RSI_OVERSOLD:
        score += 1; reasons.append(f"⚠️ RSI oversold {rsi:.1f}")
    elif not is_buy and rsi >= RSI_OVERBOUGHT:
        score += 1; reasons.append(f"⚠️ RSI overbought {rsi:.1f}")

    k, d = row["stoch_k"], row["stoch_d"]
    if (is_buy and k > d and k < 80) or (not is_buy and k < d and k > 20):
        score += 1; reasons.append(f"✅ Stochastic confirms ({k:.1f}/{d:.1f})")

    close = row["close"]
    if (is_buy and close < row["bb_mid"]) or (not is_buy and close > row["bb_mid"]):
        score += 1; reasons.append("✅ Price has BB room")

    if row["adx"] > 25:
        score += 1; reasons.append(f"✅ ADX {row['adx']:.1f} strong trend")

    if row["vol_ratio"] >= VOLUME_MULTIPLIER:
        score += 1; reasons.append(f"✅ Volume spike {row['vol_ratio']:.1f}×")

    return min(score, 10), reasons


def analyze_pair(pair: str, tf_data: dict, account_balance: float) -> "Signal | None":
    processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}

    directions = {}
    for tf, df in processed.items():
        d = determine_direction(df)
        if d is None: return None
        directions[tf] = d
    if len(set(directions.values())) != 1: return None

    direction = list(directions.values())[0]

    total, all_reasons, tfs = 0, [], []
    for tf, df in processed.items():
        s, r = score_timeframe(df, direction)
        total += s
        all_reasons += [f"[{tf}] {x}" for x in r]
        tfs.append(tf)

    avg = total / len(processed)
    if avg < MIN_SIGNAL_SCORE: return None

    sig_df  = processed.get("1h") or list(processed.values())[1]
    row     = sig_df.iloc[-1]
    entry   = row["close"]
    atr_val = row["atr"]
    ps      = pip_size(pair)
    support, resistance = support_resistance(sig_df)
    min_sl, max_sl = get_sl_tp_limits(pair)

    if direction == "BUY":
        sl_raw  = max(entry - 1.5 * atr_val, support - 5 * ps)
        sl_dist = pips_between(pair, entry, sl_raw)
        if sl_dist < min_sl: sl_dist = min_sl; sl_raw = entry - sl_dist * ps
        if sl_dist > max_sl: return None
        tp_dist = sl_dist * DEFAULT_RR_RATIO
        tp_raw  = entry + tp_dist * ps
    else:
        sl_raw  = min(entry + 1.5 * atr_val, resistance + 5 * ps)
        sl_dist = pips_between(pair, entry, sl_raw)
        if sl_dist < min_sl: sl_dist = min_sl; sl_raw = entry + sl_dist * ps
        if sl_dist > max_sl: return None
        tp_dist = sl_dist * DEFAULT_RR_RATIO
        tp_raw  = entry - tp_dist * ps

    lot, risk_usd = calculate_lot_size(pair, sl_dist, account_balance)
    confidence    = "HIGH" if avg >= 8 else "MEDIUM" if avg >= 6 else "LOW"
    asset_type    = "CRYPTO" if is_crypto(pair) else "FOREX"

    # Format prices nicely for crypto
    decimals = 2 if is_crypto(pair) and entry > 10 else 5
    return Signal(
        pair        = pair,
        direction   = direction,
        entry       = round(entry, decimals),
        stop_loss   = round(sl_raw, decimals),
        take_profit = round(tp_raw, decimals),
        lot_size    = lot,
        sl_pips     = round(sl_dist, 1),
        tp_pips     = round(tp_dist, 1),
        rr_ratio    = round(tp_dist / sl_dist, 2),
        score       = round(avg, 1),
        risk_amount = risk_usd,
        asset_type  = asset_type,
        reasons     = all_reasons,
        timeframes  = tfs,
        confidence  = confidence,
    )


def scan_all_pairs(data_map: dict, account_balance: float, crypto_only: bool = False) -> list:
    signals = []
    for pair, tfs in data_map.items():
        if crypto_only and not is_crypto(pair):
            continue
        sig = analyze_pair(pair, tfs, account_balance)
        if sig: signals.append(sig)
    signals.sort(key=lambda s: s.score, reverse=True)
    return signals
