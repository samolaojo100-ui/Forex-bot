import asyncio
import time

# Single shared lock used by /signal, /crypto, AND the background
# auto_scan scheduler job. Without this, a manual command and the
# 30-minute auto-scan (or two manual taps in a row) can fire TwelveData
# requests at the same time. Each individual loop paces itself under
# the per-minute rate limit on its own, but two loops running at once
# doubles the effective request rate and blows through the limit even
# though daily credits are nowhere close to exhausted.
_scan_lock = asyncio.Lock()
_last_scan_label = None
_last_scan_started_at = None


def is_scan_running() -> bool:
    return _scan_lock.locked()


def scan_status_text() -> str:
    if not is_scan_running() or _last_scan_started_at is None:
        return ""
    elapsed = int(time.monotonic() - _last_scan_started_at)
    return f"A scan ({_last_scan_label}) is already running, started {elapsed}s ago."


class ScanGuard:
    """Async context manager: acquires the shared scan lock, or raises
    RuntimeError immediately (non-blocking) if a scan is already running.
    Usage:
        async with ScanGuard("crypto"):
            ... do the fetch ...
    """

    def __init__(self, label: str):
        self.label = label

    async def __aenter__(self):
        global _last_scan_label, _last_scan_started_at
        if _scan_lock.locked():
            raise RuntimeError(scan_status_text())
        await _scan_lock.acquire()
        _last_scan_label = self.label
        _last_scan_started_at = time.monotonic()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        global _last_scan_started_at
        _last_scan_started_at = None
        _scan_lock.release()
        return False
