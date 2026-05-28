import os
import requests
import time
import schedule
import threading
from datetime import datetime, timezone
import json

# ── ENV VARS ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")
GEMINI_KEY      = os.getenv("GEMINI_KEY")
CHAT_ID         = os.getenv("CHAT_ID")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ✅ 10 PAIRS
PAIRS = [
    "EUR/USD", "GBP/USD", "USD/CAD", "USD/JPY", "AUD/USD",
    "EUR/GBP", "USD/CHF", "NZD/USD", "GBP/JPY", "EUR/JPY"
]

# ── USER SETTINGS ─────────────────────────────────────────────────────────────
user_settings: dict[str, dict] = {}
# Tracks users waiting to enter account/risk before signal
pending_signal: dict[str, dict] = {}

def get_settings(chat_id: str) -> dict:
    cid = str(chat_id)
    if cid not in user_settings:
        user_settings[cid] = {"account": None, "risk_pct": None}
    return user_settings[cid]

# ── PRICE ALERTS ──────────────────────────────────────────────────────────────
price_alerts: list[dict] = []

def check_price_alerts():
    while True:
        triggered = []
        for alert in price_alerts:
            try:
                candles = get_candles(alert["pair"], "5min", 1)
                if not candles:
                    continue
                current_price = float(candles[0]["close"])
                hit = (
                    (alert["direction"] == "above" and current_price >= alert["price"]) or
                    (alert["direction"] == "below" and current_price <= alert["price"])
                )
                if hit:
                    send_message(alert["chat_id"],
                        f"🔔 *PRICE ALERT TRIGGERED!*\n\n"
                        f"*{alert['pair']}* has reached *{current_price}*\n"
                        f"Your alert was set at *{alert['price']}*\n\n"
                        f"⚡ Run `/analyze {alert['pair'].replace('/', '')}` now!"
                    )
                    triggered.append(alert)
            except Exception as e:
                print(f"[check_price_alerts] error: {e}")
        for t in triggered:
            price_alerts.remove(t)
        time.sleep(60)

# ── TELEGRAM HELPERS ──────────────────────────────────────────────────────────
def send_message(chat_id, text: str):
    try:
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id":    chat_id,
            "text":       text,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        print(f"[send_message] error: {e}")

def get_updates(offset=None):
    try:
        r = requests.get(f"{BASE_URL}/getUpdates",
                         params={"timeout": 30, "offset": offset},
                         timeout=35)
        return r.json()
    except Exception as e:
        print(f"[get_updates] error: {e}")
        return {"ok": False}

# ── MARKET DATA ───────────────────────────────────────────────────────────────
def get_candles(pair: str, interval: str = "1day", size: int = 50):
    try:
        r = requests.get("https://api.twelvedata.com/time_series", params={
            "symbol":     pair,
            "interval":   interval,
            "outputsize": size,
            "apikey":     TWELVE_DATA_KEY
        }, timeout=10)
        data = r.json()
        if data.get("status") == "error":
            print(f"[get_candles] error for {pair}/{interval}: {data.get('message')}")
            return None
        return data.get("values")
    except Exception as e:
        print(f"[get_candles] exception: {e}")
        return None

# ── INDICATORS ────────────────────────────────────────────────────────────────
def calc_atr(candles: list, period: int = 14) -> float:
    trs = []
    for i in range(min(period, len(candles) - 1)):
        c          = candles[i]
        p          = candles[i + 1]
        high       = float(c["high"])
        low        = float(c["low"])
        prev_close = float(p["close"])
        tr = max(high - low,
                 abs(high - prev_close),
                 abs(low  - prev_close))
        trs.append(tr)
    return round(sum(trs) / len(trs), 5) if trs else 0.0

def calc_ema(closes: list, period: int) -> float:
    if len(closes) < period:
        return 0.0
    k   = 2 / (period + 1)
    ema = sum(closes[-period:]) / period
    for price in reversed(closes[:-period]):
        ema = price * k + ema * (1 - k)
    return round(ema, 5)

def calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(period):
        change = closes[i] - closes[i + 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs  = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calc_macd(closes: list) -> tuple[float, float, float]:
    if len(closes) < 35:
        return 0.0, 0.0, 0.0
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd  = round(ema12 - ema26, 6)
    macd_history = []
    for i in range(9):
        e12 = calc_ema(closes[i:], 12)
        e26 = calc_ema(closes[i:], 26)
        macd_history.append(e12 - e26)
    signal    = round(sum(macd_history) / len(macd_history), 6)
    histogram = round(macd - signal, 6)
    return macd, signal, histogram

def calc_bollinger(closes: list, period: int = 20) -> tuple[float, float, float]:
    """
    Bollinger Bands — upper, middle, lower.
    Price near lower band = BUY zone.
    Price near upper band = SELL zone.
    """
    if len(closes) < period:
        return 0.0, 0.0, 0.0
    sma    = sum(closes[:period]) / period
    std    = (sum((c - sma) ** 2 for c in closes[:period]) / period) ** 0.5
    upper  = round(sma + 2 * std, 5)
    lower  = round(sma - 2 * std, 5)
    middle = round(sma, 5)
    return upper, middle, lower

def calc_stochastic(candles: list, k_period: int = 14) -> tuple[float, float]:
    """
    Stochastic Oscillator %K and %D.
    Below 20 = oversold (BUY).
    Above 80 = overbought (SELL).
    """
    if len(candles) < k_period:
        return 50.0, 50.0
    highs  = [float(c["high"])  for c in candles[:k_period]]
    lows   = [float(c["low"])   for c in candles[:k_period]]
    closes = [float(c["close"]) for c in candles[:k_period]]
    highest_high = max(highs)
    lowest_low   = min(lows)
    if highest_high == lowest_low:
        return 50.0, 50.0
    k = round(((closes[0] - lowest_low) / (highest_high - lowest_low)) * 100, 2)
    # %D = 3-period SMA of %K (simplified)
    k_values = []
    for i in range(min(3, len(candles) - k_period)):
        h = max(float(c["high"])  for c in candles[i:i + k_period])
        l = min(float(c["low"])   for c in candles[i:i + k_period])
        c = float(candles[i]["close"])
        if h != l:
            k_values.append(((c - l) / (h - l)) * 100)
    d = round(sum(k_values) / len(k_values), 2) if k_values else k
    return k, d

# ── SIGNAL LOGIC ──────────────────────────────────────────────────────────────
TIMEFRAME_CONFIG = {
    "5min":  {"interval": "5min",  "atr_sl_mult": 1.5, "atr_tp_mult": 2.5, "label": "5M",    "min_sl_pips": 5},
    "15min": {"interval": "15min", "atr_sl_mult": 1.5, "atr_tp_mult": 2.5, "label": "15M",   "min_sl_pips": 10},
    "1h":    {"interval": "1h",    "atr_sl_mult": 2.0, "atr_tp_mult": 3.0, "label": "1H",    "min_sl_pips": 15},
    "4h":    {"interval": "4h",    "atr_sl_mult": 2.0, "atr_tp_mult": 3.0, "label": "4H",    "min_sl_pips": 25},
    "1day":  {"interval": "1day",  "atr_sl_mult": 2.5, "atr_tp_mult": 4.0, "label": "Daily", "min_sl_pips": 40},
}

def analyze_tf(pair: str, interval: str) -> dict | None:
    cfg     = TIMEFRAME_CONFIG[interval]
    candles = get_candles(pair, cfg["interval"], 50)
    if not candles or len(candles) < 35:
        return None

    closes = [float(v["close"]) for v in candles]
    latest = candles[0]
    entry  = float(latest["close"])
    atr    = calc_atr(candles, 14)

    # ── ALL 5 INDICATORS ──────────────────────────────────────────────────────

    # 1. EMA Trend (9 > 21 > 50 = strong BUY trend)
    ema9  = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema50 = calc_ema(closes, 50)
    ema_buy  = ema9 > ema21 > ema50
    ema_sell = ema9 < ema21 < ema50

    # 2. MACD (line above signal + positive histogram = BUY)
    macd, signal_line, histogram = calc_macd(closes)
    macd_buy  = macd > signal_line and histogram > 0
    macd_sell = macd < signal_line and histogram < 0

    # 3. RSI (40-60 neutral zone, >50 = BUY bias, <50 = SELL bias)
    rsi      = calc_rsi(closes, 14)
    rsi_buy  = 50 < rsi < 75   # bullish but not overbought
    rsi_sell = 25 < rsi < 50   # bearish but not oversold

    # 4. Bollinger Bands (price near lower = BUY, near upper = SELL)
    bb_upper, bb_middle, bb_lower = calc_bollinger(closes, 20)
    bb_buy  = entry <= bb_middle  # price below midline = buy zone
    bb_sell = entry >= bb_middle  # price above midline = sell zone

    # 5. Stochastic (below 20 = BUY, above 80 = SELL)
    stoch_k, stoch_d = calc_stochastic(candles, 14)
    stoch_buy  = stoch_k < 50 and stoch_d < 50
    stoch_sell = stoch_k > 50 and stoch_d > 50

    # ── SCORE ALL 5 ───────────────────────────────────────────────────────────
    buy_confirmations = [
        ("EMA",        ema_buy),
        ("MACD",       macd_buy),
        ("RSI",        rsi_buy),
        ("Bollinger",  bb_buy),
        ("Stochastic", stoch_buy),
    ]
    sell_confirmations = [
        ("EMA",        ema_sell),
        ("MACD",       macd_sell),
        ("RSI",        rsi_sell),
        ("Bollinger",  bb_sell),
        ("Stochastic", stoch_sell),
    ]

    buy_score  = sum(1 for _, v in buy_confirmations  if v)
    sell_score = sum(1 for _, v in sell_confirmations if v)

    buy_indicators  = [n for n, v in buy_confirmations  if v]
    sell_indicators = [n for n, v in sell_confirmations if v]

    # ── DIRECTION ─────────────────────────────────────────────────────────────
    if buy_score > sell_score:
        direction   = "BUY"
        indicators  = buy_indicators
        score       = buy_score
    elif sell_score > buy_score:
        direction   = "SELL"
        indicators  = sell_indicators
        score       = sell_score
    else:
        direction   = "BUY" if ema9 > ema21 else "SELL"
        indicators  = []
        score       = 0

    # ── RSI EXTREME WARNING ───────────────────────────────────────────────────
    if rsi >= 75:
        warning = "⚠️ RSI overbought"
    elif rsi <= 25:
        warning = "⚠️ RSI oversold"
    else:
        warning = ""

    # ── SL / TP WITH MINIMUM PIPS ─────────────────────────────────────────────
    pip_size = 0.01 if "JPY" in pair else 0.0001
    min_sl   = cfg["min_sl_pips"] * pip_size
    sl_dist  = max(round(atr * cfg["atr_sl_mult"], 5), min_sl)
    tp_dist  = round(sl_dist * (cfg["atr_tp_mult"] / cfg["atr_sl_mult"]), 5)

    if direction == "BUY":
        sl = round(entry - sl_dist, 5)
        tp = round(entry + tp_dist, 5)
    else:
        sl = round(entry + sl_dist, 5)
        tp = round(entry - tp_dist, 5)

    change = round(
        ((float(candles[0]["close"]) - float(candles[1]["close"])) /
         float(candles[1]["close"])) * 100, 4
    )

    return {
        "label":      cfg["label"],
        "interval":   interval,
        "direction":  direction,
        "score":      score,
        "indicators": indicators,
        "entry":      entry,
        "tp":         tp,
        "sl":         sl,
        "atr":        atr,
        "ema9":       ema9,
        "ema21":      ema21,
        "ema50":      ema50,
        "rsi":        rsi,
        "macd":       macd,
        "signal":     signal_line,
        "histogram":  histogram,
        "bb_upper":   bb_upper,
        "bb_lower":   bb_lower,
        "stoch_k":    stoch_k,
        "stoch_d":    stoch_d,
        "warning":    warning,
        "change":     change,
        "high":       float(latest["high"]),
        "low":        float(latest["low"]),
        "buy_score":  buy_score,
        "sell_score": sell_score,
    }

def multi_tf_agree(results: list) -> tuple[str | None, list]:
    """✅ ALL timeframes must agree on direction."""
    if not results:
        return None, []
    buys  = [r for r in results if r["direction"] == "BUY"]
    sells = [r for r in results if r["direction"] == "SELL"]
    if len(buys) == len(results):
        return "BUY",  [r["label"] for r in buys]
    if len(sells) == len(results):
        return "SELL", [r["label"] for r in sells]
    return None, []

# ── LOT SIZE CALCULATOR ───────────────────────────────────────────────────────
def calc_lot_size(account: float, risk_pct: float,
                  sl_pips: float, pair: str) -> float:
    risk_amount = account * (risk_pct / 100)
    if sl_pips <= 0:
        return 0.01
    pip_value = 6.8 if "JPY" in pair else 10.0
    raw = risk_amount / (sl_pips * pip_value)
    return max(0.01, min(round(raw, 2), 5.0))

def pips(pair: str, price_dist: float) -> float:
    if "JPY" in pair:
        return round(price_dist / 0.01, 1)
    return round(price_dist / 0.0001, 1)

# ── CONFIDENCE SCORE ──────────────────────────────────────────────────────────
def get_confidence(results: list, direction: str) -> str:
    agreeing = sum(1 for r in results if r["direction"] == direction)
    total    = len(results)
    if agreeing == total:
        return "🔥 MAXIMUM — All TFs agree"
    elif agreeing >= 4:
        return "✅ VERY HIGH — 4/5 TFs agree"
    elif agreeing >= 3:
        return "⚠️ MEDIUM — 3/5 TFs agree"
    else:
        return "❌ LOW — Skip this trade"

# ── GEMINI AI ─────────────────────────────────────────────────────────────────
def ask_gemini(prompt: str) -> str:
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20
        )
        if r.status_code != 200:
            return "AI analysis unavailable right now."
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[Gemini] exception: {e}")
        return "AI analysis unavailable right now."

