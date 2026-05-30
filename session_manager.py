from datetime import datetime, timezone
from config import SESSIONS, SESSION_OVERLAPS, AUTO_SIGNAL_INTERVAL


def get_current_session() -> tuple[str, bool]:
    """Return (session_name, is_active)."""
    now_utc = datetime.now(timezone.utc)
    hour    = now_utc.hour

    # Check overlaps first (highest priority)
    for ov in SESSION_OVERLAPS:
        if ov["start"] <= hour < ov["end"]:
            return ov["name"], True

    # Check regular sessions
    for name, times in SESSIONS.items():
        if times["start"] <= hour < times["end"]:
            return name, True

    return "Off-hours", False


def is_good_session() -> bool:
    """Returns True if we're in a high-liquidity session."""
    _, active = get_current_session()
    return active


def minutes_to_next_scan() -> int:
    """Approximate minutes until the next auto-scan fires."""
    return AUTO_SIGNAL_INTERVAL
