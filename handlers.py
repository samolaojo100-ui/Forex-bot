import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, filters,
)
from telegram.constants import ParseMode
from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs
from formatter import format_signal, format_no_signal, format_scanning, format_status
from session_manager import get_current_session, minutes_to_next_scan, is_weekend
from user_settings import get_balance, set_balance
from demo import generate_demo_signals, format_demo_signal
from config import ALL_PAIRS, CRYPTO_PAIRS

logger      = logging.getLogger(__name__)
MAX_SIGNALS = 5
ASK_BALANCE = 1


# ── /start ────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id  = update.effective_chat.id
    balance  = get_balance(chat_id)
    bal_line = f"💰 Balance: *${balance:,.2f}*" if balance else "💰 Balance: _not set — use /setbalance_"
    await update.message.reply_text(
        "🤖 *Forex & Crypto Signal Bot*\n\n"
        f"{bal_line}\n\n"
        "📌 *Commands:*\n"
        "/signal     — full scan forex + crypto\n"
        "/crypto     — crypto only *(works 24/7 ✅)*\n"
        "/demo       — preview sample signals\n"
        "/setbalance — set your account balance\n"
        "/status     — session info\n"
        "/help       — full guide\n\n"
        "✅ 47 Forex + 12 Crypto pairs\n"
        "✅ BTC · ETH · SOL · XRP · BNB · ADA + more\n"
        "✅ 3 timeframes · 7 indicators · Auto-signals",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /crypto ───────────────────────────────────────────────
async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    if balance is None:
        await update.message.reply_text(
            "⚠️ *No balance set.*\n\nUse /setbalance first, then /crypto.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    scanning_msg = await update.message.reply_text(
        format_scanning(crypto_only=True), parse_mode=ParseMode.MARKDOWN
    )
    try:
        data_map = await fetch_multiple_pairs(CRYPTO_PAIRS)
        signals  = scan_all_pairs(data_map, account_balance=balance, crypto_only=True)

        if not signals:
            await scanning_msg.edit_text(
                "🔍 *Crypto Scan Complete*\n\n"
                "No signals right now — market consolidating.\n\n"
                "📌 _Try /demo to see signal format_\n"
                "⏳ _Auto-scan retries in 30 min_",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        top = signals[:MAX_SIGNALS]
        await scanning_msg.delete()
        await context.bot.send_message(
            chat_id,
            f"₿ *Crypto Signal Results*\n"
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
        logger.error(f"crypto_command error: {e}", exc_info=True)
        await scanning_msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ── /signal ───────────────────────────────────────────────
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
            "Crypto runs 24/7 — try now:\n\n"
            "👉 /crypto — live BTC, ETH, SOL signals\n"
            "👉 /demo   — preview signal format\n\n"
            "📅 Forex resumes *Sunday 10 PM GMT+1*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    scanning_msg = await update.message.reply_text(
        format_scanning(), parse_mode=ParseMode.MARKDOWN
    )
    try:
        data_map = await fetch_multiple_pairs(ALL_PAIRS)
        signals  = scan_all_pairs(data_map, account_balance=balance)
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


# ── /demo ─────────────────────────────────────────────────
async def demo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "🎯 *Demo Mode — Sample Signals*\n\n"
        "Exact format of live signals including crypto.\n"
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
        "₿ /crypto → live BTC/ETH signals *right now*\n"
        "💱 /signal → forex signals on weekdays",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /setbalance conversation ──────────────────────────────
async def setbalance_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    current = get_balance(chat_id)
    current_text = f"\n_Current: ${current:,.2f}_" if current else ""
    await update.message.reply_text(
        f"💰 *Set Your Account Balance (USD)*{current_text}\n\n"
        "Enter your balance, e.g. `500` or `10000`\n"
        "Lot sizes calculated at *1% risk per trade*.\n\n"
        "_Send /cancel to keep current setting._",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_BALANCE


async def setbalance_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    text    = update.message.text.strip().replace(",", "").replace("$", "")
    try:
        balance = float(text)
    except ValueError:
        await update.message.reply_text(
            "❌ Numbers only, e.g. `1000`\n\nTry again:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_BALANCE
    if balance < 10:
        await update.message.reply_text("❌ Minimum $10.\n\nTry again:", parse_mode=ParseMode.MARKDOWN)
        return ASK_BALANCE
    if balance > 10_000_000:
        await update.message.reply_text("❌ Too large.\n\nTry again:", parse_mode=ParseMode.MARKDOWN)
        return ASK_BALANCE

    set_balance(chat_id, balance)
    risk = balance * 0.01
    lot  = max(0.01, round(risk / (30 * 10), 2))
    await update.message.reply_text(
        f"✅ *Balance saved: ${balance:,.2f}*\n\n"
        f"📊 *Risk preview (1%):*\n"
        f"• Risk per trade: `${risk:,.2f}`\n"
        f"• Example 30-pip SL → `{lot}` lots\n\n"
        f"Use /crypto for live signals right now!",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def setbalance_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("↩️ Cancelled. Balance unchanged.")
    return ConversationHandler.END


def build_setbalance_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setbalance", setbalance_start)],
        states={ASK_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbalance_receive)]},
        fallbacks=[CommandHandler("cancel", setbalance_cancel)],
    )


# ── /help ─────────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help — Forex & Crypto Signal Bot*\n\n"
        "*Commands:*\n"
        "• /signal     — full scan (weekdays)\n"
        "• /crypto     — crypto only (24/7)\n"
        "• /demo       — sample signal preview\n"
        "• /setbalance — set account balance\n"
        "• /status     — session & bot info\n\n"
        "*Pairs covered:*\n"
        "💱 47 Forex (majors, minors, exotics)\n"
        "₿ 12 Crypto: BTC ETH BNB SOL XRP ADA\n"
        "   AVAX DOGE MATIC DOT LTC LINK\n\n"
        "*Signal logic:*\n"
        "✅ All 3 TFs (15m/1h/4h) must agree\n"
        "✅ 7 indicators scored per timeframe\n"
        "✅ ATR-based SL · 1:2 RR minimum\n"
        "✅ Auto lot sizing at 1% account risk\n"
        "✅ Auto-signals every 30 min in sessions",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /status ───────────────────────────────────────────────
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    session_name, is_active = get_current_session()
    bal_text = f"${balance:,.2f}" if balance else "Not set — use /setbalance"
    await update.message.reply_text(
        format_status(session_name, is_active, minutes_to_next_scan(), bal_text),
        parse_mode=ParseMode.MARKDOWN,
    )
