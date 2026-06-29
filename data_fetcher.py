import aiohttp
import asyncio
import logging
import time
import pandas as pd
from config import TWELVEDATA_API_KEY, TIMEFRAMES

logger = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com"

# Basic 8 plan = 8 requests/minute
# We fetch in controlled batches to respect this limit
MAX_PER_MINUTE = 8
_request_times = []
_rate_lock     = asyncio.Lock()


async def _throttle():
    async with _rate_lock:
        now = time.monotonic()
        while _request_times and now - _request_times[0] > 60:
            _request_times.pop(0)
        if len(_request_times) >= MAX_PER_MINUTE:
            wait = 60 - (now - _request_times[0]) + 0.3
            logger.info(f"Rate limit: waiting {wait:.1f}s")
            await asyncio.sleep(max(wait, 0))
            now = time.monotonic()
            while _request_times and now - _request_times[0] > 60:
                _request_times.pop(0)
        _request_times.append(time.monotonic())


async def _fetch_one(session: aiohttp.ClientSession, symbol: str, interval: str) -> tuple:
    """Fetch one symbol/interval combo. Returns (symbol, interval, df or None)."""
    params = {
        "symbol":     symbol,
        "interval":   interval,
        "outputsize": 100,
        "apikey":     TWELVEDATA_API_KEY,
        "format":     "JSON",
    }
    try:
        await _throttle()
        async with session.get(
            f"{BASE_URL}/time_series",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()

            if data.get("status") == "error" or "values" not in data:
                logger.warning(f"{symbol} {interval}: {data.get('message', 'no values')}")
                return symbol, interval, None

            df = pd.DataFrame(data["values"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])
            if "volume" in df.columns:
                df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
            else:
                df["volume"] = 0
            df = df.sort_values("datetime").reset_index(drop=True)
            return symbol, interval, df

    except Exception as e:
        logger.warning(f"Fetch error {symbol} {interval}: {e}")
        return symbol, interval, None


async def fetch_multiple_pairs(pairs: list) -> dict:
    """
    Fetch all pairs and timeframes in parallel batches.
    Returns {pair: {tf: df}} — only pairs with complete data included.
    Much faster than sequential fetching.
    """
    # Build all tasks
    tasks = [
        (pair, tf)
        for pair in pairs
        for tf in TIMEFRAMES
    ]

    results = {pair: {} for pair in pairs}

    # Process in batches of MAX_PER_MINUTE to respect rate limit
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(tasks), MAX_PER_MINUTE):
            batch = tasks[i:i + MAX_PER_MINUTE]
            coros = [_fetch_one(session, pair, tf) for pair, tf in batch]
            responses = await asyncio.gather(*coros)

            for symbol, interval, df in responses:
                if df is not None and len(df) >= 50:
                    results[symbol][interval] = df

            # Small pause between batches to stay within rate limit
            if i + MAX_PER_MINUTE < len(tasks):
                await asyncio.sleep(61)

    # Only return pairs that have ALL timeframes
    final = {
        pair: tfs
        for pair, tfs in results.items()
        if all(tf in tfs for tf in TIMEFRAMES)
    }

    logger.info(f"✅ Fetched {len(final)}/{len(pairs)} pairs successfully")
    return final
