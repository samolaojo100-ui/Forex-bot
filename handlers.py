import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler,
    CommandHandler, MessageHandler, filters,
)
from telegram.constants import ParseMode

from data_fetcher import fetch_multiple_pairs
from signal_engine import scan_pairs, force_scan_pairs, analyze_pair, score_indicators
from indicators import compute_indicators
from formatter import (
    format_signal, format_no_trade, format_no_signal,
    format_scanning, format_status,
)
from session_manager import get_current_session, minutes_to_next_scan, is_weekend
from user_settings import (
    get_balance, set_balance, is_authorized,
    approve_user, list_approved_users,
    add_pending, remove_pending, next_pending, list_pending,
)
from config import ALL_PAIRS, CRYPTO_PAIRS, OWNER_USERNAME, OWNER_CHAT_ID
from news_filter import get_upcoming_events
from stocks_engine import fetch_stock_pairs, STOCK_PAIRS

logger  = logging.getLogger(__name__)
ASK_BAL = 1
MIN_CONFIDENCE_TO_SHOW = 70

def filter_by_confidence(signals, min_confidence=MIN_CONFIDENCE_TO_SHOW):
    return [s for s in signals if s.confidence >= min_confidence]

async def require_authorized(update):
    user    = update.effective_user
    chat_id = update.effective_chat.id
    if is_authorized(chat_id):
        return True
    add_pending(chat_id, user.full_name, user.username or "none")
    await update.message.reply_text(
        "🔒 *Access Pending Approval*\n\n"
        "Your request has been sent to the owner.\n\n"
        f"👤 You can also message: @{OWNER_USERNAME}\n\n"
        f"_Your Chat ID:_ `{chat_id}`\n\n"
        "✅ You will be notified once approved.",
        parse_mode=ParseMode.MARKDOWN,
    )
    try:
        await update.get_bot().send_message(
            chat_id=OWNER_CHAT_ID,
            text=(
                f"🔔 *New Access Request*\n\n"
                f"👤 Name: {user.full_name}\n"
                f"🆔 Chat ID: `{chat_id}`\n"
                f"📛 Username: @{user.username or 'none'}\n\n"
                f"To approve, send:\n"
                f"`/approve {chat_id}`"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.warning(f"Could not notify owner: {e}")
    return False

async def start(update, context):
    if not await require_authorized(update):
        return
    chat_id  = update.effective_chat.id
    balance  = get_balance(chat_id)
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
        "✅ 7 AI Agents · News filter\n"
        f"✅ Only shows signals ≥ {MIN_CONFIDENCE_TO_SHOW}% confidence\n"
        "✅ Session-aware auto-signals",
        parse_mode=ParseMode.MARKDOWN,
    )

async def signal_command(update, context):
    if not await require_authorized(update):
        return
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    if not balance:
        await update.message.reply_text("⚠️ *No balance set.*\n\nUse /setbalance first.", parse_mode=ParseMode.MARKDOWN)
        return
    if is_weekend():
        await update.message.reply_text("📅 *Forex closed (Weekend)*\n\nUse /crypto for 24/7 crypto signals.", parse_mode=ParseMode.MARKDOWN)
        return
    msg = await update.message.reply_text(format_scanning(), parse_mode=ParseMode.MARKDOWN)
    try:
        data_map = await fetch_multiple_pairs(ALL_PAIRS)
        if not data_map:
            await msg.edit_text("❌ Could not fetch market data.\n\nCheck TwelveData API key in Railway variables.", parse_mode=ParseMode.MARKDOWN)
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
            await context.bot.send_message(chat_id, format_signal(sig, i, len(top)), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"signal_command error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)

async def crypto_command(update, context):
    if not await require_authorized(update):
        return
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    if not balance:
        await update.message.reply_text("⚠️ *No balance set.*\n\nUse /setbalance first.", parse_mode=ParseMode.MARKDOWN)
        return
    msg = await update.message.reply_text(format_scanning(crypto_only=True), parse_mode=ParseMode.MARKDOWN)
    try:
        data_map = await fetch_multiple_pairs(CRYPTO_PAIRS)
        if not data_map:
            await msg.edit_text("❌ Could not fetch market data.\n\nTwelveData limit may be reached.", parse_mode=ParseMode.MARKDOWN)
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
            await context.bot.send_message(chat_id, format_signal(sig, i, len(top)), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"crypto_command error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)
async def stocks_command(update, context):
    if not await require_authorized(update):
        return
    chat_id = update.effective_chat.id
    balance = get_balance(chat_id)
    if not balance:
        await update.message.reply_text("⚠️ *No balance set.*\n\nUse /setbalance first.", parse_mode=ParseMode.MARKDOWN)
        return
    if is_weekend():
        await update.message.reply_text("📅 *NYSE closed (Weekend)*\n\nUse /crypto for 24/7 signals.", parse_mode=ParseMode.MARKDOWN)
        return
    msg = await update.message.reply_text(
        "📈 *Scanning US Stocks...*\n\nAAPL · TSLA · NVDA · AMZN · MSFT\n\n⏳ _Please wait..._",
        parse_mode=ParseMode.MARKDOWN,
    )
    try:
        data_map = await fetch_stock_pairs(STOCK_PAIRS)
        if not data_map:
            await msg.edit_text("❌ Could not fetch stock data.\n\nTry during market hours (9:30AM–4PM EST, Mon–Fri).", parse_mode=ParseMode.MARKDOWN)
            return
        signals = await scan_pairs(data_map, balance)
        signals = filter_by_confidence(signals)
        if not signals:
            await msg.edit_text("⏸ *No Stock Signals Right Now*\n\nTry again in 30 minutes.", parse_mode=ParseMode.MARKDOWN)
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
            await context.bot.send_message(chat_id, format_signal(sig, i, len(top)), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"stocks_command error: {e}", exc_info=True)
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode=ParseMode.MARKDOWN)

async def approve_command(update, context):
    chat_id = update.effective_chat.id
    if str(chat_id) != str(OWNER_CHAT_ID):
        await update.message.reply_text("🔒 Only the bot owner can use this.")
        return
    args = context.args
    if args and args[0].lower() == "list":
        pending  = list_pending()
        approved = list_approved_users()
        p_text   = "\n".join(f"• `{p['id']}` — {p['name']}" for p in pending) if pending else "_none_"
        a_text   = "\n".join(f"• `{c}`" for c in approved) if approved else "_none_"
        await update.message.reply_text(
            f"📋 *Pending ({len(pending)}):*\n{p_text}\n\n✅ *Approved ({len(approved)}):*\n{a_text}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if args:
        target_id = args[0].strip()
        try:
            approve_user(int(target_id))
        except ValueError:
            await update.message.reply_text("❌ Chat ID must be a number.")
            return
        await update.message.reply_text(f"✅ Approved `{target_id}` — they can now use the bot.", parse_mode=ParseMode.MARKDOWN)
        try:
            await context.bot.send_message(
                chat_id=int(target_id),
                text="🎉 *Access Approved!*\n\nWelcome to *TrendGuard AI* 🚀\n\nType /start to begin.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.warning(f"Could not notify approved user: {e}")
        return
    pending = next_pending()
    if not pending:
        approved = list_approved_users()
        a_text   = "\n".join(f"• `{c}`" for c in approved) if approved else "_none yet_"
        await update.message.reply_text(
            f"✅ *No pending requests.*\n\n*Approved users:*\n{a_text}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    total = len(list_pending())
    await update.message.reply_text(
        f"🔔 *Pending Request* ({total} waiting)\n\n"
        f"👤 Name: {pending['name']}\n"
        f"🆔 Chat ID: `{pending['id']}`\n"
        f"📛 Username: @{pending['username']}\n\n"
        f"To approve, send:\n`/approve {pending['id']}`",
        parse_mode=ParseMode.MARKDOWN,
    )

async def debug_command(update, context):
    chat_id = update.effective_chat.id
    if str(chat_id) != str(OWNER_CHAT_ID):
        return
    DEBUG_PAIR = "XAU/USD"
    await update.message.reply_text(f"🔍 *Debug scan starting on {DEBUG_PAIR}...*", parse_mode=ParseMode.MARKDOWN)
    try:
        data_map = await fetch_multiple_pairs([DEBUG_PAIR])
        if not data_map:
            await update.message.reply_text(f"❌ No data returned for {DEBUG_PAIR}", parse_mode=ParseMode.MARKDOWN)
            return
        tfs = data_map.get(DEBUG_PAIR, {})
        tf_lines = []
        for tf, df in tfs.items():
            row = df.iloc[-1]
            tf_lines.append(f"  *{tf}*: {len(df)} rows | close: `{row.get('close', 'MISSING')}`")
        await update.message.reply_text("✅ *Data fetched:*\n" + "\n".join(tf_lines), parse_mode=ParseMode.MARKDOWN)
        df_1h = tfs.get("1h")
        if df_1h is None:
            await update.message.reply_text("❌ No 1h data found", parse_mode=ParseMode.MARKDOWN)
            return
        df_ind = compute_indicators(df_1h.copy())
        row    = df_ind.iloc[-1]
        await update.message.reply_text(
            f"🔬 *Indicators (1H):*\n\n"
            f"RSI: `{float(row.get('rsi',0)):.2f}`\n"
            f"MACD: `{float(row.get('macd',0)):.6f}`\n"
            f"MACD Signal: `{float(row.get('macd_signal',0)):.6f}`\n"
            f"Stoch K: `{float(row.get('stoch_k',0)):.2f}`\n"
            f"Stoch D: `{float(row.get('stoch_d',0)):.2f}`\n"
            f"BB %B: `{float(row.get('bb_pct',0)):.4f}`\n"
            f"ADX: `{float(row.get('adx',0)):.2f}`\n"
            f"CCI: `{float(row.get('cci',0)):.2f}`\n"
            f"Williams R: `{float(row.get('williams_r',0)):.2f}`\n",
            parse_mode=ParseMode.MARKDOWN,
        )
        buy_v, sell_v, signals = score_indicators(row, "BUY")
        sig_lines = "\n".join(f"  {k}: {v}" for k, v in signals.items())
        await update.message.reply_text(
            f"🗳 *Votes:* BUY={buy_v} SELL={sell_v}\n\n{sig_lines}",
            parse_mode=ParseMode.MARKDOWN,
        )
        balance = get_balance(chat_id) or 1000.0
        sig     = await analyze_pair(DEBUG_PAIR, tfs, balance)
        if sig is None:
            await update.message.reply_text("❌ analyze\\_pair returned None", parse_mode=ParseMode.MARKDOWN)
            return
        reasons = "\n".join(f"• {r}" for r in sig.no_trade_reasons) if sig.no_trade_reasons else "_none_"
        warns   = "\n".join(f"• {w}" for w in sig.warnings) if sig.warnings else "_none_"
        await update.message.reply_text(
            f"📋 *Signal Result:*\n\n"
            f"Direction: `{sig.direction}`\n"
            f"Confidence: `{sig.confidence}%`\n"
            f"Confluence: `{sig.confluence}/8`\n"
            f"No Trade: `{sig.no_trade}`\n\n"
            f"*Blocked by:*\n{reasons}\n\n"
            f"*Warnings:*\n{warns}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Debug error: `{e}`", parse_mode=ParseMode.MARKDOWN)

async def setbalance_start(update, context):
    if not await require_authorized(update):
        return ConversationHandler.END
    chat_id = update.effective_chat.id
    current = get_balance(chat_id)
    cur_txt = f"\n_Current: ${current:,.2f}_" if current else ""
    await update.message.reply_text(
        f"💰 *Set Your Trading Balance (USD)*{cur_txt}\n\nType your balance e.g. `500` or `1000`\n_/cancel to keep current_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_BAL

async def setbalance_receive(update, context):
    chat_id = update.effective_chat.id
    text    = update.message.text.strip().replace(",", "").replace("$", "")
    try:
        balance = float(text)
    except ValueError:
        await update.message.reply_text("❌ Enter a number e.g. `500`\n\nTry again:", parse_mode=ParseMode.MARKDOWN)
        return ASK_BAL
    if balance < 1:
        await update.message.reply_text("❌ Minimum $1.\n\nTry again:", parse_mode=ParseMode.MARKDOWN)
        return ASK_BAL
    set_balance(chat_id, balance)
    risk = balance * 0.01
    await update.message.reply_text(
        f"✅ *Balance saved: ${balance:,.2f}*\n\nRisk per trade: `${risk:,.2f}` (1%)\n\nUse /signal or /crypto for live signals!",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END

async def setbalance_cancel(update, context):
    await update.message.reply_text("↩️ Cancelled.")
    return ConversationHandler.END

def build_setbalance_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("setbalance", setbalance_start)],
        states={ASK_BAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbalance_receive)]},
        fallbacks=[CommandHandler("cancel", setbalance_cancel)],
    )

async def help_command(update, context):
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
        "✅ Signal Health + Data Quality\n"
        "✅ 8 indicators across 4 timeframes\n"
        "✅ TP1, TP2, TP3 + Partial TP + Invalidation\n"
        "✅ 7 Agent Analysis\n"
        "✅ News filter + Daily trend gate\n"
        f"✅ Only shown if confidence ≥ {MIN_CONFIDENCE_TO_SHOW}%\n\n"
        "*Pairs:*\n"
        "EUR/USD · GBP/USD · USD/JPY\n"
        "XAU/USD (Gold) · XAG/USD (Silver)\n"
        "BTC · ETH · SOL",
        parse_mode=ParseMode.MARKDOWN,
    )

async def status_command(update, context):
    if not await require_authorized(update):
        return
    chat_id      = update.effective_chat.id
    balance      = get_balance(chat_id)
    session_name, is_active = get_current_session()
    bal_text     = f"${balance:,.2f}" if balance else "Not set"
    try:
        upcoming = await get_upcoming_events(hours=24)
    except Exception:
        upcoming = []
    await update.message.reply_text(
        format_status(session_name, is_active, minutes_to_next_scan(), bal_text, upcoming),
        parse_mode=ParseMode.MARKDOWN,
    )