import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from indicators import compute_indicators, support_resistance, detect_candle_pattern
from config import (
    RISK_PERCENT, CRYPTO_PAIRS, DEFAULT_RR_RATIO,
    CONFIDENCE_THRESHOLD, MIN_CONFLUENCE, REQUIRE_MTF_ALIGNED,
)
from session_manager import get_current_session

logger = logging.getLogger(__name__)

GOLD_PAIRS   = {"XAU/USD", "XAUUSD"}
SILVER_PAIRS = {"XAG/USD", "XAGUSD"}


@dataclass
class Signal:
    pair:             str
    direction:        str
    confidence:       int
    confluence:       int
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
    asset_type:       str
    trend:            str
    volatility:       str
    session:          str
    session_quality:  str
    adx:              float
    rsi:              float
    macd_signal:      str
    stoch_signal:     str
    cci_signal:       str
    williams_signal:  str
    bb_signal:        str
    candle_pattern:   str
    tf_breakdown:     dict  = field(default_factory=dict)   # NEW: per-TF summary
    news_blocked:     bool  = False
    news_reason:      str   = ""
    news_bullish:     int   = 0
    news_bearish:     int   = 0
    news_sentiment:   str   = ""
    tp_reachable:     bool  = True
    tp_reach_reason:  str   = ""
    no_trade:         bool  = False
    no_trade_reasons: list  = field(default_factory=list)
    warnings:         list  = field(default_factory=list)
    symbol:           str   = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_crypto(pair: str) -> bool:
    return pair in CRYPTO_PAIRS

def is_gold(pair: str) -> bool:
    return pair.upper().replace("/", "") in {"XAUUSD"}

def is_silver(pair: str) -> bool:
    return pair.upper().replace("/", "") in {"XAGUSD"}

def pip_value(pair: str, price: float) -> float:
    if is_crypto(pair): return 1.0
    if is_gold(pair):   return 0.1
    # NOTE: 0.01 assumed for XAG/USD (silver ~$28-35 range) — verify against
    # actual TwelveData tick size for XAG/USD before relying on this in live risk calcs.
    if is_silver(pair): return 0.01
    return 0.01 if "JPY" in pair else 0.0001

def price_to_pips(pair: str, a: float, b: float) -> float:
    return round(abs(a - b) / pip_value(pair, (a + b) / 2), 1)

def calc_lot(pair: str, sl_pips: float, balance: float, price: float) -> float:
    risk_usd = balance * RISK_PERCENT / 100
    if is_crypto(pair):
        return round(risk_usd / max(sl_pips, 0.01), 4)
    if is_gold(pair):
        return max(0.01, round(risk_usd / (sl_pips * 1.0), 2))
    if is_silver(pair):
        # NOTE: using same $/pip-unit assumption as gold for now — confirm
        # actual contract sizing for XAG/USD before trusting position sizing.
        return max(0.01, round(risk_usd / (sl_pips * 1.0), 2))
    pip_usd = 10 if "JPY" not in pair else 9.09
    return max(0.01, round(risk_usd / (sl_pips * pip_usd), 2))

def decimal_places(pair: str, price: float) -> int:
    if is_crypto(pair) and price > 100: return 2
    if is_gold(pair): return 2
    if is_silver(pair): return 2
    if "JPY" in pair: return 3
    return 5


# ── Indicator scoring ─────────────────────────────────────────────────────────

