import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN          = os.getenv("BOT_TOKEN", "")
CHAT_IDS           = [c.strip() for c in os.getenv("CHAT_IDS", "").split(",") if c.strip()]
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
ACCOUNT_BALANCE    = float(os.getenv("ACCOUNT_BALANCE", "1000"))

# ── Trading params ─────────────────────────────────────────────────────────────
RISK_PERCENT        = 1.0
DEFAULT_RR_RATIO    = 1.5
MIN_SIGNAL_SCORE    = 5.0
AUTO_SIGNAL_INTERVAL = 120  # every 2 hours

# ── Timeframes ─────────────────────────────────────────────────────────────────
TIMEFRAMES = ["1h", "4h"]   # 2 TFs only

# ── Pairs ──────────────────────────────────────────────────────────────────────
MAJOR_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY",
    "AUD/USD", "USD/CAD",
]

MINOR_PAIRS = [
    "EUR/GBP", "EUR/JPY", "GBP/JPY",
]

EXOTIC_PAIRS = []

CRYPTO_PAIRS = [
    "BTC/USD", "ETH/USD",
]

FOREX_PAIRS = MAJOR_PAIRS + MINOR_PAIRS + EXOTIC_PAIRS
ALL_PAIRS   = FOREX_PAIRS + CRYPTO_PAIRS

# ── Sessions ───────────────────────────────────────────────────────────────────
SESSIONS = {
    "Tokyo":    {"start": 0,  "end": 9},
    "London":   {"start": 7,  "end": 16},
    "New York": {"start": 12, "end": 21},
}