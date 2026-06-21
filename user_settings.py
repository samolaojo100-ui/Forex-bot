import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ─────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_IDS  = [c.strip() for c in os.getenv("CHAT_IDS", "").split(",") if c.strip()]

# ── Access control ───────────────────────────────────────────────────
# Only chat IDs in this list can use bot commands. Stored as an env var
# so new approvals (via /approve) can be added without a redeploy.
# Set OWNER_CHAT_ID to your own Telegram chat ID — you're always authorized.
OWNER_CHAT_ID      = os.getenv("OWNER_CHAT_ID", "").strip()
OWNER_USERNAME      = "SamOlaojo"  # shown to unauthorized users
_extra_authorized   = [c.strip() for c in os.getenv("AUTHORIZED_USERS", "").split(",") if c.strip()]
AUTHORIZED_USERS    = list({OWNER_CHAT_ID, *_extra_authorized}) if OWNER_CHAT_ID else _extra_authorized

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
    # Added: more majors + liquid crosses
    "NZD/USD", "EUR/GBP", "GBP/JPY", "EUR/JPY",
]

CRYPTO_PAIRS = [
    "BTC/USD", "ETH/USD", "BNB/USD", "SOL/USD",
    # Added: high-volume additional crypto
    "XRP/USD", "ADA/USD", "DOGE/USD",
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
