from datetime import datetime, timezone
from config import SESSIONS, SESSION_OVERLAPS, AUTO_SIGNAL_INTERVAL


def get_current_session() -> tuple:
    """Returns (session_name, is_active) based on current UTC hour."""
    hour = datetime.now(timezone.utc).hour

    # Check overlaps first
    for overlap in SESSION_OVERLAPS:
        if overlap["start"] <= hour < overlap["end"]:
            return overlap["name"], True

    # Check regular sessions
    for name, times in SESSIONS.items():
        if times["start"] <= hour < times["end"]:
            return name, True

    return "Off-Hours", False


def is_good_session() -> bool:
    """Returns True if currently in an active trading session."""
    _, active = get_current_session()
    return active


def is_weekend() -> bool:
    """Returns True if it's Saturday or Sunday UTC."""
    day = datetime.now(timezone.utc).weekday()
    return day >= 5  # 5=Saturday, 6=Sunday


def minutes_to_next_scan() -> int:
    """Returns minutes until next auto-scan (approximate)."""
    now     = datetime.now(timezone.utc)
    minutes = now.minute % AUTO_SIGNAL_INTERVAL
    return AUTO_SIGNAL_INTERVAL - minutes
