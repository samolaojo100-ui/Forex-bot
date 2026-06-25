"""
stocks_engine.py — TrendGuard AI
Fetches real OHLCV data for US stocks, oil, and commodities from TwelveData.
Returns data in the same {pair: {tf: df}} structure as
data_fetcher.py so scan_pairs() works unchanged.
"""

import asyncio
import logging
import pandas as pd
import aiohttp

from config import TWELVEDATA_API_KEY

logger = logging.getLogger(__name__)

# ── US Stocks (expanded) ──────────────────────────────────────────────────────
STOCK_PAIRS = [
    # Original 10
    "AAPL", "TSLA", "NVDA", "AMZN", "MSFT",
    "META", "GOOGL", "AMD", "NFLX", "JPM",
    # Added: more high-volume US stocks
    "COIN",   # Coinbase — crypto-linked
    "BABA",   # Alibaba
    "UBER",   # Uber
    "PYPL",   # PayPal
    "INTC",   # Intel
    "BAC",    # Bank of America
    "DIS",    # Disney
    "SHOP",   # Shopify
    "PLTR",   # Palantir
    "SOFI",   # SoFi
]

# ── Oil & Energy ──────────────────────────────────────────────────────────────
OIL_PAIRS = [
    "WTI/USD",    # West Texas Intermediate (US Oil)
    "BRENT/USD",  # Brent Crude (Global benchmark)
    "NATGAS/USD", # Natural Gas
]

# ── Commodities ───────────────────────────────────────────────────────────────
COMMODITY_PAIRS = [
    "XAG/USD",  # Silver
    "XPT/USD",  # Platinum
    "COPPER/USD", # Copper
]

# ── All instruments combined ──────────────────────────────────────────────────
ALL_STOCK_INSTRUMENTS = STOCK_PAIRS + OIL_PAIRS + COMMODITY_PAIRS

# TwelveData symbol mapping for oil/commodities
# (TwelveData uses different symbols for some instruments)
SYMBOL_MAP = {
    "WTI/USD":    "WTI",
    "BRENT/USD":  "BRENT",
    "NATGAS/USD": "NATGAS",
    "XAG/USD":    "XAG/USD",
    "XPT/USD":    "XPT/USD",
    "COPPER/USD": "COPPER/USD",
}

# Asset type labels for signal messages
ASSET_LABELS = {
    "WTI/USD":    "OIL (WTI) 🛢️",
    "BRENT/USD":  "OIL (Brent) 🛢️",
    "NATGAS/USD": "NATURAL GAS ⛽",
    "XAG/USD":    "SILVER 🥈",
    "XPT/USD":    "PLATINUM 💎",
    "COPPER/USD": "COPPER 🟤",
}

TIMEFRAMES  = ["15min", "1h", "4h", "1day"]
OUTPUT_SIZE = 100
BASE_URL    = "https://api.twelvedata.com/time_series"


def _get_twelvedata_symbol(pair: str) -> str:
    """Convert internal pair name to TwelveData API symbol."""
    return SYMBOL_MAP.get(pair, pair)


def get_asset_label(pair: str) -> str:
    """Return display label for signal messages."""
    if pair in ASSET_LABELS:
        return ASSET_LABELS[pair]
    return f"STOCK 📈 ({pair})"


async def _fetch_one_tf(
    session: aiohttp.ClientSession,
    symbol: str,
    interval: str,
) -> tuple:
    """Fetch one timeframe for one symbol."""
    td_symbol = _get_twelvedata_symbol(symbol)
    params = {
        "symbol":     td_symbol,
        "interval":   interval,
        "outputsize": OUTPUT_SIZE,
        "apikey":     TWELVEDATA_API_KEY,
        "format":     "JSON",
    }
    try:
        async with session.get(
            BASE_URL, params=params,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            data = await resp.json()

            if data.get("status") == "error":
                logger.warning(
                    f"TwelveData error {symbol}/{interval}: {data.get('message')}"
                )
                return symbol, interval, None

            values = data.get("values")
            if not values:
                return symbol, interval, None

            df = pd.DataFrame(list(reversed(values)))
            df.rename(columns={
                "datetime": "time",
                "open":     "open",
                "high":     "high",
                "low":      "low",
                "close":    "close",
                "volume":   "volume",
            }, inplace=True)

            for col in ["open", "high", "low", "close", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            df.dropna(subset=["open", "high", "low", "close"], inplace=True)
            return symbol, interval, df

    except Exception as e:
        logger.error(f"Failed to fetch {symbol}/{interval}: {e}")
        return symbol, interval, None


async def fetch_stock_pairs(symbols: list = None) -> dict:
    """
    Fetch all timeframes for all symbols concurrently.
    Returns {symbol: {"1h": df, "4h": df, "1day": df, "15min": df}}
    — identical structure to fetch_multiple_pairs() in data_fetcher.py.

    If symbols is None, fetches STOCK_PAIRS only (default behaviour).
    Pass ALL_STOCK_INSTRUMENTS to include oil and commodities.
    """
    if symbols is None:
        symbols = STOCK_PAIRS

    results = {sym: {} for sym in symbols}

    async with aiohttp.ClientSession() as session:
        tasks = [
            _fetch_one_tf(session, sym, tf)
            for sym in symbols
            for tf in TIMEFRAMES
        ]
        responses = await asyncio.gather(*tasks)

    for symbol, interval, df in responses:
        if df is not None and len(df) >= 30:
            results[symbol][interval] = df

    # Only keep symbols that have at least 1h data
    final = {
        sym: tfs
        for sym, tfs in results.items()
        if "1h" in tfs
    }

    logger.info(f"Fetched {len(final)}/{len(symbols)} instruments with valid data")
    return final


async def fetch_oil_pairs() -> dict:
    """Fetch oil and energy pairs only."""
    return await fetch_stock_pairs(OIL_PAIRS)


async def fetch_commodity_pairs() -> dict:
    """Fetch commodity pairs only."""
    return await fetch_stock_pairs(COMMODITY_PAIRS)


async def fetch_all_instruments() -> dict:
    """Fetch everything — stocks + oil + commodities."""
    return await fetch_stock_pairs(ALL_STOCK_INSTRUMENTS)
