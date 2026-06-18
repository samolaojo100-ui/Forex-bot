import aiohttp
import asyncio
import logging
import pandas as pd
from config import TWELVEDATA_API_KEY, TIMEFRAMES

logger = logging.getLogger(__name__)
BASE_URL = "https://api.twelvedata.com"


async def fetch_ohlcv(session, symbol: str, interval: str, outputsize: int = 100):
    symbol_fmt = symbol.replace("/", "")
    url = (
        f"{BASE_URL}/time_series"
        f"?symbol={symbol_fmt}&interval={interval}"
        f"&outputsize={outputsize}&apikey={TWELVEDATA_API_KEY}&format=JSON"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            data = await resp.json()
            if data.get("status") == "error" or "values" not in data:
                msg = data.get("message", "")
                code = data.get("code", "")
                if code == 429 or "rate limit" in str(msg).lower():
                    logger.warning(f"⛔ Rate limit — waiting 60s")
                    await asyncio.sleep(60)
                else:
                    logger.warning(f"API error {symbol} {interval}: {msg}")
                return None
            df = pd.DataFrame(data["values"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])
            df["volume"] = pd.to_numeric(
                df.get("volume", 0), errors="coerce"
            ).fillna(0)
            df = df.sort_values("datetime").reset_index(drop=True)
            return df
    except Exception as e:
        logger.warning(f"Fetch error {symbol} {interval}: {e}")
        return None


async def fetch_multiple_pairs(pairs: list) -> dict:
    """
    One shared session for ALL pairs and ALL timeframes.
    8 seconds between EVERY single request — guaranteed under 8/min.
    """
    data_map = {}
    total = len(pairs)

    # ONE session for everything
    async with aiohttp.ClientSession() as session:
        for i, pair in enumerate(pairs, 1):
            logger.info(f"Fetching {pair} ({i}/{total})...")
            results = {}
            failed = False

            for tf in TIMEFRAMES:
                # Wait BEFORE every request except the very first
                if results or i > 1:
                    await asyncio.sleep(8)

                df = await fetch_ohlcv(session, pair, tf)
                if df is None or len(df) < 50:
                    logger.warning(f"{pair} {tf}: failed — skipping pair")
                    failed = True
                    break
                results[tf] = df

            if not failed and results:
                data_map[pair] = results

    logger.info(f"Fetch complete — {len(data_map)}/{total} pairs")
    return data_map