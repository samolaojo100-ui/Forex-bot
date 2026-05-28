import os
import requests
import time
import schedule
import threading
from datetime import datetime, timezone

# ── ENV ─────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")
GEMINI_KEY = os.getenv("GEMINI_KEY")
CHAT_ID = os.getenv("CHAT_ID")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ── PAIRS ───────────────────────────────────────────────────────────────────
PAIRS = [
    "EUR/USD",
    "GBP/USD",
    "USD/CAD",
    "USD/JPY",
    "AUD/USD",
    "EUR/GBP",
    "USD/CHF",
    "NZD/USD",
    "GBP/JPY",
    "EUR/JPY"
]

# ── STORAGE ─────────────────────────────────────────────────────────────────
user_settings = {}
pending_signal = {}
price_alerts = []

# ── SETTINGS ────────────────────────────────────────────────────────────────
def get_settings(chat_id):

    cid = str(chat_id)

    if cid not in user_settings:

        user_settings[cid] = {
            "account": None,
            "risk_pct": None
        }

    return user_settings[cid]

# ── TELEGRAM ────────────────────────────────────────────────────────────────
def send_message(chat_id, text):

    try:

        requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            },
            timeout=15
        )

    except Exception as e:
        print("send_message:", e)

def get_updates(offset=None):

    try:

        r = requests.get(
            f"{BASE_URL}/getUpdates",
            params={
                "timeout": 30,
                "offset": offset
            },
            timeout=35
        )

        return r.json()

    except Exception as e:

        print("get_updates:", e)

        return {"ok": False}

# ── MARKET DATA ─────────────────────────────────────────────────────────────
def get_candles(pair, interval="1day", size=100):

    try:

        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": f"{pair}:FX",
                "interval": interval,
                "outputsize": size,
                "apikey": TWELVE_DATA_KEY
            },
            timeout=15
        )

        data = r.json()

        if data.get("status") == "error":

            print("API ERROR:", pair, interval, data.get("message"))

            return None

        return data.get("values")

    except Exception as e:

        print("get_candles:", e)

        return None

# ── EMA ─────────────────────────────────────────────────────────────────────
def calc_ema(closes, period):

    if len(closes) < period:
        return 0

    k = 2 / (period + 1)

    ema = sum(closes[-period:]) / period

    for price in reversed(closes[:-period]):

        ema = price * k + ema * (1 - k)

    return round(ema, 5)

# ── RSI ─────────────────────────────────────────────────────────────────────
def calc_rsi(closes, period=14):

    if len(closes) < period + 1:
        return 50

    gains = []
    losses = []

    for i in range(period):

        diff = closes[i] - closes[i + 1]

        if diff > 0:

            gains.append(diff)
            losses.append(0)

        else:

            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return round(100 - (100 / (1 + rs)), 2)

# ── MACD ────────────────────────────────────────────────────────────────────
def calc_macd(closes):

    if len(closes) < 35:
        return 0, 0, 0

    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)

    macd = ema12 - ema26

    hist = []

    for i in range(9):

        e12 = calc_ema(closes[i:], 12)
        e26 = calc_ema(closes[i:], 26)

        hist.append(e12 - e26)

    signal = sum(hist) / len(hist)

    histogram = macd - signal

    return round(macd, 6), round(signal, 6), round(histogram, 6)

# ── ATR ─────────────────────────────────────────────────────────────────────
def calc_atr(candles, period=14):

    trs = []

    for i in range(min(period, len(candles) - 1)):

        c = candles[i]
        p = candles[i + 1]

        high = float(c["high"])
        low = float(c["low"])
        prev_close = float(p["close"])

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        trs.append(tr)

    if not trs:
        return 0

    return round(sum(trs) / len(trs), 5)

# ── BOLLINGER ───────────────────────────────────────────────────────────────
def calc_bollinger(closes, period=20):

    if len(closes) < period:
        return 0, 0, 0

    sma = sum(closes[:period]) / period

    variance = sum((x - sma) ** 2 for x in closes[:period]) / period

    std = variance ** 0.5

    upper = sma + 2 * std
    lower = sma - 2 * std

    return round(upper, 5), round(sma, 5), round(lower, 5)

# ── STOCHASTIC ──────────────────────────────────────────────────────────────
def calc_stochastic(candles, period=14):

    if len(candles) < period:
        return 50, 50

    highs = [float(x["high"]) for x in candles[:period]]
    lows = [float(x["low"]) for x in candles[:period]]

    highest = max(highs)
    lowest = min(lows)

    current = float(candles[0]["close"])

    if highest == lowest:
        return 50, 50

    k = ((current - lowest) / (highest - lowest)) * 100

    return round(k, 2), round(k, 2)

