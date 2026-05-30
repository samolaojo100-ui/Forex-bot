import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_IDS  = os.getenv("CHAT_IDS", "").split(",")   # comma-separated chat IDs for auto-signals

# ── Data source (free) ────────────────────────────────────
# twelvedata.com — free tier: 800 req/day, 8 req/min
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "YOUR_TWELVEDATA_KEY_HERE")

# ── Trading sessions (UTC) ────────────────────────────────
SESSIONS = {
    "Tokyo":    {"start": 0,  "end": 9},   # 00:00 – 09:00 UTC
    "London":   {"start": 7,  "end": 16},  # 07:00 – 16:00 UTC
    "New York": {"start": 12, "end": 21},  # 12:00 – 21:00 UTC
}

# best overlaps → highest liquidity
SESSION_OVERLAPS = [
    {"name": "Tokyo/London Overlap",   "start": 7,  "end": 9},
    {"name": "London/New York Overlap","start": 12, "end": 16},
]

# ── Pairs to scan ─────────────────────────────────────────
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
    "USD/MXN","USD/ZAR","USD/SGD","USD/HKD",
    "USD/NOK","USD/SEK","USD/DKK","EUR/TRY",
    "USD/TRY","USD/PLN","USD/HUF","USD/CZK",
]

ALL_PAIRS = MAJOR_PAIRS + MINOR_PAIRS + EXOTIC_PAIRS

# ── Timeframes ────────────────────────────────────────────
TIMEFRAMES = ["15min", "1h", "4h"]        # all 3 must agree
SIGNAL_TF  = "1h"                         # used for SL/TP calculation

# ── Risk / lot size ───────────────────────────────────────
ACCOUNT_BALANCE      = float(os.getenv("ACCOUNT_BALANCE", "1000"))
RISK_PERCENT         = 1.0   # % of balance risked per trade
MIN_SL_PIPS          = 15    # minimum stop-loss distance (pips)
MAX_SL_PIPS          = 80    # maximum stop-loss distance
DEFAULT_RR_RATIO     = 2.0   # risk:reward

# ── Signal strength thresholds ────────────────────────────
MIN_SIGNAL_SCORE     = 6     # out of 10; signals below this are skipped
RSI_OVERSOLD         = 35
RSI_OVERBOUGHT       = 65
VOLUME_MULTIPLIER    = 1.2   # current volume must be > 1.2× average

# ── Auto-signal interval (minutes) ───────────────────────
AUTO_SIGNAL_INTERVAL = 30    # scan every 30 min during active sessions
