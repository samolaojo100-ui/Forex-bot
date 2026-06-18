import aiohttp
import asyncio
import logging
import pandas as pd
from config import TIMEFRAMES
import os

logger = logging.getLogger(__name__)
BASE_URL = "https://api.twelvedata.com"

def get_api_key():
    from config import TWELVEDATA_API_KEY
    return TWELVEDATA_API_KEY or os.getenv("TWELVEDATA_API_KEY", "")

async def fetch_ohlcv(session, symbol, interval, outputsize=100):
    api_key = get_api_key()
    symbol_fmt = symbol.replace("/", "")
    url = (
        f"{BASE_URL}/time_series"
        f"?symbol={symbol_fmt}&interval={interval}"
        f"&outputsize={outputsize}&apikey={api_key}&format=JSON"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
            if data.get("status") == "error" or "values" not in data:
                logger.warning(f"API error for {symbol} {interval}: {data.get('message','')}")
                return None
            df = pd.DataFrame(data["values"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])
            df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)
            df = df.sort_values("datetime").reset_index(drop=True)
            return df
    except Exception as e:
        logger.warning(f"Fetch error {symbol} {interval}: {e}")
        return None

async def fetch_all_timeframes(symbol, session):
    results = {}
    for i, tf in enumerate(TIMEFRAMES):
        if i > 0:
            await asyncio.sleep(10)
        df = await fetch_ohlcv(session, symbol, tf)
        if df is None or len(df) < 50:
            return None
        results[tf] = df
    return results

async def fetch_multiple_pairs(pairs):
    data_map = {}
    async with aiohttp.ClientSession() as session:
        for i, pair in enumerate(pairs):
            if i > 0:
                await asyncio.sleep(10)
            logger.info(f"Fetching {pair}...")
            tfs = await fetch_all_timeframes(pair, session)
            if tfs:
                data_map[pair] = tfs
    return data_map