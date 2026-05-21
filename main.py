import os
import requests
import time
import schedule
import threading
from datetime import datetime, timezone
import yfinance as yf

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
PAIRS    = ["EURUSD=X", "GBPUSD=X", "USDCAD=X", "USDJPY=X", "AUDUSD=X"]

def send_message(chat_id, text):
    try:
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

def get_updates(offset=None):
    try:
        r = requests.get(f"{BASE_URL}/getUpdates",
                         params={"timeout": 30, "offset": offset}, timeout=35)
        return r.json()
    except:
        return {"ok": False}

def get_data(pair):
    try:
        hist = yf.Ticker(pair).history(period="1mo", interval="1d")
        if hist.empty:
            return None
        return hist
    except Exception as e:
        print(f"Data error {pair}: {e}")
        return None

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[-(period + 1) + i] - closes[-(period + 1) + i - 1]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_g = sum(gains) / period if gains else 0.001
    avg_l = sum(losses) / period if losses else 0.001
    return round(100 - (100 / (1 + avg_g / avg_l)), 1)

def analyze(pair):
    hist = get_data(pair)
    if hist is None:
        return f"⚠️ Could not fetch data for {pair}"

    closes = hist["Close"].tolist()
    highs  = hist["High"].tolist()
    lows   = hist["Low"].tolist()

    price   = round(closes[-1], 5)
    prev    = round(closes[-2], 5)
    change  = round(((price - prev) / prev) * 100, 3)
    sma5    = round(sum(closes[-5:])  / 5, 5)
    sma20   = round(sum(closes[-20:]) / 20, 5) if len(closes) >= 20 else round(sum(closes) / len(closes), 5)
    rsi     = calc_rsi(closes)
    high14  = round(max(highs[-14:]), 5)
    low14   = round(min(lows[-14:]),  5)

    # Signal logic
    bullish_points = 0
    bearish_points = 0
    if sma5 > sma20: bullish_points += 1
    else:            bearish_points += 1
    if rsi < 45:     bullish_points += 1
    elif rsi > 55:   bearish_points += 1
    if change > 0:   bullish_points += 1
    else:            bearish_points += 1

    direction  = "BUY 📈" if bullish_points > bearish_points else "SELL 📉"
    is_buy     = bullish_points > bearish_points
    confidence = min(55 + (abs(bullish_points - bearish_points) * 10), 80)

    if is_buy:
        entry   = f"{round(price, 5)} — {round(price * 1.0005, 5)}"
        tp      = round(price * 1.005, 5)
        sl      = round(price * 0.997, 5)
        reason  = f"SMA5 ({sma5}) is {'above' if sma5 > sma20 else 'below'} SMA20 ({sma20}), RSI at {rsi}. Price showing {'bullish' if change > 0 else 'mixed'} momentum with {change}% daily change."
    else:
        entry   = f"{round(price * 0.9995, 5)} — {round(price, 5)}"
        tp      = round(price * 0.995, 5)
        sl      = round(price * 1.003, 5)
        reason  = f"SMA5 ({sma5}) is {'above' if sma5 > sma20 else 'below'} SMA20 ({sma20}), RSI at {rsi}. Price showing {'bearish' if change < 0 else 'mixed'} momentum with {change}% daily change."

    name = pair.replace("=X", "")
    return (
        f"🔵 *Direction:* {direction}\n"
        f"⏱ *Timeframe:* 4H / Daily\n"
        f"🎯 *Entry Zone:* {entry}\n"
        f"✅ *Take Profit:* {tp}\n"
        f"🛑 *Stop Loss:* {sl}\n"
        f"📊 *Confidence:* {confidence}%\n"
        f"📈 *14D Range:* {low14} — {high14}\n"
        f"💡 *Reason:* {reason}"
    )

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def handle(chat_id, text):
    cmd = text.strip().split()[0].lower()
    if cmd == "/start":
        send_message(chat_id,
            "👋 *Forex Signal Bot*\n\n"
            "Commands:\n"
            "• /signal — signals for all pairs\n"
            "• /pairs — list tracked pairs\n\n"
            "📅 Daily auto-signal at *08:00 UTC*")
    elif cmd == "/signal":
        send_message(chat_id, "⏳ Analyzing all pairs...")
        for pair in PAIRS:
            send_message(chat_id, f"📊 *{pair.replace('=X','')}*\n\n{analyze(pair)}\n\n⏰ {now_utc()}")
            time.sleep(2)
    elif cmd == "/pairs":
        lines = "\n".join(f"• {p.replace('=X','')}" for p in PAIRS)
        send_message(chat_id, f"📈 *Tracked Pairs*\n\n{lines}")

def daily_job():
    for pair in PAIRS:
        send_message(CHAT_ID, f"🌅 *Daily Signal — {pair.replace('=X','')}*\n\n{analyze(pair)}\n\n⏰ {now_utc()}")
        time.sleep(2)

def run_scheduler():
    schedule.every().day.at("08:00").do(daily_job)
    while True:
        schedule.run_pending()
        time.sleep(30)

def main():
    print("Bot running...")
    threading.Thread(target=run_scheduler, daemon=True).start()
    offset = None
    while True:
        try:
            updates = get_updates(offset)
            if updates.get("ok"):
                for u in updates.get("result", []):
                    offset = u["update_id"] + 1
                    msg = u.get("message", {})
                    if "text" in msg:
                        handle(msg["chat"]["id"], msg["text"])
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
                      