def score_indicators(row, direction: str) -> tuple:
    """
    Score all 8 indicators. Returns (buy_votes, sell_votes, signals_dict).

    RSI LOGIC (FIXED):
      <30          → oversold      → BUY
      30–45        → recovering    → BUY
      45–55        → neutral
      55–70        → bullish momentum → BUY   ← was wrongly SELL before
      >70          → overbought   → SELL
    """
    def get(key):
        val = row[key] if hasattr(row, '__getitem__') else getattr(row, key)
        if isinstance(val, pd.Series):
            val = val.iloc[0]
        return float(val)

    buy_votes  = 0
    sell_votes = 0
    signals    = {}

    # ── RSI (FIXED) ──────────────────────────────────────────────────
    rsi = get("rsi")
    if rsi < 30:
        buy_votes  += 1; signals["rsi"] = "BUY"       # oversold
    elif 30 <= rsi < 45:
        buy_votes  += 1; signals["rsi"] = "BUY"       # recovering
    elif 45 <= rsi <= 55:
        signals["rsi"] = "NEUTRAL"
    elif 55 < rsi <= 70:
        buy_votes  += 1; signals["rsi"] = "BUY"       # ← FIXED (was SELL)
    else:  # rsi > 70
        sell_votes += 1; signals["rsi"] = "SELL"      # overbought

    # ── MACD ─────────────────────────────────────────────────────────
    macd      = get("macd")
    macd_sig  = get("macd_signal")
    macd_hist = get("macd_hist")
    if macd > macd_sig and macd_hist > 0:
        buy_votes  += 1; signals["macd"] = "BUY"
    elif macd < macd_sig and macd_hist < 0:
        sell_votes += 1; signals["macd"] = "SELL"
    else:
        signals["macd"] = "NEUTRAL"

    # ── Stochastic ───────────────────────────────────────────────────
    k = get("stoch_k")
    d = get("stoch_d")
    if k > d and k < 80:
        buy_votes  += 1; signals["stoch"] = "BUY"
    elif k < d and k > 20:
        sell_votes += 1; signals["stoch"] = "SELL"
    else:
        signals["stoch"] = "NEUTRAL"

    # ── Bollinger Bands ───────────────────────────────────────────────
    bb = get("bb_pct")
    if bb < 0.2:
        buy_votes  += 1; signals["bb"] = "BUY"
    elif bb > 0.8:
        sell_votes += 1; signals["bb"] = "SELL"
    else:
        signals["bb"] = "NEUTRAL"

    signals["atr"] = "NEUTRAL"

    # ── ADX / DI ─────────────────────────────────────────────────────
    adx      = get("adx")
    plus_di  = get("plus_di")
    minus_di = get("minus_di")
    if adx > 25 and plus_di > minus_di:
        buy_votes  += 1; signals["adx"] = "BUY"
    elif adx > 25 and minus_di > plus_di:
        sell_votes += 1; signals["adx"] = "SELL"
    else:
        signals["adx"] = "NEUTRAL"

    # ── CCI ───────────────────────────────────────────────────────────
    cci = get("cci")
    if cci < -100:
        buy_votes  += 1; signals["cci"] = "BUY"
    elif cci > 100:
        sell_votes += 1; signals["cci"] = "SELL"
    else:
        signals["cci"] = "NEUTRAL"

    # ── Williams %R ───────────────────────────────────────────────────
    wr = get("williams_r")
    if wr < -80:
        buy_votes  += 1; signals["williams"] = "BUY"
    elif wr > -20:
        sell_votes += 1; signals["williams"] = "SELL"
    else:
        signals["williams"] = "NEUTRAL"

    return buy_votes, sell_votes, signals


def market_regime(df: pd.DataFrame) -> tuple:
    row   = df.iloc[-1]
    e9    = float(row["ema9"])
    e21   = float(row["ema21"])
    e50   = float(row["ema50"])
    e200  = float(row["ema200"])
    adx   = float(row["adx"])
    atr   = float(row["atr"])
    close = float(row["close"])

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


async def _score_news_sentiment(pair: str) -> tuple:
    try:
        from news_filter import get_upcoming_events
        events = await get_upcoming_events(hours=12)
        bullish_kw = ["beat","better","growth","strong","rise","gain","surplus","positive","above forecast"]
        bearish_kw = ["miss","weak","fall","drop","below","cut","deficit","negative","rate hike","hike"]
        bullish    = 0
        bearish    = 0
        currencies = pair.replace("/","").upper()
        for event in events:
            name     = event.get("event","").lower()
            currency = event.get("currency","").upper()
            if currency and currency not in currencies:
                continue
            for kw in bullish_kw:
                if kw in name: bullish += 1; break
            for kw in bearish_kw:
                if kw in name: bearish += 1; break
        if bullish == 0 and bearish == 0:   label = "NEUTRAL"
        elif bullish > bearish * 1.5:       label = "BULLISH"
        elif bearish > bullish * 1.5:       label = "BEARISH"
        else:                               label = "MIXED"
        return bullish, bearish, label
    except Exception:
        return 0, 0, "NEUTRAL"


def _check_tp_reachable(direction, entry, tp1, support, resistance, atr, pair):
    if direction == "BUY":
        tp_distance = tp1 - entry
        if resistance > entry and resistance < tp1:
            gap = resistance - entry
            if gap < tp_distance * 0.4:
                return False, f"Resistance at {resistance:.{decimal_places(pair, entry)}f} blocks TP1"
    else:
        tp_distance = entry - tp1
        if support < entry and support > tp1:
            gap = entry - support
            if gap < tp_distance * 0.4:
                return False, f"Support at {support:.{decimal_places(pair, entry)}f} blocks TP1"
    return True, ""


# ── Per-timeframe breakdown ───────────────────────────────────────────────────

