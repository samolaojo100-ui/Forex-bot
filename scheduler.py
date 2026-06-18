# scheduler.py
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import Application
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs
from formatter import format_signal, format_no_trade
from session_manager import is_good_session, is_weekend
from user_settings import get_balance
from config import CHAT_IDS, ALL_PAIRS, CRYPTO_PAIRS, AUTO_SIGNAL_INTERVAL

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def auto_scan(app: Application):
    """
    Runs every AUTO_SIGNAL_INTERVAL minutes.
    - Weekdays: scans all pairs during active sessions
    - Weekends: scans crypto only (24/7)
    """
    crypto_only = is_weekend()
    pairs       = CRYPTO_PAIRS if crypto_only else ALL_PAIRS

    # Skip forex scan during off-hours (crypto always runs)
    if not crypto_only and not is_good_session():
        logger.info("Auto-scan skipped — off-hours.")
        return

    label = "₿ Crypto" if crypto_only else "📊 Forex + Crypto"
    logger.info(f"🔄 Auto-scan started ({label})…")

    try:
        data_map = await fetch_multiple_pairs(pairs)
    except Exception as e:
        logger.error(f"Auto-scan fetch error: {e}", exc_info=True)
        return

    if not data_map:
        logger.info("Auto-scan — no data returned from API.")
        return

    for chat_id_raw in CHAT_IDS:
        chat_id = str(chat_id_raw).strip()
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

        try:
            # ── await is required — scan_all_pairs is async ──────────
            signals = await scan_all_pairs(
                data_map,
                account_balance=balance,
                crypto_only=crypto_only,
            )
        except Exception as e:
            logger.error(f"Auto-scan signal error for {chat_id}: {e}")
            continue

        if not signals:
            logger.info(f"No qualifying signals for {chat_id}")
            continue

        top = signals[:2]  # max 2 signals per auto-scan to save API credits

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
                # Handle both Signal objects and NO TRADE dicts
                if isinstance(sig, dict) and sig.get("no_trade"):
                    await app.bot.send_message(
                        chat_id,
                        format_no_trade(sig),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
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
    logger.info(f"✅ Scheduler started — every {AUTO_SIGNAL_INTERVAL} min.")