from datetime import datetime, timezone
from config import SESSIONS, AUTO_SIGNAL_INTERVAL


def is_weekend() -> bool:
    now = datetime.now(timezone.utc)
    if now.weekday() == 5:                          # Saturday
        return True
    if now.weekday() == 6 and now.hour < 22:        # Sunday before 10 PM UTC
        return True
    return False


def get_current_session() -> tuple[str, bool]:
    if is_weekend():
        return "Weekend — Crypto Only 🟡", True

    hour = datetime.now(timezone.utc).hour

    # Overlaps (highest priority)
    if 7 <= hour < 9:
        return "Tokyo/London Overlap", True
    if 12 <= hour < 16:
        return "London/New York Overlap", True

    # Individual sessions
    for name, times in SESSIONS.items():
        if times["start"] <= hour < times["end"]:
            return name, True

    return "Off-hours", False


def is_good_session() -> bool:
    _, active = get_current_session()
    return active


def minutes_to_next_scan() -> int:
    return AUTO_SIGNAL_INTERVAL
