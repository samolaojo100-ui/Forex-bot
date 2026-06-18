import aiohttp
import asyncio
import logging
import pandas as pd
from config import TWELVEDATA_API_KEY, TIMEFRAMES

logger = logging.getLogger(__name__)
BASE_URL = "https://api.twelvedata.com"

# Keep slash in symbol — TwelveData requires BTC/USD not BTCUSD
DELAY_BETWEEN_REQUESTS = 2.0  # seconds between each API call


async def fetch_ohlcv(session: aiohttp.ClientSession, symbol: str,
                      interval: str, outputsize: int = 100):
    url = (
        f"{BASE_URL}/time_series"
        f"?symbol={symbol}&interval={interval}"
        f"&outputsize={outputsize}&apikey={TWELVEDATA_API_KEY}&format=JSON"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            data = await resp.json()

            if data.get("status") == "error" or "values" not in data:
                code = data.get("code", "")
                msg  = data.get("message", "")
                if code == 429 or "rate limit" in str(msg).lower():
                    logger.warning(f"⛔ Rate limit — {symbol} {interval} — waiting 30s")
                    await asyncio.sleep(30)
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
    One shared session for all requests.
    Fixed delay between every single request to stay under rate limit.
    """
    data_map = {}
    total    = len(pairs)

    async with aiohttp.ClientSession() as session:
        for i, pair in enumerate(pairs, 1):
            logger.info(f"Fetching {pair} ({i}/{total})...")
            results = {}
            failed  = False

            for tf in TIMEFRAMES:
                await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
                df = await fetch_ohlcv(session, pair, tf)

                if df is None or len(df) < 30:
                    logger.warning(f"{pair} {tf}: no data — skipping pair")
                    failed = True
                    break

                results[tf] = df

            if not failed and results:
                data_map[pair] = results
                logger.info(f"✅ {pair} — all timeframes loaded")

    logger.info(f"Fetch complete — {len(data_map)}/{total} pairs")
    return data_map
