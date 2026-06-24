import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from indicators import compute_indicators, support_resistance, detect_candle_pattern
from config import RISK_PERCENT, CRYPTO_PAIRS, DEFAULT_RR_RATIO
from session_manager import get_current_session

logger = logging.getLogger(__name__)

GOLD_PAIRS = {"XAU/USD", "XAUUSD"}


@dataclass
class Signal:
    pair:             str
    direction:        str       # BUY or SELL
    confidence:       int       # 0-100%
    confluence:       int       # number of confirming indicators
    mtf_aligned:      bool
    entry:            float
    sl:               float
    tp1:              float
    tp2:              float
    tp3:              float
    partial_tp:       float
    invalidation:     float
    sl_pips:          float
    tp1_pips:         float
    tp2_pips:         float
    tp3_pips:         float
    rr_ratio:         float
    lot_size:         float
    risk_usd:         float
    asset_type:       str       # FOREX / CRYPTO / GOLD
    trend:            str
    volatility:       str
    session:          str
    session_quality:  str
    adx:              float
    rsi:              float
    macd_signal:      str       # BUY / SELL / NEUTRAL
    stoch_signal:     str
    cci_signal:       str
    williams_signal:  str
    bb_signal:        str
    candle_pattern:   str
    # ── News ──────────────────────────────────────────────────
    news_blocked:     bool      = False
    news_reason:      str       = ""
    news_bullish:     int       = 0   # count of bullish headlines
    news_bearish:     int       = 0   # count of bearish headlines
    news_sentiment:   str       = ""  # BULLISH / BEARISH / NEUTRAL / MIXED
    # ── TP reachability ───────────────────────────────────────
    tp_reachable:     bool      = True
    tp_reach_reason:  str       = ""
    # ── Trade verdict ─────────────────────────────────────────
    no_trade:         bool      = False
    no_trade_reasons: list      = field(default_factory=list)
    warnings:         list      = field(default_factory=list)
    symbol:           str       = ""  # alias for pair (for Gemini agent)


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_crypto(pair: str) -> bool:
    return pair in CRYPTO_PAIRS

def is_gold(pair: str) -> bool:
    return pair.upper().replace("/", "") in {"XAUUSD"}

def pip_value(pair: str, price: float) -> float:
    if is_crypto(pair): return 1.0
    if is_gold(pair):   return 0.1
    return 0.01 if "JPY" in pair else 0.0001

def price_to_pips(pair: str, a: float, b: float) -> float:
    return round(abs(a - b) / pip_value(pair, (a + b) / 2), 1)

def calc_lot(pair: str, sl_pips: float, balance: float, price: float) -> float:
    risk_usd = balance * RISK_PERCENT / 100
    if is_crypto(pair):
        return round(risk_usd / max(sl_pips, 0.01), 4)
    if is_gold(pair):
        pip_usd = 1.0
        return max(0.01, round(risk_usd / (sl_pips * pip_usd), 2))
    pip_usd = 10 if "JPY" not in pair else 9.09
    return max(0.01, round(risk_usd / (sl_pips * pip_usd), 2))

def decimal_places(pair: str, price: float) -> int:
    if is_crypto(pair) and price > 100: return 2
    if is_gold(pair): return 2
    if "JPY" in pair: return 3
    return 5


# ── Indicator scoring ─────────────────────────────────────────────────────────

