import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_IDS = os.getenv("CHAT_IDS", "").split(",")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

SESSIONS = {
    "Tokyo": {"start": 0, "end": 9},
    "London": {"start": 7, "end": 16},
    "New York": {"start": 12, "end": 21},
}

SESSION_OVERLAPS = [
    {"name": "Tokyo/London Overlap", "start": 7, "end": 9},
    {"name": "London/New York Overlap", "start": 12, "end": 16},
]

# 10 major forex pairs — the 7 true majors + the 3 most liquid crosses
MAJOR_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD",
    "USD/CAD", "NZD/USD", "EUR/JPY", "GBP/JPY", "EUR/GBP",
]

# Gold — add "XAG/USD" here too later if you ever want silver as well
METAL_PAIRS = ["XAU/USD"]

# 5 major US stocks
STOCK_PAIRS = ["AAPL", "MSFT", "TSLA", "NVDA", "AMZN"]

# 5 major crypto pairs
CRYPTO_PAIRS = ["BTC/USD", "ETH/USD", "BNB/USD", "SOL/USD", "XRP/USD"]

FOREX_PAIRS = MAJOR_PAIRS + METAL_PAIRS + STOCK_PAIRS
ALL_PAIRS = FOREX_PAIRS + CRYPTO_PAIRS

# 5 timeframes
TIMEFRAMES = ["5min", "15min", "1h", "4h", "1day"]

ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", "1000"))
RISK_PERCENT = 1.0
DEFAULT_RR_RATIO = 1.5
AUTO_SIGNAL_INTERVAL = 30