def get_news_summary(pair: str) -> str:
    prompt = (
        f"You are a senior forex analyst. In 3 plain-English sentences explain "
        f"the current market sentiment for {pair}. "
        f"Focus on: what is driving price, key risk events this week, "
        f"and what a retail trader must watch. No jargon. "
        f"End with: 'Watch for...' or 'Avoid trading when...'."
    )
    return ask_gemini(prompt)

# ── SIGNAL BUILDER ────────────────────────────────────────────────────────────
def build_signal(pair: str, account: float, risk_pct: float,
                 require_agreement: bool = True) -> str:

    results = []
    for tf in TIMEFRAME_CONFIG:
        r = analyze_tf(pair, tf)
        if r:
            results.append(r)
        time.sleep(0.5)

    if not results:
        return f"❌ Could not fetch data for *{pair}*"

    direction, agreeing = multi_tf_agree(results)

    if require_agreement and not direction:
        buys  = sum(1 for r in results if r["direction"] == "BUY")
        sells = sum(1 for r in results if r["direction"] == "SELL")
        # Show which TFs disagreed
        detail = "\n".join(
            f"  {'✅' if r['direction']=='BUY' else '🔴'} {r['label']}: "
            f"{r['direction']} ({r['buy_score'] if r['direction']=='BUY' else r['sell_score']}/5 indicators)"
            for r in results
        )
        return (
            f"⛔ *{pair}* — Signal blocked\n\n"
            f"Not all timeframes agree.\n"
            f"BUY: {buys} TF | SELL: {sells} TF\n\n"
            f"{detail}\n\n"
            f"Wait until ALL 5 TFs align before trading."
        )

    if not direction:
        direction = results[0]["direction"]
        agreeing  = [results[0]["label"]]

    emoji      = "🟢" if direction == "BUY" else "🔴"
    now        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    confidence = get_confidence(results, direction)

    tf_lines = []
    for r in results:
        sl_p = pips(pair, abs(r["entry"] - r["sl"]))
        tp_p = pips(pair, abs(r["entry"] - r["tp"]))
        lot  = calc_lot_size(account, risk_pct, sl_p, pair)
        agree_mark   = "✅" if r["label"] in agreeing else "⬜"
        warning_line = f"\n   {r['warning']}" if r["warning"] else ""
        indicators   = ", ".join(r["indicators"]) if r["indicators"] else "mixed"
        tf_lines.append(
            f"{agree_mark} *{r['label']}* | {r['direction']} | "
            f"{r['score']}/5 indicators{warning_line}\n"
            f"   ✔ {indicators}\n"
            f"   Entry: `{r['entry']}` | TP: `{r['tp']}` | SL: `{r['sl']}`\n"
            f"   SL {sl_p}p / TP {tp_p}p | Lot: `{lot}`\n"
            f"   RSI: {r['rsi']} | Stoch: {r['stoch_k']} | "
            f"MACD: {r['macd']}"
        )

    news = get_news_summary(pair)

    msg = (
        f"📊 *{pair}* {emoji} *{direction}*\n"
        f"⏰ {now}\n"
        f"Confidence: {confidence}\n\n"
        + "\n\n".join(tf_lines) +
        f"\n\n💬 *Market Context*\n{news}\n\n"
        f"💰 Account: ${account:,.0f} | "
        f"Risk: {risk_pct}% (${account * risk_pct / 100:,.0f} per trade)"
    )
    return msg

