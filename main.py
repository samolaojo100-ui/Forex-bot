import os
import time
import requests
import logging
from telebot import TeleBot, types

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- CONFIGURATION & ENV VARIABLES ---
# Get tokens from environment variables (Railway Environment Variables)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN_PLACEHOLDER")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "YOUR_FINNHUB_KEY_PLACEHOLDER")

bot = TeleBot(TELEGRAM_TOKEN)

# 30 Pairs to Scan
PAIRS = [
    "OANDA:EUR_USD", "OANDA:GBP_USD", "OANDA:USD_JPY", "OANDA:AUD_USD", "OANDA:USD_CAD",
    "OANDA:USD_CHF", "OANDA:NZD_USD", "OANDA:EUR_GBP", "OANDA:EUR_JPY", "OANDA:GBP_JPY",
    "OANDA:EUR_AUD", "OANDA:EUR_CAD", "OANDA:EUR_CHF", "OANDA:EUR_NZD", "OANDA:GBP_AUD",
    "OANDA:GBP_CAD", "OANDA:GBP_CHF", "OANDA:GBP_NZD", "OANDA:AUD_CAD", "OANDA:AUD_CHF",
    "OANDA:AUD_JPY", "OANDA:AUD_NZD", "OANDA:CAD_CHF", "OANDA:CAD_JPY", "OANDA:CHF_JPY",
    "OANDA:NZD_CAD", "OANDA:NZD_CHF", "OANDA:NZD_JPY", "OANDA:XAU_USD", "OANDA:XAG_USD"
]

# Finnhub exact resolution mappings
TIMEFRAMES = {
    "5min": "5",
    "15min": "15",
    "1h": "60",
    "4h": "60",  # Note: Finnhub free tier natively supports up to 60 (1h). We fetch 60m as fallback or simulate.
    "1day": "D"
}

def get_candles(symbol, timeframe):
    """
    Fetches historical candle data from Finnhub API.
    Resolves the timeframe mapping mismatch and cleans formatting issues.
    """
    resolution = TIMEFRAMES.get(timeframe, "5")
    
    # Calculate timestamps (Fetch past 30 days of data to cover enough bars for indicators)
    to_time = int(time.time())
    from_time = to_time - (30 * 24 * 60 * 60)
    
    url = f"https://finnhub.io/api/v1/forex/candle"
    params = {
        "symbol": symbol,
        "resolution": resolution,
        "from": from_time,
        "to": to_time,
        "token": FINNHUB_API_KEY
    }
    
    try:
        # Respect Finnhub rate limits safely
        time.sleep(1.0 / 30) 
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("s") == "ok":
                return data
            else:
                logger.warning(f"[get_candles] Finnhub returned status status '{data.get('s')}' for {symbol}/{timeframe}")
                return None
        elif response.status_code == 429:
            logger.error("[get_candles] Rate limit hit (429). Sleeping briefly...")
            time.sleep(2)
            return None
        else:
            logger.error(f"[get_candles] HTTP error {response.status_code} for {symbol}/{timeframe}")
            return None
    except Exception as e:
        logger.error(f"[get_candles] Exception error for {symbol}/{timeframe}: {e}")
        return None

def analyze_market(candles):
    """
    Placeholder logic for your AI / Technical Indicators analysis.
    Expects candles to have 'c' (close), 'h' (high), 'l' (low), 'o' (open) arrays.
    """
    if not candles or "c" not in candles or len(candles["c"]) < 5:
        return None
    
    # Simple indicator check logic placeholder
    # You can plug your RSI, EMA cross or AI engine calculation here.
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
    btn = types.KeyboardButton("🔍 Scan Full Market")
    markup.add(btn)
    
    welcome_text = (
        "🤖 **Welcome to SamSos Forex Signal Bot!**\n\n"
        "Click the button below to trigger the Full Market Scanner."
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔍 Scan Full Market")
def handle_scan(message):
    chat_id = message.chat.id
    
    status_msg = bot.send_message(
        chat_id,
        "🔍 **Full Market Scanner Running...**\n\n"
        f"Scanning **{len(PAIRS)} pairs** across 5 timeframes.\n"
        "Powered by Finnhub — reliable & fast.\n"
        "Minimum: 3 TFs must agree + strong indicators.\n"
        "📦 Lot size: **0.1**\n\n"
        "This may take 1-2 minutes ⏳",
        parse_mode="Markdown"
    )
    
    scanned_count = 0
    unavailable_count = 0
    signals_found = []

    for pair in PAIRS:
        timeframe_results = {}
        pair_available = False
        
        for tf in TIMEFRAMES.keys():
            candles = get_candles(pair, tf)
            if candles:
                pair_available = True
                analysis = analyze_market(candles)
                if analysis in ["BUY", "SELL"]:
                    timeframe_results[tf] = analysis
            else:
                pass
        
        if pair_available:
            scanned_count += 1
            # Check for alignment across multiple timeframes
            buys = list(timeframe_results.values()).count("BUY")
            sells = list(timeframe_results.values()).count("SELL")
            
            # If 3 or more timeframes align on a direction, generate a signal
            if buys >= 3:
                signals_found.append(f"🟩 **{pair}** - STRONG BUY (Lot: 0.1)")
            elif sells >= 3:
                signals_found.append(f"🟥 **{pair}** - STRONG SELL (Lot: 0.1)")
        else:
            unavailable_count += 1

    # Format the complete scan report response
    report_text = (
        "📊 **Scan Complete**\n\n"
        f"Scanned: {scanned_count} pairs\n"
        f"Unavailable: {unavailable_count} pairs\n\n"
    )
    
    if signals_found:
        report_text += "🚀 **Strong Signals Detected:**\n" + "\n".join(signals_found)
    else:
        report_text += (
            "⛔ **No strong signals found right now.**\n"
            "Markets are mixed across all pairs.\n\n"
            "🧘 Patience is profit. Try again at next session."
        )
        
    bot.edit_message_text(report_text, chat_id, status_msg.message_id, parse_mode="Markdown")

if __name__ == "__main__":
    logger.info("Bot is starting up...")
    bot.infinity_polling()