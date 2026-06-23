"""
stocks_engine.py — TrendGuard AI
Fetches real OHLCV data for US stocks from TwelveData.
Uses the same fetch pattern as data_fetcher.py so the
signal_engine works on stocks with zero changes.
"""

import asyncio
import logging
import aiohttp

from config import TWELVEDATA_API_KEY  # same key your forex bot uses

logger = logging.getLogger(__name__)

# ── Stock symbols to scan (TwelveData format) ───────────────
STOCK_PAIRS = [
    "AAPL",   # Apple
    "TSLA",   # Tesla
    "NVDA",   # NVIDIA
    "AMZN",   # Amazon
    "MSFT",   # Microsoft
    "META",   # Meta
    "GOOGL",  # Alphabet
    "AMD",    # AMD
    "NFLX",   # Netflix
    "JPM",    # JPMorgan
]

TIMEFRAME   = "1h"      # same as your forex signals
OUTPUT_SIZE = 100       # enough candles for all 8 indicators
BASE_URL    = "https://api.twelvedata.com/time_series"


async def _fetch_one_stock(session: aiohttp.ClientSession, symbol: str) -> tuple[str, list | None]:
    """Fetch OHLCV candles for a single stock symbol."""
    params = {
        "symbol":      symbol,
        "interval":    TIMEFRAME,
        "outputsize":  OUTPUT_SIZE,
        "apikey":      TWELVEDATA_API_KEY,
        "format":      "JSON",
    }
    try:
        async with session.get(BASE_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()

            if data.get("status") == "error":
                logger.warning(f"TwelveData error for {symbol}: {data.get('message')}")
                return symbol, None

            values = data.get("values")
            if not values:
                logger.warning(f"No values returned for stock {symbol}")
                return symbol, None

            # Reverse so oldest candle is first (same as data_fetcher.py)
            return symbol, list(reversed(values))

    except Exception as e:
        logger.error(f"Failed to fetch stock {symbol}: {e}")
        return symbol, None


async def fetch_stock_pairs(symbols: list[str]) -> dict:
    """
    Fetch all stock symbols concurrently.
    Returns a dict {symbol: [candles]} — same structure as fetch_multiple_pairs()
    so scan_pairs() works unchanged.
    """
    results = {}

    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_one_stock(session, sym) for sym in symbols]
        responses = await asyncio.gather(*tasks)

    for symbol, candles in responses:
        if candles:
            results[symbol] = candles
        else:
            logger.warning(f"Skipping {symbol} — no data")

    logger.info(f"Fetched {len(results)}/{len(symbols)} stocks successfully")
    return results
