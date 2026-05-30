import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from indicators import compute_indicators, support_resistance
from config import (
    RSI_OVERSOLD, RSI_OVERBOUGHT, VOLUME_MULTIPLIER,
    MIN_SL_PIPS, MAX_SL_PIPS, DEFAULT_RR_RATIO,
    RISK_PERCENT, MIN_SIGNAL_SCORE,
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
    risk_amount: float        # USD at risk
    reasons:     list[str] = field(default_factory=list)
    timeframes:  list[str] = field(default_factory=list)
    confidence:  str = ""


def pip_size(pair: str) -> float:
    return 0.01 if "JPY" in pair else 0.0001


def pips_between(pair: str, a: float, b: float) -> float:
    return abs(a - b) / pip_size(pair)


def calculate_lot_size(pair: str, sl_pips: float, account_balance: float) -> tuple[float, float]:
    """Returns (lot_size, risk_amount_usd)."""
    risk_amount = account_balance * RISK_PERCENT / 100
    pip_val     = 10 if "JPY" not in pair else 9.09
    if sl_pips <= 0:
        return 0.01, risk_amount
    lot = risk_amount / (sl_pips * pip_val)
    lot = max(0.01, round(lot, 2))
    lot = min(lot, 100.0)
    return lot, round(risk_amount, 2)


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
    score   = 0
    reasons = []
    row     = df.iloc[-1]
    is_buy  = direction == "BUY"

    # 1. EMA alignment
    ema_bull = row["ema9"] > row["ema21"] > row["ema50"]
    ema_bear = row["ema9"] < row["ema21"] < row["ema50"]
    if (is_buy and ema_bull) or (not is_buy and ema_bear):
        score += 2; reasons.append("✅ EMA fully aligned")
    elif (is_buy and row["ema9"] > row["ema21"]) or (not is_buy and row["ema9"] < row["ema21"]):
        score += 1; reasons.append("⚠️ Partial EMA alignment")

    # 2. MACD
    macd_bull = row["macd"] > row["macd_signal"] and row["macd_hist"] > 0
    macd_bear = row["macd"] < row["macd_signal"] and row["macd_hist"] < 0
    if (is_buy and macd_bull) or (not is_buy and macd_bear):
        score += 2; reasons.append("✅ MACD confirms direction")
    elif (is_buy and row["macd_hist"] > 0) or (not is_buy and row["macd_hist"] < 0):
        score += 1; reasons.append("⚠️ MACD histogram only")

    # 3. RSI
    rsi = row["rsi"]
    if is_buy and RSI_OVERSOLD < rsi < 60:
        score += 1; reasons.append(f"✅ RSI {rsi:.1f} bullish zone")
    elif not is_buy and 40 < rsi < RSI_OVERBOUGHT:
        score += 1; reasons.append(f"✅ RSI {rsi:.1f} bearish zone")
    elif is_buy and rsi <= RSI_OVERSOLD:
        score += 1; reasons.append(f"⚠️ RSI oversold {rsi:.1f}")
    elif not is_buy and rsi >= RSI_OVERBOUGHT:
        score += 1; reasons.append(f"⚠️ RSI overbought {rsi:.1f}")

    # 4. Stochastic
    k, d = row["stoch_k"], row["stoch_d"]
    if (is_buy and k > d and k < 80) or (not is_buy and k < d and k > 20):
        score += 1; reasons.append(f"✅ Stochastic confirms ({k:.1f}/{d:.1f})")

    # 5. Bollinger Bands
    close = row["close"]
    if (is_buy and close < row["bb_mid"]) or (not is_buy and close > row["bb_mid"]):
        score += 1; reasons.append("✅ Price has BB room")

    # 6. ADX
    if row["adx"] > 25:
        score += 1; reasons.append(f"✅ ADX {row['adx']:.1f} strong trend")

    # 7. Volume
    if row["vol_ratio"] >= VOLUME_MULTIPLIER:
        score += 1; reasons.append(f"✅ Volume spike {row['vol_ratio']:.1f}×")

    return min(score, 10), reasons


def analyze_pair(pair: str, tf_data: dict, account_balance: float) -> "Signal | None":
    processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}

    # All TFs must agree on direction
    directions = {}
    for tf, df in processed.items():
        d = determine_direction(df)
        if d is None: return None
        directions[tf] = d
    if len(set(directions.values())) != 1: return None

    direction = list(directions.values())[0]

    # Score all TFs
    total, all_reasons, tfs = 0, [], []
    for tf, df in processed.items():
        s, r = score_timeframe(df, direction)
        total += s
        all_reasons += [f"[{tf}] {x}" for x in r]
        tfs.append(tf)

    avg = total / len(processed)
    if avg < MIN_SIGNAL_SCORE: return None

    # SL / TP on 1h
    sig_df  = processed.get("1h") or list(processed.values())[1]
    row     = sig_df.iloc[-1]
    entry   = row["close"]
    atr_val = row["atr"]
    ps      = pip_size(pair)
    support, resistance = support_resistance(sig_df)

    if direction == "BUY":
        sl_raw  = max(entry - 1.5 * atr_val, support - 5 * ps)
        sl_pips = pips_between(pair, entry, sl_raw)
        if sl_pips < MIN_SL_PIPS: sl_pips = MIN_SL_PIPS; sl_raw = entry - sl_pips * ps
        if sl_pips > MAX_SL_PIPS: return None
        tp_pips = sl_pips * DEFAULT_RR_RATIO
        tp_raw  = entry + tp_pips * ps
    else:
        sl_raw  = min(entry + 1.5 * atr_val, resistance + 5 * ps)
        sl_pips = pips_between(pair, entry, sl_raw)
        if sl_pips < MIN_SL_PIPS: sl_pips = MIN_SL_PIPS; sl_raw = entry + sl_pips * ps
        if sl_pips > MAX_SL_PIPS: return None
        tp_pips = sl_pips * DEFAULT_RR_RATIO
        tp_raw  = entry - tp_pips * ps

    lot, risk_usd = calculate_lot_size(pair, sl_pips, account_balance)
    confidence    = "HIGH" if avg >= 8 else "MEDIUM" if avg >= 6 else "LOW"

    return Signal(
        pair        = pair,
        direction   = direction,
        entry       = round(entry, 5),
        stop_loss   = round(sl_raw, 5),
        take_profit = round(tp_raw, 5),
        lot_size    = lot,
        sl_pips     = round(sl_pips, 1),
        tp_pips     = round(tp_pips, 1),
        rr_ratio    = round(tp_pips / sl_pips, 2),
        score       = round(avg, 1),
        risk_amount = risk_usd,
        reasons     = all_reasons,
        timeframes  = tfs,
        confidence  = confidence,
    )


def scan_all_pairs(data_map: dict, account_balance: float) -> list:
    signals = []
    for pair, tfs in data_map.items():
        sig = analyze_pair(pair, tfs, account_balance)
        if sig: signals.append(sig)
    signals.sort(key=lambda s: s.score, reverse=True)
    return signals
