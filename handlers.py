import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode
from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs
from formatter import format_signal, format_no_signal, format_scanning, format_status
from session_manager import get_current_session, minutes_to_next_scan
from user_settings import get_balance, set_balance, clear_balance
from config import ALL_PAIRS

logger = logging.getLogger(__name__)

MAX_SIGNALS_PER_REQUEST = 5

# ConversationHandler states
ASK_BALANCE = 1


# ─────────────────────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id  = update.effective_chat.id
    balance  = get_balance(chat_id)
    bal_line = f"💰 Your balance: *${balance:,.2f}*" if balance else "💰 Balance: _not set — use /setbalance_"

    await update.message.reply_text(
        "🤖 *Forex Signal Bot*\n\n"
        "Professional multi-timeframe signals with real risk management.\n\n"
        f"{bal_line}\n\n"
        "📌 *Commands:*\n"
        "/signal      — scan market & get top signals\n"
        "/setbalance  — set your account balance\n"
        "/status      — session & bot status\n"
        "/help        — full explanation\n\n"
        "✅ 47 pairs · 3 timeframes · 7 indicators\n"
        "✅ Auto-signals during London & New York sessions",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────────────────────────────────────────────────
#  /setbalance conversation
# ─────────────────────────────────────────────────────────────
async def setbalance_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point — ask the user for their balance."""
    chat_id = update.effective_chat.id
    current = get_balance(chat_id)
    current_text = f"\n\n_Current balance: ${current:,.2f}_" if current else ""

    await update.message.reply_text(
        "💰 *Set Your Account Balance*\n\n"
        "Enter your trading account balance in USD.\n"
        "This is used to calculate safe lot sizes at 1% risk per trade.\n\n"
        "📌 *Examples:*\n"
        "• Type `500` for a $500 account\n"
        "• Type `10000` for a $10,000 account\n\n"
        f"_Send /cancel to keep the current setting._{current_text}",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_BALANCE


async def setbalance_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive and validate the balance."""
    chat_id = update.effective_chat.id
    text    = update.message.text.strip().replace(",", "").replace("$", "")

    try:
        balance = float(text)
    except ValueError:
        await update.message.reply_text(
            "❌ *Invalid amount.*\n\n"
            "Please enter a number only, e.g. `1000` or `5000.50`\n\n"
            "Try again:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_BALANCE   # ask again

    if balance < 10:
        await update.message.reply_text(
            "❌ Balance must be at least $10.\n\nTry again:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_BALANCE

    if balance > 10_000_000:
        await update.message.reply_text(
            "❌ Balance seems unrealistically large.\n\nTry again:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_BALANCE

    set_balance(chat_id, balance)

    # Show what 1% risk looks like
    risk_amount = balance * 0.01
    example_sl  = 30   # pips
    pip_val     = 10   # USD per pip (standard lot)
    example_lot = round(risk_amount / (example_sl * pip_val), 2)

    await update.message.reply_text(
        f"✅ *Balance saved: ${balance:,.2f}*\n\n"
        f"📊 *Risk calculation preview:*\n"
        f"• Risk per trade (1%): `${risk_amount:,.2f}`\n"
        f"• Example: 30-pip SL → lot size ≈ `{example_lot}` lots\n\n"
        f"_Use /signal to get your first signals!_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def setbalance_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "↩️ Cancelled. Balance unchanged.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


def build_setbalance_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setbalance", setbalance_start)],
        states={
            ASK_BALANCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, setbalance_receive)
            ],
        },
        fallbacks=[CommandHandler("cancel", setbalance_cancel)],
    )


# ─────────────────────────────────────────────────────────────
#  /signal
# ─────────────────────────────────────────────────────────────
async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)

    # If no balance set, prompt the user first
    if balance is None:
        await update.message.reply_text(
            "⚠️ *No account balance set.*\n\n"
            "Lot sizes can't be calculated without your balance.\n\n"
            "👉 Use /setbalance to set it now — takes 5 seconds!",
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

        top = signals[:MAX_SIGNALS_PER_REQUEST]
        await scanning_msg.delete()

        header = (
            f"📊 *Market Scan Results*\n"
            f"Found *{len(signals)}* signal(s) — showing top {len(top)}\n"
            f"💰 Balance: `${balance:,.2f}` · Risk: `1%` per trade\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await context.bot.send_message(chat_id, header, parse_mode=ParseMode.MARKDOWN)

        for i, sig in enumerate(top, 1):
            msg = format_signal(sig, index=i, total=len(top))
            await context.bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"signal_command error: {e}", exc_info=True)
        await scanning_msg.edit_text(
            f"❌ Error while scanning: `{e}`\n\nPlease try again.",
            parse_mode=ParseMode.MARKDOWN,
        )


# ─────────────────────────────────────────────────────────────
#  /help
# ─────────────────────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help — Forex Signal Bot*\n\n"
        "*Commands:*\n"
        "• /signal      — full market scan, top signals\n"
        "• /setbalance  — set your account balance for lot sizing\n"
        "• /status      — current session & auto-scan info\n"
        "• /cancel      — cancel any active prompt\n\n"
        "*How signals are generated:*\n"
        "1️⃣ 47 pairs scanned (majors + minors + exotics)\n"
        "2️⃣ 15m, 1h, 4h must ALL agree on direction\n"
        "3️⃣ 7 checks per timeframe — score 0–10:\n"
        "   EMA alignment · MACD · RSI · Stochastic\n"
        "   Bollinger Bands · ADX strength · Volume\n"
        "4️⃣ Only signals ≥ 6/10 average score are sent\n"
        "5️⃣ SL = ATR × 1.5 or nearest S/R (min 15 pips)\n"
        "6️⃣ TP = SL × 2 (1:2 risk/reward)\n"
        "7️⃣ Lot size = (Balance × 1%) ÷ (SL pips × pip value)\n\n"
        "*Auto-signals fire during:*\n"
        "🕐 Tokyo/London overlap: 07:00–09:00 UTC\n"
        "🕑 London/New York overlap: 12:00–16:00 UTC\n"
        "🕒 New York session: 12:00–21:00 UTC",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────────────────────────────────────────────────
#  /status
# ─────────────────────────────────────────────────────────────
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id      = update.effective_chat.id
    balance      = get_balance(chat_id)
    session_name, is_active = get_current_session()
    mins         = minutes_to_next_scan()
    bal_text     = f"${balance:,.2f}" if balance else "Not set — use /setbalance"
    await update.message.reply_text(
        format_status(session_name, is_active, mins, bal_text),
        parse_mode=ParseMode.MARKDOWN,
    )
