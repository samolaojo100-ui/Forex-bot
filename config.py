import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_IDS = os.getenv("CHAT_IDS", "").split(",")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

SESSIONS = {
    "Tokyo":    {"start": 0,  "end": 9},
    "London":   {"start": 7,  "end": 16},
    "New York": {"start": 12, "end": 21},
}

SESSION_OVERLAPS = [
    {"name": "Tokyo/London Overlap",     "start": 7,  "end": 9},
    {"name": "London/New York Overlap",  "start": 12, "end": 16},
]

MAJOR_PAIRS = ["EUR/USD","GBP/USD","USD/JPY","USD/CHF","AUD/USD","USD/CAD","NZD/USD"]
MINOR_PAIRS = [
    "EUR/GBP","EUR/JPY","GBP/JPY","EUR/AUD","GBP/AUD","AUD/JPY",
    "EUR/CAD","GBP/CAD","CAD/JPY","AUD/CAD","NZD/JPY","EUR/NZD",
    "GBP/NZD","AUD/NZD","CHF/JPY","EUR/CHF","GBP/CHF","AUD/CHF",
]
EXOTIC_PAIRS = ["USD/MXN","USD/ZAR","USD/SGD","USD/NOK","USD/SEK","USD/DKK","USD/PLN","USD/HUF"]
CRYPTO_PAIRS = [
    "BTC/USD","ETH/USD","BNB/USD","SOL/USD",
    "XRP/USD","ADA/USD","AVAX/USD","DOGE/USD",
    "MATIC/USD","DOT/USD","LTC/USD","LINK/USD",
]

FOREX_PAIRS = MAJOR_PAIRS + MINOR_PAIRS + EXOTIC_PAIRS
ALL_PAIRS = FOREX_PAIRS + CRYPTO_PAIRS

TIMEFRAMES = ["15min", "1h", "4h", "1day"]
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "1000"))
RISK_PERCENT = 1.0
DEFAULT_RR_RATIO = 1.5
AUTO_SIGNAL_INTERVAL = 30
