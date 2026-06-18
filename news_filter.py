import logging
import asyncio
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Cache events to avoid fetching every scan
_cache: dict = {"events": [], "fetched_at": None}
CACHE_TTL = 3600  # 1 hour

WATCHED_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "XAU"}
BLOCK_BEFORE = 90   # minutes before event
BLOCK_AFTER  = 60   # minutes after event


def _cache_valid() -> bool:
    if not _cache["fetched_at"]:
        return False
    return (datetime.now(timezone.utc) - _cache["fetched_at"]).total_seconds() < CACHE_TTL


async def _fetch_events() -> list:
    if _cache_valid():
        return _cache["events"]

    events = []
    try:
        import aiohttp
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)

        now   = datetime.now(timezone.utc)
        today = now.date()

        for item in data:
            if item.get("impact", "").upper() != "HIGH":
                continue
            currency = item.get("country", "").upper()
            if currency not in WATCHED_CURRENCIES:
                continue
            raw = item.get("date", "")
            if not raw:
                continue
            try:
                event_time = datetime.fromisoformat(raw).astimezone(timezone.utc)
            except Exception:
                continue
            if event_time.date() not in (today, today + timedelta(days=1)):
                continue
            events.append({
                "currency": currency,
                "event":    item.get("title", "Unknown"),
                "time":     event_time,
            })

        _cache["events"]     = events
        _cache["fetched_at"] = datetime.now(timezone.utc)
        logger.info(f"[News] Fetched {len(events)} HIGH impact events")

    except Exception as e:
        logger.warning(f"[News] Could not fetch calendar: {e}")
        return _cache.get("events", [])

    return events


def _pair_currencies(pair: str) -> set:
    p = pair.upper().replace("/", "").replace("_", "")
    if p == "XAUUSD":
        return {"XAU", "USD"}
    if len(p) >= 6:
        return {p[:3], p[3:6]}
    return set()


async def check_news_block(pair: str) -> tuple:
    """Returns (blocked, reason_str). blocked=True means skip signal."""
    try:
        events = await _fetch_events()
    except Exception:
        return False, ""

    now      = datetime.now(timezone.utc)
    currencies = _pair_currencies(pair)

    for ev in events:
        if ev["currency"] not in currencies:
            continue
        diff = (ev["time"] - now).total_seconds() / 60
        if -BLOCK_AFTER <= diff <= BLOCK_BEFORE:
            if diff >= 0:
                reason = f"⚠️ HIGH IMPACT in {int(diff)}min: {ev['currency']} — {ev['event']}"
            else:
                reason = f"⚠️ HIGH IMPACT {int(-diff)}min ago: {ev['currency']} — {ev['event']}"
            return True, reason

    return False, ""


async def get_upcoming_events(hours: int = 24) -> list:
    try:
        events = await _fetch_events()
    except Exception:
        return []
    now    = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours)
    return [e for e in events if now <= e["time"] <= cutoff]