TF_LABELS = {
    "15m":  "15M",
    "1h":   "1H",
    "4h":   "4H",
    "1day": "D1",
}

def build_tf_breakdown(processed: dict) -> dict:
    """
    For each timeframe, score indicators and return a summary dict:
      { "1H": {"direction": "BUY", "votes": "5/8", "rsi": 62.1, "adx": 28.4} }
    """
    breakdown = {}
    tf_order  = ["15m", "1h", "4h", "1day"]

    for tf in tf_order:
        if tf not in processed:
            continue
        df  = processed[tf]
        row = df.iloc[-1]
        bv, sv, sigs = score_indicators(row, "BUY")
        direction = "BUY" if bv >= sv else "SELL"
        votes     = bv if direction == "BUY" else sv
        label     = TF_LABELS.get(tf, tf.upper())
        breakdown[label] = {
            "direction": direction,
            "votes":     f"{votes}/8",
            "rsi":       round(float(row["rsi"]), 1),
            "adx":       round(float(row["adx"]), 1),
            "agree":     True,   # filled in later vs final direction
        }
    return breakdown


def format_tf_breakdown(breakdown: dict, final_direction: str) -> str:
    """Formats breakdown for Telegram message."""
    lines = []
    for tf_label, info in breakdown.items():
        agrees = info["direction"] == final_direction
        icon   = "✅" if agrees else "❌"
        lines.append(
            f"  {icon} *{tf_label}*: {info['direction']} "
            f"({info['votes']}) | RSI {info['rsi']} | ADX {info['adx']}"
        )
    return "\n".join(lines)


# ── Daily EMA200 trend gate ───────────────────────────────────────────────────

def get_daily_bias(df_daily: pd.DataFrame) -> str:
    """
    Returns 'BUY', 'SELL', or 'NEUTRAL' based on daily EMA200 and EMA50.
    This is the higher-timeframe filter that should override short-term signals.
    """
    if df_daily is None or len(df_daily) < 2:
        return "NEUTRAL"
    row   = df_daily.iloc[-1]
    close = float(row["close"])
    e50   = float(row["ema50"])
    e200  = float(row["ema200"])
    adx   = float(row["adx"])

    if close > e200 and e50 > e200:
        return "BUY"
    elif close < e200 and e50 < e200:
        return "SELL"
    return "NEUTRAL"


# ── Main analysis ─────────────────────────────────────────────────────────────

