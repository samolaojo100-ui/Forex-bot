import numpy as np
import logging
from dataclasses import dataclass
from indicators import compute_indicators
from config import RISK_PERCENT, CRYPTO_PAIRS, DEFAULT_RR_RATIO, MIN_SIGNAL_SCORE

logger = logging.getLogger(__name__)

# Minimum score threshold raised to 7/10 for accuracy
MIN_SCORE = 7.0


# ── Data classes ───────────────────────────────────────────────────────────────

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
    score: float
    indicators: int
    confirmed: list
    rsi: float
    stoch: float
    macd: float
    adx: float
    agrees: bool
    near_sr: bool        # is price near support/resistance?
    sr_level: float      # nearest S/R level


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
    score: float
    confidence: str
    tfs_agreed: int
    total_tfs: int
    tf_signals: list
    support: float
    resistance: float
    asset_type: str = "FOREX"
    risk_amount: float = 0.0


# ── Helpers ────────────────────────────────────────────────────────────────────

def is_crypto(pair: str) -> bool:
    return pair in CRYPTO_PAIRS


def pip_size(pair: str) -> float:
    if is_crypto(pair):
        return 1.0
    return 0.01 if "JPY" in pair else 0.0001


def pips(pair: str, a: float, b: float) -> float:
    return round(abs(a - b) / pip_size(pair), 1)


def calc_lot(pair: str, sl_pips: float, balance: float) -> float:
    risk_usd = balance * RISK_PERCENT / 100
    if is_crypto(pair):
        return round(risk_usd / max(sl_pips, 1), 4)
    pip_value = 10 if "JPY" not in pair else 9.09
    return max(0.01, round(risk_usd / (sl_pips * pip_value), 2))


def decimal_places(pair: str, close: float) -> int:
    if is_crypto(pair):
        return 2 if close > 10 else 5
    return 3 if "JPY" in pair else 5


def _safe(val, default=0.0):
    try:
        return default if np.isnan(float(val)) else float(val)
    except Exception:
        return default


# ── Support & Resistance ───────────────────────────────────────────────────────

def get_sr_levels(df, lookback: int = 50):
    """
    Find key support and resistance levels using swing highs/lows.
    Returns (support, resistance, all_levels).
    """
    recent = df.tail(lookback)
    highs  = recent["high"].values
    lows   = recent["low"].values
    close  = float(df.iloc[-1]["close"])

    # Swing highs — local maxima
    resistance_levels = []
    support_levels    = []

    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
           highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            resistance_levels.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
           lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            support_levels.append(lows[i])

    # Fallback if no swing points found
    if not resistance_levels:
        resistance_levels = [recent["high"].max()]
    if not support_levels:
        support_levels = [recent["low"].min()]

    # Nearest support below price, nearest resistance above price
    supports    = [s for s in support_levels if s < close]
    resistances = [r for r in resistance_levels if r > close]

    support    = max(supports)    if supports    else recent["low"].min()
    resistance = min(resistances) if resistances else recent["high"].max()

    return support, resistance


def is_near_level(close: float, level: float, pair: str, tolerance_pips: int = 20) -> bool:
    """Check if price is within tolerance_pips of a key level."""
    distance = abs(close - level) / pip_size(pair)
    return distance <= tolerance_pips


# ── Trend filter using higher TF ──────────────────────────────────────────────

def get_trend(df) -> str:
    """
    Determine trend from the 4H or daily chart using EMA200.
    Price above EMA200 = uptrend. Below = downtrend.
    """
    row   = df.iloc[-1]
    close = float(row["close"])
    ema200 = _safe(row["ema200"])
    ema50  = _safe(row["ema50"])
    ema21  = _safe(row["ema21"])

    bull_points = sum([
        close > ema200,
        close > ema50,
        ema50  > ema200,
        ema21  > ema50,
    ])

    return "BUY" if bull_points >= 3 else "SELL"


# ── Per-timeframe scoring ──────────────────────────────────────────────────────

