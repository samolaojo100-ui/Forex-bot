import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import Application
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs
from formatter import format_signal
from session_manager import is_good_session, is_weekend
from user_settings import get_balance
from config import CHAT_IDS, ALL_PAIRS, CRYPTO_PAIRS, AUTO_SIGNAL_INTERVAL
from scan_lock import ScanGuard

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def auto_scan(app: Application):
    # Crypto scans always; forex only on weekdays
    pairs = CRYPTO_PAIRS if is_weekend() else ALL_PAIRS

    if not is_good_session():
        logger.info("Auto-scan skipped — off-hours.")
        return

    # Shares the same lock as the manual /signal and /crypto commands.
    # If a user is mid-scan when this timer fires, skip this run rather
    # than fetch concurrently — overlapping fetch loops is what trips
    # TwelveData's per-minute rate limit even with daily credits to spare.
    try:
        async with ScanGuard("auto"):
            await _run_auto_scan(app, pairs)
    except RuntimeError as e:
        logger.info(f"Auto-scan skipped — {e}")


async def _run_auto_scan(app: Application, pairs):
    logger.info(f"🔄 Auto-scan started ({'crypto only' if is_weekend() else 'all pairs'})…")
    try:
        data_map = await fetch_multiple_pairs(pairs)
    except Exception as e:
        logger.error(f"Auto-scan fetch error: {e}", exc_info=True)
        return

    if not data_map:
        logger.warning("Auto-scan got no data back — check error log above for rate-limit/quota cause.")
        return

    for chat_id in CHAT_IDS:
        chat_id = chat_id.strip()
        if not chat_id:
            continue

        balance = get_balance(int(chat_id))
        if balance is None:
            try:
                await app.bot.send_message(
                    chat_id,
                    "⚠️ *Auto-signal ready but no balance set!*\n\n"
                    "Use /setbalance to activate auto-signals.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            continue

        crypto_only = is_weekend()
        signals = scan_all_pairs(data_map, account_balance=balance, crypto_only=crypto_only)

        if not signals:
            logger.info(f"No signals for {chat_id}")
            continue

        top = signals[:3]
        label = "₿ Crypto" if crypto_only else "📊 Auto"

        try:
            await app.bot.send_message(
                chat_id,
                f"⚡ *{label} Signal Alert*\n"
                f"Found *{len(signals)}* signal(s) — top {len(top)} shown\n"
                f"💰 Balance: `${balance:,.2f}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━",
                parse_mode=ParseMode.MARKDOWN,
            )
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
