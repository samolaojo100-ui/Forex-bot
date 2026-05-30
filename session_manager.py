from datetime import datetime, timezone
from config import SESSIONS, SESSION_OVERLAPS, AUTO_SIGNAL_INTERVAL


def is_weekend() -> bool:
    """Forex market is closed Saturday and most of Sunday."""
    now = datetime.now(timezone.utc)
    # weekday(): 5=Saturday, 6=Sunday
    # Market reopens Sunday 22:00 UTC
    if now.weekday() == 5:
        return True
    if now.weekday() == 6 and now.hour < 22:
        return True
    return False


def get_current_session() -> tuple[str, bool]:
    if is_weekend():
        return "Weekend (Market Closed)", False

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