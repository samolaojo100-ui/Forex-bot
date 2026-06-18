import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, filters,
)
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs, analyze_pair, overall_direction
from formatter import format_signal, format_no_signal, format_scanning, format_status
from session_manager import get_current_session, minutes_to_next_scan, is_weekend
from user_settings import get_balance, set_balance
from config import ALL_PAIRS, CRYPTO_PAIRS
from indicators import compute_indicators
import scan_lock

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

    acquired, wait_secs = scan_lock.try_acquire("crypto")
    if not acquired:
        await update.message.reply_text(
            f"⏳ *A scan is already running.*\n\n"
            f"It will auto-clear in ~{wait_secs}s if stuck.\n"
            f"Or use /unstuck to force-clear it now.",
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
                "❌ Could not fetch market data.\n\nCheck your TwelveData API key in Railway variables.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Force analyze ALL pairs — return best ones regardless of score
        all_signals = []
        for pair, tfs in data_map.items():
            try:
                processed = {tf: compute_indicators(df) for tf, df in tfs.items()}
                from signal_engine import analyze_pair
                sig = analyze_pair(pair, tfs, balance)
                if sig:
                    all_signals.append(sig)
                else:
                    # Force a signal even if score is low
                    from signal_engine import force_analyze_pair
                    sig = force_analyze_pair(pair, tfs, balance)
                    if sig:
                        all_signals.append(sig)
            except Exception as e:
                logger.warning(f"{pair} error: {e}")

        all_signals.sort(key=lambda s: s.score, reverse=True)
        top = all_signals[:3]

        if not top:
            await scanning_msg.edit_text(
                "❌ No data returned from API.\n\nYour TwelveData free plan may have hit its daily limit (800 req/day).\n\nTry again tomorrow or check twelvedata.com",
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
    finally:
        scan_lock.release()


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

    acquired, wait_secs = scan_lock.try_acquire("signal")
    if not acquired:
        await update.message.reply_text(
            f"⏳ *A scan is already running.*\n\n"
            f"It will auto-clear in ~{wait_secs}s if stuck.\n"
            f"Or use /unstuck to force-clear it now.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    scanning_msg = await update.message.reply_text(
        format_scanning(), parse_mode=ParseMode.MARKDOWN
    )
    try:
        data_map = await fetch_multiple_pairs(ALL_PAIRS)
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
    finally:
        scan_lock.release()


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


async def unstuck_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual escape hatch — force-clears the scan lock from inside Telegram,
    no Railway access needed."""
    running, elapsed, label = scan_lock.status()
    scan_lock.release()
    if running:
        await update.message.reply_text(
            f"🔓 *Cleared a stuck '{label}' scan*\n\n"
            f"It had been running for {elapsed}s. Try /signal or /crypto again now.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            "✅ *Nothing was stuck.* No scan was running.",
            parse_mode=ParseMode.MARKDOWN,
        )
