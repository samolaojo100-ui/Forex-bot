import aiohttp
import asyncio
import logging
import time
import pandas as pd
from config import TWELVEDATA_API_KEY, TIMEFRAMES

logger = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com"

# Basic 8 plan = 8 requests/minute max
MAX_REQUESTS_PER_MINUTE = 8
_request_times = []
_rate_lock = asyncio.Lock()


async def _throttle():
    async with _rate_lock:
        now = time.monotonic()
        while _request_times and now - _request_times[0] > 60:
            _request_times.pop(0)
        if len(_request_times) >= MAX_REQUESTS_PER_MINUTE:
            wait_time = 60 - (now - _request_times[0]) + 0.5
            logger.info(f"Rate limit: waiting {wait_time:.1f}s")
            await asyncio.sleep(max(wait_time, 0))
            now = time.monotonic()
            while _request_times and now - _request_times[0] > 60:
                _request_times.pop(0)
        _request_times.append(time.monotonic())


async def fetch_ohlcv(session, symbol, interval, outputsize=100):
    params = {
        "symbol":     symbol,
        "interval":   interval,
        "outputsize": outputsize,
        "apikey":     TWELVEDATA_API_KEY,
        "format":     "JSON",
    }
    url = f"{BASE_URL}/time_series"
    try:
        await _throttle()
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
            if data.get("status") == "error" or "values" not in data:
                logger.warning(f"{symbol} {interval}: {data.get('message', data)}")
                return None
            df = pd.DataFrame(data["values"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])
            if "volume" in df.columns:
                df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
            else:
                df["volume"] = 0
            df = df.sort_values("datetime").reset_index(drop=True)
            return df
    except Exception as e:
        logger.warning(f"Fetch error {symbol} {interval}: {e}")
        return None


async def fetch_all_timeframes(symbol):
    async with aiohttp.ClientSession() as session:
        results = {}
        for tf in TIMEFRAMES:
            df = await fetch_ohlcv(session, symbol, tf)
            if df is None or len(df) < 50:
                logger.warning(f"{symbol} {tf}: insufficient data")
                return None
            results[tf] = df
        return results


async def fetch_multiple_pairs(pairs):
    data_map = {}
    for pair in pairs:
        logger.info(f"Fetching {pair}...")
        tfs = await fetch_all_timeframes(pair)
        if tfs:
            data_map[pair] = tfs
        else:
            logger.warning(f"{pair}: skipped")
    return data_map
