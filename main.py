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

# ── USER SETTINGS ────────────────────────────────────────────────────────────
user_settings: dict[str, dict] = {}

def get_settings(chat_id: str) -> dict:
    cid = str(chat_id)
    if cid not in user_settings:
        user_settings[cid] = {"account": 20000.0, "risk_pct": 0.5}
    return user_settings[cid]

# ── PRICE ALERTS ─────────────────────────────────────────────────────────────
price_alerts: list[dict] = []

def check_price_alerts():
    """Check all active price alerts and fire if price reached."""
    while True:
        triggered = []
        for alert in price_alerts:
            try:
                candles = get_candles(alert["pair"], "5min", 1)
                if not candles:
                    continue
                current_price = float(candles[0]["close"])
                if alert["direction"] == "above" and current_price >= alert["price"]:
                    send_message(alert["chat_id"],
                        f"🔔 *PRICE ALERT TRIGGERED!*\n\n"
                        f"*{alert['pair']}* has reached *{current_price}*\n"
                        f"Your alert was set at *{alert['price']}*\n\n"
                        f"⚡ Check your signal now with /analyze {alert['pair'].replace('/', '')}"
                    )
                    triggered.append(alert)
                elif alert["direction"] == "below" and current_price <= alert["price"]:
                    send_message(alert["chat_id"],
                        f"🔔 *PRICE ALERT TRIGGERED!*\n\n"
                        f"*{alert['pair']}* has dropped to *{current_price}*\n"
                        f"Your alert was set at *{alert['price']}*\n\n"
                        f"⚡ Check your signal now with /analyze {alert['pair'].replace('/', '')}"
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
            "chat_id": chat_id,
            "text": text,
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

def calc_atr(candles: list, period: int = 14) -> float:
    trs = []
    for i in range(min(period, len(candles) - 1)):
        c = candles[i]
        p = candles[i + 1]
        high       = float(c["high"])
        low        = float(c["low"])
        prev_close = float(p["close"])
        tr = max(high - low,
                 abs(high - prev_close),
                 abs(low  - prev_close))
        trs.append(tr)
    return round(sum(trs) / len(trs), 5) if trs else 0.0

def calc_ema(closes: list, period: int) -> float:
    """Exponential Moving Average — more responsive than SMA."""
    if len(closes) < period:
        return 0.0
    k = 2 / (period + 1)
    ema = sum(closes[-period:]) / period
    for price in reversed(closes[:-period]):
        ema = price * k + ema * (1 - k)
    return round(ema, 5)

def calc_sma(closes: list, period: int) -> float:
    if len(closes) < period:
        return 0.0
    return round(sum(closes[:period]) / period, 5)

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
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def calc_macd(closes: list) -> tuple[float, float, float]:
    """
    MACD = EMA12 - EMA26
    Signal = EMA9 of MACD
    Histogram = MACD - Signal
    """
    if len(closes) < 35:
        return 0.0, 0.0, 0.0
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd  = round(ema12 - ema26, 6)

    # Build MACD history for signal line
    macd_history = []
    for i in range(9):
        e12 = calc_ema(closes[i:], 12)
        e26 = calc_ema(closes[i:], 26)
        macd_history.append(e12 - e26)

    signal    = round(sum(macd_history) / len(macd_history), 6)
    histogram = round(macd - signal, 6)
    return macd, signal, histogram

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

    # ✅ EMA instead of SMA for better accuracy
    ema9  = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema50 = calc_ema(closes, 50)
    rsi   = calc_rsi(closes, 14)

    # ✅ MACD confirmation
    macd, signal, histogram = calc_macd(closes)

    # ✅ Triple confirmation: EMA + MACD + RSI
    ema_buy  = ema9 > ema21 and ema21 > ema50
    ema_sell = ema9 < ema21 and ema21 < ema50
    macd_buy  = macd > signal and histogram > 0
    macd_sell = macd < signal and histogram < 0

    # Count confirmations
    buy_score  = sum([ema_buy, macd_buy, rsi < 60 and rsi > 40])
    sell_score = sum([ema_sell, macd_sell, rsi < 60 and rsi > 40])

    if buy_score > sell_score:
        direction = "BUY"
    elif sell_score > buy_score:
        direction = "SELL"
    else:
        # Fallback to EMA crossover
        direction = "BUY" if ema9 > ema21 else "SELL"

    # ✅ RSI extreme warning
    if direction == "BUY" and rsi > 75:
        warning = "⚠️ RSI overbought — caution"
    elif direction == "SELL" and rsi < 25:
        warning = "⚠️ RSI oversold — caution"
    else:
        warning = ""

    # ✅ Minimum SL enforcement — no more 3 pip stops
    pip_size  = 0.01 if "JPY" in pair else 0.0001
    min_sl    = cfg["min_sl_pips"] * pip_size
    sl_dist   = max(round(atr * cfg["atr_sl_mult"], 5), min_sl)
    tp_dist   = round(sl_dist * (cfg["atr_tp_mult"] / cfg["atr_sl_mult"]), 5)

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
        "label":     cfg["label"],
        "interval":  interval,
        "direction": direction,
        "entry":     entry,
        "tp":        tp,
        "sl":        sl,
        "atr":       atr,
        "ema9":      ema9,
        "ema21":     ema21,
        "ema50":     ema50,
        "rsi":       rsi,
        "macd":      macd,
        "signal":    signal,
        "histogram": histogram,
        "warning":   warning,
        "change":    change,
        "high":      float(latest["high"]),
        "low":       float(latest["low"]),
        "buy_score": buy_score,
        "sell_score":sell_score,
    }

