import os
import logging
import asyncpg

logger = logging.getLogger(__name__)

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL not set — check Railway variables")
        _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
        logger.info("✅ Postgres pool created")
    return _pool


async def init_db():
    """Creates the signals_log table if it doesn't exist yet. Safe to call every startup."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals_log (
                id           SERIAL PRIMARY KEY,
                pair         TEXT NOT NULL,
                direction    TEXT NOT NULL,
                confidence   INTEGER NOT NULL,
                confluence   INTEGER NOT NULL,
                entry        DOUBLE PRECISION NOT NULL,
                sl           DOUBLE PRECISION NOT NULL,
                tp1          DOUBLE PRECISION NOT NULL,
                tp2          DOUBLE PRECISION NOT NULL,
                tp3          DOUBLE PRECISION NOT NULL,
                asset_type   TEXT NOT NULL,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    logger.info("✅ signals_log table ready")


async def save_signal(sig):
    """
    Saves one qualifying signal. Never raises — a DB hiccup should never
    break a Telegram reply or an API response, so failures are just logged.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO signals_log
                    (pair, direction, confidence, confluence, entry, sl, tp1, tp2, tp3, asset_type)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                """,
                sig.pair, sig.direction, sig.confidence, sig.confluence,
                sig.entry, sig.sl, sig.tp1, sig.tp2, sig.tp3, sig.asset_type,
            )
    except Exception as e:
        logger.warning(f"save_signal failed for {getattr(sig, 'pair', '?')}: {e}")


async def get_stats():
    pool = await get_pool()
    async with pool.acquire() as conn:
        total       = await conn.fetchval("SELECT COUNT(*) FROM signals_log")
        last_24h    = await conn.fetchval(
            "SELECT COUNT(*) FROM signals_log WHERE created_at > now() - interval '24 hours'"
        )
        avg_conf    = await conn.fetchval("SELECT AVG(confidence) FROM signals_log")
        by_dir_rows = await conn.fetch(
            "SELECT direction, COUNT(*) AS c FROM signals_log GROUP BY direction"
        )
        by_asset_rows = await conn.fetch(
            "SELECT asset_type, COUNT(*) AS c FROM signals_log GROUP BY asset_type"
        )

    return {
        "total_signals":  total or 0,
        "last_24h":       last_24h or 0,
        "avg_confidence": round(float(avg_conf), 1) if avg_conf else 0,
        "by_direction":   {row["direction"]: row["c"] for row in by_dir_rows},
        "by_asset_type":  {row["asset_type"]: row["c"] for row in by_asset_rows},
    }


async def get_history(limit: int = 50):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM signals_log ORDER BY created_at DESC LIMIT $1", limit
        )
    return [dict(r) for r in rows]
