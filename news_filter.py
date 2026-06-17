# news_filter.py
# Fetches high-impact economic events and blocks signals around them.
# Uses ForexFactory calendar (free, no API key needed via scraping)
# Falls back gracefully if fetch fails — never crashes the bot.

import logging
import httpx
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Currencies that affect Forex pairs
WATCHED_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}

# Block signals this many minutes before AND after a high-impact event
BLOCK_BEFORE_MINUTES = 120   # 2 hours before
BLOCK_AFTER_MINUTES  = 60    # 1 hour after

# Cache so we don't fetch every single scan
_cache: dict = {"events": [], "fetched_at": None}
CACHE_TTL_MINUTES = 60


def _is_cache_valid() -> bool:
    if _cache["fetched_at"] is None:
        return False
    age = (datetime.now(timezone.utc) - _cache["fetched_at"]).total_seconds()
    return age < CACHE_TTL_MINUTES * 60


async def _fetch_events() -> list:
    """
    Fetch today's high-impact events from ForexFactory calendar JSON.
    Returns list of dicts: {currency, event, time (UTC datetime), impact}
    """
    if _is_cache_valid():
        return _cache["events"]

    events = []
    try:
        # ForexFactory provides a public JSON calendar endpoint
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

        now = datetime.now(timezone.utc)
        today = now.date()

        for item in data:
            impact = item.get("impact", "").upper()
            if impact != "HIGH":
                continue

            currency = item.get("country", "").upper()
            if currency not in WATCHED_CURRENCIES:
                continue

            # Parse event time — FF uses format "2026-06-17T14:30:00-04:00"
            raw_time = item.get("date", "")
            if not raw_time:
                continue

            try:
                event_time = datetime.fromisoformat(raw_time).astimezone(timezone.utc)
            except Exception:
                continue

            # Only keep today's and tomorrow's events
            if event_time.date() not in (today, today + timedelta(days=1)):
                continue

            events.append({
                "currency": currency,
                "event": item.get("title", "Unknown"),
                "time": event_time,
                "impact": impact,
            })

        _cache["events"] = events
        _cache["fetched_at"] = datetime.now(timezone.utc)
        logger.info(f"[NewsFilter] Fetched {len(events)} high-impact events")

    except Exception as e:
        logger.warning(f"[NewsFilter] Failed to fetch calendar: {e}")
        # Return stale cache rather than crashing
        return _cache.get("events", [])

    return events


def _pair_currencies(pair: str) -> set:
    """Extract the two currencies from a pair string e.g. EURUSD → {EUR, USD}"""
    pair = pair.upper().replace("/", "").replace("_", "")
    if len(pair) >= 6:
        return {pair[:3], pair[3:6]}
    return set()


async def check_news_block(pair: str) -> tuple[bool, str]:
    """
    Returns (blocked: bool, reason: str).
    blocked=True means DO NOT send signal for this pair right now.
    """
    events = await _fetch_events()
    now = datetime.now(timezone.utc)
    pair_currencies = _pair_currencies(pair)

    for ev in events:
        if ev["currency"] not in pair_currencies:
            continue

        event_time = ev["time"]
        diff_minutes = (event_time - now).total_seconds() / 60

        # Block window: BLOCK_BEFORE_MINUTES before to BLOCK_AFTER_MINUTES after
        if -BLOCK_AFTER_MINUTES <= diff_minutes <= BLOCK_BEFORE_MINUTES:
            if diff_minutes >= 0:
                reason = (
                    f"⚠️ HIGH IMPACT EVENT in {int(diff_minutes)}min\n"
                    f"📰 {ev['currency']}: {ev['event']}"
                )
            else:
                reason = (
                    f"⚠️ HIGH IMPACT EVENT ended {int(-diff_minutes)}min ago\n"
                    f"📰 {ev['currency']}: {ev['event']}"
                )
            return True, reason

    return False, ""


async def get_upcoming_events(hours: int = 24) -> list:
    """Return upcoming high-impact events within the next N hours. Used by /status."""
    events = await _fetch_events()
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours)
    return [
        e for e in events
        if now <= e["time"] <= cutoff
    ]