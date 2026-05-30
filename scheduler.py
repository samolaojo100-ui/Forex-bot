import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import Application
from telegram.constants import ParseMode
from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs
from formatter import format_signal
from session_manager import is_good_session
from user_settings import get_balance
from config import CHAT_IDS, ALL_PAIRS, AUTO_SIGNAL_INTERVAL

logger    = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def auto_scan(app: Application):
    if not is_good_session():
        logger.info("Auto-scan skipped — off-hours.")
        return

    logger.info("🔄 Auto-scan started…")
    try:
        data_map = await fetch_multiple_pairs(ALL_PAIRS)
    except Exception as e:
        logger.error(f"Auto-scan fetch error: {e}", exc_info=True)
        return

    for chat_id in CHAT_IDS:
        chat_id = chat_id.strip()
        if not chat_id:
            continue

        balance = get_balance(int(chat_id))
        if balance is None:
            # Remind user to set balance instead of skipping silently
            try:
                await app.bot.send_message(
                    chat_id,
                    "⚠️ *Auto-signal ready but no balance set!*\n\n"
                    "Use /setbalance so I can calculate lot sizes for you.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            continue

        signals = scan_all_pairs(data_map, account_balance=balance)
        if not signals:
            logger.info(f"Auto-scan: no signals for chat {chat_id}")
            continue

        top = signals[:3]
        try:
            header = (
                f"⚡ *Auto-Signal Alert*\n"
                f"Found *{len(signals)}* signal(s) — top {len(top)} shown\n"
                f"💰 Balance: `${balance:,.2f}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━"
            )
            await app.bot.send_message(chat_id, header, parse_mode=ParseMode.MARKDOWN)
            for i, sig in enumerate(top, 1):
                await app.bot.send_message(
                    chat_id, format_signal(sig, i, len(top)),
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
    logger.info(f"✅ Scheduler started — every {AUTO_SIGNAL_INTERVAL} min.")
