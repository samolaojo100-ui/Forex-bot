import os
import requests
import time
import json
from datetime import datetime, timezone
import yfinance as yf

# ── ENV ─────────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL = f"https://api.telegram.org/bot{TOKEN}"

# ── PAIRS ───────────────────────────────────────────
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

# ── MENU ────────────────────────────────────────────
MENU = [
    ["🚀 5m", "📈 15m"],
    ["🔥 30m", "🧠 1h"],
    ["👑 daily"]
]

# ── TELEGRAM ────────────────────────────────────────
def send(cid, text):
    try:
        requests.post(f"{URL}/sendMessage", json={
            "chat_id": cid,
            "text": text
        })
    except:
        pass

def get_updates(offset=None):
    try:
        r = requests.get(f"{URL}/getUpdates",
                         params={"timeout": 30, "offset": offset})
        return r.json()
    except:
        return {}

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# ── DATA ────────────────────────────────────────────
def fetch(ticker, period, interval):
    try:
        return yf.Ticker(ticker).history(period=period, interval=interval)
    except:
        return None

# ── INDICATORS ──────────────────────────────────────
def ema(values, period):
    k = 2 / (period + 1)
    e = values[0]
    for v in values:
        e = v * k + e * (1 - k)
    return e

def rsi(values):
    gains, losses = [], []

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains[-14:]) / 14 if gains else 1
    avg_loss = sum(losses[-14:]) / 14 if losses else 1

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ── TIMEFRAMES ──────────────────────────────────────
TF = {
    "5m": ("5d", "5m"),
    "15m": ("5d", "15m"),
    "30m": ("1mo", "30m"),
    "1h": ("1mo", "1h"),
    "daily": ("3mo", "1d")
}

TF_LABEL = {
    "5m": "5 Minutes",
    "15m": "15 Minutes",
    "30m": "30 Minutes",
    "1h": "1 Hour",
    "daily": "Daily"
}

# ── SL / TP ENGINE (FIXED) ──────────────────────────
def get_sl_tp(price, direction, tf):

    multipliers = {
        "5m": 0.0020,
        "15m": 0.0035,
        "30m": 0.0050,
        "1h": 0.0070,
        "daily": 0.0120
    }

    m = multipliers.get(tf, 0.003)

    sl_distance = price * m
    tp_distance = sl_distance * 2  # 1:2 RR

    if direction == "BUY":
        sl = price - sl_distance
        tp = price + tp_distance
    else:
        sl = price + sl_distance
        tp = price - tp_distance

    return round(sl, 5), round(tp, 5)

# ── SCORE ENGINE ────────────────────────────────────
def score_pair(name, ticker, tf="5m"):

    period, interval = TF.get(tf, ("5d", "5m"))
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

# ── FORMAT SIGNAL ───────────────────────────────────
def format_signal(d, acc, risk, tf):

    risk_usd = round(acc * (risk / 100), 2)

    sl, tp = get_sl_tp(d["price"], d["direction"], tf)

    return (
        f"🚨 FOREX SIGNAL 🚨\n\n"
        f"📊 {d['name']}\n"
        f"⏰ {TF_LABEL.get(tf)}\n"
        f"📈 {d['direction']}\n\n"
        f"🎯 Entry: {d['price']}\n"
        f"🛑 SL: {sl}\n"
        f"✅ TP: {tp}\n\n"
        f"💰 Risk: ${risk_usd}\n"
        f"🔥 Score: {d['score']}/7\n"
        f"🕐 {now()}"
    )

# ── SCAN ────────────────────────────────────────────
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

# ── HANDLE ──────────────────────────────────────────
def handle(cid, txt, acc=100, risk=2):

    text = txt.lower().strip()

    if text in ["🚀 5m", "5m", "5"]:
        scan(cid, acc, risk, "5m")

    elif text in ["📈 15m", "15m", "15"]:
        scan(cid, acc, risk, "15m")

    elif text in ["🔥 30m", "30m", "30"]:
        scan(cid, acc, risk, "30m")

    elif text in ["🧠 1h", "1h", "hour"]:
        scan(cid, acc, risk, "1h")

    elif text in ["👑 daily", "daily", "1d"]:
        scan(cid, acc, risk, "daily")

    else:
        send(cid, "Choose timeframe:\n🚀5m 📈15m 🔥30m 🧠1H 👑Daily")

# ── MAIN LOOP ───────────────────────────────────────
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