# ── ACCOUNT SETUP FLOW ────────────────────────────────────────────────────────
def ask_account(chat_id, context: dict):
    """Store context and ask for account size."""
    pending_signal[str(chat_id)] = context
    send_message(chat_id,
        "💰 *Before I run your signal:*\n\n"
        "What is your current account balance?\n"
        "Reply with just the number, e.g: `20000`"
    )

def handle_pending(chat_id, text: str) -> bool:
    """
    Handle account/risk setup conversation.
    Returns True if message was consumed by setup flow.
    """
    cid      = str(chat_id)
    settings = get_settings(chat_id)

    # Step 1 — waiting for account size
    if cid in pending_signal and settings["account"] is None:
        try:
            amount = float(text.strip())
            if amount < 10:
                send_message(chat_id, "❌ Account must be at least $10. Try again:")
                return True
            settings["account"] = amount
            send_message(chat_id,
                f"✅ Account set to *${amount:,.2f}*\n\n"
                f"⚠️ What is your risk per trade (%)?\n"
                f"Reply with a number between 0.1 and 5.\n"
                f"Recommended for ${amount:,.0f}: *0.5%* = "
                f"${amount * 0.005:,.0f} per trade"
            )
            return True
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number, e.g: `20000`")
            return True

    # Step 2 — waiting for risk %
    if cid in pending_signal and settings["risk_pct"] is None:
        try:
            pct = float(text.strip())
            if not (0.1 <= pct <= 5):
                send_message(chat_id, "❌ Risk must be between 0.1% and 5%. Try again:")
                return True
            settings["risk_pct"] = pct
            context = pending_signal.pop(cid)

            send_message(chat_id,
                f"✅ Risk set to *{pct}%* "
                f"(${settings['account'] * pct / 100:,.2f} per trade)\n\n"
                f"⏳ Running your signal now..."
            )

            # Now run the actual signal
            pair              = context.get("pair")
            require_agreement = context.get("require_agreement", True)

            if pair:
                msg = build_signal(pair, settings["account"],
                                   settings["risk_pct"], require_agreement)
                send_message(chat_id, msg)
            else:
                # /signal — all pairs
                for p in PAIRS:
                    msg = build_signal(p, settings["account"],
                                       settings["risk_pct"], True)
                    send_message(chat_id, msg)
                    time.sleep(3)
            return True
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number, e.g: `0.5`")
            return True

    return False