def _score_tf(row, overall_dir: str) -> tuple[float, list]:
    """
    Score indicators 0–7 (7 checks instead of 5 for better accuracy).
    """
    score     = 0.0
    confirmed = []

    # 1. EMA full alignment (0–1.5 pts)
    ema9  = _safe(row["ema9"])
    ema21 = _safe(row["ema21"])
    ema50 = _safe(row["ema50"])
    ema200 = _safe(row["ema200"])

    if overall_dir == "BUY":
        if ema9 > ema21 > ema50 > ema200:
            score += 1.5; confirmed.append("EMA fully aligned ↑")
        elif ema9 > ema21 > ema50:
            score += 1.0; confirmed.append("EMA aligned ↑")
        elif ema9 > ema21:
            score += 0.5; confirmed.append("EMA partial ↑")
    else:
        if ema9 < ema21 < ema50 < ema200:
            score += 1.5; confirmed.append("EMA fully aligned ↓")
        elif ema9 < ema21 < ema50:
            score += 1.0; confirmed.append("EMA aligned ↓")
        elif ema9 < ema21:
            score += 0.5; confirmed.append("EMA partial ↓")

    # 2. MACD (0–1 pt) — must have crossover AND histogram agreement
    macd_val  = _safe(row["macd"])
    macd_sig  = _safe(row["macd_signal"])
    macd_hist = _safe(row["macd_hist"])
    if overall_dir == "BUY":
        if macd_val > macd_sig and macd_hist > 0 and macd_val < 0:
            # Crossover below zero = strongest buy signal
            score += 1.0; confirmed.append("MACD crossover bullish")
        elif macd_val > macd_sig and macd_hist > 0:
            score += 0.7; confirmed.append("MACD bullish")
        elif macd_hist > 0:
            score += 0.3
    else:
        if macd_val < macd_sig and macd_hist < 0 and macd_val > 0:
            score += 1.0; confirmed.append("MACD crossover bearish")
        elif macd_val < macd_sig and macd_hist < 0:
            score += 0.7; confirmed.append("MACD bearish")
        elif macd_hist < 0:
            score += 0.3

    # 3. RSI — zone based scoring (0–1.5 pts)
    rsi_val = _safe(row["rsi"], 50)
    if overall_dir == "BUY":
        if 45 < rsi_val < 60:
            # Sweet spot — bullish momentum without being overbought
            score += 1.5; confirmed.append(f"RSI {rsi_val:.0f} ideal")
        elif 60 <= rsi_val < 70:
            score += 0.8; confirmed.append(f"RSI {rsi_val:.0f} bullish")
        elif rsi_val >= 50:
            score += 0.4
        elif rsi_val < 35:
            # Oversold bounce opportunity
            score += 1.0; confirmed.append(f"RSI {rsi_val:.0f} oversold bounce")
    else:
        if 40 < rsi_val < 55:
            score += 1.5; confirmed.append(f"RSI {rsi_val:.0f} ideal")
        elif 30 <= rsi_val < 40:
            score += 0.8; confirmed.append(f"RSI {rsi_val:.0f} bearish")
        elif rsi_val <= 50:
            score += 0.4
        elif rsi_val > 65:
            # Overbought reversal opportunity
            score += 1.0; confirmed.append(f"RSI {rsi_val:.0f} overbought reversal")

    # 4. Stochastic (0–1 pt) — must be crossing not extreme
    k = _safe(row["stoch_k"], 50)
    d = _safe(row["stoch_d"], 50)
    if overall_dir == "BUY":
        if k > d and 20 < k < 50:
            # Crossing up from oversold = strongest
            score += 1.0; confirmed.append(f"Stoch {k:.0f} crossing up")
        elif k > d and k < 80:
            score += 0.6; confirmed.append(f"Stoch {k:.0f} bullish")
        elif k > d:
            score += 0.3
    else:
        if k < d and 50 < k < 80:
            score += 1.0; confirmed.append(f"Stoch {k:.0f} crossing down")
        elif k < d and k > 20:
            score += 0.6; confirmed.append(f"Stoch {k:.0f} bearish")
        elif k < d:
            score += 0.3

    # 5. ADX — trend strength (0–1 pt)
    adx_val  = _safe(row["adx"])
    plus_di  = _safe(row["plus_di"])
    minus_di = _safe(row["minus_di"])
    di_agree = (overall_dir == "BUY" and plus_di > minus_di) or \
               (overall_dir == "SELL" and minus_di > plus_di)

    if adx_val >= 30 and di_agree:
        score += 1.0; confirmed.append(f"ADX {adx_val:.0f} strong trend")
    elif adx_val >= 25 and di_agree:
        score += 0.7; confirmed.append(f"ADX {adx_val:.0f} trending")
    elif adx_val >= 20:
        score += 0.3

    # 6. Bollinger Band position (0–1 pt)
    close    = _safe(row["close"])
    bb_upper = _safe(row["bb_upper"])
    bb_lower = _safe(row["bb_lower"])
    bb_mid   = _safe(row["bb_mid"])
    if overall_dir == "BUY":
        if close > bb_mid and close < bb_upper:
            score += 1.0; confirmed.append("Price above BB mid")
        elif close <= bb_lower:
            score += 0.8; confirmed.append("Price at BB lower (bounce)")
    else:
        if close < bb_mid and close > bb_lower:
            score += 1.0; confirmed.append("Price below BB mid")
        elif close >= bb_upper:
            score += 0.8; confirmed.append("Price at BB upper (reversal)")

    return score, confirmed


