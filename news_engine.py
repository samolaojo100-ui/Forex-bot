"""
news_engine.py
─────────────────────────────────────────────────────────────────────────
Standalone "news consciousness" module.

Fetches recent headlines from BBC + CNN business RSS feeds (no API key
needed), scans them for currency/economy-related keywords, and produces
a short "news context" summary for a given pair — e.g. warning if there's
a Fed decision, NFP report, war/conflict headline, etc. that could move
that pair.

This module is FULLY SELF-CONTAINED. It does not import from or modify
any other file in the project. To use it, just call:

    from news_engine import get_news_context
    context = get_news_context("EURUSD")
    if context:
        message += "\n\n" + context

Requires: feedparser, requests (both lightweight, add to requirements.txt
if not already present: `pip install feedparser`)
"""

import feedparser
import logging
import time

logger = logging.getLogger(__name__)

# ── RSS FEEDS (free, no API key) ────────────────────────────────────────
NEWS_FEEDS = {
    "BBC": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "CNN": "http://rss.cnn.com/rss/money_latest.rss",
}

# Cache so we don't hammer the feeds on every signal in a scan cycle
_cache = {"timestamp": 0, "headlines": []}
CACHE_TTL_SECONDS = 600  # refresh news every 10 minutes


# ── CURRENCY / EVENT KEYWORD MAP ────────────────────────────────────────
# Maps keywords found in headlines -> currencies they likely affect.
# Keep this list small and high-signal; too many keywords = too much noise.
CURRENCY_KEYWORDS = {
    "USD": ["federal reserve", "fed ", "fomc", "jerome powell", "nonfarm",
            "us inflation", "cpi", "us jobs", "treasury", "white house",
            "us economy", "dollar"],
    "EUR": ["european central bank", "ecb", "eurozone", "lagarde",
            "euro area", "european union economy"],
    "GBP": ["bank of england", "boe", "uk inflation", "uk economy",
            "pound sterling", "andrew bailey", "uk gdp"],
    "JPY": ["bank of japan", "boj", "yen", "japan economy", "ueda"],
    "AUD": ["reserve bank of australia", "rba", "australian dollar",
            "australia economy"],
    "CAD": ["bank of canada", "boc", "canadian dollar", "canada economy"],
    "CHF": ["swiss national bank", "snb", "swiss franc"],
    "XAU": ["gold price", "gold ", "safe haven"],
}

# High-impact event keywords (regardless of currency) — these usually
# cause volatility spikes across the board.
HIGH_IMPACT_KEYWORDS = [
    "interest rate", "rate decision", "rate hike", "rate cut",
    "inflation report", "jobs report", "recession", "war", "conflict",
    "ceasefire", "sanctions", "election result", "crisis", "default",
    "bank collapse", "emergency meeting",
]


def _fetch_headlines() -> list:
    """Fetch + cache headlines from all feeds. Returns list of (title, source)."""
    now = time.time()
    if now - _cache["timestamp"] < CACHE_TTL_SECONDS and _cache["headlines"]:
        return _cache["headlines"]

    headlines = []
    for source, url in NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:  # latest 15 per source
                title = entry.get("title", "")
                if title:
                    headlines.append((title, source))
        except Exception as e:
            logger.warning(f"News fetch failed for {source}: {e}")

    _cache["timestamp"] = now
    _cache["headlines"] = headlines
    return headlines


def _currency_from_pair(pair: str) -> set:
    """Extract the relevant currency codes from a pair like 'EURUSD' or 'XAUUSD'."""
    pair = pair.upper().replace("/", "")
    currencies = set()
    for code in CURRENCY_KEYWORDS.keys():
        if code in pair:
            currencies.add(code)
    # Always include USD as the universal counter-currency for forex pairs
    if "USD" in pair:
        currencies.add("USD")
    return currencies


def get_news_context(pair: str, max_items: int = 2) -> str:
    """
    Return a short formatted string of relevant/high-impact news for `pair`,
    or an empty string if nothing relevant is found (so it can be safely
    appended to a message without adding clutter on quiet days).
    """
    try:
        headlines = _fetch_headlines()
    except Exception as e:
        logger.warning(f"News engine error: {e}")
        return ""

    if not headlines:
        return ""

    relevant_currencies = _currency_from_pair(pair)
    matches = []  # (title, source, tag)

    for title, source in headlines:
        title_lower = title.lower()

        # Check high-impact keywords first
        is_high_impact = any(kw in title_lower for kw in HIGH_IMPACT_KEYWORDS)

        # Check currency-specific keywords
        matched_currency = None
        for code, keywords in CURRENCY_KEYWORDS.items():
            if code not in relevant_currencies:
                continue
            if any(kw in title_lower for kw in keywords):
                matched_currency = code
                break

        if matched_currency or is_high_impact:
            tag = matched_currency if matched_currency else "⚠️ HIGH IMPACT"
            matches.append((title, source, tag))

        if len(matches) >= max_items:
            break

    if not matches:
        return ""

    lines = ["📰 *News Watch:*"]
    for title, source, tag in matches:
        # Truncate long titles
        short_title = title if len(title) <= 90 else title[:87] + "..."
        lines.append(f"  • [{tag}] {short_title} ({source})")

    lines.append("  ⚠️ _Consider waiting for volatility to settle around major news._")
    return "\n".join(lines)


def get_general_market_news(max_items: int = 5) -> str:
    """
    Return a digest of the latest high-impact / currency-relevant headlines,
    regardless of pair. Useful for a standalone /news command.
    """
    try:
        headlines = _fetch_headlines()
    except Exception as e:
        logger.warning(f"News engine error: {e}")
        return "⚠️ Could not fetch news right now."

    if not headlines:
        return "⚠️ No news available right now."

    flagged = []
    for title, source in headlines:
        title_lower = title.lower()
        is_high_impact = any(kw in title_lower for kw in HIGH_IMPACT_KEYWORDS)
        matched_currency = None
        for code, keywords in CURRENCY_KEYWORDS.items():
            if any(kw in title_lower for kw in keywords):
                matched_currency = code
                break
        if is_high_impact or matched_currency:
            tag = matched_currency if matched_currency else "HIGH IMPACT"
            flagged.append((title, source, tag))
        if len(flagged) >= max_items:
            break

    if not flagged:
        return "📰 *Market News*\n\nNothing major flagged in the last scan — quiet news cycle."

    lines = ["📰 *Market News Digest*\n"]
    for title, source, tag in flagged:
        short_title = title if len(title) <= 90 else title[:87] + "..."
        lines.append(f"  • [{tag}] {short_title} ({source})")

    return "\n".join(lines)