# ── COMMAND HANDLER ───────────────────────────────────────────────────────────
def handle(chat_id, text: str):
    text = text.strip()

    # ✅ Check if user is in account/risk setup flow first
    if handle_pending(chat_id, text):
        return

    settings = get_settings(chat_id)

    if text == "/start":
        # Reset settings on each /start
        user_settings[str(chat_id)] = {"account": None, "risk_pct": None}
        send_message(chat_id,
            "👋 *Welcome to SOS Trading Signal Bot*\n\n"
            "📌 *Commands*\n"
            "• /signal — scan all 10 pairs\n"
            "• /analyze EURUSD — single pair deep analysis\n"
            "• /pairs — list all pairs\n"
            "• /news EURUSD — AI market context\n"
            "• /alert EURUSD above 1.1200 — price alert\n"
            "• /alerts — view active alerts\n"
            "• /cancelalerts — cancel all alerts\n"
            "• /settings — view current settings\n"
            "• /reset — reset account & risk\n"
            "• /app — open Mini App\n\n"
            "📊 *Timeframes*: 5M | 15M | 1H | 4H | Daily\n"
            "📈 *Pairs*: EUR/USD GBP/USD USD/CAD USD/JPY AUD/USD\n"
            "          EUR/GBP USD/CHF NZD/USD GBP/JPY EUR/JPY\n\n"
            "🔒 *Signal Rules*\n"
            "• ALL 5 timeframes must agree\n"
            "• ALL 5 indicators must confirm\n"
            "• EMA + MACD + RSI + Bollinger + Stochastic\n"
            "• Minimum SL enforced per timeframe\n\n"
            "Type /signal to start! 🚀"
        )

    elif text == "/reset":
        user_settings[str(chat_id)] = {"account": None, "risk_pct": None}
        send_message(chat_id,
            "🔄 Settings reset.\n"
            "Your account and risk will be asked fresh next signal."
        )

    elif text == "/app":
        keyboard = {
            "inline_keyboard": [[{
                "text": "📱 Open SOS Trading App",
                "web_app": {"url": "https://sparkly-biscochitos-5477ba.netlify.app/"}
            }]]
        }
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id":      chat_id,
            "text":         "Tap below to open SOS Trading App 👇",
            "reply_markup": keyboard
        })

    elif text == "/signal":
        # Reset settings and ask fresh
        user_settings[str(chat_id)] = {"account": None, "risk_pct": None}
        ask_account(chat_id, {"pair": None, "require_agreement": True})

    elif text.startswith("/analyze"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Usage: `/analyze EURUSD`")
            return
        raw  = parts[1].upper()
        pair = (raw[:3] + "/" + raw[3:]) if "/" not in raw else raw
        # Reset settings and ask fresh
        user_settings[str(chat_id)] = {"account": None, "risk_pct": None}
        ask_account(chat_id, {"pair": pair, "require_agreement": False})

    elif text == "/settings":
        s = get_settings(chat_id)
        if s["account"] is None or s["risk_pct"] is None:
            send_message(chat_id,
                "⚙️ No settings saved yet.\n"
                "Run /signal or /analyze to set them."
            )
        else:
            send_message(chat_id,
                f"⚙️ *Last Used Settings*\n\n"
                f"💰 Account: *${s['account']:,.2f}*\n"
                f"⚠️ Risk:    *{s['risk_pct']}%* per trade\n"
                f"💵 Risk $:  *${s['account'] * s['risk_pct'] / 100:,.2f}*\n\n"
                f"These will be asked again next signal."
            )

    elif text.startswith("/alert"):
        parts = text.split()
        if len(parts) < 4:
            send_message(chat_id,
                "Usage: `/alert EURUSD above 1.1200`\n"
                "Or:    `/alert EURUSD below 1.1000`"
            )
            return
        try:
            raw       = parts[1].upper()
            pair      = (raw[:3] + "/" + raw[3:]) if "/" not in raw else raw
            direction = parts[2].lower()
            price     = float(parts[3])
            if direction not in ["above", "below"]:
                send_message(chat_id,
                    "❌ Use *above* or *below*.\n"
                    "Example: `/alert EURUSD above 1.1200`"
                )
                return
            price_alerts.append({
                "chat_id":   chat_id,
                "pair":      pair,
                "direction": direction,
                "price":     price
            })
            send_message(chat_id,
                f"🔔 *Alert Set!*\n\n"
                f"Pair: *{pair}*\n"
                f"Trigger: Price goes *{direction}* `{price}`\n\n"
                f"I'll notify you the moment it's hit! ✅"
            )
        except ValueError:
            send_message(chat_id,
                "❌ Invalid price.\n"
                "Example: `/alert EURUSD above 1.1200`"
            )

    elif text == "/alerts":
        user_alerts = [a for a in price_alerts if str(a["chat_id"]) == str(chat_id)]
        if not user_alerts:
            send_message(chat_id,
                "📭 No active alerts.\n"
                "Set one with `/alert EURUSD above 1.1200`"
            )
            return
        lines = ["🔔 *Your Active Alerts*\n"]
        for i, a in enumerate(user_alerts, 1):
            lines.append(f"{i}. *{a['pair']}* — {a['direction']} `{a['price']}`")
        send_message(chat_id, "\n".join(lines))

    elif text == "/cancelalerts":
        before = len([a for a in price_alerts if str(a["chat_id"]) == str(chat_id)])
        price_alerts[:] = [a for a in price_alerts if str(a["chat_id"]) != str(chat_id)]
        send_message(chat_id, f"✅ Cancelled *{before}* alert(s).")

    elif text == "/pairs":
        send_message(chat_id,
            "📈 *Trading Pairs*\n\n" +
            "\n".join(f"• {p}" for p in PAIRS)
        )

    elif text.startswith("/news"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Usage: `/news EURUSD`")
            return
        raw  = parts[1].upper()
        pair = (raw[:3] + "/" + raw[3:]) if "/" not in raw else raw
        send_message(chat_id, f"📰 Fetching AI analysis for *{pair}*...")
        summary = get_news_summary(pair)
        send_message(chat_id, f"📰 *{pair} — Market Context*\n\n{summary}")

    else:
        if text.lower().startswith("/"):
            send_message(chat_id,
                "❓ Unknown command.\n\n"
                "/signal /analyze /pairs\n"
                "/alert /alerts /cancelalerts\n"
                "/settings /reset /news\n"
                "/app /start"
            )
        else:
            send_message(chat_id,
                "💬 I only respond to commands.\n"
                "Send /start to see the full list."
            )

# ── WEB APP DATA HANDLER ──────────────────────────────────────────────────────
def handle_web_app(chat_id, raw_data: str):
    try:
        data     = json.loads(raw_data)
        settings = get_settings(chat_id)

        if data["action"] == "signal":
            pair = data["pair"]
            if settings["account"] is None or settings["risk_pct"] is None:
                user_settings[str(chat_id)] = {"account": None, "risk_pct": None}
                ask_account(chat_id, {"pair": pair, "require_agreement": False})
            else:
                send_message(chat_id, f"⏳ Analyzing *{pair}*...")
                result = build_signal(pair, settings["account"],
                                      settings["risk_pct"], False)
                send_message(chat_id, result)

        elif data["action"] == "settings":
            settings["account"]  = float(data["account"])
            settings["risk_pct"] = float(data["risk"])
            send_message(chat_id,
                f"✅ Settings updated!\n"
                f"💰 Account: *${settings['account']:,.2f}*\n"
                f"⚠️ Risk: *{settings['risk_pct']}%*\n"
                f"💵 Risk $: "
                f"*${settings['account'] * settings['risk_pct'] / 100:,.2f}*"
            )
    except Exception as e:
        print(f"[handle_web_app] error: {e}")
        send_message(chat_id, "❌ Error processing app request.")

# ── AUTO SESSION SIGNALS ──────────────────────────────────────────────────────
def session_job(session_name: str, flag: str):
    print(f"[scheduler] {session_name} firing")
    send_message(CHAT_ID,
        f"{flag} *{session_name} Session*\n\n"
        f"⏳ Scanning 10 pairs...\n"
        f"Only firing when ALL 5 TFs + ALL 5 indicators agree."
    )
    # Use last known settings or defaults for auto signals
    s        = get_settings(CHAT_ID)
    account  = s["account"]  or 20000.0
    risk_pct = s["risk_pct"] or 0.5
    sent     = 0
    for pair in PAIRS:
        msg = build_signal(pair, account, risk_pct, require_agreement=True)
        if "Signal blocked" not in msg and "Could not" not in msg:
            send_message(CHAT_ID, msg)
            sent += 1
        time.sleep(3)
    if sent == 0:
        send_message(CHAT_ID,
            f"{flag} *{session_name}* — No maximum-confidence setups.\n"
            f"Markets are mixed. Patience is profit. 🧘"
        )

def run_scheduler():
    schedule.every().day.at("00:00").do(session_job, "Tokyo",    "🇯🇵")
    schedule.every().day.at("07:00").do(session_job, "London",   "🇬🇧")
    schedule.every().day.at("12:00").do(session_job, "New York", "🇺🇸")
    schedule.every().day.at("13:00").do(session_job, "Overlap",  "🔥")
    schedule.every().day.at("21:00").do(session_job, "Sydney",   "🇦🇺")
    while True:
        schedule.run_pending()
        time.sleep(30)

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────
def main():
    print("SOS Trading Bot running...")
    threading.Thread(target=run_scheduler,      daemon=True).start()
    threading.Thread(target=check_price_alerts, daemon=True).start()

    offset = None
    while True:
        try:
            updates = get_updates(offset)
            if updates.get("ok"):
                for u in updates.get("result", []):
                    offset = u["update_id"] + 1
                    msg    = u.get("message", {})
                    if "text" in msg:
                        handle(msg["chat"]["id"], msg["text"])
                    if "web_app_data" in msg:
                        handle_web_app(
                            msg["chat"]["id"],
                            msg["web_app_data"]["data"]
                        )
        except Exception as e:
            print(f"[main] error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()