def score_indicators(row: pd.Series, direction: str) -> tuple:
    buy_votes  = 0
    sell_votes = 0
    signals    = {}

    rsi = row["rsi"]
    if rsi < 30:              buy_votes  += 1; signals["rsi"] = "BUY"
    elif 30 <= rsi < 45:      buy_votes  += 1; signals["rsi"] = "BUY"
    elif 45 <= rsi <= 55:     signals["rsi"] = "NEUTRAL"
    elif 55 < rsi <= 70:      sell_votes += 1; signals["rsi"] = "SELL"
    elif rsi > 70:            sell_votes += 1; signals["rsi"] = "SELL"
    else:                     signals["rsi"] = "NEUTRAL"

    if row["macd"] > row["macd_signal"] and row["macd_hist"] > 0:
        buy_votes  += 1; signals["macd"] = "BUY"
    elif row["macd"] < row["macd_signal"] and row["macd_hist"] < 0:
        sell_votes += 1; signals["macd"] = "SELL"
    else:
        signals["macd"] = "NEUTRAL"

    k, d = row["stoch_k"], row["stoch_d"]
    if k > d and k < 80:     buy_votes  += 1; signals["stoch"] = "BUY"
    elif k < d and k > 20:   sell_votes += 1; signals["stoch"] = "SELL"
    else:                    signals["stoch"] = "NEUTRAL"

    bb = row["bb_pct"]
    if bb < 0.2:              buy_votes  += 1; signals["bb"] = "BUY"
    elif bb > 0.8:            sell_votes += 1; signals["bb"] = "SELL"
    else:                     signals["bb"] = "NEUTRAL"

    signals["atr"] = "NEUTRAL"

    adx = row["adx"]
    if adx > 25 and row["plus_di"] > row["minus_di"]:
        buy_votes  += 1; signals["adx"] = "BUY"
    elif adx > 25 and row["minus_di"] > row["plus_di"]:
        sell_votes += 1; signals["adx"] = "SELL"
    else:
        signals["adx"] = "NEUTRAL"

    cci = row["cci"]
    if cci < -100:            buy_votes  += 1; signals["cci"] = "BUY"
    elif cci > 100:           sell_votes += 1; signals["cci"] = "SELL"
    else:                     signals["cci"] = "NEUTRAL"

    wr = row["williams_r"]
    if wr < -80:              buy_votes  += 1; signals["williams"] = "BUY"
    elif wr > -20:            sell_votes += 1; signals["williams"] = "SELL"
    else:                     signals["williams"] = "NEUTRAL"

    return buy_votes, sell_votes, signals


def market_regime(df: pd.DataFrame) -> tuple:
    row  = df.iloc[-1]
    e9   = row["ema9"]
    e21  = row["ema21"]
    e50  = row["ema50"]
    e200 = row["ema200"]
    adx  = row["adx"]
    atr  = row["atr"]
    close= row["close"]

    if e9 > e21 > e50 and close > e200:
        trend = "Trending Up 📈"
    elif e9 < e21 < e50 and close < e200:
        trend = "Trending Down 📉"
    elif adx > 25:
        trend = "Trending"
    else:
        trend = "Ranging ↔️"

    atr_pct = (atr / close) * 100 if close > 0 else 0
    if atr_pct > 1.0:    volatility = "High ⚡"
    elif atr_pct > 0.3:  volatility = "Normal"
    else:                volatility = "Low 😴"

    return trend, volatility


# ── NEW: News sentiment scorer ────────────────────────────────────────────────

async def _score_news_sentiment(pair: str) -> tuple:
    """
    Returns (bullish_count, bearish_count, sentiment_label).
    Tries to use news_filter headlines. Falls back to (0, 0, NEUTRAL).
    """
    try:
        from news_filter import get_upcoming_events
        events = await get_upcoming_events(hours=12)

        # Simple keyword scoring on event names/titles
        bullish_keywords = ["beat", "better", "growth", "strong", "rise",
                            "gain", "surplus", "positive", "above forecast"]
        bearish_keywords = ["miss", "weak", "fall", "drop", "below",
                            "cut", "deficit", "negative", "rate hike", "hike"]

        bullish = 0
        bearish = 0

        # Check currency relevance for the pair
        currencies = pair.replace("/", "").upper()

        for event in events:
            name = event.get("event", "").lower()
            currency = event.get("currency", "").upper()

            # Only score events relevant to this pair's currencies
            if currency and currency not in currencies:
                continue

            for kw in bullish_keywords:
                if kw in name:
                    bullish += 1
                    break
            for kw in bearish_keywords:
                if kw in name:
                    bearish += 1
                    break

        # Label
        if bullish == 0 and bearish == 0:
            label = "NEUTRAL"
        elif bullish > bearish * 1.5:
            label = "BULLISH"
        elif bearish > bullish * 1.5:
            label = "BEARISH"
        else:
            label = "MIXED"

        return bullish, bearish, label

    except Exception:
        return 0, 0, "NEUTRAL"


