import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import Application
from telegram.constants import ParseMode
from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs
from formatter import format_signal
from session_manager import is_good_session, is_weekend, get_current_session, get_session_pairs
from user_settings import get_balance
from config import CHAT_IDS, CRYPTO_PAIRS, AUTO_SIGNAL_INTERVAL

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

MAX_SIGNALS_PER_SESSION = 2

# Tracks signals sent: { "2025-06-16_London": 1 }
_session_signal_count: dict = {}


def _session_key(session_name: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{today}_{session_name}"


def _can_send(session_name: str) -> bool:
    return _session_signal_count.get(_session_key(session_name), 0) < MAX_SIGNALS_PER_SESSION


def _record_sent(session_name: str):
    key = _session_key(session_name)
    _session_signal_count[key] = _session_signal_count.get(key, 0) + 1


async def auto_scan(app: Application):
    session_name, is_active = get_current_session()

    if is_weekend():
        pairs = CRYPTO_PAIRS
    else:
        if not is_active:
            logger.info("Auto-scan skipped — off-hours.")
            return
        if not _can_send(session_name):
            logger.info(f"Skipped — already sent {MAX_SIGNALS_PER_SESSION} signals for [{session_name}].")
            return
        pairs = get_session_pairs(session_name)

    logger.info(f"🔄 Auto-scan [{session_name}] — pairs: {pairs}")

    try:
        data_map = await fetch_multiple_pairs(pairs)
    except Exception as e:
        logger.error(f"Auto-scan fetch error: {e}", exc_info=True)
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
                    "⚠️ *Auto-signal ready but no balance set!*\n\nUse /setbalance to activate auto-signals.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            continue

        crypto_only = is_weekend()
        signals = scan_all_pairs(data_map, account_balance=balance, crypto_only=crypto_only)

        if not signals:
            logger.info(f"No signals for {chat_id} in [{session_name}]")
            continue

        sent_so_far = _session_signal_count.get(_session_key(session_name), 0)
        label = "₿ Crypto" if crypto_only else f"📊 {session_name}"

        try:
            await app.bot.send_message(
                chat_id,
                f"⚡ *{label} Signal*\n"
                f"Signal {sent_so_far + 1}/{MAX_SIGNALS_PER_SESSION} this session\n"
                f"💰 Balance: `${balance:,.2f}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━",
                parse_mode=ParseMode.MARKDOWN,
            )
            top = signals[:1]
            for i, sig in enumerate(top, 1):
                await app.bot.send_message(
                    chat_id,
                    format_signal(sig, i, len(top)),
                    parse_mode=ParseMode.MARKDOWN,
                )
        except Exception as e:
            logger.error(f"Send error to {chat_id}: {e}")

    if not is_weekend():
        _record_sent(session_name)


async def start_scheduler(app: Application):
    scheduler.add_job(
        auto_scan,
        trigger=IntervalTrigger(minutes=AUTO_SIGNAL_INTERVAL),
        args=[app],
        id="auto_scan",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"✅ Scheduler started — every {AUTO_SIGNAL_INTERVAL} min, max {MAX_SIGNALS_PER_SESSION} signals/session.")
