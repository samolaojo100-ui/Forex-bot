import logging

from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, filters,
)
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs, analyze_pair, overall_direction, force_analyze_pair
from formatter import format_signal, format_no_signal, format_scanning, format_status
from session_manager import get_current_session, minutes_to_next_scan, is_weekend
from user_settings import get_balance, set_balance
from demo import generate_demo_signals, format_demo_signal
from config import ALL_PAIRS, CRYPTO_PAIRS
from indicators import compute_indicators
from scan_lock import ScanGuard

logger = logging.getLogger(__name__)

MAX_SIGNALS = 5
ASK_BALANCE = 1


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    bal_line = f"💰 Balance: *${balance:,.2f}*" if balance else "💰 Balance: _not set — use /setbalance_"
    await update.message.reply_text(
        "🤖 *Forex & Crypto Signal Bot*\n\n"
        f"{bal_line}\n\n"
        "📌 *Commands:*\n"
        "/signal — full forex + crypto scan\n"
        "/crypto — crypto only *(24/7 ✅)*\n"
        "/demo — preview signal format\n"
        "/setbalance — set your balance\n"
        "/status — session info\n"
        "/help — full guide\n\n"
        "✅ 47 Forex + 12 Crypto pairs\n"
        "✅ 5 timeframes · 5 indicators each\n"
        "✅ Auto-signals every 30 min",
        parse_mode=ParseMode.MARKDOWN,
    )


