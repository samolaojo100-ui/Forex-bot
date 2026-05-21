import os
import requests
import time
import threading
import statistics
from datetime import datetime, timezone

# =========================
# CONFIG
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")
GEMINI_KEY = os.getenv("GEMINI_KEY")
CHAT_ID = os.getenv("CHAT_ID")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

PAIRS = [
    "EUR/USD",
    "GBP/USD",
    "USD/CAD",
    "USD/JPY",
    "AUD/USD"
]

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
    except:
        print("Telegram send failed")


def get_updates(offset=None):
    try:
        response = requests.get(
            f"{BASE_URL}/getUpdates",
            params={
                "timeout": 30,
                "offset": offset
            },
            timeout=35
        )
        return response.json()
    except:
        return {"ok": False}


# =========================
# MARKET DATA
# =========================

def get_data(pair, interval="1h", outputsize=100):
    try:
        response = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": pair,
                "interval": interval,
                "outputsize": outputsize,
                "apikey": TWELVE_DATA_KEY
            },
            timeout=15
        )

        data = response.json()

        if "values" not in data:
            return None

        return data["values"]

    except:
        return None


# =========================
# INDICATORS
# =========================

def sma(data, period):
    return sum(data[:period]) / period


def ema(prices, period):
    multiplier = 2 / (period + 1)
    ema_value = sum(prices[:period]) / period

    for price in prices[period:]:
        ema_value = (price - ema_value) * multiplier + ema_value

    return ema_value


def calculate_rsi(closes, period=14):
    gains = []
    losses = []

    for i in range(period):
        diff = closes[i] - closes[i + 1]

        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains) / period if gains else 0.0001
    avg_loss = sum(losses) / period if losses else 0.0001

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return round(rsi, 2)


def calculate_atr(values, period=14):
    trs = []

    for i in range(period):
        high = float(values[i]["high"])
        low = float(values[i]["low"])
        prev_close = float(values[i + 1]["close"])

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        trs.append(tr)

    return round(sum(trs) / period, 5)


# =========================
# SIGNAL ENGINE
# =========================

