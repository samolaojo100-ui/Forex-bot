import aiohttp
import asyncio
import logging
import pandas as pd

from config import TWELVEDATA_API_KEY, TIMEFRAMES

logger = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com"

# TwelveData free tier returns status 429 (or a JSON error with code 429 /
# message mentioning "limit") when you've hit the per-minute rate limit.
# This is DIFFERENT from running out of daily credits (code 401/403 or a
# message about API key / credits / quota), and DIFFERENT again from a
# malformed/unrecognized symbol (code 400 with a message about the symbol
# or figi parameter). Previously the bot treated every failure identically
# and just returned None, silently — so all three causes looked the same
# to the user ("check your API key"), which sent us chasing the wrong fix
# more than once.
RATE_LIMIT_RETRY_SECONDS = 65   # TwelveData's limit window is per-minute
MAX_RATE_LIMIT_RETRIES = 2


def _classify_error(data: dict, http_status: int) -> str:
    """Best-effort classification of a TwelveData error response."""
    code = data.get("code", http_status)
    message = str(data.get("message", "")).lower()

    if code == 429 or "rate limit" in message or ("limit" in message and "minute" in message):
        return "rate_limit"
    if code in (401, 403) or "api key" in message or "credit" in message or "quota" in message:
        return "auth_or_quota"
    if "symbol" in message or "figi" in message:
        return "bad_symbol"
    return "unknown"


def _format_symbol(symbol: str) -> str:
    """
    TwelveData requires the slash for BOTH forex and crypto symbols
    (e.g. "EUR/USD", "BTC/USD") — it is NOT just visual formatting.
    Stripping the slash (symbol.replace("/", "")) sends TwelveData a
    symbol it does not recognize, which is why every single crypto
    pair was failing with a "symbol missing or invalid" error: the
    slash was being removed before the request was ever sent.
    This function now just normalizes spacing/case, and explicitly
    does NOT remove the slash.
    """
    return symbol.strip().upper()


async def fetch_ohlcv(session, symbol, interval, outputsize=100, _retry_count=0):
    symbol_fmt = _format_symbol(symbol)
    url = (
        f"{BASE_URL}/time_series"
        f"?symbol={symbol_fmt}&interval={interval}"
        f"&outputsize={outputsize}&apikey={TWELVEDATA_API_KEY}&format=JSON"
    )
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()

            if data.get("status") == "error" or "values" not in data:
                error_type = _classify_error(data, resp.status)
                raw_message = data.get("message", "no message in response")

                if error_type == "rate_limit" and _retry_count < MAX_RATE_LIMIT_RETRIES:
                    logger.warning(
                        f"[RATE LIMIT] {symbol} {interval}: {raw_message} "
                        f"- backing off {RATE_LIMIT_RETRY_SECONDS}s and retrying "
                        f"(attempt {_retry_count + 1}/{MAX_RATE_LIMIT_RETRIES})"
                    )
                    await asyncio.sleep(RATE_LIMIT_RETRY_SECONDS)
                    return await fetch_ohlcv(
                        session, symbol, interval, outputsize, _retry_count + 1
                    )

                if error_type == "rate_limit":
                    logger.error(
                        f"[RATE LIMIT - GAVE UP] {symbol} {interval}: {raw_message} "
                        f"- exhausted {MAX_RATE_LIMIT_RETRIES} retries"
                    )
                elif error_type == "auth_or_quota":
                    logger.error(
                        f"[QUOTA/AUTH ERROR] {symbol} {interval}: {raw_message} "
                        f"- this means daily credits or API key, not rate limiting"
                    )
                elif error_type == "bad_symbol":
                    logger.error(
                        f"[BAD SYMBOL] {symbol} {interval} (sent as '{symbol_fmt}'): {raw_message}"
                    )
                else:
                    logger.error(
                        f"[UNKNOWN API ERROR] {symbol} {interval}: "
                        f"http_status={resp.status} full_response={data}"
                    )
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


async def fetch_all_timeframes(symbol):
    async with aiohttp.ClientSession() as session:
        results = {}
        for tf in TIMEFRAMES:
            df = await fetch_ohlcv(session, symbol, tf)
            if df is None or len(df) < 50:
                logger.warning(
                    f"{symbol} {tf}: no usable data (see error log above for cause) "
                    f"- skipping rest of this pair"
                )
                return None
            results[tf] = df
            await asyncio.sleep(8)
        return results


async def fetch_multiple_pairs(pairs):
    data_map = {}
    failed_pairs = []
    for pair in pairs:
        logger.info(f"Fetching {pair}...")
        tfs = await fetch_all_timeframes(pair)
        if tfs:
            data_map[pair] = tfs
        else:
            failed_pairs.append(pair)
        await asyncio.sleep(2)

    if failed_pairs:
        logger.warning(
            f"Failed to fetch data for {len(failed_pairs)}/{len(pairs)} pairs: "
            f"{', '.join(failed_pairs)} - check error log above for the real cause "
            f"(rate limit vs quota vs bad symbol)"
        )
    return data_map