async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)

    if balance is None:
        await update.message.reply_text(
            "⚠️ *No balance set.*\n\nUse /setbalance first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Prevent overlapping with another manual scan OR the background
    # auto-scan job. Running two fetch loops at once is what actually
    # trips TwelveData's per-minute rate limit, even with plenty of
    # daily credits left.
    try:
        async with ScanGuard("crypto"):
            await _run_crypto_scan(update, context, chat_id, balance)
    except RuntimeError as e:
        await update.message.reply_text(
            f"⏳ *Scan already in progress.*\n\n{e}\n\nPlease wait for it to finish before trying again.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _run_crypto_scan(update, context, chat_id, balance):
    scanning_msg = await update.message.reply_text(
        format_scanning(crypto_only=True), parse_mode=ParseMode.MARKDOWN
    )

    try:
        data_map = await fetch_multiple_pairs(CRYPTO_PAIRS)

        if not data_map:
            await scanning_msg.edit_text(
                "❌ *Could not fetch market data.*\n\n"
                "This usually means TwelveData rate-limited the request "
                "(too many calls in the last minute), not a credits or "
                "API-key problem. Check the Railway logs for the exact "
                "reason, then wait a minute before retrying.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Force analyze ALL pairs — return best ones regardless of score
        all_signals = []
        for pair, tfs in data_map.items():
            try:
                sig = analyze_pair(pair, tfs, balance)
                if sig:
                    all_signals.append(sig)
                else:
                    # Force a signal even if score is low / daily filter blocked it
                    sig = force_analyze_pair(pair, tfs, balance)
                    if sig:
                        all_signals.append(sig)
            except Exception as e:
                logger.warning(f"{pair} error: {e}")

        all_signals.sort(key=lambda s: s.score, reverse=True)
        top = all_signals[:3]

        if not top:
            await scanning_msg.edit_text(
                "❌ *No signals from the data returned.*\n\n"
                "Data was fetched fine, but no pair produced a usable signal "
                "this scan. This is normal sometimes — try again shortly.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await scanning_msg.delete()

        header = (
            f"₿ *Crypto Scan Results*\n"
            f"Scanned *{len(data_map)}* pairs — top {len(top)} shown\n"
            f"💰 Balance: `${balance:,.2f}` · Risk: `1%`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await context.bot.send_message(chat_id, header, parse_mode=ParseMode.MARKDOWN)

        for i, sig in enumerate(top, 1):
            await context.bot.send_message(
                chat_id, format_signal(sig, i, len(top)),
                parse_mode=ParseMode.MARKDOWN,
            )

    except Exception as e:
        logger.error(f"crypto_command error: {e}", exc_info=True)
        await scanning_msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)

    if balance is None:
        await update.message.reply_text(
            "⚠️ *No balance set.*\n\nUse /setbalance first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if is_weekend():
        await update.message.reply_text(
            "📅 *Forex market closed (Weekend)*\n\n"
            "👉 Use /crypto for live BTC/ETH signals now\n"
            "📅 Forex resumes *Sunday 10 PM GMT+1*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        async with ScanGuard("forex"):
            await _run_signal_scan(update, context, chat_id, balance)
    except RuntimeError as e:
        await update.message.reply_text(
            f"⏳ *Scan already in progress.*\n\n{e}\n\nPlease wait for it to finish before trying again.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _run_signal_scan(update, context, chat_id, balance):
    scanning_msg = await update.message.reply_text(
        format_scanning(), parse_mode=ParseMode.MARKDOWN
    )

    try:
        data_map = await fetch_multiple_pairs(ALL_PAIRS)

        if not data_map:
            await scanning_msg.edit_text(
                "❌ *Could not fetch market data.*\n\n"
                "This usually means TwelveData rate-limited the request "
                "(too many calls in the last minute), not a credits or "
                "API-key problem. Check the Railway logs for the exact "
                "reason, then wait a minute before retrying.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        signals = scan_all_pairs(data_map, account_balance=balance)

        if not signals:
            await scanning_msg.edit_text(format_no_signal(), parse_mode=ParseMode.MARKDOWN)
            return

        top = signals[:MAX_SIGNALS]
        await scanning_msg.delete()

        await context.bot.send_message(
            chat_id,
            f"📊 *Market Scan Results*\n"
            f"Found *{len(signals)}* signal(s) — top {len(top)}\n"
            f"💰 Balance: `${balance:,.2f}` · Risk: `1%`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.MARKDOWN,
        )

        for i, sig in enumerate(top, 1):
            await context.bot.send_message(
                chat_id, format_signal(sig, i, len(top)),
                parse_mode=ParseMode.MARKDOWN,
            )

    except Exception as e:
        logger.error(f"signal_command error: {e}", exc_info=True)
        await scanning_msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def demo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "🎯 *Demo Mode — Sample Signals*\n\n"
        "Exact format of live signals.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━",
        parse_mode=ParseMode.MARKDOWN,
    )
    signals = generate_demo_signals()
    for i, sig in enumerate(signals, 1):
        await context.bot.send_message(
            chat_id, format_demo_signal(sig, i, len(signals)),
            parse_mode=ParseMode.MARKDOWN,
        )
    await context.bot.send_message(
        chat_id,
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ *Live signals look exactly like this*\n\n"
        "₿ /crypto → live signals right now\n"
        "💱 /signal → forex on weekdays",
        parse_mode=ParseMode.MARKDOWN,
    )


async def setbalance_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    current = get_balance(chat_id)
    cur_txt = f"\n_Current: ${current:,.2f}_" if current else ""
    await update.message.reply_text(
        f"💰 *Set Your Account Balance (USD)*{cur_txt}\n\n"
        "Type your balance e.g. `500` or `20`\n"
        "_/cancel to keep current_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_BALANCE


async def setbalance_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    text = update.message.text.strip().replace(",", "").replace("$", "")
    try:
        balance = float(text)
    except ValueError:
        await update.message.reply_text("❌ Numbers only e.g. `20`\n\nTry again:", parse_mode=ParseMode.MARKDOWN)
        return ASK_BALANCE

    if balance < 1:
        await update.message.reply_text("❌ Minimum $1.\n\nTry again:", parse_mode=ParseMode.MARKDOWN)
        return ASK_BALANCE

    set_balance(chat_id, balance)
    risk = balance * 0.01
    await update.message.reply_text(
        f"✅ *Balance saved: ${balance:,.2f}*\n\n"
        f"• Risk per trade: `${risk:,.2f}` (1%)\n\n"
        f"Use /crypto for live signals now!",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def setbalance_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("↩️ Cancelled.")
    return ConversationHandler.END


def build_setbalance_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setbalance", setbalance_start)],
        states={ASK_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbalance_receive)]},
        fallbacks=[CommandHandler("cancel", setbalance_cancel)],
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help*\n\n"
        "• /signal — full scan (weekdays)\n"
        "• /crypto — crypto 24/7\n"
        "• /demo — sample signals\n"
        "• /setbalance — set balance\n"
        "• /status — session info\n\n"
        "*Signal format shows:*\n"
        "✅ 5 timeframes (5M/15M/1H/4H/Daily)\n"
        "✅ Per-TF direction, entry, SL, TP, lot\n"
        "✅ RSI, Stochastic, MACD values\n"
        "✅ Overall confidence & pair score",
        parse_mode=ParseMode.MARKDOWN,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    session_name, is_active = get_current_session()
    bal_text = f"${balance:,.2f}" if balance else "Not set"
    await update.message.reply_text(
        format_status(session_name, is_active, minutes_to_next_scan(), bal_text),
        parse_mode=ParseMode.MARKDOWN,
    )
