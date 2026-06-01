import aiohttp
import asyncio
import logging
import pandas as pd
from config import TWELVEDATA_API_KEY, TIMEFRAMES

logger = logging.getLogger(__name__)
BASE_URL = "https://api.twelvedata.com"


async def fetch_ohlcv(session: aiohttp.ClientSession, symbol: str, interval: str, outputsize: int = 100):
    """
    Fetch OHLCV data for one symbol + interval from TwelveData.
    Symbol format: "EUR/USD" (slash is fine — TwelveData accepts it).
    """
    url = (
        f"{BASE_URL}/time_series"
        f"?symbol={symbol}&interval={interval}"
        f"&outputsize={outputsize}&apikey={TWELVEDATA_API_KEY}&format=JSON"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            data = await resp.json(content_type=None)

        if data.get("status") == "error" or "values" not in data:
            logger.warning(f"API error {symbol} {interval}: {data.get('message', 'no values')}")
            return None

        df = pd.DataFrame(data["values"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        # volume is absent on TwelveData free plan for crypto — default to 0
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
        else:
            df["volume"] = 0.0
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.sort_values("datetime").reset_index(drop=True)

        if len(df) < 50:
            logger.warning(f"{symbol} {interval}: only {len(df)} rows — skipping")
            return None

        return df

    except asyncio.TimeoutError:
        logger.warning(f"Timeout: {symbol} {interval}")
        return None
    except Exception as e:
        logger.warning(f"Fetch error {symbol} {interval}: {e}")
        return None


async def fetch_all_timeframes(symbol: str) -> dict | None:
    """
    Fetch all configured timeframes for one symbol.
    Returns {tf: df} or None if any timeframe fails.
    FIX: was sleeping 8 s between each TF (= 40 s/pair). Now 1 s.
    """
    async with aiohttp.ClientSession() as session:
        results = {}
        for tf in TIMEFRAMES:
            df = await fetch_ohlcv(session, symbol, tf)
            if df is None:
                return None          # all TFs must succeed
            results[tf] = df
            await asyncio.sleep(1)   # 1 s between calls — safe for free tier
        return results


async def fetch_multiple_pairs(pairs: list) -> dict:
    """Fetch data for a list of pairs. Skips any that fail."""
    data_map = {}
    for pair in pairs:
        logger.info(f"Fetching {pair}…")
        tfs = await fetch_all_timeframes(pair)
        if tfs:
            data_map[pair] = tfs
        await asyncio.sleep(2)   # pause between pairs
    return data_map
