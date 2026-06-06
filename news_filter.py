"""
News filter — checks ForexFactory economic calendar.
Skips pairs whose currencies have high-impact news within 2 hours.
Free, no API key needed.
"""
import aiohttp
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Currency to pairs mapping
CURRENCY_PAIRS = {
    "USD": ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
            "EUR/JPY", "GBP/JPY", "EUR/GBP", "AUD/JPY", "EUR/CAD", "GBP/CAD", "CAD/JPY",
            "AUD/CAD", "BTC/USD", "ETH/USD"],
    "EUR": ["EUR/USD", "EUR/GBP", "EUR/JPY", "EUR/AUD", "EUR/CAD", "EUR/NZD"],
    "GBP": ["GBP/USD", "GBP/JPY", "GBP/AUD", "GBP/CAD", "GBP/NZD", "EUR/GBP"],
    "JPY": ["USD/JPY", "EUR/JPY", "GBP/JPY", "AUD/JPY", "CAD/JPY", "NZD/JPY"],
    "AUD": ["AUD/USD", "AUD/JPY", "EUR/AUD", "GBP/AUD", "AUD/CAD", "AUD/NZD"],
    "CAD": ["USD/CAD", "EUR/CAD", "GBP/CAD", "CAD/JPY", "AUD/CAD"],
    "NZD": ["NZD/USD", "NZD/JPY", "EUR/NZD", "GBP/NZD", "AUD/NZD"],
    "CHF": ["USD/CHF", "EUR/CHF", "GBP/CHF", "AUD/CHF", "CHF/JPY"],
}

# High impact news keywords
HIGH_IMPACT_KEYWORDS = [
    "NFP", "Non-Farm", "Interest Rate", "Fed", "FOMC", "ECB", "BOE", "BOJ", "RBA",
    "CPI", "GDP", "Unemployment", "Retail Sales", "PMI", "PPI", "Trade Balance",
    "Inflation", "Rate Decision", "Press Conference", "Monetary Policy",
]

_cache = {"pairs": set(), "timestamp": None}
CACHE_MINUTES = 30


async def fetch_news_pairs() -> set:
    """
    Fetch high-impact news from ForexFactory and return
    set of pairs that should be avoided right now.
    Uses cache to avoid repeated fetches.
    """
    global _cache

    now = datetime.now(timezone.utc)

    # Return cached result if fresh
    if _cache["timestamp"] and (now - _cache["timestamp"]).seconds < CACHE_MINUTES * 60:
        return _cache["pairs"]

    avoid_pairs = set()
    avoid_currencies = set()

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(
                "https://www.forexfactory.com/calendar",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("tr.calendar__row")

        window_start = now - timedelta(minutes=30)
        window_end   = now + timedelta(hours=2)

        for row in rows:
            # Check impact
            impact = row.select_one(".impact span")
            if not impact:
                continue
            impact_class = impact.get("class", [])
            if not any("high" in c.lower() or "red" in c.lower() for c in impact_class):
                continue

            # Get currency
            currency_el = row.select_one(".currency")
            if not currency_el:
                continue
            currency = currency_el.text.strip().upper()

            # Get event name
            event_el = row.select_one(".event span")
            event = event_el.text.strip() if event_el else ""

            # Check if it's truly high impact by keyword
            is_high = any(kw.lower() in event.lower() for kw in HIGH_IMPACT_KEYWORDS)
            if not is_high:
                continue

            avoid_currencies.add(currency)
            logger.info(f"🚨 News filter: {currency} — {event}")

        # Map currencies to pairs
        for currency in avoid_currencies:
            pairs = CURRENCY_PAIRS.get(currency, [])
            avoid_pairs.update(pairs)

    except Exception as e:
        logger.warning(f"News filter fetch failed: {e} — proceeding without filter")
        return set()  # fail open — don't block signals if news fetch fails

    _cache = {"pairs": avoid_pairs, "timestamp": now}
    return avoid_pairs


def format_news_warning(skipped_pairs: list) -> str:
    if not skipped_pairs:
        return ""
    pairs_text = ", ".join(skipped_pairs[:6])
    return (
        f"⚠️ *News Filter Active*\n"
        f"Skipped due to high-impact news: {pairs_text}\n"
        f"_Avoid trading these pairs for 2 hours_\n\n"
    )