async def analyze_pair(pair: str, tf_data: dict, balance: float):
    from news_filter import check_news_block

    no_trade_reasons   = []
    warnings           = []
    confidence_penalty = 0
    crypto             = is_crypto(pair)
    gold               = is_gold(pair)
    silver             = is_silver(pair)

    try:
        processed = {tf: compute_indicators(df.copy()) for tf, df in tf_data.items()}
    except Exception as e:
        logger.warning(f"{pair} indicators error: {e}")
        return None

    # ── News gate ────────────────────────────────────────────────────
    news_blocked, news_reason = await check_news_block(pair)
    if news_blocked and not crypto:
        no_trade_reasons.append(news_reason)
    elif news_blocked and crypto:
        warnings.append(f"📰 News caution: {news_reason}")
        confidence_penalty += 5

    # ── News sentiment ───────────────────────────────────────────────
    news_bullish, news_bearish, news_sentiment = await _score_news_sentiment(pair)

    # ── 1H primary ───────────────────────────────────────────────────
    if "1h" in processed:
        df_1h = processed["1h"]
    elif "4h" in processed:
        df_1h = processed["4h"]
    else:
        df_1h = list(processed.values())[-1]
    row   = df_1h.iloc[-1]
    close = float(row["close"])
    dec   = decimal_places(pair, close)

    # ── MTF vote ─────────────────────────────────────────────────────
    tf_buy_votes  = 0
    tf_sell_votes = 0
    for tf, df in processed.items():
        if tf == "1day":
            continue   # exclude daily from vote — used as filter only
        r      = df.iloc[-1]
        bv, sv, _ = score_indicators(r, "BUY")
        if bv > sv:   tf_buy_votes  += 1
        elif sv > bv: tf_sell_votes += 1

    total_tfs   = max(len(processed) - 1, 1)   # exclude 1day from denominator
    direction   = "BUY" if tf_buy_votes >= tf_sell_votes else "SELL"
    mtf_aligned = abs(tf_buy_votes - tf_sell_votes) >= 2

    # ── Per-TF breakdown ─────────────────────────────────────────────
    tf_breakdown = build_tf_breakdown(processed)
    for tf_label, info in tf_breakdown.items():
        info["agree"] = (info["direction"] == direction)

    # ── Daily EMA200 trend gate (STRONGER) ───────────────────────────
    df_daily   = processed.get("1day")
    daily_bias = get_daily_bias(df_daily)

    if daily_bias != "NEUTRAL" and daily_bias != direction:
        if gold:
            # Gold: HARD block counter-trend — daily EMA200 is law for XAU/USD
            no_trade_reasons.append(
                f"🚫 Daily trend is {daily_bias} — {direction} trades on gold are blocked"
            )
        else:
            # Forex/Crypto/Silver: heavy penalty, warn
            warnings.append(
                f"⚠️ Daily EMA200 bias is {daily_bias} — conflicts with {direction}"
            )
            confidence_penalty += 20

    elif df_daily is not None:
        # Even if daily matches, check the legacy indicator vote for fine-tuning
        r_daily       = df_daily.iloc[-1]
        bv_d, sv_d, _ = score_indicators(r_daily, direction)
        daily_adx     = float(r_daily["adx"])
        counter_trend = (direction == "BUY" and sv_d > bv_d) or \
                        (direction == "SELL" and bv_d > sv_d)
        if counter_trend and daily_adx > 25 and not crypto:
            warnings.append(
                f"⚠️ Daily indicators lean against {direction} (ADX {daily_adx:.0f})"
            )
            confidence_penalty += 10

    # ── News conflict ────────────────────────────────────────────────
    if news_sentiment == "BEARISH" and direction == "BUY":
        warnings.append("⚠️ News sentiment bearish — conflicts with BUY")
        confidence_penalty += 8
    elif news_sentiment == "BULLISH" and direction == "SELL":
        warnings.append("⚠️ News sentiment bullish — conflicts with SELL")
        confidence_penalty += 8
    elif news_sentiment == "MIXED":
        warnings.append("⚠️ Mixed news sentiment — caution")
        confidence_penalty += 4

    # ── Score on 1H ──────────────────────────────────────────────────
    buy_votes, sell_votes, ind_signals = score_indicators(row, direction)
    confluence = buy_votes if direction == "BUY" else sell_votes

    # ── Confidence ───────────────────────────────────────────────────
    tf_agree   = tf_buy_votes if direction == "BUY" else tf_sell_votes
    confidence = int(((confluence / 8) * 0.5 + (tf_agree / total_tfs) * 0.5) * 100)
    confidence = max(0, confidence - confidence_penalty)
    confidence = min(confidence, 99)

    # ── Confluence gate (config-driven) ───────────────────────────────
    if confluence < MIN_CONFLUENCE:
        no_trade_reasons.append(
            f"📊 Only {confluence}/8 indicators confirm — need ≥{MIN_CONFLUENCE}"
        )

    # ── MTF alignment gate (config-driven, NEW) ───────────────────────
    if REQUIRE_MTF_ALIGNED and not mtf_aligned:
        no_trade_reasons.append(
            f"📊 Timeframes not aligned (BUY {tf_buy_votes} vs SELL {tf_sell_votes}) — MTF alignment required"
        )

    # ── S/R check ────────────────────────────────────────────────────
    support, resistance = support_resistance(df_1h)
    support    = float(support)
    resistance = float(resistance)

    if direction == "BUY":
        dist_pct = (resistance - close) / close if close > 0 else 1
        if dist_pct < 0.001:
            no_trade_reasons.append(f"⚠️ Entry on resistance ({resistance:.{dec}f})")
        elif dist_pct < 0.003:
            warnings.append(f"⚠️ Entry near resistance ({resistance:.{dec}f})")
            confidence = max(0, confidence - 5)
    else:
        dist_pct = (close - support) / close if close > 0 else 1
        if dist_pct < 0.001:
            no_trade_reasons.append(f"⚠️ Entry on support ({support:.{dec}f})")
        elif dist_pct < 0.003:
            warnings.append(f"⚠️ Entry near support ({support:.{dec}f})")
            confidence = max(0, confidence - 5)

    # ── Confidence floor (absolute safety floor — unchanged) ─────────
    if confidence < 30:
        no_trade_reasons.append(f"📊 Confidence too low ({confidence}%) — need ≥30%")

    # ── Confidence threshold gate (config-driven, NEW) ────────────────
    # This is the "quality bar" knob from config.py. If bot.py already
    # compares against CONFIDENCE_THRESHOLD before sending, this makes
    # the gate redundant-but-harmless (stricter of the two wins). If
    # bot.py does NOT check it, this is now the single source of truth.
    if confidence < CONFIDENCE_THRESHOLD:
        no_trade_reasons.append(
            f"📊 Confidence below threshold ({confidence}% < {CONFIDENCE_THRESHOLD}%)"
        )

    # ── SL/TP ────────────────────────────────────────────────────────
    atr     = max(float(row["atr"]), close * 0.001)
    sl_dist = atr * 1.5

    if direction == "BUY":
        sl           = round(close - sl_dist, dec)
        partial_tp   = round(close + sl_dist * 0.5, dec)
        tp1          = round(close + sl_dist * 1.0, dec)
        tp2          = round(close + sl_dist * 2.0, dec)
        tp3          = round(close + sl_dist * 3.0, dec)
        invalidation = round(sl - sl_dist * 0.5, dec)
    else:
        sl           = round(close + sl_dist, dec)
        partial_tp   = round(close - sl_dist * 0.5, dec)
        tp1          = round(close - sl_dist * 1.0, dec)
        tp2          = round(close - sl_dist * 2.0, dec)
        tp3          = round(close - sl_dist * 3.0, dec)
        invalidation = round(sl + sl_dist * 0.5, dec)

    sl_pips  = price_to_pips(pair, close, sl)
    tp1_pips = price_to_pips(pair, close, tp1)
    tp2_pips = price_to_pips(pair, close, tp2)
    tp3_pips = price_to_pips(pair, close, tp3)
    rr       = round(tp2_pips / sl_pips, 1) if sl_pips > 0 else 0
    lot      = calc_lot(pair, sl_pips, balance, close)
    risk_usd = round(balance * RISK_PERCENT / 100, 2)

    # ── TP Reachability ───────────────────────────────────────────────
    tp_reachable, tp_reach_reason = _check_tp_reachable(
        direction, close, tp1, support, resistance, atr, pair
    )
    if not tp_reachable:
        warnings.append(f"🎯 {tp_reach_reason}")
        confidence   = max(0, confidence - 8)
        tp_reachable = True

    # ── Market regime ─────────────────────────────────────────────────
    trend, volatility = market_regime(df_1h)

    # ── Session ───────────────────────────────────────────────────────
    session_name, is_active = get_current_session()
    if "Overlap" in session_name:    session_quality = "High ✅"
    elif is_active:                  session_quality = "Medium"
    else:                            session_quality = "Low"

    # ── Candle pattern ────────────────────────────────────────────────
    candle = detect_candle_pattern(df_1h)

    # ── Asset type ────────────────────────────────────────────────────
    if gold:               asset_type = "GOLD 🥇"
    elif silver:           asset_type = "SILVER 🥈"
    elif is_crypto(pair):  asset_type = "CRYPTO ₿"
    else:                  asset_type = "FOREX 💱"

    return Signal(
        pair=pair, symbol=pair,
        direction=direction,
        confidence=confidence,
        confluence=confluence,
        mtf_aligned=mtf_aligned,
        entry=round(close, dec),
        sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
        partial_tp=partial_tp,
        invalidation=invalidation,
        sl_pips=sl_pips, tp1_pips=tp1_pips,
        tp2_pips=tp2_pips, tp3_pips=tp3_pips,
        rr_ratio=rr, lot_size=lot, risk_usd=risk_usd,
        asset_type=asset_type,
        trend=trend, volatility=volatility,
        session=session_name, session_quality=session_quality,
        adx=round(float(row["adx"]), 1),
        rsi=round(float(row["rsi"]), 2),
        macd_signal=ind_signals.get("macd", "NEUTRAL"),
        stoch_signal=ind_signals.get("stoch", "NEUTRAL"),
        cci_signal=ind_signals.get("cci", "NEUTRAL"),
        williams_signal=ind_signals.get("williams", "NEUTRAL"),
        bb_signal=ind_signals.get("bb", "NEUTRAL"),
        candle_pattern=candle,
        tf_breakdown=tf_breakdown,
        news_blocked=news_blocked, news_reason=news_reason,
        news_bullish=news_bullish, news_bearish=news_bearish,
        news_sentiment=news_sentiment,
        tp_reachable=tp_reachable, tp_reach_reason=tp_reach_reason,
        no_trade=len(no_trade_reasons) > 0,
        no_trade_reasons=no_trade_reasons,
        warnings=warnings,
    )


async def scan_pairs(data_map: dict, balance: float) -> list:
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
    signals = []
    for pair, tfs in data_map.items():
        try:
            sig = await analyze_pair(pair, tfs, balance)
            if sig:
                sig.no_trade         = False
                sig.no_trade_reasons = []
                signals.append(sig)
        except Exception as e:
            logger.warning(f"{pair} error: {e}")
    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals
