import logging
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, filters,
)
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_all_pairs, analyze_pair, overall_direction
from formatter import format_signal, format_no_signal, format_scanning, format_status
from session_manager import get_current_session, minutes_to_next_scan, is_weekend, get_session_pairs
from user_settings import get_balance, set_balance
from config import ALL_PAIRS, CRYPTO_PAIRS
from indicators import compute_indicators

logger = logging.getLogger(__name__)

MAX_SIGNALS = 5
ASK_BALANCE = 1

WAT_OFFSET = timedelta(hours=1)  # Nigeria = UTC+1

NEXT_SESSION_GUIDE = [
    {"name": "Tokyo",                   "start": 0,  "end": 9,  "pairs": "USD/JPY, EUR/JPY, GBP/JPY"},
    {"name": "Tokyo/London Overlap",    "start": 7,  "end": 9,  "pairs": "EUR/JPY, GBP/JPY, EUR/GBP"},
    {"name": "London",                  "start": 7,  "end": 16, "pairs": "EUR/USD, GBP/USD, EUR/GBP"},
    {"name": "London/New York Overlap", "start": 12, "end": 16, "pairs": "EUR/USD, GBP/USD, USD/JPY ⭐ BEST"},
    {"name": "New York",                "start": 12, "end": 21, "pairs": "EUR/USD, USD/JPY, USD/CAD"},
]


def get_next_session_with_wait(now_utc: datetime) -> tuple:
    current_hour = now_utc.hour
    current_minute = now_utc.minute
    for s in NEXT_SESSION_GUIDE:
        if s["start"] > current_hour:
            wait_mins = (s["start"] - current_hour) * 60 - current_minute
            return s, wait_mins
    first = NEXT_SESSION_GUIDE[0]
    mins_to_midnight = (24 - current_hour) * 60 - current_minute
    return first, mins_to_midnight


def format_wait_time(wait_mins: int) -> str:
    if wait_mins <= 0:
        return "very soon"
    hours = wait_mins // 60
    mins = wait_mins % 60
    if hours > 0 and mins > 0:
        return f"{hours} hr {mins} mins"
    elif hours > 0:
        return f"{hours} hr"
    else:
        return f"{mins} mins"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    bal_line = f"💰 Balance: *${balance:,.2f}*" if balance else "💰 Balance: _not set — use /setbalance_"

    await update.message.reply_text(
        "🤖 *Forex & Crypto Signal Bot*\n\n"
        f"{bal_line}\n\n"
        "📌 *Commands:*\n"
        "/signal — live forex signals (session-aware)\n"
        "/crypto — live crypto signals *(24/7 ✅)*\n"
        "/setbalance — set your balance\n"
        "/status — current session info\n"
        "/help — full guide\n\n"
        "✅ 47 Forex + 12 Crypto pairs\n"
        "✅ 5 timeframes · multiple indicators\n"
        "✅ Auto-signals every 30 min during sessions",
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

        all_signals = []
        for pair, tfs in data_map.items():
            try:
                sig = analyze_pair(pair, tfs, balance)
                if sig:
                    all_signals.append(sig)
                else:
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

        await context.bot.send_message(
            chat_id,
            f"₿ *Live Crypto Signals*\n"
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
            "📅 Forex resumes *Sunday 11 PM Nigerian time*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    session_name, is_active = get_current_session()
    now_utc = datetime.now(timezone.utc)

    if not is_active:
        next_s, wait_mins = get_next_session_with_wait(now_utc)
        wait_str = format_wait_time(wait_mins)

        start_wat_hour = (next_s["start"] + 1) % 24
        period = "AM" if start_wat_hour < 12 else "PM"
        display_hour = start_wat_hour % 12 or 12

        await update.message.reply_text(
            f"⏳ *Not a good time to trade*\n\n"
            f"Market is in off-hours — low liquidity & unpredictable moves.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ *Next session:* {next_s['name']}\n"
            f"🕐 *Starts in:* *{wait_str}*\n"
            f"🇳🇬 *Nigerian time:* {display_hour}:00 {period} WAT\n"
            f"💱 *Best pairs then:* `{next_s['pairs']}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Come back in *{wait_str}* and use /signal for real signals on those pairs. 🎯\n\n"
            f"₿ Want live signals *right now*? Use /crypto",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    session_pairs = get_session_pairs(session_name)

    scanning_msg = await update.message.reply_text(
        f"🔍 *Scanning live market...*\n"
        f"Session: *{session_name}*\n"
        f"Pairs: `{', '.join(session_pairs)}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        data_map = await fetch_multiple_pairs(session_pairs)
        signals = scan_all_pairs(data_map, account_balance=balance)

        if not signals:
            await scanning_msg.edit_text(
                f"📭 *No strong signals right now*\n\n"
                f"Session: *{session_name}*\n"
                f"Market may be consolidating. Try again in 15–30 minutes.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        top = signals[:MAX_SIGNALS]
        await scanning_msg.delete()

        await context.bot.send_message(
            chat_id,
            f"📊 *{session_name} — Live Signals*\n"
            f"Found *{len(signals)}* signal(s) — top {len(top)} shown\n"
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
        f"Use /signal for live forex or /crypto for live crypto!",
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
        "• /signal — live session-aware forex scan\n"
        "• /crypto — live crypto signals 24/7\n"
        "• /setbalance — set your balance\n"
        "• /status — current session info\n\n"
        "*How /signal works:*\n"
        "🕐 Off-hours → tells you next session & countdown\n"
        "✅ Active session → live scan of best pairs\n\n"
        "*Sessions (Nigerian time WAT):*\n"
        "🇯🇵 Tokyo: 1AM–10AM\n"
        "🇬🇧 London: 8AM–5PM\n"
        "🇺🇸 New York: 1PM–10PM\n"
        "⭐ Best window: 1PM–5PM",
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
