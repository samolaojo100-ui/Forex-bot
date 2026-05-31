import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_IDS  = os.getenv("CHAT_IDS", "").split(",")

# ── Data source ───────────────────────────────────────────
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "YOUR_TWELVEDATA_KEY_HERE")

# ── Trading sessions (UTC) ────────────────────────────────
SESSIONS = {
    "Tokyo":    {"start": 0,  "end": 9},
    "London":   {"start": 7,  "end": 16},
    "New York": {"start": 12, "end": 21},
}
SESSION_OVERLAPS = [
    {"name": "Tokyo/London Overlap",    "start": 7,  "end": 9},
    {"name": "London/New York Overlap", "start": 12, "end": 16},
]

# ── Forex Pairs ───────────────────────────────────────────
MAJOR_PAIRS = [
    "EUR/USD","GBP/USD","USD/JPY","USD/CHF",
    "AUD/USD","USD/CAD","NZD/USD",
]
MINOR_PAIRS = [
    "EUR/GBP","EUR/JPY","GBP/JPY","EUR/AUD",
    "GBP/AUD","AUD/JPY","EUR/CAD","GBP/CAD",
    "CAD/JPY","AUD/CAD","NZD/JPY","EUR/NZD",
    "GBP/NZD","AUD/NZD","CHF/JPY","EUR/CHF",
    "GBP/CHF","AUD/CHF",
]
EXOTIC_PAIRS = [
    "USD/MXN","USD/ZAR","USD/SGD","USD/NOK",
    "USD/SEK","USD/DKK","USD/PLN","USD/HUF",
]

# ── Crypto Pairs (24/7) ───────────────────────────────────
CRYPTO_PAIRS = [
    "BTC/USD","ETH/USD","BNB/USD","SOL/USD",
    "XRP/USD","ADA/USD","AVAX/USD","DOGE/USD",
    "MATIC/USD","DOT/USD","LTC/USD","LINK/USD",
]

FOREX_PAIRS = MAJOR_PAIRS + MINOR_PAIRS + EXOTIC_PAIRS
ALL_PAIRS   = FOREX_PAIRS + CRYPTO_PAIRS

# ── Timeframes ────────────────────────────────────────────
TIMEFRAMES = ["15min", "1h", "4h"]
SIGNAL_TF  = "1h"

# ── Risk settings ─────────────────────────────────────────
ACCOUNT_BALANCE      = float(os.getenv("ACCOUNT_BALANCE", "1000"))
RISK_PERCENT         = 1.0
MIN_SL_PIPS          = 15
MAX_SL_PIPS          = 80
DEFAULT_RR_RATIO     = 2.0

# ── Signal thresholds ─────────────────────────────────────
MIN_SIGNAL_SCORE     = 6
RSI_OVERSOLD         = 35
RSI_OVERBOUGHT       = 65
VOLUME_MULTIPLIER    = 1.2

# ── Scheduler ─────────────────────────────────────────────
AUTO_SIGNAL_INTERVAL = 30