def build_signal(pair):

    daily_data = get_data(pair, "1day", 50)
    h4_data = get_data(pair, "4h", 50)
    h1_data = get_data(pair, "1h", 50)

    if not daily_data or not h4_data or not h1_data:
        return "❌ Failed to fetch market data."

    closes = [float(v["close"]) for v in h4_data]

    latest = h4_data[0]
    latest_close = float(latest["close"])

    sma5 = round(sma(closes, 5), 5)
    sma20 = round(sma(closes, 20), 5)

    ema10 = round(ema(closes[::-1], 10), 5)

    rsi = calculate_rsi(closes)

    atr = calculate_atr(h4_data)

    previous_high = float(h4_data[1]["high"])
    previous_low = float(h4_data[1]["low"])

    direction = None
    confidence = 0

    # =========================
    # BUY CONDITIONS
    # =========================

    if (
        sma5 > sma20 and
        latest_close > ema10 and
        50 < rsi < 70 and
        latest_close > previous_high
    ):

        direction = "BUY"

        entry = latest_close

        stop_loss = round(entry - (atr * 1.5), 5)

        take_profit = round(entry + (atr * 3), 5)

        risk = entry - stop_loss
        reward = take_profit - entry

        rr = round(reward / risk, 2)

        confidence = min(
            85,
            round(
                60 +
                ((sma5 - sma20) * 10000 / 4) +
                ((70 - rsi) / 3)
            )
        )

    # =========================
    # SELL CONDITIONS
    # =========================

    elif (
        sma5 < sma20 and
        latest_close < ema10 and
        30 < rsi < 50 and
        latest_close < previous_low
    ):

        direction = "SELL"

        entry = latest_close

        stop_loss = round(entry + (atr * 1.5), 5)

        take_profit = round(entry - (atr * 3), 5)

        risk = stop_loss - entry
        reward = entry - take_profit

        rr = round(reward / risk, 2)

        confidence = min(
            85,
            round(
                60 +
                ((sma20 - sma5) * 10000 / 4) +
                ((rsi - 30) / 3)
            )
        )

    else:
        return (
            f"📊 *{pair}*\n\n"
            f"⚠️ No high-quality setup right now.\n"
            f"Market conditions are unclear."
        )

    # =========================
    # RISK FILTER
    # =========================

    if rr < 1.5:
        return (
            f"📊 *{pair}*\n\n"
            f"⚠️ Trade rejected.\n"
            f"Risk-to-reward too weak ({rr}:1)."
        )

    # =========================
    # AI EXPLANATION
    # =========================

    explanation = ask_gemini(
        pair,
        direction,
        entry,
        take_profit,
        stop_loss,
        confidence,
        sma5,
        sma20,
        rsi,
        atr
    )

    return (
        f"📊 *{pair}*\n\n"
        f"{explanation}\n\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )


# =========================
# GEMINI EXPLANATION ONLY
# =========================

def ask_gemini(
    pair,
    direction,
    entry,
    tp,
    sl,
    confidence,
    sma5,
    sma20,
    rsi,
    atr
):

    prompt = f"""
You are a professional forex analyst.

DO NOT invent prices.

Use the exact data below.

Pair: {pair}
Direction: {direction}
Entry: {entry}
Take Profit: {tp}
Stop Loss: {sl}
Confidence: {confidence}%
SMA5: {sma5}
SMA20: {sma20}
RSI: {rsi}
ATR: {atr}

Create a SHORT clean Telegram signal.

Format:

Direction:
Timeframe:
Entry Zone:
Take Profit:
Stop Loss:
Confidence:
Reason:

Maximum 2 short sentences for reason.
"""

    try:

        response = requests.post(
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

        data = response.json()

        return data["candidates"][0]["content"]["parts"][0]["text"]

    except:
        return (
            f"🔵 Direction: {direction}\n"
            f"🎯 Entry: {entry}\n"
            f"✅ TP: {tp}\n"
            f"🛑 SL: {sl}\n"
            f"📊 Confidence: {confidence}%"
        )


# =========================
# COMMAND HANDLER
# =========================

def handle(chat_id, text):

    text = text.strip()

    if text == "/start":

        send_message(
            chat_id,
            "👋 *Advanced Forex Signal Bot*\n\n"
            "Commands:\n"
            "• /signal — analyze all pairs\n"
            "• /analyze EURUSD — analyze one pair\n"
            "• /pairs — list pairs"
        )

    elif text == "/pairs":

        send_message(
            chat_id,
            "📈 *Available Pairs*\n\n" +
            "\n".join([f"• {p}" for p in PAIRS])
        )

    elif text == "/signal":

        send_message(chat_id, "⏳ Scanning market...")

        for pair in PAIRS:

            result = build_signal(pair)

            send_message(chat_id, result)

            time.sleep(3)

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

        send_message(chat_id, f"⏳ Analyzing {pair}...")

        result = build_signal(pair)

        send_message(chat_id, result)


# =========================
# DAILY SIGNAL SYSTEM
# =========================

def auto_signals():

    while True:

        now = datetime.now(timezone.utc)

        # 08:00 UTC
        if now.hour == 8 and now.minute == 0:

            for pair in PAIRS:

                result = build_signal(pair)

                send_message(
                    CHAT_ID,
                    f"🌅 *Daily Signal*\n\n{result}"
                )

                time.sleep(5)

            time.sleep(60)

        time.sleep(20)


# =========================
# MAIN LOOP
# =========================

def main():

    print("Advanced forex bot running...")

    threading.Thread(
        target=auto_signals,
        daemon=True
    ).start()

    offset = None

    while True:

        try:

            updates = get_updates(offset)

            if updates.get("ok"):

                for update in updates.get("result", []):

                    offset = update["update_id"] + 1

                    message = update.get("message", {})

                    if "text" in message:

                        handle(
                            message["chat"]["id"],
                            message["text"]
                        )

        except:

            print("Main loop error")

            time.sleep(5)


if __name__ == "__main__":
    main()