# ── CONFIG ──────────────────────────────────────────────────────────────────
TIMEFRAME_CONFIG = {
    "5min": {
        "label": "5M",
        "sl_mult": 1.5,
        "tp_mult": 2.5,
        "min_sl": 5
    },

    "15min": {
        "label": "15M",
        "sl_mult": 1.5,
        "tp_mult": 2.5,
        "min_sl": 10
    },

    "1h": {
        "label": "1H",
        "sl_mult": 2.0,
        "tp_mult": 3.0,
        "min_sl": 15
    },

    "4h": {
        "label": "4H",
        "sl_mult": 2.0,
        "tp_mult": 3.0,
        "min_sl": 25
    },

    "1day": {
        "label": "Daily",
        "sl_mult": 2.5,
        "tp_mult": 4.0,
        "min_sl": 40
    }
}

# ── PIPS ────────────────────────────────────────────────────────────────────
def pips(pair, distance):

    if "JPY" in pair:
        return round(distance / 0.01, 1)

    return round(distance / 0.0001, 1)

# ── LOT SIZE ────────────────────────────────────────────────────────────────
def calc_lot_size(account, risk_pct, sl_pips, pair):

    risk_amount = account * (risk_pct / 100)

    if sl_pips <= 0:
        return 0.01

    pip_value = 6.8 if "JPY" in pair else 10

    lot = risk_amount / (sl_pips * pip_value)

    lot = round(lot, 2)

    return max(0.01, min(lot, 5.0))

# ── ANALYSIS ────────────────────────────────────────────────────────────────
def analyze_tf(pair, tf):

    cfg = TIMEFRAME_CONFIG[tf]

    candles = get_candles(pair, tf, 100)

    if not candles or len(candles) < 50:
        return None

    closes = [float(x["close"]) for x in candles]

    entry = float(candles[0]["close"])

    atr = calc_atr(candles)

    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema50 = calc_ema(closes, 50)

    macd, signal, hist = calc_macd(closes)

    rsi = calc_rsi(closes)

    bb_upper, bb_mid, bb_lower = calc_bollinger(closes)

    stoch_k, stoch_d = calc_stochastic(candles)

    buy_checks = [
        ema9 > ema21 > ema50,
        macd > signal and hist > 0,
        rsi > 55,
        entry <= bb_lower,
        stoch_k < 20
    ]

    sell_checks = [
        ema9 < ema21 < ema50,
        macd < signal and hist < 0,
        rsi < 45,
        entry >= bb_upper,
        stoch_k > 80
    ]

    buy_score = sum(buy_checks)
    sell_score = sum(sell_checks)

    if buy_score >= 3:

        direction = "BUY"
        score = buy_score

    elif sell_score >= 3:

        direction = "SELL"
        score = sell_score

    else:

        return None

    pip_size = 0.01 if "JPY" in pair else 0.0001

    min_sl = cfg["min_sl"] * pip_size

    sl_distance = max(
        atr * cfg["sl_mult"],
        min_sl
    )

    tp_distance = sl_distance * (
        cfg["tp_mult"] / cfg["sl_mult"]
    )

    if direction == "BUY":

        sl = entry - sl_distance
        tp = entry + tp_distance

    else:

        sl = entry + sl_distance
        tp = entry - tp_distance

    return {
        "label": cfg["label"],
        "direction": direction,
        "score": score,
        "entry": round(entry, 5),
        "sl": round(sl, 5),
        "tp": round(tp, 5),
        "rsi": rsi,
        "macd": macd
    }

# ── TF AGREEMENT ────────────────────────────────────────────────────────────
def multi_tf_agree(results):

    buys = [x for x in results if x["direction"] == "BUY"]

    sells = [x for x in results if x["direction"] == "SELL"]

    if len(buys) >= 3:
        return "BUY", buys

    if len(sells) >= 3:
        return "SELL", sells

    return None, []

# ── CONFIDENCE ──────────────────────────────────────────────────────────────
def confidence(total):

    if total == 5:
        return "🔥 MAXIMUM"

    if total == 4:
        return "✅ VERY HIGH"

    return "⚠️ MEDIUM"

# ── GEMINI ──────────────────────────────────────────────────────────────────
def ask_gemini(prompt):

    try:

        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": prompt}
                        ]
                    }
                ]
            },
            timeout=20
        )

        if r.status_code != 200:
            return "AI unavailable."

        return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    except:
        return "AI unavailable."

def get_news_summary(pair):

    prompt = (
        f"Explain the current forex market sentiment for {pair} "
        f"in 3 short professional sentences."
    )

    return ask_gemini(prompt)

