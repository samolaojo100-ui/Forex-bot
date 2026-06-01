import aiohttp
import asyncio
import logging
import pandas as pd
from config import TWELVEDATA_API_KEY, TIMEFRAMES

logger = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com"

# TwelveData free tier: 8 req/min = ~800/day
# With 5 TFs per pair, fetch sequentially with a small delay to stay safe
_REQUEST_DELAY = 1.0  # seconds between requests (safe for free tier)


def _fmt_symbol(pair: str) -> str:
    """
    Convert 'EUR/USD' → 'EUR/USD' for TwelveData.
    TwelveData accepts the slash format for forex; only crypto needs the slash too.
    Keep as-is — do NOT strip the slash.
    """
    return pair  # e.g. "EUR/USD", "BTC/USD" — TwelveData supports this format


async def fetch_ohlcv(session: aiohttp.ClientSession, symbol: str, interval: str, outputsize: int = 100):
    url = (
        f"{BASE_URL}/time_series"
        f"?symbol={symbol}&interval={interval}"
        f"&outputsize={outputsize}&apikey={TWELVEDATA_API_KEY}&format=JSON"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()

        if data.get("status") == "error" or "values" not in data:
            err_msg = data.get("message", "unknown error")
            logger.warning(f"API error for {symbol} {interval}: {err_msg}")
            return None

        df = pd.DataFrame(data["values"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.sort_values("datetime").reset_index(drop=True)
        return df

    except asyncio.TimeoutError:
        logger.warning(f"Timeout fetching {symbol} {interval}")
        return None
    except Exception as e:
        logger.warning(f"Fetch error {symbol} {interval}: {e}")
        return None


async def fetch_all_timeframes(symbol: str):
    """
    Fetch all configured timeframes for a single symbol.
    Returns dict {tf: df} or None if any timeframe failed.
    
    FIX: Removed the 8-second sleep between each TF call (was causing timeouts
    and massively slowing down the scan). Now uses a 1-second delay only.
    """
    async with aiohttp.ClientSession() as session:
        results = {}
        for tf in TIMEFRAMES:
            df = await fetch_ohlcv(session, symbol, tf)
            if df is None or len(df) < 50:
                logger.warning(f"{symbol} {tf}: insufficient data ({len(df) if df is not None else 0} rows)")
                return None  # all TFs must succeed
            results[tf] = df
            await asyncio.sleep(_REQUEST_DELAY)  # FIX: was 8 seconds, now 1 second
        return results


async def fetch_multiple_pairs(pairs: list) -> dict:
    """
    Fetch data for multiple pairs. Returns {pair: {tf: df}}.
    Pairs that fail are silently skipped.
    """
    data_map = {}
    for pair in pairs:
        logger.info(f"Fetching {pair}...")
        tfs = await fetch_all_timeframes(pair)
        if tfs:
            data_map[pair] = tfs
        await asyncio.sleep(2)  # pause between pairs
    return data_map
