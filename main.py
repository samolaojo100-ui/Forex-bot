import os
import requests
import time
from datetime import datetime, timezone

# =========================
# ENV VARIABLES
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
# TELEGRAM
# =========================

def send_message(chat_id, text):
    try:
        requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
    except Exception as e:
        print("SEND ERROR:", e)


def get_updates(offset=None):
    try:
        r = requests.get(
            f"{BASE_URL}/getUpdates",
            params={"timeout": 20, "offset": offset},
            timeout=25
        )
        return r.json()
    except Exception as e:
        print("GETUPDATES ERROR:", e)
        return {"ok": False}


# =========================
# MARKET DATA
# =========================

def get_data(pair):
    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": pair,
                "interval": "1h",
                "outputsize": 100,
                "apikey": TWELVE_DATA_KEY
            },
            timeout=15
        )

        data = r.json()

        if "values" not in data:
            return None

        return list(reversed(data["values"]))  # oldest → newest

    except Exception as e:
        print("DATA ERROR:", e)
        return None


# =========================
# INDICATORS
# =========================

def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values, period):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period

    for v in values[period:]:
        ema_val = v * k + ema_val * (1 - k)

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


def atr(data, period=14):
    if len(data) < period + 1:
        return 0.001

    trs = []

    for i in range(-period, 0):
        high = float(data[i]["high"])
        low = float(data[i]["low"])
        prev_close = float(data[i - 1]["close"])

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        trs.append(tr)

    return sum(trs) / period


# =========================
# GEMINI (TEXT ONLY)
# =========================

def ask_gemini(prompt):
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20
        )

        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        print("GEMINI ERROR:", e)
        return "AI analysis unavailable."


# =========================
# SIGNAL ENGINE
# =========================

def analyze(pair):

    data = get_data(pair)

    if not data:
        return f"❌ No data for {pair}"

    closes = [float(x["close"]) for x in data]

    price = closes[-1]

    sma5 = sma(closes, 5)
    sma20 = sma(closes, 20)
    ema10 = ema(closes, 10)
    rsi_val = rsi(closes)
    atr_val = atr(data)

    if not sma5 or not sma20 or not ema10:
        return "❌ Not enough data"

    direction = None

    # BUY
    if sma5 > sma20 and price > ema10 and 50 < rsi_val < 70:
        direction = "BUY"
        entry = price
        sl = entry - (atr_val * 1.5)
        tp = entry + (atr_val * 3)

    # SELL
    elif sma5 < sma20 and price < ema10 and 30 < rsi_val < 50:
        direction = "SELL"
        entry = price
        sl = entry + (atr_val * 1.5)
        tp = entry - (atr_val * 3)

    else:
        return f"📊 {pair}\n\n⚠️ No valid setup"

    risk = abs(entry - sl)
    reward = abs(tp - entry)

    rr = reward / risk if risk else 0

    if rr < 1.5:
        return f"📊 {pair}\n\n⚠️ Weak RR ({rr:.2f})"

    prompt = f"""
Forex signal only.

Pair: {pair}
Direction: {direction}
Entry: {entry}
TP: {tp}
SL: {sl}
RSI: {rsi_val}
ATR: {atr_val}

Format:
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
        send_message(chat_id,
            "📊 Forex Bot Ready\n\n"
            "/signal - all pairs\n"
            "/analyze eurusd\n"
            "/pairs"
        )

    elif text == "/pairs":
        send_message(chat_id, "\n".join(PAIRS))

    elif text == "/signal":
        send_message(chat_id, "Analyzing market...")

        for p in PAIRS:
            send_message(chat_id, analyze(p))
            time.sleep(2)

    elif text.startswith("/analyze"):
        parts = text.split()

        if len(parts) < 2:
            send_message(chat_id, "Usage: /analyze eurusd")
            return

        raw = parts[1].upper()
        pair = raw[:3] + "/" + raw[3:]

        send_message(chat_id, analyze(pair))


# =========================
# MAIN LOOP (IMPORTANT FIXED PART)
# =========================

def main():

    print("BOT STARTED SUCCESSFULLY")

    offset = None

    while True:

        updates = get_updates(offset)

        if updates.get("ok"):

            for u in updates.get("result", []):

                offset = u["update_id"] + 1

                msg = u.get("message", {})

                if "text" in msg:
                    chat_id = msg["chat"]["id"]
                    text = msg["text"]

                    print("MSG:", text)

                    handle(chat_id, text)

        time.sleep(2)


if __name__ == "__main__":
    main()
