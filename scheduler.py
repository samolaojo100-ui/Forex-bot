import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import Application
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_pairs
from formatter import format_signal
from session_manager import is_good_session, is_weekend
from user_settings import get_balance
from config import CHAT_IDS, ALL_PAIRS, CRYPTO_PAIRS, AUTO_SIGNAL_INTERVAL

logger    = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

# Same threshold as handlers.py — keep these two values in sync.
# Auto-scan must apply the same confidence floor as /signal and /crypto,
# otherwise low-confidence signals (e.g. 51%) get auto-posted even though
# a manual scan would have filtered them out.
MIN_CONFIDENCE_TO_SHOW = 70


def filter_by_confidence(signals: list, min_confidence: int = MIN_CONFIDENCE_TO_SHOW) -> list:
    """Keep only signals at or above the confidence threshold."""
    return [s for s in signals if s.confidence >= min_confidence]


async def auto_scan(app: Application):
    crypto_only = is_weekend()
    pairs       = CRYPTO_PAIRS if crypto_only else ALL_PAIRS

    if not crypto_only and not is_good_session():
        logger.info("Auto-scan skipped — off-hours")
        return

    label = "₿ Crypto" if crypto_only else "📊 All Pairs"
    logger.info(f"🔄 Auto-scan started ({label})…")

    try:
        data_map = await fetch_multiple_pairs(pairs)
    except Exception as e:
        logger.error(f"Auto-scan fetch error: {e}")
        return

    if not data_map:
        logger.info("Auto-scan — no data returned")
        return

    for chat_id_raw in CHAT_IDS:
        chat_id = str(chat_id_raw).strip()
        if not chat_id:
            continue

        balance = get_balance(int(chat_id))
        if not balance:
            continue

        try:
            signals = await scan_pairs(data_map, balance)
            signals = filter_by_confidence(signals)
        except Exception as e:
            logger.error(f"Auto-scan signal error {chat_id}: {e}")
            continue

        if not signals:
            logger.info(f"No qualifying signals (\u226570% confidence) for {chat_id}")
            continue

        top = signals[:2]

        try:
            await app.bot.send_message(
                chat_id,
                f"⚡ *TrendGuard AI — Auto Signal*\n"
                f"{label} · Found *{len(signals)}* signal(s) ≥{MIN_CONFIDENCE_TO_SHOW}%\n"
                f"💰 Balance: `${balance:,.2f}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            for i, sig in enumerate(top, 1):
                await app.bot.send_message(
                    chat_id,
                    format_signal(sig, i, len(top)),
                    parse_mode=ParseMode.MARKDOWN,
                )
        except Exception as e:
            logger.error(f"Send error to {chat_id}: {e}")


async def start_scheduler(app: Application):
    scheduler.add_job(
        auto_scan,
        trigger=IntervalTrigger(minutes=AUTO_SIGNAL_INTERVAL),
        args=[app],
        id="auto_scan",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"✅ Scheduler started — every {AUTO_SIGNAL_INTERVAL} min")
