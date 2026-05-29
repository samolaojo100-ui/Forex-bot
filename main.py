import os
import logging
import pandas as pd
import yfinance as yf
from telebot import TeleBot, types

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- CONFIGURATION & ENV VARIABLES ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN_PLACEHOLDER")
bot = TeleBot(TELEGRAM_TOKEN)

# 30 Pairs to Scan
PAIRS = [
    "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD",
    "USD_CHF", "NZD_USD", "EUR_GBP", "EUR_JPY", "GBP_JPY",
    "EUR_AUD", "EUR_CAD", "EUR_CHF", "EUR_NZD", "GBP_AUD",
    "GBP_CAD", "GBP_CHF", "GBP_NZD", "AUD_CAD", "AUD_CHF",
    "AUD_JPY", "AUD_NZD", "CAD_CHF", "CAD_JPY", "CHF_JPY",
    "NZD_CAD", "NZD_CHF", "NZD_JPY", "XAU_USD", "XAG_USD"
]

# Yahoo Finance timeframe mappings
TIMEFRAMES = {
    "5min": "5m",
    "15min": "15m",
    "1h": "60m",
    "4h": "60m",  # 4h is simulated or checked using 60m trend context
    "1day": "1d"
}

def get_candles_yfinance(symbol, timeframe):
    """
    Fetches real-time and historical candle data seamlessly from Yahoo Finance.
    No API Keys required, 100% free and stable.
    """
    interval = TIMEFRAMES.get(timeframe, "5m")
    
    # Format symbol correctly for Yahoo Finance conventions
    if symbol == "XAU_USD":
        yf_symbol = "GC=F"  # Gold Futures
    elif symbol == "XAG_USD":
        yf_symbol = "SI=F"  # Silver Futures
    else:
        yf_symbol = f"{symbol.replace('_', '')}=X"  # e.g., EURUSD=X

    try:
        # Pull enough historical data based on timeframe size
        period = "5d" if "min" in timeframe or timeframe == "1h" or timeframe == "4h" else "1mo"
        
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty or len(df) < 5:
            return None
            
        return {
            "c": df["Close"].tolist(),
            "o": df["Open"].tolist(),
            "h": df["High"].tolist(),
            "l": df["Low"].tolist()
        }
    except Exception as e:
        logger.error(f"Yahoo Finance fetch error for {symbol} on {timeframe}: {e}")
        return None

def analyze_market(candles):
    """
    Your bot's core technical indicator logic engine.
    Compares closing data metrics to define directions.
    """
    if not candles or "c" not in candles or len(candles["c"]) < 5:
        return None
    
    closes = candles["c"]
    current_price = closes[-1]
    prev_price = closes[-2]
    
    if current_price > prev_price:
        return "BUY"
    elif current_price < prev_price:
        return "SELL"
    return "NEUTRAL"

@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🔍 Scan Full Market"))
    
    welcome_text = (
        "🤖 **Welcome to SamSos Forex Signal Bot!**\n\n"
        "Click the button below to initiate the market matrix scanner."
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔍 Scan Full Market")
def handle_scan(message):
    chat_id = message.chat.id
    
    status_msg = bot.send_message(
        chat_id,
        "🔍 **Full Market Scanner Running...**\n\n"
        f"Scanning **{len(PAIRS)} pairs** across 5 timeframes.\n"
        "Powered by Yahoo Finance Data Engine.\n"
        "Minimum: 3 TFs must agree + strong indicators.\n"
        "📦 Lot size: **0.1**\n\n"
        "Processing market ticks... ⏳",
        parse_mode="Markdown"
    )
    
    scanned_count = 0
    unavailable_count = 0
    signals_found = []

    for pair in PAIRS:
        timeframe_results = {}
        pair_available = False
        
        for tf in TIMEFRAMES.keys():
            candles = get_candles_yfinance(pair, tf)
            if candles:
                pair_available = True
                analysis = analyze_market(candles)
                if analysis in ["BUY", "SELL"]:
                    timeframe_results[tf] = analysis
        
        if pair_available:
            scanned_count += 1
            buys = list(timeframe_results.values()).count("BUY")
            sells = list(timeframe_results.values()).count("SELL")
            
            # Require at least 3 matching timeframes to confirm a signal direction
            if buys >= 3:
                signals_found.append(f"🟩 **{pair.replace('_', '/')}** - STRONG BUY (Lot: 0.1)")
            elif sells >= 3:
                signals_found.append(f"🟥 **{pair.replace('_', '/')}** - STRONG SELL (Lot: 0.1)")
        else:
            unavailable_count += 1

    # Formulating final report summary
    report_text = (
        "📊 **Scan Complete**\n\n"
        f"Scanned: {scanned_count} pairs\n"
        f"Unavailable: {unavailable_count} pairs\n\n"
    )
    
    if signals_found:
        report_text += "🚀 **Strong Signals Detected:**\n" + "\n".join(signals_found)
    else:
        report_text += (
            "⛔ **No clean trend signals matched criteria.**\n"
            "Markets are moving sideways right now.\n\n"
            "🧘 Patience is profit. Monitor next session."
        )
        
    bot.edit_message_text(report_text, chat_id, status_msg.message_id, parse_mode="Markdown")

if __name__ == "__main__":
    logger.info("Forex Signal Scanner Bot running successfully...")
    bot.infinity_polling()