# ── Overall direction ──────────────────────────────────────────────────────────

def overall_direction(processed: dict) -> str:
    """
    Weighted vote — higher TFs (4H) get more weight than lower (15min).
    """
    weights = {"15min": 1, "1h": 2, "4h": 3, "1day": 4}
    buy_weight  = 0.0
    total_weight = 0.0

    for tf, df in processed.items():
        w   = weights.get(tf, 1)
        row = df.iloc[-1]
        votes = sum([
            float(row["ema9"])     > float(row["ema21"]),
            float(row["macd"])     > float(row["macd_signal"]),
            _safe(row["rsi"], 50)  > 50,
            _safe(row["stoch_k"])  > _safe(row["stoch_d"]),
            _safe(row["plus_di"])  > _safe(row["minus_di"]),
            _safe(row["close"])    > _safe(row["ema200"]),  # price above EMA200
        ])
        if votes >= 4:   # stricter: need 4/6 to be bullish
            buy_weight += w
        total_weight += w

    return "BUY" if buy_weight >= total_weight / 2 else "SELL"


# ── Per-TF analysis ────────────────────────────────────────────────────────────

def analyze_tf(df, pair: str, tf: str, balance: float, o_dir: str,
               support: float, resistance: float) -> TFSignal:
    row   = df.iloc[-1]
    close = float(row["close"])
    dec   = decimal_places(pair, close)

    score, confirmed = _score_tf(row, o_dir)

    # Check if near S/R
    near_support    = is_near_level(close, support, pair, 25)
    near_resistance = is_near_level(close, resistance, pair, 25)
    near_sr = near_support or near_resistance

    # Bonus point for being near key S/R level
    if near_sr:
        if o_dir == "BUY" and near_support:
            score += 0.5; confirmed.append("Near support ✅")
        elif o_dir == "SELL" and near_resistance:
            score += 0.5; confirmed.append("Near resistance ✅")

    sr_level = support if (o_dir == "BUY") else resistance

    # Direction vote for this TF
    votes = sum([
        float(row["ema9"])     > float(row["ema21"]),
        float(row["macd"])     > float(row["macd_signal"]),
        _safe(row["rsi"], 50)  > 50,
        _safe(row["stoch_k"])  > _safe(row["stoch_d"]),
        _safe(row["plus_di"])  > _safe(row["minus_di"]),
        close                  > _safe(row["ema200"]),
    ])
    tf_dir = "BUY" if votes >= 4 else "SELL"

    # SL/TP from ATR — tighter multiplier for better RR
    atr_val = _safe(row["atr"], close * 0.001)
    min_sl  = close * 0.003 if is_crypto(pair) else (0.002 if "JPY" not in pair else 0.2)
    sl_dist = max(1.2 * atr_val, min_sl)  # tighter than before (was 1.5)

    if tf_dir == "BUY":
        # SL below nearest support for accuracy
        sl = min(close - sl_dist, support - pip_size(pair) * 5) if near_support else close - sl_dist
        tp = close + sl_dist * DEFAULT_RR_RATIO
    else:
        sl = max(close + sl_dist, resistance + pip_size(pair) * 5) if near_resistance else close + sl_dist
        tp = close - sl_dist * DEFAULT_RR_RATIO

    sl_p = pips(pair, close, sl)
    tp_p = pips(pair, close, tp)
    lot  = calc_lot(pair, max(sl_p, 0.1), balance)

    return TFSignal(
        tf=tf,
        direction=tf_dir,
        entry=round(close, dec),
        stop_loss=round(sl, dec),
        take_profit=round(tp, dec),
        sl_pips=round(sl_p, 1),
        tp_pips=round(tp_p, 1),
        lot_size=lot,
        score=round(score, 2),
        indicators=len(confirmed),
        confirmed=confirmed,
        rsi=round(_safe(row["rsi"], 50), 1),
        stoch=round(k := _safe(row["stoch_k"]), 1),
        macd=round(float(row["macd"]), 6),
        adx=round(_safe(row["adx"]), 1),
        agrees=(tf_dir == o_dir),
        near_sr=near_sr,
        sr_level=round(sr_level, dec),
    )


