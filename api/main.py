from fastapi import FastAPI, Query
from dataclasses import asdict

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_pairs
from config import ALL_PAIRS, ACCOUNT_BALANCE

app = FastAPI()

# Kept in sync with handlers.py — signals below this confidence aren't
# considered "shown" quality. Update both places if you change this.
MIN_CONFIDENCE_TO_SHOW = 60


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/signals/latest")
async def latest_signals(balance: float = Query(default=None)):
    bal = balance or ACCOUNT_BALANCE

    data_map = await fetch_multiple_pairs(ALL_PAIRS)
    if not data_map:
        return {"count": 0, "signals": [], "error": "Could not fetch market data"}

    signals = await scan_pairs(data_map, bal)
    signals = [s for s in signals if s.confidence >= MIN_CONFIDENCE_TO_SHOW]

    return {
        "count": len(signals),
        "signals": [asdict(s) for s in signals],
    }