def multi_tf_agree(results: list) -> tuple[str | None, list]:
    """
    ✅ Stricter: at least 3 TFs must agree for high confidence signal.
    """
    if not results:
        return None, []
    buys  = [r for r in results if r["direction"] == "BUY"]
    sells = [r for r in results if r["direction"] == "SELL"]
    if len(buys) >= 3:
        return "BUY",  [r["label"] for r in buys]
    if len(sells) >= 3:
        return "SELL", [r["label"] for r in sells]
    return None, []

# ── LOT SIZE CALCULATOR ───────────────────────────────────────────────────────
def calc_lot_size(account: float, risk_pct: float,
                  sl_pips: float, pair: str) -> float:
    """
    ✅ Fixed lot size calculation for $20k account.
    Risk amount / (SL pips x pip value per lot)
    """
    risk_amount = account * (risk_pct / 100)
    if sl_pips <= 0:
        return 0.01
    # JPY pairs have different pip value
    if "JPY" in pair:
        pip_value = 6.8   # approximate per standard lot
    else:
        pip_value = 10.0  # $ per pip per standard lot
    raw = risk_amount / (sl_pips * pip_value)
    lot = max(0.01, min(round(raw, 2), 5.0))  # cap at 5.0 lots max
    return lot

def pips(pair: str, price_dist: float) -> float:
    if "JPY" in pair:
        return round(price_dist / 0.01, 1)
    return round(price_dist / 0.0001, 1)

# ── CONFIDENCE SCORE ──────────────────────────────────────────────────────────
def get_confidence(results: list, direction: str) -> str:
    """Return a confidence rating based on how many TFs agree."""
    agreeing = sum(1 for r in results if r["direction"] == direction)
    total    = len(results)
    pct      = (agreeing / total) * 100 if total > 0 else 0
    if pct == 100:
        return "🔥 VERY HIGH (5/5 TFs)"
    elif pct >= 80:
        return "✅ HIGH (4/5 TFs)"
    elif pct >= 60:
        return "⚠️ MEDIUM (3/5 TFs)"
    else:
        return "❌ LOW — skip this trade"

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
        f"You are a forex analyst. In 3 plain-English sentences explain "
        f"the current market sentiment for {pair}. "
        f"Focus on: what is driving the price, key risk events this week, "
        f"and what a retail trader should watch out for. No jargon. "
        f"End with one action sentence: 'Watch for...' or 'Avoid trading when...'."
    )
    return ask_gemini(prompt)

