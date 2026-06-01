import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, filters,
)
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs, analyze_pair, force_analyze_pair
from formatter import format_signal, format_no_signal, format_scanning, format_status
from session_manager import get_current_session, minutes_to_next_scan, is_weekend
from user_settings import get_balance, set_balance
from config import ALL_PAIRS, CRYPTO_PAIRS, FOREX_PAIRS

logger   = logging.getLogger(__name__)
MAX_SIGS = 5
ASK_BAL  = 1


# ── /start ─────────────────────────────────────────────────────────────────────

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
        "/setbalance — set your account balance\n"
        "/status — session & bot info\n"
        "/help — full guide\n\n"
        "✅ Majors + Minors + Exotics + Crypto\n"
        "✅ 3 timeframes · 5 indicators each\n"
        "✅ Auto-signals every 30 min during sessions",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /signal ────────────────────────────────────────────────────────────────────

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
            "👉 Use /crypto for live crypto signals right now.\n"
            "📅 Forex resumes Sunday 10 PM GMT+1.",
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
                "❌ *Could not fetch market data.*\n\n"
                "Check your TwelveData API key in Railway variables.\n"
                "Free tier limit: 800 req/day.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        signals = scan_all_pairs(data_map, account_balance=balance)

        if not signals:
            await scanning_msg.edit_text(format_no_signal(), parse_mode=ParseMode.MARKDOWN)
            return

        top = signals[:MAX_SIGS]
        await scanning_msg.delete()

        await context.bot.send_message(
            chat_id,
            f"📊 *Market Scan Results*\n"
            f"Found *{len(signals)}* signal(s) — showing top {len(top)}\n"
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


# ── /crypto ────────────────────────────────────────────────────────────────────

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
                "❌ *No crypto data returned.*\n\n"
                "TwelveData free plan may have hit its daily limit (800 req/day).\n"
                "Try again later or check twelvedata.com.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Try normal threshold first; force-generate if nothing qualifies
        signals = []
        for pair, tfs in data_map.items():
            sig = analyze_pair(pair, tfs, balance)
            if sig:
                signals.append(sig)

        if not signals:
            for pair, tfs in data_map.items():
                sig = force_analyze_pair(pair, tfs, balance)
                if sig:
                    signals.append(sig)

        signals.sort(key=lambda s: s.score, reverse=True)
        top = signals[:3]

        if not top:
            await scanning_msg.edit_text(
                "❌ No signals generated.\n\nCheck your API key.",
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
                chat_id, format_signal(sig, i, len(top)),
                parse_mode=ParseMode.MARKDOWN,
            )

    except Exception as e:
        logger.error(f"crypto_command error: {e}", exc_info=True)
        await scanning_msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ── /setbalance conversation ────────────────────────────────────────────────────

async def _setbalance_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    current = get_balance(chat_id)
    cur_txt = f"\n_Current: ${current:,.2f}_" if current else ""
    await update.message.reply_text(
        f"💰 *Set Your Account Balance (USD)*{cur_txt}\n\n"
        "Type your balance e.g. `500` or `20`\n"
        "_/cancel to keep current_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_BAL


async def _setbalance_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    text = update.message.text.strip().replace(",", "").replace("$", "")
    try:
        balance = float(text)
    except ValueError:
        await update.message.reply_text(
            "❌ Numbers only e.g. `20`\n\nTry again:", parse_mode=ParseMode.MARKDOWN
        )
        return ASK_BAL

    if balance < 1:
        await update.message.reply_text(
            "❌ Minimum $1.\n\nTry again:", parse_mode=ParseMode.MARKDOWN
        )
        return ASK_BAL

    set_balance(chat_id, balance)
    risk = balance * 0.01
    await update.message.reply_text(
        f"✅ *Balance saved: ${balance:,.2f}*\n\n"
        f"• Risk per trade: `${risk:,.2f}` (1%)\n\n"
        f"Use /crypto for live signals now!",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def _setbalance_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("↩️ Cancelled.")
    return ConversationHandler.END


def build_setbalance_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setbalance", _setbalance_start)],
        states={ASK_BAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, _setbalance_receive)]},
        fallbacks=[CommandHandler("cancel", _setbalance_cancel)],
    )


# ── /help ──────────────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help*\n\n"
        "• /signal — full scan (weekdays)\n"
        "• /crypto — crypto signals 24/7\n"
        "• /setbalance — set balance for lot sizing\n"
        "• /status — session info\n\n"
        "*Each signal shows:*\n"
        "✅ 3 timeframes (15M / 1H / 4H)\n"
        "✅ Per-TF direction, entry, SL, TP, lot size\n"
        "✅ RSI, Stochastic, MACD, ADX values\n"
        "✅ Overall confidence score (0–10)\n\n"
        "*Score guide:* 5–6 = ok · 7–8 = good · 9–10 = strong",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /status ────────────────────────────────────────────────────────────────────

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    session_name, is_active = get_current_session()
    bal_text = f"${balance:,.2f}" if balance else "Not set"

    await update.message.reply_text(
        format_status(session_name, is_active, minutes_to_next_scan(), bal_text),
        parse_mode=ParseMode.MARKDOWN,
)
