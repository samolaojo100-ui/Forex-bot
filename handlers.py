import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode
from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs, is_crypto
from formatter import format_signal, format_no_signal, format_scanning, format_status
from session_manager import get_current_session, minutes_to_next_scan, is_weekend
from user_settings import get_balance, set_balance
from demo import generate_demo_signals, format_demo_signal
from config import ALL_PAIRS, CRYPTO_PAIRS, FOREX_PAIRS

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
        "/signal  — scan forex + crypto (weekdays)\n"
        "/crypto  — scan crypto only (24/7 ✅)\n"
        "/demo    — preview sample signals\n"
        "/setbalance — set your balance\n"
        "/status  — session info\n"
        "/help    — full guide\n\n"
        "✅ 47 Forex pairs + 12 Crypto pairs\n"
        "✅ BTC, ETH, SOL, XRP, BNB + more\n"
        "✅ 3 timeframes · 7 indicators · Auto-signals",
        parse_mode=ParseMode.MARKDOWN,
    )


async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scan crypto only — works 24/7 including weekends."""
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
        signals  = scan_all_pairs(data_map, account_balance=balance, crypto_only=True)

        if not signals:
            await scanning_msg.edit_text(
                "🔍 *Crypto Scan Complete*\n\n"
                "No high-confidence crypto signals right now.\n"
                "Market may be consolidating — try again in 30 min.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        top = signals[:MAX_SIGNALS]
        await scanning_msg.delete()
        header = (
            f"₿ *Crypto Signal Results*\n"
            f"Found *{len(signals)}* signal(s) — showing top {len(top)}\n"
            f"💰 Balance: `${balance:,.2f}` · Risk: `1%` per trade\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await context.bot.send_message(chat_id, header, parse_mode=ParseMode.MARKDOWN)
        for i, sig in enumerate(top, 1):
            await context.bot.send_message(chat_id, format_signal(sig, i, len(top)), parse_mode=ParseMode.MARKDOWN)
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
            "📅 *Forex market is closed (Weekend)*\n\n"
            "But crypto runs 24/7! Try:\n\n"
            "👉 /crypto — scan BTC, ETH, SOL & more *right now*\n"
            "👉 /demo   — preview signal format\n\n"
            "📅 Forex resumes *Sunday 10 PM GMT+1*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    scanning_msg = await update.message.reply_text(format_scanning(), parse_mode=ParseMode.MARKDOWN)
    try:
        data_map = await fetch_multiple_pairs(ALL_PAIRS)
        signals  = scan_all_pairs(data_map, account_balance=balance)
        if not signals:
            await scanning_msg.edit_text(format_no_signal(), parse_mode=ParseMode.MARKDOWN)
            return
        top = signals[:MAX_SIGNALS]
        await scanning_msg.delete()
        header = (
            f"📊 *Market Scan Results*\n"
            f"Found *{len(signals)}* signal(s) — showing top {len(top)}\n"
            f"💰 Balance: `${balance:,.2f}` · Risk: `1%` per trade\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await context.bot.send_message(chat_id, header, parse_mode=ParseMode.MARKDOWN)
        for i, sig in enumerate(top, 1):
            await context.bot.send_message(chat_id, format_signal(sig, i, len(top)), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"signal_command error: {e}", exc_info=True)
        await scanning_msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def demo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "🎯 *Demo Mode — Sample Signals*\n\n"
        "Exactly how live signals look.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━",
        parse_mode=ParseMode.MARKDOWN,
    )
    signals = generate_demo_signals()
    for i, sig in enumerate(signals, 1):
        await context.bot.send_message(chat_id, format_demo_signal(sig, i, len(signals)), parse_mode=ParseMode.MARKDOWN)
    await context.bot.send_message(
        chat_id,
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ *This is the exact live signal format*\n\n"
        "₿ Use /crypto right now for *live* BTC/ETH signals\n"
        "💱 Use /signal on weekdays for forex signals",
        parse_mode=ParseMode.MARKDOWN,
    )


async def setbalance_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    current = get_balance(chat_id)
    current_text = f"\n_Current: ${current:,.2f}_" if current else ""
    await update.message.reply_text(
        f"💰 *Set Your Account Balance (USD)*{current_text}\n\n"
        "Type your balance, e.g. `500` or `10000`\n"
        "Used to calculate lot sizes at 1% risk per trade.\n\n"
        "_/cancel to keep current setting_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_BALANCE


async def setbalance_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    text    = update.message.text.strip().replace(",", "").replace("$", "")
    try:
        balance = float(text)
    except ValueError:
        await update.message.reply_text("❌ Enter a number only, e.g. `1000`\n\nTry again:", parse_mode=ParseMode.MARKDOWN)
        return ASK_BALANCE
    if balance < 10:
        await update.message.reply_text("❌ Minimum $10.\n\nTry again:", parse_mode=ParseMode.MARKDOWN)
        return ASK_BALANCE
    set_balance(chat_id, balance)
    risk = balance * 0.01
    await update.message.reply_text(
        f"✅ *Balance saved: ${balance:,.2f}*\n\n"
        f"• Risk per trade: `${risk:,.2f}` (1%)\n\n"
        f"Use /crypto for live signals right now!\n"
        f"Use /signal on weekdays for forex signals.",
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
        "📖 *Help — Forex & Crypto Signal Bot*\n\n"
        "*Commands:*\n"
        "• /signal     — full scan forex + crypto\n"
        "• /crypto     — crypto only (24/7, works now!)\n"
        "• /demo       — sample signal preview\n"
        "• /setbalance — set your account balance\n"
        "• /status     — session info\n\n"
        "*Assets covered:*\n"
        "💱 47 Forex pairs (majors, minors, exotics)\n"
        "₿ 12 Crypto: BTC ETH BNB SOL XRP ADA\n"
        "         AVAX DOGE MATIC DOT LTC LINK\n\n"
        "*Signal logic:*\n"
        "✅ All 3 TFs (15m/1h/4h) must agree\n"
        "✅ Score ≥ 6/10 from 7 indicators\n"
        "✅ ATR-based SL, 1:2 RR minimum\n"
        "✅ 1% risk lot sizing",
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
