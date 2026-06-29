import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import Application
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_pairs
from formatter import format_signal
from session_manager import is_weekend
from user_settings import get_balance
from config import CHAT_IDS

logger    = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

# ── Confidence thresholds ─────────────────────────────────────────────
MIN_CONFIDENCE_TO_SHOW = 70   # private users
GROUP_MIN_CONFIDENCE   = 75   # Telegram group

# ── Group chat ID ─────────────────────────────────────────────────────
GROUP_CHAT_ID = "-3884983020"

# ── Session pair map ──────────────────────────────────────────────────
# Each session defines which pairs are most powerful during that window.
# XAU/USD and crypto run 24/7 and are always included.

ALWAYS_ON = [
    "XAU/USD",
    "BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD",
]

SESSION_PAIRS = {
    "tokyo": {
        "utc_start": 0,
        "utc_end":   9,
        "pairs": ["USD/JPY", "AUD/USD", "NZD/USD", "EUR/GBP"] + ALWAYS_ON,
        "label": "🗼 Tokyo Session",
    },
    "london": {
        "utc_start": 7,
        "utc_end":   12,   # 7-12 pure London (before NY opens)
        "pairs": ["EUR/USD", "GBP/USD", "USD/CHF", "EUR/GBP", "GBP/JPY"] + ALWAYS_ON,
        "label": "🇬🇧 London Session",
    },
    "overlap": {
        "utc_start": 12,
        "utc_end":   16,   # London/NY overlap — strongest window
        "pairs": [
            "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
            "GBP/JPY", "AUD/USD", "USD/CAD", "NZD/USD",
            "EUR/GBP",
        ] + ALWAYS_ON,
        "label": "⚡ London/NY Overlap",
    },
    "newyork": {
        "utc_start": 16,
        "utc_end":   21,   # NY afternoon (after overlap)
        "pairs": ["USD/CAD", "USD/CHF", "EUR/USD", "GBP/USD"] + ALWAYS_ON,
        "label": "🗽 New York Session",
    },
    "dead": {
        "utc_start": 21,
        "utc_end":   24,   # Dead hours — forex sleeps
        "pairs": ALWAYS_ON,  # Only gold + crypto
        "label": "🌙 After Hours",
    },
}


def get_active_session() -> dict:
    """Return the active session config based on current UTC hour."""
    hour = datetime.now(timezone.utc).hour

    # Check overlap first (most specific)
    if 12 <= hour < 16:
        return SESSION_PAIRS["overlap"]
    elif 0 <= hour < 7:
        return SESSION_PAIRS["tokyo"]
    elif 7 <= hour < 12:
        return SESSION_PAIRS["london"]
    elif 16 <= hour < 21:
        return SESSION_PAIRS["newyork"]
    else:
        return SESSION_PAIRS["dead"]


def filter_by_confidence(signals: list, min_conf: int) -> list:
    return [s for s in signals if s.confidence >= min_conf]


async def auto_scan(app: Application):
    """
    Session-aware auto scan.
    Scans only the pairs that are powerful in the current session.
    XAU/USD and crypto always included.
    """
    # Weekend — crypto + gold only
    if is_weekend():
        session = {
            "pairs": ALWAYS_ON,
            "label": "🌐 Weekend — Crypto & Gold",
        }
    else:
        session = get_active_session()

    pairs = session["pairs"]
    label = session["label"]

    logger.info(f"🔄 Auto-scan: {label} — {len(pairs)} pairs")

    try:
        data_map = await fetch_multiple_pairs(pairs)
    except Exception as e:
        logger.error(f"Auto-scan fetch error: {e}")
        return

    if not data_map:
        logger.info("Auto-scan — no data returned")
        return

    # ── Send to private users (70%+) ─────────────────────────────────
    for chat_id_raw in CHAT_IDS:
        chat_id = str(chat_id_raw).strip()
        if not chat_id:
            continue

        balance = get_balance(int(chat_id))
        if not balance:
            continue

        try:
            signals = await scan_pairs(data_map, balance)
            signals = filter_by_confidence(signals, MIN_CONFIDENCE_TO_SHOW)
        except Exception as e:
            logger.error(f"Signal scan error {chat_id}: {e}")
            continue

        if not signals:
            logger.info(f"No signals ≥{MIN_CONFIDENCE_TO_SHOW}% for {chat_id}")
            continue

        top = signals[:2]

        try:
            await app.bot.send_message(
                chat_id,
                f"⚡ *TrendGuard AI — Auto Signal*\n"
                f"{label}\n"
                f"Found *{len(signals)}* signal(s) ≥{MIN_CONFIDENCE_TO_SHOW}%\n"
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

    # ── Send to group (75%+) ──────────────────────────────────────────
    try:
        group_balance = 1000.0
        all_signals   = await scan_pairs(data_map, group_balance)
        group_signals = filter_by_confidence(all_signals, GROUP_MIN_CONFIDENCE)

        if not group_signals:
            logger.info(f"No signals ≥{GROUP_MIN_CONFIDENCE}% for group")
            return

        top_group = group_signals[:2]

        await app.bot.send_message(
            GROUP_CHAT_ID,
            f"🚨 *TrendGuard AI — Signal Alert*\n\n"
            f"{label}\n"
            f"*{len(group_signals)}* signal(s) ≥{GROUP_MIN_CONFIDENCE}% confidence\n\n"
            f"⚠️ _Not financial advice. Manage your risk._",
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
        trigger=IntervalTrigger(minutes=30),
        args=[app],
        id="auto_scan",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("✅ Session-aware scheduler started — every 30 min")
