import numpy as np
import logging
from dataclasses import dataclass
from indicators import compute_indicators
from config import RISK_PERCENT, CRYPTO_PAIRS, DEFAULT_RR_RATIO, MIN_SIGNAL_SCORE

logger = logging.getLogger(__name__)


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class TFSignal:
    tf: str
    direction: str      # "BUY" or "SELL"
    entry: float
    stop_loss: float
    take_profit: float
    sl_pips: float
    tp_pips: float
    lot_size: float
    score: float        # 0–5 for this timeframe
    indicators: int     # count of confirmed indicators (for display)
    confirmed: list     # names of confirmed indicators
    rsi: float
    stoch: float
    macd: float
    adx: float
    agrees: bool        # does this TF agree with the overall direction?


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
    score: float        # 0–10 normalised
    confidence: str
    tfs_agreed: int
    total_tfs: int
    tf_signals: list
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
    """Return default if val is NaN/None."""
    try:
        return default if np.isnan(float(val)) else float(val)
    except Exception:
        return default


# ── Per-timeframe scoring ──────────────────────────────────────────────────────

def _score_tf(row, overall_dir: str) -> tuple[float, list]:
    """
    Score a single row of indicators from 0 to 5.
    Returns (score, confirmed_names).
    FIX: RSI was inverted — RSI > 50 is bullish, < 50 is bearish.
    """
    score = 0.0
    confirmed = []

    # 1. EMA alignment (0–1 pt)
    ema9, ema21, ema50 = row["ema9"], row["ema21"], row["ema50"]
    if overall_dir == "BUY":
        if ema9 > ema21 > ema50:
            score += 1.0; confirmed.append("EMA aligned ↑")
        elif ema9 > ema21:
            score += 0.5; confirmed.append("EMA partial ↑")
    else:
        if ema9 < ema21 < ema50:
            score += 1.0; confirmed.append("EMA aligned ↓")
        elif ema9 < ema21:
            score += 0.5; confirmed.append("EMA partial ↓")

    # 2. MACD (0–1 pt)
    macd_val  = _safe(row["macd"])
    macd_sig  = _safe(row["macd_signal"])
    macd_hist = _safe(row["macd_hist"])
    if overall_dir == "BUY":
        if macd_val > macd_sig and macd_hist > 0:
            score += 1.0; confirmed.append("MACD bullish")
        elif macd_hist > 0:
            score += 0.4; confirmed.append("MACD hist +")
    else:
        if macd_val < macd_sig and macd_hist < 0:
            score += 1.0; confirmed.append("MACD bearish")
        elif macd_hist < 0:
            score += 0.4; confirmed.append("MACD hist -")

    # 3. RSI (0–1 pt)  ← FIX: was inverted (< 50 gave BUY points, which is WRONG)
    rsi_val = _safe(row["rsi"], 50)
    if overall_dir == "BUY":
        if 50 < rsi_val < 70:          # bullish momentum, not overbought
            score += 1.0; confirmed.append(f"RSI {rsi_val:.0f} bullish")
        elif rsi_val >= 50:
            score += 0.5
    else:
        if 30 < rsi_val < 50:          # bearish momentum, not oversold
            score += 1.0; confirmed.append(f"RSI {rsi_val:.0f} bearish")
        elif rsi_val <= 50:
            score += 0.5

    # 4. Stochastic (0–1 pt)
    k = _safe(row["stoch_k"], 50)
    d = _safe(row["stoch_d"], 50)
    if overall_dir == "BUY":
        if k > d and k < 80:
            score += 1.0; confirmed.append(f"Stoch {k:.0f} ↑")
        elif k > d:
            score += 0.4
    else:
        if k < d and k > 20:
            score += 1.0; confirmed.append(f"Stoch {k:.0f} ↓")
        elif k < d:
            score += 0.4

    # 5. ADX trend strength (0–1 pt) — direction-agnostic
    adx_val  = _safe(row["adx"])
    plus_di  = _safe(row["plus_di"])
    minus_di = _safe(row["minus_di"])
    if adx_val >= 25:
        score += 1.0; confirmed.append(f"ADX {adx_val:.0f} strong")
    elif adx_val >= 18:
        score += 0.5; confirmed.append(f"ADX {adx_val:.0f} moderate")

    return score, confirmed


# ── Overall direction ──────────────────────────────────────────────────────────

def overall_direction(processed: dict) -> str:
    """
    Vote across all TFs: majority rules.
    FIX: now takes the processed (indicator) dict directly.
    FIX: RSI > 50 = bullish vote (was reversed).
    """
    buy_votes = 0
    for tf, df in processed.items():
        row = df.iloc[-1]
        votes = sum([
            float(row["ema9"])      > float(row["ema21"]),
            float(row["macd"])      > float(row["macd_signal"]),
            _safe(row["rsi"], 50)   > 50,           # FIX: > 50 is bullish
            _safe(row["stoch_k"])   > _safe(row["stoch_d"]),
            _safe(row["plus_di"])   > _safe(row["minus_di"]),
        ])
        if votes >= 3:
            buy_votes += 1
    return "BUY" if buy_votes >= len(processed) / 2 else "SELL"


# ── Per-TF analysis ────────────────────────────────────────────────────────────

def analyze_tf(df, pair: str, tf: str, balance: float, o_dir: str) -> TFSignal:
    row   = df.iloc[-1]
    close = float(row["close"])
    dec   = decimal_places(pair, close)

    score, confirmed = _score_tf(row, o_dir)

    # Determine this TF's own direction
    votes = sum([
        float(row["ema9"])     > float(row["ema21"]),
        float(row["macd"])     > float(row["macd_signal"]),
        _safe(row["rsi"], 50)  > 50,
        _safe(row["stoch_k"])  > _safe(row["stoch_d"]),
        _safe(row["plus_di"])  > _safe(row["minus_di"]),
    ])
    tf_dir = "BUY" if votes >= 3 else "SELL"

    # SL / TP from ATR
    atr_val = _safe(row["atr"], close * 0.001)
    min_sl  = close * 0.003 if is_crypto(pair) else (0.0015 if "JPY" not in pair else 0.15)
    sl_dist = max(1.5 * atr_val, min_sl)

    if tf_dir == "BUY":
        sl = close - sl_dist
        tp = close + sl_dist * DEFAULT_RR_RATIO
    else:
        sl = close + sl_dist
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
        sl_pips=sl_p,
        tp_pips=tp_p,
        lot_size=lot,
        score=round(score, 2),
        indicators=len(confirmed),
        confirmed=confirmed,
        rsi=round(_safe(row["rsi"], 50), 1),
        stoch=round(_safe(row["stoch_k"]), 1),
        macd=round(float(row["macd"]), 6),
        adx=round(_safe(row["adx"]), 1),
        agrees=(tf_dir == o_dir),
    )


# ── Pair analysis ──────────────────────────────────────────────────────────────

def _build_signal(pair: str, processed: dict, tf_sigs: list, balance: float) -> Signal | None:
    """Build a Signal object from TF signals (shared by analyze_pair & force_analyze_pair)."""
    if not tf_sigs:
        return None

    agreed      = sum(1 for t in tf_sigs if t.agrees)
    raw_score   = sum(t.score for t in tf_sigs)
    max_score   = len(tf_sigs) * 5.0
    normalised  = round((raw_score / max_score) * 10, 1) if max_score > 0 else 0.0

    conf_pct = agreed / len(tf_sigs)
    if conf_pct >= 0.8:   confidence = "VERY HIGH ⭐⭐⭐"
    elif conf_pct >= 0.6: confidence = "HIGH ⭐⭐"
    elif conf_pct >= 0.4: confidence = "MEDIUM ⭐"
    else:                 confidence = "LOW"

    # Use 1h TF for main entry/SL/TP; fall back to first
    main = next((t for t in tf_sigs if t.tf == "1h"), tf_sigs[0])

    return Signal(
        pair=pair,
        direction=overall_direction(processed),
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
        asset_type="CRYPTO" if is_crypto(pair) else "FOREX",
        risk_amount=round(balance * RISK_PERCENT / 100, 2),
    )


def analyze_pair(pair: str, tf_data: dict, balance: float) -> Signal | None:
    """Analyse a pair; returns None if score below MIN_SIGNAL_SCORE."""
    try:
        processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicator error: {e}")
        return None

    o_dir   = overall_direction(processed)   # FIX: pass processed, not tf_data
    tf_sigs = []
    for tf, df in processed.items():
        try:
            tf_sigs.append(analyze_tf(df, pair, tf, balance, o_dir))
        except Exception as e:
            logger.warning(f"{pair} {tf} tf error: {e}")

    sig = _build_signal(pair, processed, tf_sigs, balance)
    if sig is None:
        return None

    agreed = sum(1 for t in tf_sigs if t.agrees)
    if sig.score < MIN_SIGNAL_SCORE:
        return None
    if agreed < max(1, len(tf_sigs) // 2):
        return None

    return sig


def force_analyze_pair(pair: str, tf_data: dict, balance: float) -> Signal | None:
    """Like analyze_pair but skips the score threshold — used for crypto /crypto command."""
    try:
        processed = {tf: compute_indicators(df) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicator error: {e}")
        return None

    o_dir   = overall_direction(processed)
    tf_sigs = []
    for tf, df in processed.items():
        try:
            tf_sigs.append(analyze_tf(df, pair, tf, balance, o_dir))
        except Exception as e:
            logger.warning(f"{pair} {tf} tf error: {e}")

    return _build_signal(pair, processed, tf_sigs, balance)


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
