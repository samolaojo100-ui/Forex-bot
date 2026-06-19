import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ─────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_IDS  = [c.strip() for c in os.getenv("CHAT_IDS", "").split(",") if c.strip()]

# ── TwelveData ───────────────────────────────────────────────────────
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

# ── Trading sessions (UTC hours) ─────────────────────────────────────
SESSIONS = {
    "Tokyo":    {"start": 0,  "end": 9},
    "London":   {"start": 7,  "end": 16},
    "New York": {"start": 12, "end": 21},
}

SESSION_OVERLAPS = [
    {"name": "Tokyo/London Overlap",    "start": 7,  "end": 9},
    {"name": "London/New York Overlap", "start": 12, "end": 16},
]

# ── Pairs ─────────────────────────────────────────────────────────────
FOREX_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "USD/CAD", "XAU/USD",
]

CRYPTO_PAIRS = [
    "BTC/USD", "ETH/USD", "BNB/USD", "SOL/USD",
]

ALL_PAIRS = FOREX_PAIRS + CRYPTO_PAIRS

# ── Timeframes ────────────────────────────────────────────────────────
TIMEFRAMES = ["15min", "1h", "4h", "1day"]

# ── Risk ─────────────────────────────────────────────────────────────
ACCOUNT_BALANCE      = float(os.getenv("ACCOUNT_BALANCE", "1000"))
RISK_PERCENT         = 1.0
DEFAULT_RR_RATIO     = 2.0

# ── Scheduler ────────────────────────────────────────────────────────
AUTO_SIGNAL_INTERVAL = 30  # minutes
