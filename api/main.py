from fastapi import FastAPI, Query
from dataclasses import asdict

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_pairs
from config import ALL_PAIRS, ACCOUNT_BALANCE
from db import init_db, get_stats, get_history

app = FastAPI()

# Kept in sync with handlers.py — signals below this confidence aren't
# considered "shown" quality. Update both places if you change this.
MIN_CONFIDENCE_TO_SHOW = 60


@app.on_event("startup")
async def on_startup():
    # The bot runs as a separate process (see start.py), so this API
    # process needs its own call to make sure signals_log exists —
    # it doesn't share memory with bot.py's post_init.
    await init_db()


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


@app.get("/stats")
async def stats():
    """
    Aggregate stats from every signal that's ever been saved
    (i.e. every signal that passed the 60% confidence bar, from
    /signal, /crypto, /stocks, or the auto-scheduler).
    """
    return await get_stats()


@app.get("/signals/history")
async def history(limit: int = Query(default=50, le=200)):
    """Most recent saved signals, newest first. ?limit=N, capped at 200."""
    return await get_history(limit)