# ── NEW: TP Reachability Check ────────────────────────────────────────────────

def _check_tp_reachable(
    direction: str,
    entry: float,
    tp1: float,
    support: float,
    resistance: float,
    atr: float,
    pair: str,
) -> tuple:
    """
    Returns (is_reachable: bool, reason: str).

    Logic:
    - BUY: tp1 must be below resistance (not blocked by it)
    - SELL: tp1 must be above support (not blocked by it)
    - TP distance must be achievable (not more than 3x ATR away)
    """
    max_tp_distance = atr * 3.0  # TP shouldn't be more than 3x ATR away

    if direction == "BUY":
        tp_distance = tp1 - entry
        # Check if resistance blocks TP
        if resistance > entry and resistance < tp1:
            gap = resistance - entry
            if gap < tp_distance * 0.6:
                return False, f"Resistance at {resistance:.{decimal_places(pair, entry)}f} blocks TP1"
        # Check if TP is too far
        if tp_distance > max_tp_distance:
            return False, f"TP1 distance ({price_to_pips(pair, entry, tp1):.0f} pips) exceeds 3x ATR — unreachable in session"

    else:  # SELL
        tp_distance = entry - tp1
        # Check if support blocks TP
        if support < entry and support > tp1:
            gap = entry - support
            if gap < tp_distance * 0.6:
                return False, f"Support at {support:.{decimal_places(pair, entry)}f} blocks TP1"
        # Check if TP is too far
        if tp_distance > max_tp_distance:
            return False, f"TP1 distance ({price_to_pips(pair, entry, tp1):.0f} pips) exceeds 3x ATR — unreachable in session"

    return True, ""


# ── Main analysis ─────────────────────────────────────────────────────────────

