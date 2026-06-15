import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from indicators import compute_indicators
from config import RISK_PERCENT, CRYPTO_PAIRS, DEFAULT_RR_RATIO

logger = logging.getLogger(__name__)

@dataclass
class TFSignal:
    tf: str
    direction: str  # BUY / SELL
    entry: float
    stop_loss: float
    take_profit: float
    sl_pips: float
    tp_pips: float
    lot_size: float
    indicators: int  # how many confirmed
    confirmed: list  # names of confirmed indicators
    rsi: float
    stoch: float
    macd: float
    adx: float
    agrees: bool  # agrees with overall direction

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


def analyze_tf(df: pd.DataFrame, pair: str, tf: str, balance: float, overall_dir: str) -> TFSignal:
    row = df.iloc[-1]
    prev = df.iloc[-2]  # previous candle for confirmation
    close = row["close"]
    ps = pip_size(pair)

    confirmed = []
    buy_pts = 0.0

    # ── 1. EMA TREND (weighted: higher EMAs = stronger trend) ──────────────
    # All 4 EMAs aligned = strong trend
    if row["ema9"] > row["ema21"] > row["ema50"] > row["ema200"]:
        buy_pts += 2.0
        confirmed.append("EMA Stack ✅")
    elif row["ema9"] > row["ema21"] > row["ema50"]:
        buy_pts += 1.5
        confirmed.append("EMA Trend")
    elif row["ema9"] > row["ema21"]:
        buy_pts += 0.5
    elif row["ema9"] < row["ema21"] < row["ema50"] < row["ema200"]:
        buy_pts -= 2.0
    elif row["ema9"] < row["ema21"] < row["ema50"]:
        buy_pts -= 1.5
    elif row["ema9"] < row["ema21"]:
        buy_pts -= 0.5

    # ── 2. EMA200 MACRO FILTER (price above/below = bias) ─────────────────
    if close > row["ema200"]:
        buy_pts += 0.5  # macro uptrend bias
        confirmed.append("Above EMA200")
    elif close < row["ema200"]:
        buy_pts -= 0.5

    # ── 3. MACD (line cross + histogram direction) ──────────────────────────
    macd_cross_up = row["macd"] > row["macd_signal"] and prev["macd"] <= prev["macd_signal"]
    macd_cross_dn = row["macd"] < row["macd_signal"] and prev["macd"] >= prev["macd_signal"]

    if macd_cross_up:
        buy_pts += 1.5  # fresh crossover = strong signal
        confirmed.append("MACD Cross ✅")
    elif row["macd"] > row["macd_signal"] and row["macd_hist"] > 0:
        buy_pts += 1.0
        confirmed.append("MACD Bullish")
    elif macd_cross_dn:
        buy_pts -= 1.5
    elif row["macd"] < row["macd_signal"] and row["macd_hist"] < 0:
        buy_pts -= 1.0

    # ── 4. RSI (FIXED: proper overbought/oversold + momentum) ──────────────
    rsi = row["rsi"]
    rsi_prev = prev["rsi"]

    if rsi < 30:
        # Oversold — potential BUY reversal
        buy_pts += 1.5
        confirmed.append("RSI Oversold")
    elif rsi > 70:
        # Overbought — potential SELL reversal
        buy_pts -= 1.5
    elif 40 < rsi < 60:
        # Neutral zone — small directional bias
        if rsi > 50 and rsi > rsi_prev:
            buy_pts += 0.5
            confirmed.append("RSI Rising")
        elif rsi < 50 and rsi < rsi_prev:
            buy_pts -= 0.5
    elif 50 < rsi <= 70:
        # Bullish momentum zone
        buy_pts += 0.8
        confirmed.append("RSI Bullish")
    elif 30 <= rsi < 50:
        # Bearish momentum zone
        buy_pts -= 0.8

    # ── 5. STOCHASTIC (crossover is key, not just position) ─────────────────
    k = row["stoch_k"]
    d = row["stoch_d"]
    k_prev = prev["stoch_k"]
    d_prev = prev["stoch_d"]

    stoch_cross_up = k > d and k_prev <= d_prev
    stoch_cross_dn = k < d and k_prev >= d_prev

    if k < 20 and stoch_cross_up:
        buy_pts += 1.5  # oversold + fresh cross = strong BUY
        confirmed.append("Stoch Oversold Cross ✅")
    elif k > 80 and stoch_cross_dn:
        buy_pts -= 1.5  # overbought + fresh cross = strong SELL
    elif stoch_cross_up:
        buy_pts += 0.8
        confirmed.append("Stoch Cross")
    elif stoch_cross_dn:
        buy_pts -= 0.8
    elif k > d:
        buy_pts += 0.3
    else:
        buy_pts -= 0.3

    # ── 6. BOLLINGER BANDS (FIXED: proper logic) ────────────────────────────
    bb_upper = row["bb_upper"]
    bb_mid = row["bb_mid"]
    bb_lower = row["bb_lower"]

    if close <= bb_lower:
        buy_pts += 1.5  # price at lower band = potential BUY
        confirmed.append("BB Lower Bounce")
    elif close >= bb_upper:
        buy_pts -= 1.5  # price at upper band = potential SELL
    elif close > bb_mid:
        buy_pts += 0.5  # price above mid = bullish
        confirmed.append("BB Above Mid")
    else:
        buy_pts -= 0.3  # price below mid = slightly bearish

    # ── 7. ADX (NOW USED: trend strength filter) ────────────────────────────
    adx_val = row["adx"]
    plus_di = row["plus_di"]
    minus_di = row["minus_di"]

    if adx_val > 25:
        # Strong trend — DI direction is reliable
        if plus_di > minus_di:
            buy_pts += 1.5
            confirmed.append(f"ADX Strong Bull ({adx_val:.0f})")
        else:
            buy_pts -= 1.5
    elif adx_val > 20:
        if plus_di > minus_di:
            buy_pts += 0.8
            confirmed.append(f"ADX Bull ({adx_val:.0f})")
        else:
            buy_pts -= 0.8
    # ADX < 20 = ranging market, don't score — avoids choppy false signals

    # ── 8. VOLUME CONFIRMATION (NOW USED) ───────────────────────────────────
    vol_ratio = row.get("vol_ratio", 1.0)
    if pd.notna(vol_ratio):
        if vol_ratio >= 1.5:
            # Volume spike confirms the move
            buy_pts += 1.0 if buy_pts > 0 else -1.0
            confirmed.append(f"Vol Spike {vol_ratio:.1f}x")
        elif vol_ratio < 0.7:
            # Low volume = weak signal, reduce confidence
            buy_pts *= 0.8

    # ── 9. CANDLE CONFIRMATION (new) ────────────────────────────────────────
    candle_body = row["close"] - row["open"]
    candle_range = row["high"] - row["low"]
    if candle_range > 0:
        body_ratio = abs(candle_body) / candle_range
        if body_ratio > 0.6:  # strong candle (60%+ body)
            if candle_body > 0:
                buy_pts += 0.5
                confirmed.append("Strong Bull Candle")
            else:
                buy_pts -= 0.5

    # ── DETERMINE DIRECTION ──────────────────────────────────────────────────
    direction = "BUY" if buy_pts > 0 else "SELL"
    ind_score = min(len(confirmed), 8)  # max 8 confirmations now

    # ── SL/TP CALCULATION ───────────────────────────────────────────────────
    atr = row["atr"]
    min_sl = close * 0.003 if is_crypto(pair) else (0.0010 if "JPY" not in pair else 0.10)

    # Wider SL buffer (2x ATR) so normal noise/retracement doesn't clip it.
    # Recent swing high/low (last 10 candles) used as a structure-based floor/ceiling
    # for SL, since price often reverses right at these levels.
    lookback = df.iloc[-11:-1]  # last 10 candles excluding current
    swing_low = lookback["low"].min()
    swing_high = lookback["high"].max()

    sl_dist = max(2.0 * atr, min_sl)
    # Lower RR (1.5 instead of original) makes TP more achievable while
    # still keeping positive expectancy if win rate stays above ~40%.
    tp_rr = 1.5

    if direction == "BUY":
        # SL placed below recent swing low (with small buffer) OR 2xATR, whichever is further
        structure_sl = swing_low - (0.2 * atr)
        sl = min(close - sl_dist, structure_sl)
        sl_dist_final = close - sl
        tp = close + sl_dist_final * tp_rr
    else:
        structure_sl = swing_high + (0.2 * atr)
        sl = max(close + sl_dist, structure_sl)
        sl_dist_final = sl - close
        tp = close - sl_dist_final * tp_rr

    sl_p = pips(pair, close, sl)
    tp_p = pips(pair, close, tp)
    lot = lot_size(pair, max(sl_p, 0.1), balance)

    dec = 2 if is_crypto(pair) and close > 10 else 5

    return TFSignal(
        tf=tf,
        direction=direction,
        entry=round(close, dec),
        stop_loss=round(sl, dec),
        take_profit=round(tp, dec),
        sl_pips=sl_p,
        tp_pips=tp_p,
        lot_size=lot,
        indicators=ind_score,
        confirmed=confirmed,
        rsi=round(rsi, 2),
        stoch=round(k, 2),
        macd=round(row["macd"], 6),
        adx=round(adx_val, 1),
        agrees=direction == overall_dir,
    )


