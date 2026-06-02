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
MIN_SIGNAL_SCORE    = 5.0   # out of 10  (lower = more signals)
AUTO_SIGNAL_INTERVAL = 120  # every 2 hours — fits within 800 req/day free tier

# ── Timeframes ─────────────────────────────────────────────────────────────────
TIMEFRAMES = ["1h", "4h"]   # 2 TFs — halves API usage vs 3 TFs

# ── Pairs — kept small to stay within 800 req/day free tier ───────────────────
# Budget: 800 req/day ÷ 12 auto-scans/day = 66 req/scan max
# 10 pairs × 2 TFs = 20 req/scan ✅ leaves room for manual scans too

MAJOR_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY",
    "AUD/USD", "USD/CAD",
]

MINOR_PAIRS = [
    "EUR/GBP", "EUR/JPY", "GBP/JPY",
]

EXOTIC_PAIRS = []   # disabled on free tier — re-enable on paid plan

CRYPTO_PAIRS = [
    "BTC/USD", "ETH/USD",
]

FOREX_PAIRS = MAJOR_PAIRS + MINOR_PAIRS + EXOTIC_PAIRS
ALL_PAIRS   = FOREX_PAIRS + CRYPTO_PAIRS

# Full pair lists — used when you upgrade to a paid TwelveData plan
MAJOR_PAIRS_FULL = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "NZD/USD",
]
MINOR_PAIRS_FULL = [
    "EUR/GBP", "EUR/JPY", "GBP/JPY", "EUR/AUD",
    "GBP/AUD", "AUD/JPY", "EUR/CAD", "GBP/CAD",
    "CAD/JPY", "AUD/CAD", "NZD/JPY", "EUR/NZD",
]
EXOTIC_PAIRS_FULL = [
    "USD/MXN", "USD/ZAR", "USD/SGD", "USD/NOK",
]
CRYPTO_PAIRS_FULL = [
    "BTC/USD", "ETH/USD", "BNB/USD", "SOL/USD",
    "XRP/USD", "ADA/USD", "DOGE/USD", "LTC/USD",
]

# ── Sessions ───────────────────────────────────────────────────────────────────
SESSIONS = {
    "Tokyo":    {"start": 0,  "end": 9},
    "London":   {"start": 7,  "end": 16},
    "New York": {"start": 12, "end": 21},
}