async def analyze_pair(pair: str, tf_data: dict, balance: float):
    """
    Full analysis of one pair across all timeframes.
    Returns a Signal object or None.
    """
    from news_filter import check_news_block

    no_trade_reasons = []
    warnings         = []
    confidence_penalty = 0

    # ── Compute indicators ───────────────────────────────────────────
    try:
        processed = {tf: compute_indicators(df.copy()) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicators error: {e}")
        return None

    # ── News gate (hard) ─────────────────────────────────────────────
    news_blocked, news_reason = await check_news_block(pair)
    if news_blocked:
        no_trade_reasons.append(news_reason)

    # ── News sentiment (soft — affects confidence) ───────────────────
    news_bullish, news_bearish, news_sentiment = await _score_news_sentiment(pair)

    # ── 1H for primary analysis ──────────────────────────────────────
    df_1h = processed.get("1h") or processed.get("4h") or list(processed.values())[-1]
    row   = df_1h.iloc[-1]
    close = float(row["close"])
    dec   = decimal_places(pair, close)

    # ── Direction from MTF vote ──────────────────────────────────────
    tf_buy_votes  = 0
    tf_sell_votes = 0
    for tf, df in processed.items():
        r      = df.iloc[-1]
        bv, sv, _ = score_indicators(r, "BUY")
        if bv > sv:   tf_buy_votes  += 1
        elif sv > bv: tf_sell_votes += 1

    total_tfs   = len(processed)
    direction   = "BUY" if tf_buy_votes >= tf_sell_votes else "SELL"
    mtf_aligned = abs(tf_buy_votes - tf_sell_votes) >= 2

    # ── News sentiment vs direction conflict ─────────────────────────
    if news_sentiment == "BEARISH" and direction == "BUY":
        warnings.append(f"⚠️ News sentiment bearish ({news_bearish} events) — conflicts with BUY")
        confidence_penalty += 8
    elif news_sentiment == "BULLISH" and direction == "SELL":
        warnings.append(f"⚠️ News sentiment bullish ({news_bullish} events) — conflicts with SELL")
        confidence_penalty += 8
    elif news_sentiment == "MIXED":
        warnings.append("⚠️ Mixed news sentiment — caution advised")
        confidence_penalty += 4

    # ── Daily trend check ────────────────────────────────────────────
    df_daily = processed.get("1day")
    if df_daily is not None:
        r_daily       = df_daily.iloc[-1]
        bv_d, sv_d, _ = score_indicators(r_daily, direction)
        daily_adx     = float(r_daily.get("adx", 0))
        counter_trend = (direction == "BUY" and sv_d > bv_d) or \
                        (direction == "SELL" and bv_d > sv_d)
        if counter_trend:
            if daily_adx > 25:
                no_trade_reasons.append(
                    f"📉 Strong daily trend opposes {direction} (ADX {daily_adx:.0f})"
                )
            else:
                warnings.append(f"⚠️ Daily trend leans against {direction} (weak, ADX {daily_adx:.0f})")
                confidence_penalty += 10

    # ── Score on 1H ──────────────────────────────────────────────────
    buy_votes, sell_votes, ind_signals = score_indicators(row, direction)
    confluence = buy_votes if direction == "BUY" else sell_votes

    # ── Confidence % ─────────────────────────────────────────────────
    tf_agree   = tf_buy_votes if direction == "BUY" else tf_sell_votes
    confidence = int(((confluence / 8) * 0.5 + (tf_agree / total_tfs) * 0.5) * 100)
    confidence = max(0, confidence - confidence_penalty)
    confidence = min(confidence, 99)

    # ── Minimum confluence gate ──────────────────────────────────────
    if confluence < 3:
        no_trade_reasons.append(f"📊 Only {confluence}/8 indicators confirm — need ≥3")

    # ── S/R check ────────────────────────────────────────────────────
    support, resistance = support_resistance(df_1h)
    warn_threshold = 0.003
    hard_threshold = 0.001

    if direction == "BUY":
        dist_pct = (resistance - close) / close if close > 0 else 1
        if dist_pct < hard_threshold:
            no_trade_reasons.append(f"⚠️ Entry sitting on resistance ({resistance:.{dec}f})")
        elif dist_pct < warn_threshold:
            warnings.append(f"⚠️ Entry near resistance ({resistance:.{dec}f})")
            confidence_penalty += 5
            confidence = max(0, confidence - 5)
    else:
        dist_pct = (close - support) / close if close > 0 else 1
        if dist_pct < hard_threshold:
            no_trade_reasons.append(f"⚠️ Entry sitting on support ({support:.{dec}f})")
        elif dist_pct < warn_threshold:
            warnings.append(f"⚠️ Entry near support ({support:.{dec}f})")
            confidence_penalty += 5
            confidence = max(0, confidence - 5)

    # ── Confidence floor ─────────────────────────────────────────────
    if confidence < 40:
        no_trade_reasons.append(f"📊 Combined confidence too low ({confidence}%) — need ≥40%")

    # ── ATR-based SL/TP ──────────────────────────────────────────────
    atr     = max(float(row["atr"]), close * 0.001)
    sl_dist = atr * 1.5

    if direction == "BUY":
        sl          = round(close - sl_dist, dec)
        partial_tp  = round(close + sl_dist * 0.5, dec)
        tp1         = round(close + sl_dist * 1.0, dec)
        tp2         = round(close + sl_dist * 2.0, dec)
        tp3         = round(close + sl_dist * 3.0, dec)
        invalidation= round(sl - sl_dist * 0.5, dec)
    else:
        sl          = round(close + sl_dist, dec)
        partial_tp  = round(close - sl_dist * 0.5, dec)
        tp1         = round(close - sl_dist * 1.0, dec)
        tp2         = round(close - sl_dist * 2.0, dec)
        tp3         = round(close - sl_dist * 3.0, dec)
        invalidation= round(sl + sl_dist * 0.5, dec)

    sl_pips  = price_to_pips(pair, close, sl)
    tp1_pips = price_to_pips(pair, close, tp1)
    tp2_pips = price_to_pips(pair, close, tp2)
    tp3_pips = price_to_pips(pair, close, tp3)
    rr       = round(tp2_pips / sl_pips, 1) if sl_pips > 0 else 0
    lot      = calc_lot(pair, sl_pips, balance, close)
    risk_usd = round(balance * RISK_PERCENT / 100, 2)

    # ── NEW: TP Reachability Check ───────────────────────────────────
    tp_reachable, tp_reach_reason = _check_tp_reachable(
        direction, close, tp1, support, resistance, atr, pair
    )
    if not tp_reachable:
        no_trade_reasons.append(f"🎯 TP unreachable: {tp_reach_reason}")

    # ── Market regime ─────────────────────────────────────────────────
    trend, volatility = market_regime(df_1h)

    # ── Session ───────────────────────────────────────────────────────
    session_name, is_active = get_current_session()
    if "Overlap" in session_name:
        session_quality = "High ✅"
    elif is_active:
        session_quality = "Medium"
    else:
        session_quality = "Low"

    # ── Candle pattern ────────────────────────────────────────────────
    candle = detect_candle_pattern(df_1h)

    # ── Asset type ────────────────────────────────────────────────────
    if is_gold(pair):     asset_type = "GOLD 🥇"
    elif is_crypto(pair): asset_type = "CRYPTO ₿"
    else:                 asset_type = "FOREX 💱"

    return Signal(
        pair=pair,
        symbol=pair,
        direction=direction,
        confidence=confidence,
        confluence=confluence,
        mtf_aligned=mtf_aligned,
        entry=round(close, dec),
        sl=sl,
        tp1=tp1, tp2=tp2, tp3=tp3,
        partial_tp=partial_tp,
        invalidation=invalidation,
        sl_pips=sl_pips,
        tp1_pips=tp1_pips,
        tp2_pips=tp2_pips,
        tp3_pips=tp3_pips,
        rr_ratio=rr,
        lot_size=lot,
        risk_usd=risk_usd,
        asset_type=asset_type,
        trend=trend,
        volatility=volatility,
        session=session_name,
        session_quality=session_quality,
        adx=round(float(row["adx"]), 1),
        rsi=round(float(row["rsi"]), 2),
        macd_signal=ind_signals.get("macd", "NEUTRAL"),
        stoch_signal=ind_signals.get("stoch", "NEUTRAL"),
        cci_signal=ind_signals.get("cci", "NEUTRAL"),
        williams_signal=ind_signals.get("williams", "NEUTRAL"),
        bb_signal=ind_signals.get("bb", "NEUTRAL"),
        candle_pattern=candle,
        news_blocked=news_blocked,
        news_reason=news_reason,
        news_bullish=news_bullish,
        news_bearish=news_bearish,
        news_sentiment=news_sentiment,
        tp_reachable=tp_reachable,
        tp_reach_reason=tp_reach_reason,
        no_trade=len(no_trade_reasons) > 0,
        no_trade_reasons=no_trade_reasons,
        warnings=warnings,
    )


async def scan_pairs(data_map: dict, balance: float) -> list:
    """Scan all pairs and return valid signals sorted by confidence."""
    signals = []
    for pair, tfs in data_map.items():
        try:
            sig = await analyze_pair(pair, tfs, balance)
            if sig and not sig.no_trade:
                signals.append(sig)
        except Exception as e:
            logger.warning(f"{pair} error: {e}")
    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


async def force_scan_pairs(data_map: dict, balance: float) -> list:
    """Force signals for crypto — ignores NO TRADE gates."""
    signals = []
    for pair, tfs in data_map.items():
        try:
            sig = await analyze_pair(pair, tfs, balance)
            if sig:
                sig.no_trade = False
                sig.no_trade_reasons = []
                signals.append(sig)
        except Exception as e:
            logger.warning(f"{pair} error: {e}")
    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals
