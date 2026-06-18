import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, filters,
)
from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs, analyze_pair, force_analyze_pair
from formatter import format_signal, format_no_signal, format_scanning, format_status
from session_manager import get_current_session, minutes_to_next_scan, is_weekend
from user_settings import get_balance, set_balance
from demo import generate_demo_signals, format_demo_signal
from config import ALL_PAIRS, CRYPTO_PAIRS
from indicators import compute_indicators

logger = logging.getLogger(__name__)

MAX_SIGNALS = 5
ASK_BALANCE = 1


async def safe_send(bot, chat_id, text):
    """Send a message as plain text, splitting if over 4000 chars."""
    try:
        if len(text) > 4000:
            # Split into chunks
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for chunk in chunks:
                await bot.send_message(chat_id, chunk)
        else:
            await bot.send_message(chat_id, text)
    except Exception as e:
        logger.error(f"safe_send error: {e}")
        try:
            await bot.send_message(chat_id, f"Error sending signal: {e}")
        except Exception:
            pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    bal_line = f"Balance: ${balance:,.2f}" if balance else "Balance: not set -- use /setbalance"

    await safe_send(
        context.bot, chat_id,
        "🤖 Forex & Crypto Signal Bot\n\n"
        f"{bal_line}\n\n"
        "Commands:\n"
        "/signal -- full forex + crypto scan\n"
        "/crypto -- crypto only (24/7)\n"
        "/demo -- preview signal format\n"
        "/setbalance -- set your balance\n"
        "/status -- session info\n"
        "/help -- full guide\n\n"
        "✅ 47 Forex + 12 Crypto pairs\n"
        "✅ 5 timeframes, 5 indicators each\n"
        "✅ Auto-signals every 30 min"
    )


async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)

    if balance is None:
        await safe_send(
            context.bot, chat_id,
            "⚠️ No balance set.\n\nUse /setbalance first."
        )
        return

    scanning_msg = await update.message.reply_text(
        format_scanning(crypto_only=True)
    )

    try:
        data_map = await fetch_multiple_pairs(CRYPTO_PAIRS)

        if not data_map:
            await scanning_msg.edit_text(
                "❌ Could not fetch market data.\n\n"
                "Check your TwelveData API key in Railway variables."
            )
            return

        all_signals = []
        for pair, tfs in data_map.items():
            try:
                sig = analyze_pair(pair, tfs, balance)
                if sig:
                    all_signals.append(sig)
                else:
                    sig = force_analyze_pair(pair, tfs, balance)
                    if sig:
                        all_signals.append(sig)
            except Exception as e:
                logger.warning(f"{pair} error: {e}")

        all_signals.sort(key=lambda s: s.score, reverse=True)
        top = all_signals[:3]

        if not top:
            await scanning_msg.edit_text(
                "❌ No data returned from API.\n\n"
                "Your TwelveData free plan may have hit its daily limit (800 req/day).\n\n"
                "Try again tomorrow or check twelvedata.com"
            )
            return

        await scanning_msg.delete()

        header = (
            f"Crypto Scan Results\n"
            f"Scanned {len(data_map)} pairs -- top {len(top)} shown\n"
            f"Balance: ${balance:,.2f} | Risk: 1%\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await safe_send(context.bot, chat_id, header)

        for i, sig in enumerate(top, 1):
            msg = format_signal(sig, i, len(top))
            await safe_send(context.bot, chat_id, msg)

    except Exception as e:
        logger.error(f"crypto_command error: {e}", exc_info=True)
        try:
            await scanning_msg.edit_text(f"❌ Error: {e}")
        except Exception:
            await safe_send(context.bot, chat_id, f"❌ Error: {e}")


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)

    if balance is None:
        await safe_send(
            context.bot, chat_id,
            "⚠️ No balance set.\n\nUse /setbalance first."
        )
        return

    if is_weekend():
        await safe_send(
            context.bot, chat_id,
            "📅 Forex market closed (Weekend)\n\n"
            "Use /crypto for live BTC/ETH signals now\n"
            "Forex resumes Sunday 10 PM GMT+1"
        )
        return

    scanning_msg = await update.message.reply_text(
        format_scanning()
    )

    try:
        data_map = await fetch_multiple_pairs(ALL_PAIRS)
        signals = scan_all_pairs(data_map, account_balance=balance)

        if not signals:
            await scanning_msg.edit_text(format_no_signal())
            return

        top = signals[:MAX_SIGNALS]

        await scanning_msg.delete()

        header = (
            f"📊 Market Scan Results\n"
            f"Found {len(signals)} signal(s) -- top {len(top)}\n"
            f"Balance: ${balance:,.2f} | Risk: 1%\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await safe_send(context.bot, chat_id, header)

        for i, sig in enumerate(top, 1):
            msg = format_signal(sig, i, len(top))
            await safe_send(context.bot, chat_id, msg)

    except Exception as e:
        logger.error(f"signal_command error: {e}", exc_info=True)
        try:
            await scanning_msg.edit_text(f"❌ Error: {e}")
        except Exception:
            await safe_send(context.bot, chat_id, f"❌ Error: {e}")


async def demo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    await safe_send(
        context.bot, chat_id,
        "🎯 Demo Mode -- Sample Signals\n\n"
        "Exact format of live signals.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━"
    )

    signals = generate_demo_signals()
    for i, sig in enumerate(signals, 1):
        msg = format_demo_signal(sig, i, len(signals))
        await safe_send(context.bot, chat_id, msg)

    await safe_send(
        context.bot, chat_id,
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Live signals look exactly like this\n\n"
        "/crypto -- live signals right now\n"
        "/signal -- forex on weekdays"
    )


async def setbalance_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    current = get_balance(chat_id)
    cur_txt = f"\nCurrent: ${current:,.2f}" if current else ""

    await safe_send(
        context.bot, chat_id,
        f"💰 Set Your Account Balance (USD){cur_txt}\n\n"
        "Type your balance e.g. 500 or 20\n"
        "/cancel to keep current"
    )
    return ASK_BALANCE


async def setbalance_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    text = update.message.text.strip().replace(",", "").replace("$", "")

    try:
        balance = float(text)
    except ValueError:
        await safe_send(context.bot, chat_id, "❌ Numbers only e.g. 20\n\nTry again:")
        return ASK_BALANCE

    if balance < 1:
        await safe_send(context.bot, chat_id, "❌ Minimum $1.\n\nTry again:")
        return ASK_BALANCE

    set_balance(chat_id, balance)
    risk = balance * 0.01

    await safe_send(
        context.bot, chat_id,
        f"✅ Balance saved: ${balance:,.2f}\n\n"
        f"Risk per trade: ${risk:,.2f} (1%)\n\n"
        f"Use /crypto for live signals now!"
    )
    return ConversationHandler.END


async def setbalance_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await safe_send(context.bot, update.effective_chat.id, "↩️ Cancelled.")
    return ConversationHandler.END


def build_setbalance_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setbalance", setbalance_start)],
        states={ASK_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbalance_receive)]},
        fallbacks=[CommandHandler("cancel", setbalance_cancel)],
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_send(
        context.bot, update.effective_chat.id,
        "📖 Help\n\n"
        "/signal -- full scan (weekdays)\n"
        "/crypto -- crypto 24/7\n"
        "/demo -- sample signals\n"
        "/setbalance -- set balance\n"
        "/status -- session info\n\n"
        "Signal format shows:\n"
        "✅ 5 timeframes (5M/15M/1H/4H/Daily)\n"
        "✅ Per-TF direction, entry, SL, TP, lot\n"
        "✅ RSI, Stochastic, MACD values\n"
        "✅ Overall confidence and pair score"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    session_name, is_active = get_current_session()
    bal_text = f"${balance:,.2f}" if balance else "Not set"

    await safe_send(
        context.bot, chat_id,
        format_status(session_name, is_active, minutes_to_next_scan(), bal_text)
    )
