import os
import requests
import time
import threading
import json
from datetime import datetime, timezone
import yfinance as yf

# ── ENV ────────────────────────────────────────────────────────────────────────
TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL     = f"https://api.telegram.org/bot{TOKEN}"

# ── PAIRS ──────────────────────────────────────────────────────────────────────
ALL_PAIRS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDCAD": "USDCAD=X",
    "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X",
    "USDCHF": "USDCHF=X",
    "XAUUSD": "GC=F",
}

# ── MENU ───────────────────────────────────────────────────────────────────────
MENU = [
    ["⚡ 1M", "🚀 5M"],
    ["📈 15M", "🔥 30M"],
    ["🧠 1H", "👑 Daily"],
    ["📰 News"]
]

# ── UTIL ───────────────────────────────────────────────────────────────────────
def send(cid, text):
    try:
        requests.post(f"{URL}/sendMessage", json={
            "chat_id": cid,
            "text": text
        })
    except Exception as e:
        print("Send error:", e)

def get_updates(offset=None):
    try:
        r = requests.get(f"{URL}/getUpdates",
                         params={"timeout": 30, "offset": offset})
        return r.json()
    except:
        return {}

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# ── DATA ───────────────────────────────────────────────────────────────────────
def fetch(ticker, period, interval):
    try:
        data = yf.Ticker(ticker).history(period=period, interval=interval)
        return data
    except:
        return None

# ── INDICATORS ─────────────────────────────────────────────────────────────────
def ema(values, period):
    k = 2 / (period + 1)
    e = values[0]
    for v in values:
        e = v * k + e * (1 - k)
    return e

def rsi(values, period=14):
    gains = []
    losses = []

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains[-period:]) / period if gains else 1
    avg_loss = sum(losses[-period:]) / period if losses else 1

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ── TIMEFRAME MAP ──────────────────────────────────────────────────────────────
TF_MAP = {
    "1m": ("1d", "1m"),
    "5m": ("5d", "5m"),
    "15m": ("5d", "15m"),
    "30m": ("1mo", "30m"),
    "1h": ("1mo", "1h"),
    "1d": ("3mo", "1d")
}

TF_LABEL = {
    "1m": "1 Minute",
    "5m": "5 Minutes",
    "15m": "15 Minutes",
    "30m": "30 Minutes",
    "1h": "1 Hour",
    "1d": "Daily"
}

# ── SCORE ──────────────────────────────────────────────────────────────────────
def score_pair(name, ticker, tf="5m"):

    period, interval = TF_MAP.get(tf, ("5d", "5m"))
    data = fetch(ticker, period, interval)

    if data is None or len(data) < 50:
        return None

    closes = data["Close"].tolist()

    price = closes[-1]

    ema50 = ema(closes[-50:], 50)
    ema200 = ema(closes[-200:], 200)

    r = rsi(closes[-30:])

    bull = 0
    bear = 0

    if ema50 > ema200:
        bull += 2
    else:
        bear += 2

    if r < 35:
        bull += 2
    elif r > 65:
        bear += 2

    if closes[-1] > closes[-2]:
        bull += 1
    else:
        bear += 1

    direction = "BUY" if bull > bear else "SELL"
    score = max(bull, bear)

    return {
        "name": name,
        "price": round(price, 5),
        "direction": direction,
        "score": score
    }

# ── FORMAT ─────────────────────────────────────────────────────────────────────
def format_signal(d, acc, risk, tf):

    risk_usd = round(acc * (risk / 100), 2)

    return (
        f"🚨 FOREX SIGNAL 🚨\n\n"
        f"📊 {d['name']}\n"
        f"⏰ {TF_LABEL.get(tf, tf)}\n"
        f"📈 {d['direction']}\n\n"
        f"🎯 Entry: {d['price']}\n"
        f"🛑 SL / TP: Auto (1:2)\n\n"
        f"💰 Risk: ${risk_usd}\n"
        f"🔥 Score: {d['score']}/7\n"
        f"🕐 {now()}"
    )

# ── SCAN ──────────────────────────────────────────────────────────────────────
def scan(cid, acc, risk, tf):

    send(cid, f"Scanning {TF_LABEL.get(tf)}...")

    results = []

    for name, ticker in ALL_PAIRS.items():

        d = score_pair(name, ticker, tf)

        if d:
            results.append(d)

        time.sleep(0.5)

    results.sort(key=lambda x: x["score"], reverse=True)

    top = [r for r in results if r["score"] >= 5]

    if not top:
        top = results[:3]

    for r in top:
        send(cid, format_signal(r, acc, risk, tf))

# ── BOT LOOP ───────────────────────────────────────────────────────────────────
def handle(cid, txt, acc=100, risk=2):

    txt = txt.lower()

    if txt == "⚡ 1m":
        scan(cid, acc, risk, "1m")

    elif txt == "🚀 5m":
        scan(cid, acc, risk, "5m")

    elif txt == "📈 15m":
        scan(cid, acc, risk, "15m")

    elif txt == "🔥 30m":
        scan(cid, acc, risk, "30m")

    elif txt == "🧠 1h":
        scan(cid, acc, risk, "1h")

    elif txt == "👑 daily":
        scan(cid, acc, risk, "1d")

    else:
        send(cid,
             "Choose timeframe:\n⚡1M 🚀5M 📈15M 🔥30M 🧠1H 👑Daily")

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():

    print("Bot running...")

    offset = None

    while True:

        try:
            updates = get_updates(offset)

            if "result" in updates:

                for u in updates["result"]:

                    offset = u["update_id"] + 1

                    msg = u.get("message")

                    if msg and "text" in msg:

                        cid = msg["chat"]["id"]
                        txt = msg["text"]

                        handle(cid, txt)

        except Exception as e:
            print("Error:", e)

        time.sleep(1)

if __name__ == "__main__":
    main()