# ── CORRELATION GROUPS ───────────────────────────────────────────────────
# Pairs in the same group tend to move together (positively correlated).
# If two pairs in the same group both fire a signal in the SAME direction,
# only the highest-scoring one is kept — the rest are marked as filtered
# duplicates to avoid stacking correlated risk.
CORRELATION_GROUPS = [
    {"EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"},   # "vs USD" — tend to move together
    {"USDJPY", "USDCHF", "USDCAD"},              # USD as base — often inverse to above
    {"EURGBP", "EURJPY", "GBPJPY"},              # cross pairs sharing legs
    {"XAUUSD", "XAGUSD"},                        # metals
]


def find_correlation_group(pair: str):
    """Return the correlation group set containing `pair`, or None."""
    for group in CORRELATION_GROUPS:
        if pair in group:
            return group
    return None


def filter_correlated_signals(signals: list) -> list:
    """
    Given a list of Signal objects (already sorted by score, highest first),
    remove signals that are correlated duplicates of a higher-scoring signal
    already kept (same correlation group + same direction).

    The dropped signal's pair name is appended to `correlation_note` on the
    kept signal so it can optionally be shown in the formatter.
    """
    kept = []
    kept_groups = []  # list of (group_set, direction, pair_name) for kept signals

    for sig in signals:
        group = find_correlation_group(sig.pair)

        if group is None:
            # Not part of any known correlation group — always keep
            kept.append(sig)
            continue

        # Check if a higher-scoring signal from the same group + direction
        # has already been kept
        duplicate_of = None
        for kept_group, kept_dir, kept_pair in kept_groups:
            if kept_group is group and kept_dir == sig.direction:
                duplicate_of = kept_pair
                break

        if duplicate_of:
            # Skip this one — it's a correlated duplicate of a stronger signal
            continue

        kept.append(sig)
        kept_groups.append((group, sig.direction, sig.pair))

    return kept


