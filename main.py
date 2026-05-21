import os
import asyncio
import requests
import threading
import schedule
import time
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
TWELVE_DATA_KEY   = os.getenv("TWELVE_DATA_KEY")
GEMINI_KEY        = os.getenv("GEMINI_KEY")
CHAT_ID           = os.getenv("CHAT_ID")

PAIRS = ["EUR/USD", "GBP/USD", "USD/CAD", "USD/JPY", "AUD/USD"]

def get_data(pair):
    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={"symbol": pair, "interval": "1day", "outputsize": 20, "apikey": TWELVE_DATA_KEY},
            timeout=10
        )
        data = r.json()
        if "values" not in data:
            return None
        return data["values"]
    except:
        return None

def ask_gemini(prompt):
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15
        )
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except:
        return "AI analysis unavailable right now."

def analyze(pair):
    values = get_data(pair)
    if not values:
        return f"⚠️ Could not fetch data for {pair}"

    closes = [float(v["close"]) for v in values]
    latest = values[0]
    prev   = values[1]
    change = round(((float(latest["close"]) - float(prev["close"])) / float(prev["close"])) * 100, 4)
    sma5   = round(sum(closes[:5]) / 5, 5)
    sma20  = round(sum(closes[:20]) / 20, 5)
    trend  = "BULLISH ↑" if sma5 > sma20 else "BEARISH ↓"

    prompt = f"""You are a professional forex trader.
Analyze {pair}:
Price: {latest['close']}
Change: {change}%
High: {latest['high']} Low: {latest['low']}
5-SMA: {sma5} | 20-SMA: {sma20}
Trend: {trend}
Last 5 closes: {', '.join(str(round(c,5)) for c in closes[:5])}

Reply with a clean Telegram message including:
🔵 Direction: BUY or SELL
⏱ Timeframe: 1H / 4H / Daily
🎯 Entry Zone:
✅ Take Profit:
🛑 Stop Loss:
📊 Confidence: (max 85%)
💡 Reason: (2 sentences)"""

    return ask_gemini(prompt)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Forex Signal Bot*\n\n"
        "Commands:\n"
        "• /signal — signals for all pairs\n"
        "• /analyze EURUSD — one pair\n"
        "• /pairs — tracked pairs\n\n"
        "📅 Auto signal daily at *08:00 UTC*",
        parse_mode="Markdown"
    )

async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Analyzing all pairs, please wait...")
    for pair in PAIRS:
        result = analyze(pair)
        await update.message.reply_text(
            f"📊 *{pair}*\n\n{result}\n\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            parse_mode="Markdown"
        )
        time.sleep(3)

async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /analyze EURUSD")
        return
    raw  = context.args[0].upper()
    pair = raw[:3] + "/" + raw[3:] if "/" not in raw else raw
    await update.message.reply_text(f"⏳ Analyzing {pair}...")
    result = analyze(pair)
    await update.message.reply_text(
        f"📊 *{pair}*\n\n{result}\n\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        parse_mode="Markdown"
    )

async def cmd_pairs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = "\n".join(f"• {p}" for p in PAIRS)
    await update.message.reply_text(f"📈 *Tracked Pairs*\n\n{lines}", parse_mode="Markdown")

def run_scheduler(app):
    def job():
        async def _send():
            for pair in PAIRS:
                result = analyze(pair)
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🌅 *Daily Signal — {pair}*\n\n{result}\n\n⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
                    parse_mode="Markdown"
                )
                time.sleep(3)
        asyncio.run(_send())

    schedule.every().day.at("08:00").do(job)
    while True:
        schedule.run_pending()
        time.sleep(30)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("signal",  cmd_signal))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("pairs",   cmd_pairs))

    t = threading.Thread(target=run_scheduler, args=(app,), daemon=True)
    t.start()

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()