# ── Build signal ───────────────────────────────────────────────────────────────

def _build_signal(pair: str, processed: dict, tf_sigs: list,
                  balance: float, support: float, resistance: float) -> Signal | None:
    if not tf_sigs:
        return None

    agreed     = sum(1 for t in tf_sigs if t.agrees)
    raw_score  = sum(t.score for t in tf_sigs)
    max_score  = len(tf_sigs) * 7.5   # max per TF is now ~7.5
    normalised = round((raw_score / max_score) * 10, 1) if max_score > 0 else 0.0

    conf_pct = agreed / len(tf_sigs)
    if conf_pct >= 0.9:   confidence = "VERY HIGH ⭐⭐⭐"
    elif conf_pct >= 0.7: confidence = "HIGH ⭐⭐"
    elif conf_pct >= 0.5: confidence = "MEDIUM ⭐"
    else:                 confidence = "LOW"

    main = next((t for t in tf_sigs if t.tf == "1h"), tf_sigs[0])
    o_dir = overall_direction(processed)

    return Signal(
        pair=pair,
        direction=o_dir,
        entry=main.entry,
        stop_loss=main.stop_loss,
        take_profit=main.take_profit,
        sl_pips=main.sl_pips,
        tp_pips=main.tp_pips,
        lot_size=main.lot_size,
        score=normalised,
        confidence=confidence,
        tfs_agreed=agreed,
        total_tfs=len(tf_sigs),
        tf_signals=tf_sigs,
        support=round(support, 5),
        resistance=round(resistance, 5),
        asset_type="CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount=round(balance * RISK_PERCENT / 100, 2),
    )


# ── Main analysis ──────────────────────────────────────────────────────────────

def analyze_pair(pair: str, tf_data: dict, balance: float) -> Signal | None:
    try:
        processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicator error: {e}")
        return None

    o_dir = overall_direction(processed)

    # Get S/R from the 1H chart (best balance of detail vs noise)
    ref_df = processed.get("1h", list(processed.values())[0])
    support, resistance = get_sr_levels(ref_df)

    # Trend filter — 4H must agree with direction
    high_tf = processed.get("4h", list(processed.values())[-1])
    trend   = get_trend(high_tf)
    if trend != o_dir:
        logger.info(f"{pair}: skipped — 4H trend ({trend}) disagrees with signal ({o_dir})")
        return None

    tf_sigs = []
    for tf, df in processed.items():
        try:
            tf_sigs.append(analyze_tf(df, pair, tf, balance, o_dir, support, resistance))
        except Exception as e:
            logger.warning(f"{pair} {tf} error: {e}")

    sig = _build_signal(pair, processed, tf_sigs, balance, support, resistance)
    if sig is None:
        return None

    # Strict filters for accuracy
    agreed = sum(1 for t in tf_sigs if t.agrees)
    if sig.score < MIN_SCORE:
        return None
    if agreed < len(tf_sigs):   # ALL timeframes must agree
        return None

    return sig


def force_analyze_pair(pair: str, tf_data: dict, balance: float) -> Signal | None:
    """Skip score threshold — used for crypto forced signals."""
    try:
        processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicator error: {e}")
        return None

    o_dir = overall_direction(processed)
    ref_df = processed.get("1h", list(processed.values())[0])
    support, resistance = get_sr_levels(ref_df)

    tf_sigs = []
    for tf, df in processed.items():
        try:
            tf_sigs.append(analyze_tf(df, pair, tf, balance, o_dir, support, resistance))
        except Exception as e:
            logger.warning(f"{pair} {tf} error: {e}")

    return _build_signal(pair, processed, tf_sigs, balance, support, resistance)


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
