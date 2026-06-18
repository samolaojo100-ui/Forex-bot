# data_fetcher.py
import aiohttp
import asyncio
import logging
import pandas as pd
from config import TWELVEDATA_API_KEY, TIMEFRAMES

logger = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com"

# ── Rate limit: Basic 8 plan = 8 requests/minute ──────────────────────
# We allow max 7 per minute to stay safely under the limit.
# 60 seconds / 7 = ~8.5 seconds between each request.
RATE_LIMIT_DELAY = 9.0   # seconds between every single API call
PAIR_DELAY       = 2.0   # extra pause between pairs


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
                code = data.get("code", "")
                msg  = data.get("message", "")
                # Rate limit hit — log clearly
                if code == 429 or "rate limit" in str(msg).lower():
                    logger.warning(f"⛔ Rate limit hit on {symbol} {interval} — backing off")
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


async def fetch_all_timeframes(symbol: str):
    """
    Fetch all timeframes for one pair.
    Waits RATE_LIMIT_DELAY seconds between each timeframe fetch
    to stay within 8 req/min limit.
    """
    async with aiohttp.ClientSession() as session:
        results = {}
        for tf in TIMEFRAMES:
            df = await fetch_ohlcv(session, symbol, tf)
            if df is None or len(df) < 50:
                logger.warning(f"{symbol} {tf}: insufficient data — skipping pair")
                return None
            results[tf] = df
            # Wait between each timeframe call
            await asyncio.sleep(RATE_LIMIT_DELAY)
        return results


async def fetch_multiple_pairs(pairs: list) -> dict:
    """
    Fetch all pairs sequentially with rate limiting.
    Never fires more than 1 request per RATE_LIMIT_DELAY seconds.
    """
    data_map = {}
    total    = len(pairs)

    for i, pair in enumerate(pairs, 1):
        logger.info(f"Fetching {pair} ({i}/{total})...")
        tfs = await fetch_all_timeframes(pair)
        if tfs:
            data_map[pair] = tfs
        # Extra pause between pairs
        await asyncio.sleep(PAIR_DELAY)

    logger.info(f"Fetch complete — {len(data_map)}/{total} pairs returned data")
    return data_map