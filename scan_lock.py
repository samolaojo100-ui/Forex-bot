"""
scan_lock.py — Global scan lock with hard auto-expiry.

Prevents two scans (manual + auto, or two manual commands) from running
at the same time and stepping on each other / hitting rate limits twice.

CRITICAL DIFFERENCE vs a naive lock: this one can NEVER get stuck forever.
Even if a scan crashes without releasing the lock, the lock auto-expires
after LOCK_TIMEOUT_SECONDS and the next command will simply take over.
"""

import time
import threading

LOCK_TIMEOUT_SECONDS = 90  # hard ceiling — no scan should ever take longer than this

_lock = threading.Lock()
_scan_started_at: float | None = None
_scan_label: str = ""


def try_acquire(label: str = "scan") -> tuple[bool, int]:
    """
    Try to start a scan.

    Returns (acquired, seconds_remaining_on_existing_lock).
    - If acquired is True, you now hold the lock — call release() when done,
      ideally in a try/finally.
    - If acquired is False, someone else is scanning; seconds_remaining
      tells you roughly how much longer until it auto-expires.
    """
    global _scan_started_at, _scan_label

    with _lock:
        now = time.time()

        if _scan_started_at is None:
            _scan_started_at = now
            _scan_label = label
            return True, 0

        elapsed = now - _scan_started_at

        if elapsed >= LOCK_TIMEOUT_SECONDS:
            # Previous scan never released — treat it as dead and take over.
            _scan_started_at = now
            _scan_label = label
            return True, 0

        return False, int(LOCK_TIMEOUT_SECONDS - elapsed)


def release() -> None:
    """Release the lock. Safe to call even if you don't hold it."""
    global _scan_started_at, _scan_label
    with _lock:
        _scan_started_at = None
        _scan_label = ""


def status() -> tuple[bool, int, str]:
    """Returns (is_running, seconds_elapsed, label) without acquiring."""
    with _lock:
        if _scan_started_at is None:
            return False, 0, ""
        elapsed = int(time.time() - _scan_started_at)
        return True, elapsed, _scan_label