def overall_direction(tf_data: dict, processed: dict) -> str:
    """
    Determine overall bias using weighted timeframe voting.
    Higher timeframes carry more weight than lower ones.
    """
    TF_WEIGHTS = {
        "15min": 1, "15m": 1,
        "30min": 1, "30m": 1,
        "45min": 1, "45m": 1,
        "1h": 2,
        "2h": 2,
        "4h": 3,
    }
    buy_weight = 0
    total_weight = 0

    for tf, df in processed.items():
        row = df.iloc[-1]
        prev = df.iloc[-2]
        weight = TF_WEIGHTS.get(tf, 1)
        total_weight += weight

        pts = 0

        # EMA alignment
        if row["ema9"] > row["ema21"] > row["ema50"]: pts += 1
        elif row["ema9"] < row["ema21"] < row["ema50"]: pts -= 1

        # MACD
        if row["macd"] > row["macd_signal"]: pts += 1
        else: pts -= 1

        # RSI (FIXED: > 50 = bullish)
        if row["rsi"] > 50: pts += 1
        else: pts -= 1

        # Stochastic
        if row["stoch_k"] > row["stoch_d"]: pts += 1
        else: pts -= 1

        # ADX DI direction
        if row["plus_di"] > row["minus_di"]: pts += 1
        else: pts -= 1

        # Price vs EMA200 (macro bias)
        if row["close"] > row["ema200"]: pts += 1
        else: pts -= 1

        if pts > 0:
            buy_weight += weight

    return "BUY" if buy_weight > total_weight / 2 else "SELL"


