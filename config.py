import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN          = os.getenv("BOT_TOKEN", "")
CHAT_IDS           = [c.strip() for c in os.getenv("CHAT_IDS", "").split(",") if c.strip()]
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
ACCOUNT_BALANCE    = float(os.getenv("ACCOUNT_BALANCE", "1000"))

# ── Trading params ─────────────────────────────────────────────────────────────
RISK_PERCENT        = 1.0   # % of balance risked per trade
DEFAULT_RR_RATIO    = 1.5   # risk : reward ratio
MIN_SIGNAL_SCORE    = 5.0   # out of 10
AUTO_SIGNAL_INTERVAL = 30   # every 30 minutes — unlimited on paid plan ✅

# ── Timeframes ─────────────────────────────────────────────────────────────────
TIMEFRAMES = ["15min", "1h", "4h"]   # 3 TFs — full analysis ✅

# ── Pairs — FULL lists, no restrictions on paid plan ──────────────────────────
MAJOR_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "NZD/USD",
]

MINOR_PAIRS = [
    "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/AUD",
    "GBP/AUD", "AUD/JPY", "EUR/CAD", "GBP/CAD",
    "CAD/JPY", "AUD/CAD", "NZD/JPY", "EUR/NZD",
    "GBP/NZD", "AUD/NZD", "CHF/JPY", "EUR/CHF",
    "GBP/CHF", "AUD/CHF",
]

EXOTIC_PAIRS = [
    "USD/MXN", "USD/ZAR", "USD/SGD", "USD/NOK",
    "USD/SEK", "USD/DKK", "USD/PLN", "USD/HUF",
]

CRYPTO_PAIRS = [
    "BTC/USD", "ETH/USD", "BNB/USD", "SOL/USD",
    "XRP/USD", "ADA/USD", "DOGE/USD", "LTC/USD",
    "AVAX/USD", "DOT/USD", "MATIC/USD", "LINK/USD",
]

FOREX_PAIRS = MAJOR_PAIRS + MINOR_PAIRS + EXOTIC_PAIRS
ALL_PAIRS   = FOREX_PAIRS + CRYPTO_PAIRS

# ── Sessions ───────────────────────────────────────────────────────────────────
SESSIONS = {
    "Tokyo":    {"start": 0,  "end": 9},
    "London":   {"start": 7,  "end": 16},
    "New York": {"start": 12, "end": 21},
}
