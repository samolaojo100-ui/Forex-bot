import os
import requests
import time
import threading
from datetime import datetime, timezone

# =========================
# ENV CHECK
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")
GEMINI_KEY = os.getenv("GEMINI_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("Missing TELEGRAM_TOKEN")
if not TWELVE_DATA_KEY:
    raise ValueError("Missing TWELVE_DATA_KEY")
if not GEMINI_KEY:
    raise ValueError("Missing GEMINI_KEY")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

PAIRS = ["EUR/USD", "GBP/USD", "USD/CAD", "USD/JPY", "AUD/USD"]

# =========================
# TELEGRAM CORE
# =========================

def send_message(chat_id, text):
    try:
        r = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
        return r.json()
    except Exception as e:
        print("SEND ERROR:", e)


def get_updates(offset=None):
    try:
        r = requests.get(
            f"{BASE_URL}/getUpdates",
            params={
                "timeout": 20,
                "offset": offset
            },
            timeout=25
        )
        return r.json()
    except Exception as e:
        print("GETUPDATES ERROR:", e)
        return {"ok": False}


# =========================
# MARKET DATA
# =========================

def get_data(pair, interval="1h", size=100):
    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": pair,
                "interval": interval,
                "outputsize": size,
                "apikey": TWELVE_DATA_KEY
            },
            timeout=15
        )

        data = r.json()

        if "values" not in data:
            return None

        # reverse so oldest -> newest
        return list(reversed(data["values"]))

    except Exception as e:
        print("DATA ERROR:", e)
        return None


# =========================
# INDICATORS
# =========================

def sma(data, period):
    if len(data) < period:
        return None
    return sum(data[-period:]) / period


def ema(data, period):
    if len(data) < period:
        return None

    k = 2 / (period + 1)
    ema_val = sum(data[:period]) / period

    for price in data[period:]:
        ema_val = price * k + ema_val * (1 - k)

    return ema_val


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50

    gains = 0
    losses = 0

    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses += abs(diff)

    if losses == 0:
        return 100

    rs = gains / losses
    return round(100 - (100 / (1 + rs)), 2)


def atr(values, period=14):
    if len(values) < period + 1:
        return 0.001

    trs = []

    for i in range(-period, 0):
        high = float(values[i]["high"])
        low = float(values[i]["low"])
        prev_close = float(values[i - 1]["close"])

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        trs.append(tr)

    return sum(trs) / period


# =========================
# GEMINI (EXPLANATION ONLY)
# =========================

def ask_gemini(prompt):
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
            json={
                "contents": [
                    {"parts": [{"text": prompt}]}
                ]
            },
            timeout=20
        )

        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        print("GEMINI ERROR:", e)
        return "Analysis unavailable."


# =========================
# SIGNAL ENGINE
# =========================

def analyze(pair):

    data = get_data(pair)

    if not data:
        return f"❌ No data for {pair}"

    closes = [float(x["close"]) for x in data]

    latest = data[-1]
    price = float(latest["close"])

    sma5 = sma(closes, 5)
    sma20 = sma(closes, 20)
    ema10 = ema(closes, 10)
    rsi_val = rsi(closes)
    atr_val = atr(data)

    if not sma5 or not sma20 or not ema10:
        return "❌ Not enough data"

    direction = None

    # ================= BUY =================
    if sma5 > sma20 and price > ema10 and 50 < rsi_val < 70:
        direction = "BUY"
        entry = price
        sl = entry - (atr_val * 1.5)
        tp = entry + (atr_val * 3)

    # ================= SELL =================
    elif sma5 < sma20 and price < ema10 and 30 < rsi_val < 50:
        direction = "SELL"
        entry = price
        sl = entry + (atr_val * 1.5)
        tp = entry - (atr_val * 3)

    else:
        return f"📊 {pair}\n\n⚠️ No clean setup."

    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / risk if risk != 0 else 0

    if rr < 1.5:
        return f"📊 {pair}\n\n⚠️ Weak RR ({rr:.2f})"

    prompt = f"""
Forex analysis only. Do not invent numbers.

Pair: {pair}
Direction: {direction}
Entry: {entry}
TP: {tp}
SL: {sl}
RSI: {rsi_val}
ATR: {atr_val}

Return clean signal:
Direction:
Entry:
TP:
SL:
Confidence:
Reason (max 2 lines)
"""

    ai = ask_gemini(prompt)

    return (
        f"📊 *{pair}*\n\n"
        f"{ai}\n\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )


# =========================
# COMMAND HANDLER
# =========================

def handle(chat_id, text):

    text = text.strip().lower()

    if text == "/start":
        send_message(
            chat_id,
            "📊 Forex Bot Ready\n\n"
            "/signal - all pairs\n"
            "/analyze eurusd"
        )

    elif text == "/pairs":
        send_message(chat_id, "\n".join(PAIRS))

    elif text == "/signal":
        send_message(chat_id, "Analyzing...")
        for p in PAIRS:
            send_message(chat_id, analyze(p))
            time.sleep(2)

    elif text.startswith("/analyze"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Use /analyze eurusd")
            return

        raw = parts[1].upper()
        pair = raw[:3] + "/" + raw[3:]

        send_message(chat_id, analyze(pair))


# =========================
# MAIN LOOP
# =========================

def main():
    print("Bot running...")

    offset = None

    while True:
        updates = get_updates(offset)

        if updates.get("ok"):
            for u in updates.get("result", []):

                offset = u["update_id"] + 1

                msg = u.get("message", {})

                if "text" in msg:
                    handle(msg["chat"]["id"], msg["text"])

        time.sleep(2)


if __name__ == "__main__":
    main()