def _select_main_tf(tf_sigs: list):
    """
    Pick the 'main' timeframe signal to use for entry price display.
    Prefers 1h, then 2h, then 4h, then falls back to the first available
    — works regardless of which/how many timeframes were scanned.
    """
    priority = ["1h", "1hour", "60min", "60m", "2h", "4h"]
    for tf_name in priority:
        match = next((t for t in tf_sigs if t.tf == tf_name), None)
        if match:
            return match
    return tf_sigs[0]


def analyze_pair(pair: str, tf_data: dict, account_balance: float):
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

    # At least 3 timeframes must agree with the overall direction for a
    # valid signal (relaxed from "all must agree" now that there are up
    # to 6 timeframes — requiring all 6 would be too strict).
    MIN_AGREEING_TFS = 3
    if agreed < MIN_AGREEING_TFS:
        return None

    # ── STABILITY CHECK ──────────────────────────────────────────────
    # Problem this fixes: borderline signals where the overall direction
    # is decided by a narrow majority can flip to the OPPOSITE direction
    # moments later from tiny indicator shifts (e.g. RSI crossing 50,
    # MACD histogram flipping sign) — causing the bot to send BUY, then
    # SELL on the same pair within minutes.
    #
    # Fix: require the LONGEST available timeframe (most weight, slowest
    # to change, least noisy) to individually agree with the overall
    # direction. If the "anchor" timeframe disagrees, the overall
    # direction is being decided by faster/noisier timeframes alone —
    # exactly the kind of signal likely to flip soon. Reject it.
    TF_PRIORITY_FOR_ANCHOR = ["4h", "2h", "1h", "45min", "45m", "30min", "30m", "15min", "15m"]
    anchor_tf = None
    for tf_name in TF_PRIORITY_FOR_ANCHOR:
        anchor_tf = next((t for t in tf_sigs if t.tf == tf_name), None)
        if anchor_tf:
            break

    if anchor_tf and not anchor_tf.agrees:
        return None  # anchor (longest) timeframe disagrees -> unstable, skip

    # ADX filter: at least one TF must show a trending market
    max_adx = max(t.adx for t in tf_sigs)
    if max_adx < 18:
        return None  # avoid ranging/choppy markets entirely

    score = total_ind

    # Raised from 6 to 7 — combined with the stability check above, this
    # reduces the frequency of borderline/contradictory signals.
    if score < 7:
        return None

    conf_pct = agreed / len(tf_sigs)
    if conf_pct >= 0.8: confidence = "VERY HIGH"
    elif conf_pct >= 0.6: confidence = "HIGH"
    elif conf_pct >= 0.4: confidence = "MEDIUM"
    else: confidence = "LOW"

    main_tf = _select_main_tf(tf_sigs)
    risk_usd = round(account_balance * RISK_PERCENT / 100, 2)

    return Signal(
        pair=pair,
        direction=o_dir,
        entry=main_tf.entry,
        score=score,
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
        if crypto_only and not is_crypto(pair): continue
        try:
            sig = analyze_pair(pair, tfs, account_balance)
            if sig: signals.append(sig)
        except Exception as e:
            logger.warning(f"{pair} error: {e}")

    signals.sort(key=lambda s: s.score, reverse=True)
    signals = filter_correlated_signals(signals)
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
    if conf_pct >= 0.8: confidence = "VERY HIGH"
    elif conf_pct >= 0.6: confidence = "HIGH"
    elif conf_pct >= 0.4: confidence = "MEDIUM"
    else: confidence = "LOW"

    main_tf = _select_main_tf(tf_sigs)
    risk_usd = round(account_balance * RISK_PERCENT / 100, 2)

    return Signal(
        pair=pair,
        direction=o_dir,
        entry=main_tf.entry,
        score=score,
        confidence=confidence,
        tfs_agreed=agreed,
        total_tfs=len(tf_sigs),
        tf_signals=tf_sigs,
        asset_type="CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount=risk_usd,
    )
