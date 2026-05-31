import aiohttp
import asyncio
import logging
import pandas as pd
from config import TWELVEDATA_API_KEY, TIMEFRAMES

logger   = logging.getLogger(__name__)
BASE_URL = "https://api.twelvedata.com"


async def fetch_ohlcv(session: aiohttp.ClientSession, symbol: str,
                      interval: str, outputsize: int = 100) -> pd.DataFrame | None:
    symbol_fmt = symbol.replace("/", "")
    url = (
        f"{BASE_URL}/time_series"
        f"?symbol={symbol_fmt}&interval={interval}"
        f"&outputsize={outputsize}&apikey={TWELVEDATA_API_KEY}&format=JSON"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
            if data.get("status") == "error" or "values" not in data:
                logger.debug(f"No data for {symbol} {interval}: {data.get('message','')}")
                return None
            df = pd.DataFrame(data["values"])
            df = df.rename(columns={"datetime": "time"})
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])
            df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)
            df = df.sort_values("time").reset_index(drop=True)
            return df
    except Exception as e:
        logger.warning(f"Fetch error {symbol} {interval}: {e}")
        return None


async def fetch_all_timeframes(symbol: str) -> dict | None:
    async with aiohttp.ClientSession() as session:
        results = {}
        for tf in TIMEFRAMES:
            df = await fetch_ohlcv(session, symbol, tf)
            if df is None or len(df) < 50:
                return None
            results[tf] = df
            await asyncio.sleep(0.3)
        return results


async def fetch_multiple_pairs(pairs: list) -> dict:
    data_map = {}
    for pair in pairs:
        logger.info(f"Fetching {pair}...")
        tfs = await fetch_all_timeframes(pair)
        if tfs:
            data_map[pair] = tfs
        await asyncio.sleep(0.8)
    return data_map
