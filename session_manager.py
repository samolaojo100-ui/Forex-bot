from datetime import datetime, timezone
from config import SESSIONS, SESSION_OVERLAPS, AUTO_SIGNAL_INTERVAL, CRYPTO_PAIRS


def is_weekend() -> bool:
    now = datetime.now(timezone.utc)
    if now.weekday() == 5:
        return True
    if now.weekday() == 6 and now.hour < 22:
        return True
    return False


def is_crypto(pair: str) -> bool:
    return pair in CRYPTO_PAIRS


def get_current_session() -> tuple[str, bool]:
    """Crypto is always active. Forex checks session hours."""
    if is_weekend():
        return "Weekend — Crypto Only 🟡", True   # still active for crypto
    hour = datetime.now(timezone.utc).hour
    for ov in SESSION_OVERLAPS:
        if ov["start"] <= hour < ov["end"]:
            return ov["name"], True
    for name, times in SESSIONS.items():
        if times["start"] <= hour < times["end"]:
            return name, True
    return "Off-hours", False


def is_good_session() -> bool:
    _, active = get_current_session()
    return active


def minutes_to_next_scan() -> int:
    return AUTO_SIGNAL_INTERVAL