# ── SIGNAL BUILDER ──────────────────────────────────────────────────────────
def build_signal(pair, account, risk_pct):

    results = []

    for tf in TIMEFRAME_CONFIG:

        r = analyze_tf(pair, tf)

        if r:
            results.append(r)

        time.sleep(0.5)

    if not results:
        return f"❌ Could not fetch data for {pair}"

    direction, agreeing = multi_tf_agree(results)

    if not direction:
        return f"⛔ {pair} blocked — TFs not aligned"

    emoji = "🟢" if direction == "BUY" else "🔴"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = (
        f"📊 *{pair}* {emoji} *{direction}*\n"
        f"⏰ {now}\n"
        f"Confidence: {confidence(len(agreeing))}\n\n"
    )

    for r in agreeing:

        sl_pips = pips(pair, abs(r["entry"] - r["sl"]))

        tp_pips = pips(pair, abs(r["entry"] - r["tp"]))

        lot = calc_lot_size(
            account,
            risk_pct,
            sl_pips,
            pair
        )

        msg += (
            f"✅ *{r['label']}* | {r['score']}/5 indicators\n"
            f"Entry: `{r['entry']}`\n"
            f"TP: `{r['tp']}`\n"
            f"SL: `{r['sl']}`\n"
            f"SL {sl_pips}p | TP {tp_pips}p\n"
            f"Lot Size: `{lot}`\n"
            f"RSI: {r['rsi']} | MACD: {r['macd']}\n\n"
        )

    news = get_news_summary(pair)

    msg += (
        f"💬 *Market Context*\n"
        f"{news}\n\n"
        f"💰 Account: ${account:,.0f}\n"
        f"⚠️ Risk: {risk_pct}% "
        f"(${account * risk_pct / 100:,.2f})"
    )

    return msg

# ── AUTO RISK ───────────────────────────────────────────────────────────────
def auto_risk(account):

    if account < 500:
        return 1.0

    if account < 5000:
        return 0.5

    if account < 20000:
        return 0.25

    return 0.1

# ── ACCOUNT FLOW ────────────────────────────────────────────────────────────
def ask_account(chat_id):

    pending_signal[str(chat_id)] = True

    send_message(
        chat_id,
        "💰 Enter your account balance.\n"
        "Example: `2000`"
    )

def handle_pending(chat_id, text):

    cid = str(chat_id)

    if cid not in pending_signal:
        return False

    try:

        amount = float(text)

        if amount < 10:

            send_message(chat_id, "❌ Minimum account is $10")

            return True

        risk_pct = auto_risk(amount)

        user_settings[cid] = {
            "account": amount,
            "risk_pct": risk_pct
        }

        pending_signal.pop(cid)

        send_message(
            chat_id,
            f"✅ Account: *${amount:,.2f}*\n"
            f"🛡 Auto Risk: *{risk_pct}%*\n"
            f"💵 Risk per trade: "
            f"*${amount * risk_pct / 100:,.2f}*"
        )

        send_message(
            chat_id,
            "⏳ Running signal scan..."
        )

        for pair in PAIRS:

            msg = build_signal(
                pair,
                amount,
                risk_pct
            )

            send_message(chat_id, msg)

            time.sleep(2)

        return True

    except:

        send_message(chat_id, "❌ Enter valid number")

        return True

# ── ALERT CHECKER ───────────────────────────────────────────────────────────
def check_price_alerts():

    while True:

        triggered = []

        for alert in price_alerts:

            try:

                candles = get_candles(
                    alert["pair"],
                    "5min",
                    1
                )

                if not candles:
                    continue

                current = float(candles[0]["close"])

                hit = (
                    (
                        alert["direction"] == "above"
                        and current >= alert["price"]
                    )
                    or
                    (
                        alert["direction"] == "below"
                        and current <= alert["price"]
                    )
                )

                if hit:

                    send_message(
                        alert["chat_id"],
                        f"🔔 ALERT TRIGGERED\n\n"
                        f"{alert['pair']} reached {current}"
                    )

                    triggered.append(alert)

            except Exception as e:
                print("alert error:", e)

        for t in triggered:
            price_alerts.remove(t)

        time.sleep(60)

