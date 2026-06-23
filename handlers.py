import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
from user_settings import (
    get_balance, set_balance, is_authorized,
    approve_user, revoke_user, list_approved_users,
    add_pending, remove_pending, next_pending, list_pending,
)
from config import ALL_PAIRS, CRYPTO_PAIRS, OWNER_USERNAME, OWNER_CHAT_ID
from news_filter import get_upcoming_events
from stocks_engine import fetch_stock_pairs, STOCK_PAIRS

logger  = logging.getLogger(__name__)
ASK_BAL = 1

MIN_CONFIDENCE_TO_SHOW = 70


def filter_by_confidence(signals: list, min_confidence: int = MIN_CONFIDENCE_TO_SHOW) -> list:
    return [s for s in signals if s.confidence >= min_confidence]


# ── ACCESS CONTROL ────────────────────────────────────────────────────────────

async def require_authorized(update: Update) -> bool:
    """
    Returns True if sender is authorized.
    If not: tells them to wait, saves them to pending queue,
    and pings the owner with Approve / Reject buttons.
    """
    user    = update.effective_user
    chat_id = update.effective_chat.id

    if is_authorized(chat_id):
        return True

    # Save to pending queue
    add_pending(chat_id, user.full_name, user.username or "none")

    # Tell the user to wait
    await update.message.reply_text(
        "🔒 *Access Pending Approval*\n\n"
        "Your request has been sent to the owner.\n\n"
        f"👤 You can also message: @{OWNER_USERNAME}\n\n"
        f"_Your Chat ID:_ `{chat_id}`\n\n"
        "✅ You will be notified once approved.",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Notify owner with inline buttons
    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{chat_id}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"cancel_{chat_id}"),
    ]]
    try:
        await update.get_bot().send_message(
            chat_id=OWNER_CHAT_ID,
            text=(
                "🔔 *New Access Request*\n\n"
                f"👤 Name: {user.full_name}\n"
                f"🆔 Chat ID: `{chat_id}`\n"
                f"📛 Username: @{user.username or 'none'}\n\n"
                "Tap to approve or reject:"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.warning(f"Could not notify owner: {e}")

    return False


async def handle_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner taps ✅ Approve or ❌ Reject on the notification message."""
    query = update.callback_query
    await query.answer()

    # Only owner can use these buttons
    if str(query.from_user.id) != str(OWNER_CHAT_ID):
        await query.answer("🔒 Only the bot owner can do this.", show_alert=True)
        return

    action, user_id_str = query.data.split("_", 1)
    target_id = int(user_id_str)

    if action == "approve":
        approve_user(target_id)
        await query.edit_message_text(
            f"✅ *Approved!*\n\nChat ID `{target_id}` can now use the bot.",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    "🎉 *Access Approved!*\n\n"
                    "Welcome to *TrendGuard AI* 🚀\n\n"
                    "You now have full access to live trading signals.\n"
                    "Type /start to begin."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.warning(f"Could not notify approved user {target_id}: {e}")

    elif action == "cancel":
        remove_pending(target_id)
        await query.edit_message_text(
            f"❌ *Rejected.*\n\nChat ID `{target_id}` has been denied.",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    "❌ *Access Denied*\n\n"
                    "Your request was not approved.\n"
                    f"Contact @{OWNER_USERNAME} if you think this is a mistake."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.warning(f"Could not notify rejected user {target_id}: {e}")


# ── COMMANDS ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_authorized(update):
        return

    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    bal_line = f"💰 Balance: *${balance:,.2f}*" if balance else "💰 _Balance not set — use /setbalance_"

    await update.message.reply_text(
        "🤖 *TrendGuard AI*\n\n"
        f"{bal_line}\n\n"
        "📌 *Commands:*\n"
        "/signal — full scan (forex + gold + crypto)\n"
        "/crypto — crypto only (24/7)\n"
        "/stocks — US stocks scan (weekdays)\n"
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
    if not await require_authorized(update):
        return

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
                chat_id, format_signal(sig, i, len(top)),
                parse_mode=ParseMode.MARKDOWN,
            )

    except Exception as e:
        logger.error(f"signal_command error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_authorized(update):
        return

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
                chat_id, format_signal(sig, i, len(top)),
                parse_mode=ParseMode.MARKDOWN,
            )

    except Exception as e:
        logger.error(f"crypto_command error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def stocks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_authorized(update):
        return

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
            "📅 *NYSE closed (Weekend)*\n\n"
            "Stock markets are closed on weekends.\n"
            "Use /crypto for 24/7 signals.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = await update.message.reply_text(
        "📈 *Scanning US Stocks...*\n\n"
        "🔍 AAPL · TSLA · NVDA · AMZN · MSFT\n"
        "META · GOOGL · AMD · NFLX · JPM\n\n"
        "⏳ _Please wait..._",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        data_map = await fetch_stock_pairs(STOCK_PAIRS)

        if not data_map:
            await msg.edit_text(
                "❌ Could not fetch stock data.\n\n"
                "API limit may be reached or NYSE is closed.\n"
                "Try during market hours (9:30AM–4PM EST, Mon–Fri).",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        signals = await scan_pairs(data_map, balance)
        signals = filter_by_confidence(signals)

        if not signals:
            await msg.edit_text(
                "⏸ *No Stock Signals Right Now*\n\n"
                "No setups met the ≥70% confidence threshold.\n"
                "_Market may be consolidating._\n\nTry again in 30 minutes.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        top = signals[:3]
        await msg.delete()

        await context.bot.send_message(
            chat_id,
            f"📈 *TrendGuard AI — Stocks Scan*\n"
            f"Scanned *{len(data_map)}* stocks — *{len(signals)}* ≥{MIN_CONFIDENCE_TO_SHOW}% — top {len(top)} shown\n"
            f"💰 Balance: `${balance:,.2f}` · Risk: `1%`",
            parse_mode=ParseMode.MARKDOWN,
        )
        for i, sig in enumerate(top, 1):
            await context.bot.send_message(
                chat_id, format_signal(sig, i, len(top)),
                parse_mode=ParseMode.MARKDOWN,
            )

    except Exception as e:
        logger.error(f"stocks_command error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Owner-only.

    /approve          → shows next pending user with Approve / Reject buttons
    /approve <id>     → directly approves that chat ID
    /approve list     → shows all pending + approved users
    """
    chat_id = update.effective_chat.id

    if str(chat_id) != str(OWNER_CHAT_ID):
        await update.message.reply_text("🔒 Only the bot owner can use this.")
        return

    args = context.args

    # ── /approve list ──────────────────────────────────────────
    if args and args[0].lower() == "list":
        pending  = list_pending()
        approved = list_approved_users()

        p_text = "\n".join(
            f"• `{p['id']}` — {p['name']} (@{p['username']})"
            for p in pending
        ) if pending else "_none_"

        a_text = "\n".join(f"• `{c}`" for c in approved) if approved else "_none_"

        await update.message.reply_text(
            f"📋 *Pending ({len(pending)}):*\n{p_text}\n\n"
            f"✅ *Approved ({len(approved)}):*\n{a_text}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── /approve <chat_id> ─────────────────────────────────────
    if args:
        target_id = args[0].strip()
        try:
            approve_user(int(target_id))
        except ValueError:
            await update.message.reply_text("❌ Chat ID must be a number.")
            return

        await update.message.reply_text(
            f"✅ Approved `{target_id}` — they can now use the bot.",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            await context.bot.send_message(
                chat_id=int(target_id),
                text=(
                    "🎉 *Access Approved!*\n\n"
                    "Welcome to *TrendGuard AI* 🚀\n\n"
                    "You now have full access to live trading signals.\n"
                    "Type /start to begin."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.warning(f"Could not notify approved user: {e}")
        return

    # ── /approve (no args) → show next pending with buttons ────
    pending = next_pending()

    if not pending:
        approved = list_approved_users()
        a_text = "\n".join(f"• `{c}`" for c in approved) if approved else "_none yet_"
        await update.message.reply_text(
            "✅ *No pending requests.*\n\n"
            f"*Approved users:*\n{a_text}\n\n"
            "_Tip: /approve list — see everyone_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{pending['id']}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"cancel_{pending['id']}"),
    ]]

    total = len(list_pending())
    await update.message.reply_text(
        f"🔔 *Pending Request* ({total} waiting)\n\n"
        f"👤 Name: {pending['name']}\n"
        f"🆔 Chat ID: `{pending['id']}`\n"
        f"📛 Username: @{pending['username']}\n\n"
        "Approve or reject?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def setbalance_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await require_authorized(update):
        return ConversationHandler.END

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
        f"Use /signal, /crypto or /stocks for live signals!",
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
    if not await require_authorized(update):
        return

    await update.message.reply_text(
        "📖 *TrendGuard AI — Help*\n\n"
        "*Commands:*\n"
        "• /signal — scan all pairs (weekdays)\n"
        "• /crypto — crypto only (24/7)\n"
        "• /stocks — US stocks scan (weekdays)\n"
        "• /setbalance — set your balance\n"
        "• /status — current session + news\n\n"
        "*Signal includes:*\n"
        "✅ Direction + Confidence %\n"
        "✅ 8 indicators (RSI, MACD, Stoch, BB, ATR, ADX, CCI, Williams)\n"
        "✅ TP1, TP2, TP3 + Partial TP + Invalidation\n"
        "✅ Market Regime + Session quality\n"
        "✅ News filter (blocks FOMC, NFP etc)\n"
        "✅ Daily trend gate\n"
        f"✅ Only shown if confidence ≥ {MIN_CONFIDENCE_TO_SHOW}%\n\n"
        "*Forex/Gold pairs:*\n"
        "EUR/USD · GBP/USD · USD/JPY · USD/CHF\n"
        "AUD/USD · USD/CAD · XAU/USD (Gold)\n\n"
        "*Crypto pairs:*\n"
        "BTC · ETH · BNB · SOL\n\n"
        "*US Stocks:*\n"
        "AAPL · TSLA · NVDA · AMZN · MSFT\n"
        "META · GOOGL · AMD · NFLX · JPM",
        parse_mode=ParseMode.MARKDOWN,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_authorized(update):
        return

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
