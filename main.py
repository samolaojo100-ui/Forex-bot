import os
import requests
import time
import schedule
import threading
from datetime import datetime

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
        print(f"Send error: {e}")

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
        print(f"Update error: {e}")
        return {"ok": False}

def get_data(pair):
    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol": pair,
                "interval": "1day",
                "outputsize": 20,
                "apikey": TWELVE_DATA_KEY
            },
            timeout=10
        )

        data = r.json()
        return data.get("values")

    except Exception as e:
        print(f"Data error: {e}")
        return None

# FIXED GEMINI FUNCTION
def ask_gemini(prompt):
    try:
        url = (
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ]
        }

        r = requests.post(url, json=payload, timeout=20)

        print("Gemini status:", r.status_code)
        print("Gemini response:", r.text)

        data = r.json()

        if "candidates" not in data:
            return f"Gemini API Error:\n{data}"

        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        return f"Gemini Exception:\n{e}"

def analyze(pair):
    values = get_data(pair)

    if not values:
        return f"Could not fetch data for {pair}"

    closes = [float(v["close"]) for v in values]

    latest = values[0]
    prev = values[1]

    change = round(
        (
            (
                float(latest["close"]) -
                float(prev["close"])
            ) / float(prev["close"])
        ) * 100,
        4
    )

    sma5 = round(sum(closes[:5]) / 5, 5)
    sma20 = round(sum(closes[:20]) / 20, 5)

    trend = "BULLISH" if sma5 > sma20 else "BEARISH"

    prompt = f"""
You are a professional forex trader.

Analyze {pair}

Price: {latest['close']}
Change: {change}%

High: {latest['high']}
Low: {latest['low']}

5-SMA: {sma5}
20-SMA: {sma20}

Trend: {trend}

Reply with a clean Telegram message.

Direction: BUY or SELL
Timeframe: 1H / 4H / Daily
Entry Zone:
Take Profit:
Stop Loss:
Confidence: (max 85%)
Reason: (2 sentences max)
"""

    return ask_gemini(prompt)

def handle(chat_id, text):
    text = text.strip()

    if text == "/start":
        send_message(
            chat_id,
            "👋 *Forex Signal Bot*\n\n"
            "• /signal — all pairs\n"
            "• /analyze EURUSD — one pair\n"
            "• /pairs — list pairs\n\n"
            "📅 Auto signal at *08:00 UTC* daily"
        )

    elif text == "/signal":

        send_message(chat_id, "⏳ Analyzing all pairs...")

        for pair in PAIRS:

            send_message(
                chat_id,
                f"📊 *{pair}*\n\n"
                f"{analyze(pair)}\n\n"
                f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
            )

            time.sleep(4)

    elif text.startswith("/analyze"):

        parts = text.split()

        if len(parts) < 2:
            send_message(chat_id, "Usage: /analyze EURUSD")
            return

        raw = parts[1].upper()

        pair = (
            raw[:3] + "/" + raw[3:]
            if "/" not in raw
            else raw
        )

        send_message(chat_id, f"⏳ Analyzing {pair}...")

        send_message(
            chat_id,
            f"📊 *{pair}*\n\n"
            f"{analyze(pair)}\n\n"
            f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )

    elif text == "/pairs":

        send_message(
            chat_id,
            "📈 *Pairs*\n\n" +
            "\n".join(f"• {p}" for p in PAIRS)
        )

def daily_job():

    for pair in PAIRS:

        send_message(
            CHAT_ID,
            f"🌅 *Daily — {pair}*\n\n"
            f"{analyze(pair)}\n\n"
            f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )

        time.sleep(4)

def run_scheduler():

    schedule.every().day.at("08:00").do(daily_job)

    while True:
        schedule.run_pending()
        time.sleep(30)

def main():

    print("Bot running...")

    threading.Thread(
        target=run_scheduler,
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

            print(f"Error: {e}")

            time.sleep(5)

if __name__ == "__main__":
    main()