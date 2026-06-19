import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, filters,
)
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_pairs, force_scan_pairs
from formatter import (
    format_signal, format_no_trade, format_no_signal,
    format_scanning, format_status,
)
from session_manager import get_current_session, minutes_to_next_scan, is_weekend
from user_settings import get_balance, set_balance
from config import ALL_PAIRS, CRYPTO_PAIRS
from news_filter import get_upcoming_events

logger    = logging.getLogger(__name__)
ASK_BAL   = 1

# Minimum confidence required for a signal to actually be shown to the user.
# Applies uniformly to /signal, /crypto, and the auto-scan job — nothing below
# this bar gets sent, regardless of which path triggered the scan.
MIN_CONFIDENCE_TO_SHOW = 65


def filter_by_confidence(signals: list, min_confidence: int = MIN_CONFIDENCE_TO_SHOW) -> list:
    """Keep only signals at or above the confidence threshold."""
    return [s for s in signals if s.confidence >= min_confidence]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    bal_line = f"💰 Balance: *${balance:,.2f}*" if balance else "💰 _Balance not set — use /setbalance_"

    await update.message.reply_text(
        "🤖 *TrendGuard AI*\n\n"
        f"{bal_line}\n\n"
        "📌 *Commands:*\n"
        "/signal — full scan (forex + gold + crypto)\n"
        "/crypto — crypto only (24/7)\n"
        "/setbalance — set your trading balance\n"
        "/status — session info + upcoming news\n"
        "/help — how to use this bot\n\n"
        "✅ 8 indicators · 4 timeframes\n"
        "✅ TP1, TP2, TP3 + Invalidation\n"
        "✅ News filter + Daily trend gate\n"
        f"✅ Only shows signals ≥ {MIN_CONFIDENCE_TO_SHOW}% confidence\n"
        "✅ Auto-signals every 30 min",
        parse_mode=ParseMode.MARKDOWN,
    )


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)

    if not balance:
        await update.message.reply_text(
            "⚠️ *No balance set.*\n\nUse /setbalance first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if is_weekend():
        await update.message.reply_text(
            "📅 *Forex closed (Weekend)*\n\n"
            "Use /crypto for 24/7 crypto signals.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = await update.message.reply_text(
        format_scanning(), parse_mode=ParseMode.MARKDOWN
    )

    try:
        data_map = await fetch_multiple_pairs(ALL_PAIRS)

        if not data_map:
            await msg.edit_text(
                "❌ Could not fetch market data.\n\n"
                "Check TwelveData API key in Railway variables.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        signals = await scan_pairs(data_map, balance)
        signals = filter_by_confidence(signals)

        if not signals:
            await msg.edit_text(format_no_signal(), parse_mode=ParseMode.MARKDOWN)
            return

        top = signals[:3]
        await msg.delete()

        await context.bot.send_message(
            chat_id,
            f"📊 *TrendGuard AI — Scan Results*\n"
            f"Found *{len(signals)}* signal(s) ≥{MIN_CONFIDENCE_TO_SHOW}% — top {len(top)} shown\n"
            f"💰 Balance: `${balance:,.2f}` · Risk: `1%`",
            parse_mode=ParseMode.MARKDOWN,
        )

        for i, sig in enumerate(top, 1):
            await context.bot.send_message(
                chat_id,
                format_signal(sig, i, len(top)),
                parse_mode=ParseMode.MARKDOWN,
            )

    except Exception as e:
        logger.error(f"signal_command error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)

    if not balance:
        await update.message.reply_text(
            "⚠️ *No balance set.*\n\nUse /setbalance first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = await update.message.reply_text(
        format_scanning(crypto_only=True), parse_mode=ParseMode.MARKDOWN
    )

    try:
        data_map = await fetch_multiple_pairs(CRYPTO_PAIRS)

        if not data_map:
            await msg.edit_text(
                "❌ Could not fetch market data.\n\n"
                "TwelveData daily limit (800 req/day) may be reached.\n"
                "Try again tomorrow or check twelvedata.com",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # force_scan_pairs ignores the engine's internal gates (news/trend/S-R)
        # so crypto always produces a result — but we still apply our own
        # confidence floor here so low-quality setups don't get sent.
        signals = await force_scan_pairs(data_map, balance)
        signals = filter_by_confidence(signals)

        if not signals:
            await msg.edit_text(format_no_signal(), parse_mode=ParseMode.MARKDOWN)
            return

        top = signals[:3]
        await msg.delete()

        await context.bot.send_message(
            chat_id,
            f"₿ *TrendGuard AI — Crypto Scan*\n"
            f"Scanned *{len(data_map)}* pairs — *{len(signals)}* ≥{MIN_CONFIDENCE_TO_SHOW}% — top {len(top)} shown\n"
            f"💰 Balance: `${balance:,.2f}` · Risk: `1%`",
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
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def setbalance_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    current = get_balance(chat_id)
    cur_txt = f"\n_Current: ${current:,.2f}_" if current else ""

    await update.message.reply_text(
        f"💰 *Set Your Trading Balance (USD)*{cur_txt}\n\n"
        "Type your balance e.g. `500` or `1000`\n"
        "_/cancel to keep current_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_BAL


async def setbalance_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    text    = update.message.text.strip().replace(",", "").replace("$", "")

    try:
        balance = float(text)
    except ValueError:
        await update.message.reply_text(
            "❌ Enter a number e.g. `500`\n\nTry again:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ASK_BAL

    if balance < 1:
        await update.message.reply_text("❌ Minimum $1.\n\nTry again:", parse_mode=ParseMode.MARKDOWN)
        return ASK_BAL

    set_balance(chat_id, balance)
    risk = balance * 0.01

    await update.message.reply_text(
        f"✅ *Balance saved: ${balance:,.2f}*\n\n"
        f"Risk per trade: `${risk:,.2f}` (1%)\n\n"
        f"Use /signal or /crypto for live signals!",
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
            ASK_BAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbalance_receive)]
        },
        fallbacks=[CommandHandler("cancel", setbalance_cancel)],
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *TrendGuard AI — Help*\n\n"
        "*Commands:*\n"
        "• /signal — scan all pairs (weekdays)\n"
        "• /crypto — crypto only (24/7)\n"
        "• /setbalance — set your balance\n"
        "• /status — current session + news\n\n"
        "*Signal includes:*\n"
        "✅ Direction + Confidence %\n"
        "✅ 8 indicators (RSI, MACD, Stoch, BB, ATR, ADX, CCI, Williams)\n"
        "✅ TP1, TP2, TP3 + Partial TP + Invalidation\n"
        "✅ Market Regime + Session quality\n"
        "✅ Candle patterns\n"
        "✅ News filter (blocks FOMC, NFP etc)\n"
        "✅ Daily trend gate\n"
        f"✅ Only shown if confidence ≥ {MIN_CONFIDENCE_TO_SHOW}%\n\n"
        "*Pairs covered:*\n"
        "EUR/USD · GBP/USD · USD/JPY · USD/CHF\n"
        "AUD/USD · USD/CAD · XAU/USD (Gold)\n"
        "BTC · ETH · BNB · SOL",
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
