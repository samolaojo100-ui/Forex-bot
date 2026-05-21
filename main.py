import os
import requests
import time
import schedule
import threading
from datetime import datetime, timezone
import yfinance as yf

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY     = os.getenv("GEMINI_KEY")
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
        ticker = yf.Ticker(pair)
        hist   = ticker.history(period="1mo", interval="1d")
        if hist.empty:
            print(f"Empty data for {pair}")
            return None
        closes = hist["Close"].tolist()[::-1][:20]
        return closes
    except Exception as e:
        print(f"Data error {pair}: {e}")
        return None

def ask_gemini(prompt):
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15)
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"Gemini error: {e}")
        return "AI analysis unavailable right now."

def analyze(pair):
    closes = get_data(pair)
    if not closes or len(closes) < 5:
        return f"Could not fetch data for {pair}"
    label  = pair.replace("=X", "").replace("USD", "/USD").replace("EUR/", "EUR/")
    change = round(((closes[0] - closes[1]) / closes[1]) * 100, 4)
    sma5   = round(sum(closes[:5])  / 5,  5)
    sma20  = round(sum(closes[:min(20,len(closes))]) / min(20,len(closes)), 5)
    trend  = "BULLISH" if sma5 > sma20 else "BEARISH"
    prompt = f"""You are a professional forex trader. Analyze {pair}:
Latest Rate: {round(closes[0],5)}
Daily Change: {change}%
5-day SMA: {sma5} | 20-day SMA: {sma20} | Trend: {trend}
Last 5 closes: {', '.join(str(round(c,5)) for c in closes[:5])}

Reply with a clean Telegram message:
🔵 Direction: BUY or SELL
⏱ Timeframe: 1H / 4H / Daily
🎯 Entry Zone:
✅ Take Profit:
🛑 Stop Loss:
📊 Confidence: (max 85%)
💡 Reason: (2 sentences max)"""
    return ask_gemini(prompt)

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def handle(chat_id, text):
    cmd = text.strip().split()[0].lower()
    if cmd == "/start":
        send_message(chat_id,
            "👋 *Forex Signal Bot*\n\n"
            "• /signal — all pairs\n"
            "• /pairs — list pairs\n\n"
            "📅 Auto signal at *08:00 UTC* daily")
    elif cmd == "/signal":
        send_message(chat_id, "⏳ Analyzing all pairs...")
        for pair in PAIRS:
            send_message(chat_id, f"📊 *{pair}*\n\n{analyze(pair)}\n\n⏰ {now_utc()}")
            time.sleep(3)
    elif cmd == "/pairs":
        send_message(chat_id, "📈 *Pairs*\n\n" + "\n".join(f"• {p}" for p in PAIRS))

def daily_job():
    for pair in PAIRS:
        send_message(CHAT_ID, f"🌅 *Daily — {pair}*\n\n{analyze(pair)}\n\n⏰ {now_utc()}")
        time.sleep(3)

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
    