# ── COMMANDS ────────────────────────────────────────────────────────────────
def handle(chat_id, text):

    text = text.strip()

    if handle_pending(chat_id, text):
        return

    if text == "/start":

        send_message(
            chat_id,
            "👋 *SOS Trading Bot*\n\n"
            "/signal\n"
            "/analyze EURUSD\n"
            "/news EURUSD\n"
            "/alert EURUSD above 1.1200\n"
            "/pairs\n"
            "/alerts\n"
            "/cancelalerts\n"
            "/reset"
        )

    elif text == "/signal":

        ask_account(chat_id)

    elif text.startswith("/analyze"):

        parts = text.split()

        if len(parts) < 2:

            send_message(
                chat_id,
                "Usage:\n/analyze EURUSD"
            )

            return

        raw = parts[1].upper()

        pair = (
            raw[:3] + "/" + raw[3:]
            if "/" not in raw
            else raw
        )

        settings = get_settings(chat_id)

        if settings["account"] is None:

            send_message(
                chat_id,
                "❌ Run /signal first."
            )

            return

        send_message(
            chat_id,
            f"⏳ Analyzing *{pair}*..."
        )

        msg = build_signal(
            pair,
            settings["account"],
            settings["risk_pct"]
        )

        send_message(chat_id, msg)

    elif text.startswith("/news"):

        parts = text.split()

        if len(parts) < 2:

            send_message(
                chat_id,
                "Usage:\n/news EURUSD"
            )

            return

        raw = parts[1].upper()

        pair = (
            raw[:3] + "/" + raw[3:]
            if "/" not in raw
            else raw
        )

        send_message(
            chat_id,
            f"📰 Fetching news for *{pair}*..."
        )

        news = get_news_summary(pair)

        send_message(
            chat_id,
            f"📰 *{pair} Market Context*\n\n"
            f"{news}"
        )

    elif text.startswith("/alert"):

        parts = text.split()

        if len(parts) < 4:

            send_message(
                chat_id,
                "Usage:\n"
                "/alert EURUSD above 1.1200"
            )

            return

        try:

            raw = parts[1].upper()

            pair = (
                raw[:3] + "/" + raw[3:]
                if "/" not in raw
                else raw
            )

            direction = parts[2].lower()

            price = float(parts[3])

            if direction not in ["above", "below"]:

                send_message(
                    chat_id,
                    "❌ Use above or below"
                )

                return

            price_alerts.append({
                "chat_id": chat_id,
                "pair": pair,
                "direction": direction,
                "price": price
            })

            send_message(
                chat_id,
                f"🔔 Alert Set\n\n"
                f"Pair: {pair}\n"
                f"Direction: {direction}\n"
                f"Price: {price}"
            )

        except:

            send_message(
                chat_id,
                "❌ Invalid alert format"
            )

    elif text == "/alerts":

        alerts = [
            x for x in price_alerts
            if str(x["chat_id"]) == str(chat_id)
        ]

        if not alerts:

            send_message(
                chat_id,
                "📭 No alerts"
            )

            return

        msg = "🔔 *Your Alerts*\n\n"

        for i, a in enumerate(alerts, 1):

            msg += (
                f"{i}. {a['pair']} | "
                f"{a['direction']} | "
                f"{a['price']}\n"
            )

        send_message(chat_id, msg)

    elif text == "/cancelalerts":

        before = len(price_alerts)

        price_alerts[:] = [
            x for x in price_alerts
            if str(x["chat_id"]) != str(chat_id)
        ]

        removed = before - len(price_alerts)

        send_message(
            chat_id,
            f"✅ Removed {removed} alerts"
        )

    elif text == "/pairs":

        msg = "📈 *Pairs*\n\n"

        for pair in PAIRS:
            msg += f"• {pair}\n"

        send_message(chat_id, msg)

    elif text == "/reset":

        user_settings[str(chat_id)] = {
            "account": None,
            "risk_pct": None
        }

        send_message(
            chat_id,
            "✅ Reset complete"
        )

    else:

        send_message(
            chat_id,
            "❌ Unknown command"
        )

# ── SESSION JOB ─────────────────────────────────────────────────────────────
def session_job(name, flag):

    send_message(
        CHAT_ID,
        f"{flag} {name} session scan started"
    )

    settings = get_settings(CHAT_ID)

    account = settings["account"] or 2000

    risk_pct = settings["risk_pct"] or 0.5

    for pair in PAIRS:

        msg = build_signal(
            pair,
            account,
            risk_pct
        )

        if "blocked" not in msg.lower():
            send_message(CHAT_ID, msg)

        time.sleep(3)

# ── SCHEDULER ───────────────────────────────────────────────────────────────
def run_scheduler():

    schedule.every().day.at("00:00").do(
        session_job,
        "Tokyo",
        "🇯🇵"
    )

    schedule.every().day.at("07:00").do(
        session_job,
        "London",
        "🇬🇧"
    )

    schedule.every().day.at("12:00").do(
        session_job,
        "New York",
        "🇺🇸"
    )

    while True:

        schedule.run_pending()

        time.sleep(30)

# ── MAIN ────────────────────────────────────────────────────────────────────
def main():

    print("BOT RUNNING")

    threading.Thread(
        target=run_scheduler,
        daemon=True
    ).start()

    threading.Thread(
        target=check_price_alerts,
        daemon=True
    ).start()

    offset = None

    while True:

        try:

            updates = get_updates(offset)

            if updates.get("ok"):

                for u in updates.get("result", []):

                    offset = u["update_id"] + 1

                    msg = u.get("message", {})

                    if "text" in msg:

                        handle(
                            msg["chat"]["id"],
                            msg["text"]
                        )

        except Exception as e:

            print("main:", e)

            time.sleep(5)

if __name__ == "__main__":
    main()