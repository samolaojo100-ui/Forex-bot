"""
check_handler.py
─────────────────────────────────────────────────────────────────────────
Self-contained /check command — analyze ONE specific pair on demand.

Usage in Telegram:
    /check XAUUSD
    /check EURUSD
    /check BTCUSD

This file is INDEPENDENT of handlers.py — it imports directly from
data_fetcher, signal_engine, formatter, user_settings, and config,
exactly like handlers.py does. Nothing in handlers.py needs to change.

ONLY bot.py needs two additions (see bottom of this file for the
exact lines, also provided in the full bot.py).
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import analyze_pair, force_analyze_pair
from formatter import format_signal
from user_settings import get_balance
from config import ALL_PAIRS, CRYPTO_PAIRS

logger = logging.getLogger(__name__)


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /check <PAIR> — analyze ONE specific pair on demand.

    Examples:
        /check XAUUSD
        /check EURUSD
        /check BTCUSD

    Useful when a trading contest restricts you to specific instruments
    (e.g. only XAUUSD) and you need a signal for that exact pair instead
    of whatever /signal's full scan happens to rank highest.
    """
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)

    if balance is None:
        await update.message.reply_text(
            "⚠️ *No balance set.*\n\nUse /setbalance first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not context.args:
        await update.message.reply_text(
            "📌 *Usage:* `/check PAIR`\n\n"
            "Examples:\n"
            "`/check XAUUSD`\n"
            "`/check EURUSD`\n"
            "`/check BTCUSD`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    raw = context.args[0]
    pair = raw.upper().replace("/", "").replace(" ", "").strip()

    all_known = set(ALL_PAIRS) | set(CRYPTO_PAIRS)
    if pair not in all_known:
        suggestions = [p for p in all_known if pair in p or p in pair]
        suggestion_text = ""
        if suggestions:
            suggestion_text = "\n\nDid you mean: " + ", ".join(f"`{s}`" for s in suggestions[:5])

        await update.message.reply_text(
            f"❌ *Unknown pair:* `{pair}`\n\n"
            f"It's not in the bot's tracked pair list.{suggestion_text}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    scanning_msg = await update.message.reply_text(
        f"🔍 *Checking {pair}...*\n\n⏳ Please wait a few seconds...",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        data_map = await fetch_multiple_pairs([pair])

        if not data_map or pair not in data_map:
            await scanning_msg.edit_text(
                f"❌ Could not fetch data for `{pair}`.\n\n"
                "This could mean the TwelveData API limit was hit, "
                "or this symbol isn't supported by the data provider.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        tfs = data_map[pair]

        sig = analyze_pair(pair, tfs, balance)
        forced = False
        if sig is None:
            sig = force_analyze_pair(pair, tfs, balance)
            forced = True

        if sig is None:
            await scanning_msg.edit_text(
                f"❌ Could not generate a signal for `{pair}` — "
                "insufficient data returned.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await scanning_msg.delete()

        note = ""
        if forced:
            note = (
                "\n⚠️ _This signal did not meet the normal quality filters "
                "(low timeframe agreement / score). Shown anyway since you "
                "requested this specific pair — trade with extra caution._"
            )

        await context.bot.send_message(
            chat_id,
            format_signal(sig, 1, 1) + note,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"check_command error: {e}", exc_info=True)
        await scanning_msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)