# ── SIGNAL BUILDER ────────────────────────────────────────────────────────────
def build_signal(pair: str, chat_id=None, require_agreement: bool = True) -> str:
    settings = get_settings(chat_id) if chat_id else {"account": 20000.0, "risk_pct": 0.5}
    account  = settings["account"]
    risk_pct = settings["risk_pct"]

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
        return (
            f"⚠️ *{pair}* — No high-confidence signal\n"
            f"BUY: {buys} TF | SELL: {sells} TF\n"
            f"Need at least 3 TFs to agree. Wait for alignment."
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
        tf_lines.append(
            f"{agree_mark} *{r['label']}* | {r['direction']} | RSI: {r['rsi']}{warning_line}\n"
            f"   Entry: `{r['entry']}` | TP: `{r['tp']}` | SL: `{r['sl']}`\n"
            f"   SL {sl_p}p / TP {tp_p}p | Lot: `{lot}`\n"
            f"   MACD: `{r['macd']}` | EMA9: `{r['ema9']}`"
        )

    news = get_news_summary(pair)

    msg = (
        f"📊 *{pair}* {emoji} *{direction}*\n"
        f"⏰ {now}\n"
        f"Confidence: {confidence}\n"
        f"Agreement: {', '.join(agreeing)}\n\n"
        + "\n\n".join(tf_lines) +
        f"\n\n💬 *Market Context*\n{news}\n\n"
        f"💰 Account: ${account:,.0f} | Risk: {risk_pct}% (${account * risk_pct / 100:,.0f})"
    )
    return msg

# ── COMMAND HANDLER ───────────────────────────────────────────────────────────
def handle(chat_id, text: str):
    text     = text.strip()
    settings = get_settings(chat_id)

    if text == "/start":
        send_message(chat_id,
            "👋 *SOS Trading Signal Bot*\n\n"
            "📌 *Commands*\n"
            "• /signal — all pairs (multi-TF)\n"
            "• /analyze EURUSD — single pair\n"
            "• /pairs — list all pairs\n"
            "• /news — market context all pairs\n"
            "• /news EURUSD — context one pair\n"
            "• /alert EURUSD above 1.1200 — price alert\n"
            "• /alerts — view your active alerts\n"
            "• /cancelalerts — cancel all alerts\n"
            "• /setaccount 20000 — set account size\n"
            "• /setrisk 0.5 — set risk % per trade\n"
            "• /settings — show your settings\n"
            "• /app — open Mini App\n\n"
            "📅 *Auto Signals*\n"
            "🇯🇵 Tokyo:    00:00 UTC\n"
            "🇬🇧 London:   07:00 UTC\n"
            "🇺🇸 New York: 12:00 UTC\n"
            "🔥 Overlap:   13:00 UTC\n"
            "🇦🇺 Sydney:   21:00 UTC\n\n"
            "📊 *Timeframes*: 5M | 15M | 1H | 4H | Daily\n"
            "📈 *Pairs*: EUR/USD GBP/USD USD/CAD USD/JPY AUD/USD\n"
            "          EUR/GBP USD/CHF NZD/USD GBP/JPY EUR/JPY\n\n"
            "✅ Signals fire only when 3+ TFs agree.\n"
            "🔥 EMA + MACD + RSI triple confirmation."
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

    elif text.startswith("/alert"):
        # Usage: /alert EURUSD above 1.1200
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
                send_message(chat_id, "❌ Use *above* or *below*.\nExample: `/alert EURUSD above 1.1200`")
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
            send_message(chat_id, "❌ Invalid price. Example: `/alert EURUSD above 1.1200`")

    elif text == "/alerts":
        user_alerts = [a for a in price_alerts if str(a["chat_id"]) == str(chat_id)]
        if not user_alerts:
            send_message(chat_id, "📭 You have no active alerts.\nSet one with `/alert EURUSD above 1.1200`")
            return
        lines = [f"🔔 *Your Active Alerts*\n"]
        for i, a in enumerate(user_alerts, 1):
            lines.append(f"{i}. *{a['pair']}* — {a['direction']} `{a['price']}`")
        send_message(chat_id, "\n".join(lines))

    elif text == "/cancelalerts":
        before = len([a for a in price_alerts if str(a["chat_id"]) == str(chat_id)])
        price_alerts[:] = [a for a in price_alerts if str(a["chat_id"]) != str(chat_id)]
        send_message(chat_id, f"✅ Cancelled *{before}* alert(s).")

    elif text.startswith("/setaccount"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Usage: `/setaccount 20000`")
            return
        try:
            amount = float(parts[1])
            settings["account"] = amount
            send_message(chat_id, f"✅ Account set to *${amount:,.2f}*")
        except ValueError:
            send_message(chat_id, "❌ Invalid amount. Use: `/setaccount 20000`")

    elif text.startswith("/setrisk"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Usage: `/setrisk 0.5`")
            return
        try:
            pct = float(parts[1])
            if not (0.1 <= pct <= 10):
                send_message(chat_id, "⚠️ Risk must be between 0.1% and 10%")
                return
            settings["risk_pct"] = pct
            send_message(chat_id, f"✅ Risk set to *{pct}%* per trade")
        except ValueError:
            send_message(chat_id, "❌ Invalid value. Use: `/setrisk 0.5`")

    elif text == "/settings":
        send_message(chat_id,
            f"⚙️ *Your Settings*\n\n"
            f"💰 Account: *${settings['account']:,.2f}*\n"
            f"⚠️ Risk:    *{settings['risk_pct']}%* per trade\n"
            f"💵 Risk $:  *${settings['account'] * settings['risk_pct'] / 100:,.2f}* per trade"
        )

    elif text == "/signal":
        send_message(chat_id, "⏳ Scanning 10 pairs across 5 timeframes...\nOnly showing high-confidence signals (3+ TFs agree).")
        for pair in PAIRS:
            msg = build_signal(pair, chat_id, require_agreement=True)
            send_message(chat_id, msg)
            time.sleep(3)

    elif text.startswith("/analyze"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Usage: `/analyze EURUSD`")
            return
        raw  = parts[1].upper()
        pair = (raw[:3] + "/" + raw[3:]) if "/" not in raw else raw
        send_message(chat_id, f"⏳ Analyzing *{pair}* across 5M, 15M, 1H, 4H, Daily...")
        msg = build_signal(pair, chat_id, require_agreement=False)
        send_message(chat_id, msg)

    elif text == "/pairs":
        send_message(chat_id,
            "📈 *Trading Pairs*\n\n"
            + "\n".join(f"• {p}" for p in PAIRS)
        )

    elif text.startswith("/news"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "📰 Fetching market news for all pairs...")
            for pair in PAIRS:
                summary = get_news_summary(pair)
                send_message(chat_id, f"📰 *{pair} — Market Context*\n\n{summary}")
                time.sleep(2)
        else:
            raw  = parts[1].upper()
            pair = (raw[:3] + "/" + raw[3:]) if "/" not in raw else raw
            send_message(chat_id, f"📰 Fetching news for *{pair}*...")
            summary = get_news_summary(pair)
            send_message(chat_id, f"📰 *{pair} — Market Context*\n\n{summary}")

    else:
        lower = text.lower()
        if lower.startswith("/"):
            send_message(chat_id,
                "❓ Unknown command. Available:\n\n"
                "/signal /analyze /pairs\n"
                "/alert /alerts /cancelalerts\n"
                "/setaccount /setrisk /settings\n"
                "/news /app /start"
            )
        else:
            send_message(chat_id,
                "💬 I only respond to commands.\n"
                "Send /start to see the full list."
            )

# ── WEB APP DATA HANDLER ──────────────────────────────────────────────────────
def handle_web_app(chat_id, raw_data: str):
    try:
        data = json.loads(raw_data)
        if data["action"] == "signal":
            pair = data["pair"]
            send_message(chat_id, f"⏳ Analyzing *{pair}* across 5M, 15M, 1H, 4H, Daily...")
            result = build_signal(pair, chat_id, require_agreement=False)
            send_message(chat_id, result)
        elif data["action"] == "settings":
            settings = get_settings(chat_id)
            settings["account"] = float(data["account"])
            settings["risk_pct"] = float(data["risk"])
            send_message(chat_id,
                f"✅ Settings updated!\n"
                f"💰 Account: *${settings['account']:,.2f}*\n"
                f"⚠️ Risk: *{settings['risk_pct']}%*\n"
                f"💵 Risk $: *${settings['account'] * settings['risk_pct'] / 100:,.2f}*"
            )
    except Exception as e:
        print(f"[handle_web_app] error: {e}")
        send_message(chat_id, "❌ Error processing app request.")

# ── AUTO SESSION SIGNALS ──────────────────────────────────────────────────────
def session_job(session_name: str, flag: str):
    print(f"[scheduler] {session_name} session signal firing")
    send_message(CHAT_ID,
        f"{flag} *{session_name} Session Signals*\n\n"
        f"⏳ Scanning 10 pairs (5M, 15M, 1H, 4H, Daily)...\n"
        f"Only high-confidence signals (3+ TFs agree)."
    )
    sent = 0
    for pair in PAIRS:
        msg = build_signal(pair, CHAT_ID, require_agreement=True)
        if "No high-confidence" not in msg and "Could not" not in msg:
            send_message(CHAT_ID, msg)
            sent += 1
        time.sleep(3)
    if sent == 0:
        send_message(CHAT_ID,
            f"{flag} *{session_name}* — No high-confidence setups right now.\n"
            f"TFs are mixed across all pairs. Wait for alignment."
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
    threading.Thread(target=run_scheduler, daemon=True).start()
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