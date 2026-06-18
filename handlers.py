# handlers.py
import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, filters,
)
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs, analyze_pair, force_analyze_pair, overall_direction
from formatter import format_signal, format_no_signal, format_scanning, format_status, format_no_trade
from session_manager import get_current_session, minutes_to_next_scan, is_weekend
from user_settings import get_balance, set_balance
from config import ALL_PAIRS, CRYPTO_PAIRS
from news_filter import get_upcoming_events

logger = logging.getLogger(__name__)

MAX_SIGNALS = 5
ASK_BALANCE = 1


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    bal_line = f"💰 Balance: *${balance:,.2f}*" if balance else "💰 Balance: _not set — use /setbalance_"

    await update.message.reply_text(
        "🤖 *TrendGuard AI Signal Bot*\n\n"
        f"{bal_line}\n\n"
        "📌 *Commands:*\n"
        "/signal — full forex + crypto scan\n"
        "/crypto — crypto only *(24/7 ✅)*\n"
        "/setbalance — set your balance\n"
        "/status — session info\n"
        "/help — full guide\n\n"
        "✅ 7 Forex + 12 Crypto pairs\n"
        "✅ 4 timeframes · 5 indicators each\n"
        "✅ Auto-signals every 30 min\n"
        "✅ News filter — skips high-impact events\n"
        "✅ Daily trend gate + S/R proximity check",
        parse_mode=ParseMode.MARKDOWN,
    )


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

    scanning_msg = await update.message.reply_text(
        format_scanning(), parse_mode=ParseMode.MARKDOWN
    )

    try:
        data_map = await fetch_multiple_pairs(ALL_PAIRS)

        if not data_map:
            await scanning_msg.edit_text(
                "❌ Could not fetch market data.\n\n"
                "Check your TwelveData API key in Railway variables.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # ── await is required — scan_all_pairs is async ──
        signals = await scan_all_pairs(data_map, account_balance=balance)

        if not signals:
            await scanning_msg.edit_text(
                format_no_signal(), parse_mode=ParseMode.MARKDOWN
            )
            return

        top = signals[:MAX_SIGNALS]
        await scanning_msg.delete()

        await context.bot.send_message(
            chat_id,
            f"📊 *Market Scan Results*\n"
            f"Found *{len(signals)}* signal(s) — top {len(top)} shown\n"
            f"💰 Balance: `${balance:,.2f}` · Risk: `1%`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.MARKDOWN,
        )

        for i, sig in enumerate(top, 1):
            if isinstance(sig, dict) and sig.get("no_trade"):
                await context.bot.send_message(
                    chat_id,
                    format_no_trade(sig),
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await context.bot.send_message(
                    chat_id,
                    format_signal(sig, i, len(top)),
                    parse_mode=ParseMode.MARKDOWN,
                )

    except Exception as e:
        logger.error(f"signal_command error: {e}", exc_info=True)
        await scanning_msg.edit_text(
            f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN
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

    scanning_msg = await update.message.reply_text(
        format_scanning(crypto_only=True), parse_mode=ParseMode.MARKDOWN
    )

    try:
        data_map = await fetch_multiple_pairs(CRYPTO_PAIRS)

        if not data_map:
            await scanning_msg.edit_text(
                "❌ Could not fetch market data.\n\n"
                "Check your TwelveData API key in Railway variables.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        all_signals = []

        for pair, tfs in data_map.items():
            try:
                # ── await is required — analyze_pair is async ──
                sig = await analyze_pair(pair, tfs, balance)

                if sig and not isinstance(sig, dict):
                    all_signals.append(sig)
                else:
                    # Force a signal for crypto — always show something
                    forced = await force_analyze_pair(pair, tfs, balance)
                    if forced:
                        all_signals.append(forced)

            except Exception as e:
                logger.warning(f"{pair} error: {e}")

        all_signals.sort(key=lambda s: s.score, reverse=True)
        top = all_signals[:3]

        if not top:
            await scanning_msg.edit_text(
                "❌ No data returned from API.\n\n"
                "Your TwelveData free plan may have hit its daily limit (800 req/day).\n\n"
                "Try again tomorrow or check twelvedata.com",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await scanning_msg.delete()

        await context.bot.send_message(
            chat_id,
            f"₿ *Crypto Scan Results*\n"
            f"Scanned *{len(data_map)}* pairs — top {len(top)} shown\n"
            f"💰 Balance: `${balance:,.2f}` · Risk: `1%`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.MARKDOWN,
        )

        for i, sig in enumerate(top, 1):
            await context.bot.send_message(
                chat_id,
                format_signal(sig, i, len(top)),
                parse_mode=ParseMode.MARKDOWN,
            )

    except Exception as e:
        logger.error(f"crypto_command error: {e}", exc_info=True)
        await scanning_msg.edit_text(
            f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN
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
        await update.message.reply_text(
            "❌ Numbers only e.g. `20`\n\nTry again:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_BALANCE

    if balance < 1:
        await update.message.reply_text(
            "❌ Minimum $1.\n\nTry again:",
            parse_mode=ParseMode.MARKDOWN,
        )
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
        states={
            ASK_BALANCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, setbalance_receive)
            ]
        },
        fallbacks=[CommandHandler("cancel", setbalance_cancel)],
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help*\n\n"
        "• /signal — full scan (weekdays)\n"
        "• /crypto — crypto 24/7\n"
        "• /setbalance — set balance\n"
        "• /status — session + upcoming news\n\n"
        "*Signal format shows:*\n"
        "✅ 4 timeframes (15M/1H/4H/Daily)\n"
        "✅ Per-TF direction, entry, SL, TP, lot\n"
        "✅ RSI, Stochastic, MACD values\n"
        "✅ TP1, TP2, TP3 + Invalidation level\n"
        "✅ Market Regime + Session quality\n"
        "✅ Conviction % and pair score\n"
        "✅ News filter + Daily trend gate",
        parse_mode=ParseMode.MARKDOWN,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    session_name, is_active = get_current_session()
    bal_text = f"${balance:,.2f}" if balance else "Not set"

    try:
        upcoming = await get_upcoming_events(hours=24)
    except Exception:
        upcoming = []

    await update.message.reply_text(
        format_status(session_name, is_active, minutes_to_next_scan(), bal_text, upcoming),
        parse_mode=ParseMode.MARKDOWN,
    )
