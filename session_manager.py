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
    """
    Returns True if the Forex market is currently closed for the weekend.

    Forex doesn't close at calendar midnight Saturday — it closes Friday
    evening (~21:00 UTC, when the NY session ends) and reopens Sunday
    evening (~21:00 UTC, when Sydney/Asia opens). A pure
    `weekday() >= 5` check misses the Friday-evening and Sunday-evening
    closed windows, which is what let Forex signals fire after Friday
    close and before Sunday open.
    """
    now = datetime.now(timezone.utc)
    day = now.weekday()  # 0=Monday ... 5=Saturday, 6=Sunday
    hour = now.hour

    FRIDAY_CLOSE_HOUR = 21   # Forex closes ~21:00 UTC Friday
    SUNDAY_OPEN_HOUR  = 21   # Forex reopens ~21:00 UTC Sunday

    if day == 4 and hour >= FRIDAY_CLOSE_HOUR:   # Friday after close
        return True
    if day == 5:                                  # all of Saturday
        return True
    if day == 6 and hour < SUNDAY_OPEN_HOUR:      # Sunday before reopen
        return True

    return False


def minutes_to_next_scan() -> int:
    """Returns minutes until next auto-scan (approximate)."""
    now     = datetime.now(timezone.utc)
    minutes = now.minute % AUTO_SIGNAL_INTERVAL
    return AUTO_SIGNAL_INTERVAL - minutes
