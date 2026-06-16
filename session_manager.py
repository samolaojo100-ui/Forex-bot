from datetime import datetime, timezone
from config import SESSIONS, SESSION_OVERLAPS, AUTO_SIGNAL_INTERVAL, CRYPTO_PAIRS

# Best pairs to trade per session (high liquidity, tight spreads)
SESSION_PAIRS_MAP = {
    "Sydney": ["AUD/USD", "NZD/USD", "AUD/JPY", "NZD/JPY"],
    "Tokyo": ["USD/JPY", "EUR/JPY", "GBP/JPY", "AUD/JPY", "USD/CHF"],
    "London": ["EUR/USD", "GBP/USD", "EUR/GBP", "USD/CHF", "GBP/JPY"],
    "New York": ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CAD", "USD/CHF"],
    "London/New York Overlap": ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/GBP"],  # Best window
}

# Fallback if session name doesn't match
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
    """Return the best pairs to trade for the given session."""
    # Strip emoji or extra text if session name has it
    for key in SESSION_PAIRS_MAP:
        if key.lower() in session_name.lower():
            return SESSION_PAIRS_MAP[key]
    return DEFAULT_PAIRS


def is_good_session() -> bool:
    _, active = get_current_session()
    return active


def minutes_to_next_scan() -> int:
    return AUTO_SIGNAL_INTERVAL
