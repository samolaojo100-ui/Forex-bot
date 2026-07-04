from fastapi import FastAPI
import asyncio

from signal_engine import scan_pairs
from config import ALL_PAIRS, ACCOUNT_BALANCE
from data_fetcher import fetch_all_pairs_data  # adjust import to match your actual data-fetching module/function name

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/signals/latest")
async def latest_signals():
    data_map = await fetch_all_pairs_data(ALL_PAIRS)
    signals = await scan_pairs(data_map, ACCOUNT_BALANCE)
    return {
        "count": len(signals),
        "signals": [s.__dict__ for s in signals],
    }