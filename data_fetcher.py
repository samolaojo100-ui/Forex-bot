import aiohttp
import asyncio
import logging
import time
import pandas as pd
from config import TWELVEDATA_API_KEY, TIMEFRAMES

logger = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com"

# --- Global rate limiter ---------------------------------------------------
# TwelveData free tier allows ~8 requests/minute. This limiter is shared
# across ALL calls to fetch_ohlcv, no matter where they're triggered from
# (manual /signal, /check, or the auto-signaling background loop), so we
# never burst past the cap even if multiple pairs are processed close
# together in time.
MAX_REQUESTS_PER_MINUTE = 8
_request_times = []
_rate_lock = asyncio.Lock()


async def _throttle():
    """Block until it's safe to make another TwelveData request."""
    async with _rate_lock:
        now = time.monotonic()
        # Drop timestamps older than 60s
        while _request_times and now - _request_times[0] > 60:
            _request_times.pop(0)

        if len(_request_times) >= MAX_REQUESTS_PER_MINUTE:
            wait_time = 60 - (now - _request_times[0]) + 0.5
            logger.info(f"Rate limit guard: waiting {wait_time:.1f}s before next TwelveData call")
            await asyncio.sleep(max(wait_time, 0))
            now = time.monotonic()
            while _request_times and now - _request_times[0] > 60:
                _request_times.pop(0)

        _request_times.append(time.monotonic())
# -----------------------------------------------------------------------


async def fetch_ohlcv(session, symbol, interval, outputsize=100):
    symbol_fmt = symbol.replace("/", "")
    url = (
        f"{BASE_URL}/time_series"
        f"?symbol={symbol_fmt}&interval={interval}"
        f"&outputsize={outputsize}&apikey={TWELVEDATA_API_KEY}&format=JSON"
    )
    try:
        await _throttle()

        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()

            if data.get("status") == "error" or "values" not in data:
                logger.warning(f"{symbol} {interval}: API error - {data.get('message', data)}")
                return None

            df = pd.DataFrame(data["values"])

            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])

            # df.get("volume", 0) returns a plain int when the "volume"
            # column is missing, and int has no .fillna() method.
            # TwelveData often omits volume for forex pairs - check first.
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
    return data_map
