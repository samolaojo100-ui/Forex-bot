import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ─────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_IDS  = [c.strip() for c in os.getenv("CHAT_IDS", "").split(",") if c.strip()]

# ── Access control ───────────────────────────────────────────────────
OWNER_CHAT_ID     = os.getenv("OWNER_CHAT_ID", "").strip()
OWNER_USERNAME    = "SamOlaojo"
_extra_authorized = [c.strip() for c in os.getenv("AUTHORIZED_USERS", "").split(",") if c.strip()]
AUTHORIZED_USERS  = list({OWNER_CHAT_ID, *_extra_authorized}) if OWNER_CHAT_ID else _extra_authorized

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

# ── 7 Core Pairs ─────────────────────────────────────────────────────
FOREX_PAIRS = [
    "EUR/USD",   # Most liquid forex pair
    "GBP/USD",   # High volatility forex
    "USD/JPY",   # Safe haven forex
    "XAU/USD",   # Gold — 24/7
]

CRYPTO_PAIRS = [
    "BTC/USD",   # Bitcoin
    "ETH/USD",   # Ethereum
    "SOL/USD",   # Solana
]

ALL_PAIRS = FOREX_PAIRS + CRYPTO_PAIRS  # 7 total

# ── Timeframes ────────────────────────────────────────────────────────
TIMEFRAMES = ["15min", "1h", "4h", "1day"]

# ── Risk ─────────────────────────────────────────────────────────────
ACCOUNT_BALANCE  = float(os.getenv("ACCOUNT_BALANCE", "1000"))
RISK_PERCENT     = 1.0
DEFAULT_RR_RATIO = 2.0

# ── Scheduler ────────────────────────────────────────────────────────
AUTO_SIGNAL_INTERVAL = 30  # minutes