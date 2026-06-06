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
from access_control import (
    is_approved, is_admin, is_banned,
    approve_user, remove_user, ban_user,
    list_users, denied_message, ADMIN_ID,
)
from news_filter import fetch_news_pairs, format_news_warning
from config import ALL_PAIRS, CRYPTO_PAIRS, FOREX_PAIRS

logger   = logging.getLogger(__name__)
MAX_SIGS = 5
ASK_BAL  = 1


# ── Access check ───────────────────────────────────────────────────────────────

async def _check_access(update: Update) -> bool:
    chat_id = update.effective_chat.id
    if is_banned(chat_id):
        await update.message.reply_text("⛔ You have been banned from this bot.")
        return False
    if not is_approved(chat_id):
        await update.message.reply_text(denied_message(), parse_mode=ParseMode.MARKDOWN)
        return False
    return True


# ── /start ─────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not is_approved(chat_id):
        await update.message.reply_text(
            "👋 *Welcome to SamSignals Bot!*\n\n"
            "This is a private forex & crypto signal bot.\n\n"
            "📩 Contact *@SamSos* to request access.\n\n"
            "💰 *Plans available:*\n"
            "• Basic — FREE (Forex signals)\n"
            "• Premium — $15/month (Forex + Crypto, unlimited)",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            user = update.effective_user
            name = f"@{user.username}" if user.username else user.full_name
            await context.bot.send_message(
                ADMIN_ID,
                f"🔔 *New user tried /start*\n"
                f"Name: {name}\n"
                f"ID: `{chat_id}`\n\n"
                f"To approve: `/approve {chat_id}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        return

    balance    = get_balance(chat_id)
    bal_line   = f"💰 Balance: *${balance:,.2f}*" if balance else "💰 Balance: _not set — use /setbalance_"
    admin_line = "\n👑 *Admin:* /approve /remove /ban /members" if is_admin(chat_id) else ""

    await update.message.reply_text(
        "📊 *SamSignals Bot*\n\n"
        f"{bal_line}\n\n"
        "📌 *Commands:*\n"
        "/signal — forex + crypto scan\n"
        "/crypto — crypto only *(24/7)*\n"
        "/setbalance — set account balance\n"
        "/status — session info\n"
        "/help — guide & tips\n"
        f"{admin_line}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /signal ────────────────────────────────────────────────────────────────────

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return

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
            "Use /crypto for live crypto signals.\n"
            "Forex resumes Sunday 10 PM GMT+1.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    scanning_msg = await update.message.reply_text(
        format_scanning(), parse_mode=ParseMode.MARKDOWN
    )

    try:
        # Check news filter first
        news_pairs   = await fetch_news_pairs()
        safe_pairs   = [p for p in ALL_PAIRS if p not in news_pairs]
        skipped      = [p for p in ALL_PAIRS if p in news_pairs]
        news_warning = format_news_warning(skipped)

        data_map = await fetch_multiple_pairs(safe_pairs)

        if not data_map:
            await scanning_msg.edit_text(
                "❌ *Could not fetch market data.*\n\n"
                "TwelveData free tier limit: 800 req/day.\n"
                "Try again after midnight UTC.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        signals = scan_all_pairs(data_map, account_balance=balance)

        if not signals:
            await scanning_msg.edit_text(
                news_warning + format_no_signal(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        top = signals[:MAX_SIGS]
        await scanning_msg.delete()

        await context.bot.send_message(
            chat_id,
            f"{news_warning}"
            f"📊 *Market Scan Results*\n"
            f"Found *{len(signals)}* signal(s) — showing top {len(top)}\n"
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
        logger.error(f"signal_command error: {e}", exc_info=True)
        await scanning_msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ── /crypto ────────────────────────────────────────────────────────────────────

async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return

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
        news_pairs   = await fetch_news_pairs()
        safe_crypto  = [p for p in CRYPTO_PAIRS if p not in news_pairs]
        skipped      = [p for p in CRYPTO_PAIRS if p in news_pairs]
        news_warning = format_news_warning(skipped)

        data_map = await fetch_multiple_pairs(safe_crypto if safe_crypto else CRYPTO_PAIRS)

        if not data_map:
            await scanning_msg.edit_text(
                "❌ *No crypto data returned.*\n\n"
                "TwelveData free plan limit hit (800 req/day).\n"
                "Try again after midnight UTC.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

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
            f"{news_warning}"
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
        await scanning_msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ── /setbalance ────────────────────────────────────────────────────────────────

async def _setbalance_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _check_access(update):
        return ConversationHandler.END
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
    text    = update.message.text.strip().replace(",", "").replace("$", "")
    try:
        balance = float(text)
    except ValueError:
        await update.message.reply_text("❌ Numbers only e.g. `20`\n\nTry again:", parse_mode=ParseMode.MARKDOWN)
        return ASK_BAL
    if balance < 1:
        await update.message.reply_text("❌ Minimum $1.\n\nTry again:", parse_mode=ParseMode.MARKDOWN)
        return ASK_BAL
    set_balance(chat_id, balance)
    risk = balance * 0.01
    await update.message.reply_text(
        f"✅ *Balance saved: ${balance:,.2f}*\n\n"
        f"• Risk per trade: `${risk:,.2f}` (1%)\n\n"
        f"Use /signal or /crypto to get signals!",
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
    if not await _check_access(update):
        return
    await update.message.reply_text(
        "📖 *SamSignals Help*\n\n"
        "• /signal — full forex + crypto scan\n"
        "• /crypto — crypto signals 24/7\n"
        "• /setbalance — set balance for lot sizing\n"
        "• /status — session info\n\n"
        "*Reading a signal:*\n"
        "• *Entry* — price to open the trade\n"
        "• *SL* — stop loss, exit if wrong\n"
        "• *TP* — take profit, exit when right\n"
        "• *Lot* — position size for your balance\n"
        "• *Score* — 7–8 good · 9–10 strong\n\n"
        "*⚠️ Always check news before trading!*\n"
        "Bot skips pairs with high-impact news automatically.\n"
        "Check: _forexfactory.com/calendar_",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /status ────────────────────────────────────────────────────────────────────

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_access(update):
        return
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    session_name, is_active = get_current_session()
    bal_text = f"${balance:,.2f}" if balance else "Not set"
    await update.message.reply_text(
        format_status(session_name, is_active, minutes_to_next_scan(), bal_text),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Admin commands ─────────────────────────────────────────────────────────────

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/approve 123456789`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return
    added = approve_user(target_id)
    if added:
        await update.message.reply_text(f"✅ User `{target_id}` approved.", parse_mode=ParseMode.MARKDOWN)
        try:
            await context.bot.send_message(
                target_id,
                "✅ *You have been approved for SamSignals!*\n\n"
                "Use /start to begin.\n"
                "Set your balance with /setbalance first.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            await update.message.reply_text("⚠️ Approved but couldn't notify user.")
    else:
        await update.message.reply_text(f"ℹ️ User `{target_id}` already approved.", parse_mode=ParseMode.MARKDOWN)


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/remove 123456789`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return
    removed = remove_user(target_id)
    if removed:
        await update.message.reply_text(f"✅ User `{target_id}` removed.", parse_mode=ParseMode.MARKDOWN)
        try:
            await context.bot.send_message(
                target_id,
                "⚠️ *Your SamSignals access has been removed.*\n\nContact @SamSos to renew.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
    else:
        await update.message.reply_text(f"ℹ️ User `{target_id}` was not approved.", parse_mode=ParseMode.MARKDOWN)


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/ban 123456789`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return
    ban_user(target_id)
    await update.message.reply_text(f"🚫 User `{target_id}` banned.", parse_mode=ParseMode.MARKDOWN)


async def members_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    users = list_users()
    if not users:
        await update.message.reply_text("📋 No approved users yet.")
        return
    lines = "\n".join([f"• `{uid}`" for uid in users])
    await update.message.reply_text(
        f"📋 *Approved Users ({len(users)})*\n\n{lines}",
        parse_mode=ParseMode.MARKDOWN,
    )
