"""
stocks_engine.py — TrendGuard AI
Fetches real OHLCV data for US stocks from TwelveData.
Returns data in the same {pair: {tf: df}} structure as
data_fetcher.py so scan_pairs() works unchanged.
"""

import asyncio
import logging
import pandas as pd
import aiohttp

from config import TWELVEDATA_API_KEY

logger = logging.getLogger(__name__)

STOCK_PAIRS = [
    "AAPL", "TSLA", "NVDA", "AMZN", "MSFT",
    "META", "GOOGL", "AMD", "NFLX", "JPM",
]

# Timeframes to fetch — matches your forex bot exactly
TIMEFRAMES  = ["15min", "1h", "4h", "1day"]
OUTPUT_SIZE = 100
BASE_URL    = "https://api.twelvedata.com/time_series"


async def _fetch_one_tf(
    session: aiohttp.ClientSession,
    symbol: str,
    interval: str,
) -> tuple[str, str, pd.DataFrame | None]:
    """Fetch one timeframe for one stock symbol."""
    params = {
        "symbol":     symbol,
        "interval":   interval,
        "outputsize": OUTPUT_SIZE,
        "apikey":     TWELVEDATA_API_KEY,
        "format":     "JSON",
    }
    try:
        async with session.get(
            BASE_URL, params=params,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            data = await resp.json()

            if data.get("status") == "error":
                logger.warning(f"TwelveData error {symbol}/{interval}: {data.get('message')}")
                return symbol, interval, None

            values = data.get("values")
            if not values:
                return symbol, interval, None

            # Convert to DataFrame — same structure as data_fetcher.py
            df = pd.DataFrame(list(reversed(values)))
            df.rename(columns={
                "datetime": "time",
                "open":     "open",
                "high":     "high",
                "low":      "low",
                "close":    "close",
                "volume":   "volume",
            }, inplace=True)

            for col in ["open", "high", "low", "close", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            df.dropna(subset=["open", "high", "low", "close"], inplace=True)
            return symbol, interval, df

    except Exception as e:
        logger.error(f"Failed to fetch {symbol}/{interval}: {e}")
        return symbol, interval, None


async def fetch_stock_pairs(symbols: list[str]) -> dict:
    """
    Fetch all timeframes for all symbols concurrently.
    Returns {symbol: {"1h": df, "4h": df, "1day": df, "15min": df}}
    — identical structure to fetch_multiple_pairs() in data_fetcher.py.
    """
    results = {sym: {} for sym in symbols}

    async with aiohttp.ClientSession() as session:
        tasks = [
            _fetch_one_tf(session, sym, tf)
            for sym in symbols
            for tf in TIMEFRAMES
        ]
        responses = await asyncio.gather(*tasks)

    for symbol, interval, df in responses:
        if df is not None and len(df) >= 30:
            results[symbol][interval] = df

    # Only keep symbols that have at least 1h data
    final = {
        sym: tfs
        for sym, tfs in results.items()
        if "1h" in tfs
    }

    logger.info(f"Fetched {len(final)}/{len(symbols)} stocks with valid data")
    return final
