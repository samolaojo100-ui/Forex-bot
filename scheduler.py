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

# Confidence floor for private users (same as handlers.py)
MIN_CONFIDENCE_TO_SHOW = 70

# Only signals AT OR ABOVE this threshold get posted to the group
GROUP_MIN_CONFIDENCE = 80

# Your Telegram group chat ID
GROUP_CHAT_ID = "-3884983020"


def filter_by_confidence(signals: list, min_confidence: int = MIN_CONFIDENCE_TO_SHOW) -> list:
    return [s for s in signals if s.confidence >= min_confidence]


def filter_group_signals(signals: list) -> list:
    """Only the best signals go to the group — 85% and above."""
    return [s for s in signals if s.confidence >= GROUP_MIN_CONFIDENCE]


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

    # ── Post to private users (70%+) ─────────────────────────
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
            logger.info(f"No qualifying signals (≥70%) for {chat_id}")
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

    # ── Post to group (85%+ only) ─────────────────────────────
    try:
        # Use a default balance for group scanning (no user-specific balance)
        group_balance = 1000.0
        all_signals   = await scan_pairs(data_map, group_balance)
        group_signals = filter_group_signals(all_signals)

        if not group_signals:
            logger.info("No 85%+ signals for group this scan")
            return

        top_group = group_signals[:2]

        await app.bot.send_message(
            GROUP_CHAT_ID,
            f"🚨 *TrendGuard AI — Premium Signal Alert*\n\n"
            f"{label} · *{len(group_signals)}* HIGH CONFIDENCE signal(s) ≥{GROUP_MIN_CONFIDENCE}%\n\n"
            f"⚠️ _Always use proper risk management. Not financial advice._",
            parse_mode=ParseMode.MARKDOWN,
        )

        for i, sig in enumerate(top_group, 1):
            await app.bot.send_message(
                GROUP_CHAT_ID,
                format_signal(sig, i, len(top_group)),
                parse_mode=ParseMode.MARKDOWN,
            )

        logger.info(f"✅ Posted {len(top_group)} signal(s) to group")

    except Exception as e:
        logger.error(f"Group post error: {e}")


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
