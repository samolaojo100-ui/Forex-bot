from datetime import datetime, timezone
from config import AUTO_SIGNAL_INTERVAL, CRYPTO_PAIRS

# Define sessions and overlaps directly here — no import from config needed
SESSIONS = {
    "Tokyo":    {"start": 0,  "end": 9},
    "London":   {"start": 7,  "end": 16},
    "New York": {"start": 12, "end": 21},
}

SESSION_OVERLAPS = [
    {"name": "Tokyo/London Overlap",      "start": 7,  "end": 9},
    {"name": "London/New York Overlap",   "start": 12, "end": 16},
]

# Best pairs to scan per session
SESSION_PAIRS_MAP = {
    "Tokyo":                    ["USD/JPY", "EUR/JPY", "GBP/JPY", "AUD/JPY", "CHF/JPY"],
    "Tokyo/London Overlap":     ["EUR/JPY", "GBP/JPY", "EUR/GBP", "USD/JPY"],
    "London":                   ["EUR/USD", "GBP/USD", "EUR/GBP", "USD/CHF", "GBP/JPY"],
    "London/New York Overlap":  ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/GBP"],
    "New York":                 ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CAD", "USD/CHF"],
}

DEFAULT_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY"]


def is_weekend() -> bool:
    now = datetime.now(timezone.utc)
    if now.weekday() == 5:
        return True
    if now.weekday() == 6 and now.hour < 22:
        return True
    return False


def is_crypto(pair: str) -> bool:
    return pair in CRYPTO_PAIRS


def get_current_session() -> tuple:
    if is_weekend():
        return "Weekend — Crypto Active 🟡", True

    hour = datetime.now(timezone.utc).hour

    for ov in SESSION_OVERLAPS:
        if ov["start"] <= hour < ov["end"]:
            return ov["name"], True

    for name, times in SESSIONS.items():
        if times["start"] <= hour < times["end"]:
            return name, True

    return "Off-hours", False


def get_session_pairs(session_name: str) -> list:
    return SESSION_PAIRS_MAP.get(session_name, DEFAULT_PAIRS)


def is_good_session() -> bool:
    _, active = get_current_session()
    return active


def minutes_to_next_scan() -> int:
    return AUTO_SIGNAL_INTERVAL
