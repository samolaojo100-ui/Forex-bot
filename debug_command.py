# Add this temporary debug handler to handlers.py
# Register it in bot.py as:
# app.add_handler(CommandHandler("debug", debug_command))
# Remove after fixing

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from data_fetcher import fetch_multiple_pairs
from indicators import compute_indicators
from signal_engine import analyze_pair, score_indicators
from config import CRYPTO_PAIRS
from user_settings import get_balance, is_authorized

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        return

    await update.message.reply_text("🔍 Running debug scan on BTC/USD...", parse_mode=ParseMode.MARKDOWN)

    try:
        # Fetch just BTC
        data_map = await fetch_multiple_pairs(["BTC/USD"])

        if not data_map:
            await update.message.reply_text("❌ No data returned for BTC/USD — TwelveData fetch failed completely")
            return

        tfs = data_map.get("BTC/USD", {})
        if not tfs:
            await update.message.reply_text("❌ BTC/USD key missing from data_map")
            return

        # Check timeframes
        tf_info = []
        for tf, df in tfs.items():
            row = df.iloc[-1]
            cols = list(df.columns)
            tf_info.append(
                f"*{tf}*: {len(df)} rows\n"
                f"  Cols: {', '.join(cols[:8])}\n"
                f"  Close: {row.get('close', 'MISSING')}\n"
            )

        await update.message.reply_text(
            "📊 *Raw Data Check:*\n\n" + "\n".join(tf_info),
            parse_mode=ParseMode.MARKDOWN
        )

        # Try computing indicators on 1h
        df_1h = tfs.get("1h")
        if df_1h is None:
            await update.message.reply_text("❌ No 1h data found")
            return

        df_ind = compute_indicators(df_1h.copy())
        row = df_ind.iloc[-1]

        await update.message.reply_text(
            f"🔬 *Indicator Values (1H last candle):*\n\n"
            f"RSI: `{row.get('rsi', 'MISSING'):.2f}`\n"
            f"MACD: `{row.get('macd', 'MISSING'):.6f}`\n"
            f"MACD Signal: `{row.get('macd_signal', 'MISSING'):.6f}`\n"
            f"Stoch K: `{row.get('stoch_k', 'MISSING'):.2f}`\n"
            f"Stoch D: `{row.get('stoch_d', 'MISSING'):.2f}`\n"
            f"BB %B: `{row.get('bb_pct', 'MISSING'):.4f}`\n"
            f"ADX: `{row.get('adx', 'MISSING'):.2f}`\n"
            f"CCI: `{row.get('cci', 'MISSING'):.2f}`\n"
            f"Williams R: `{row.get('williams_r', 'MISSING'):.2f}`\n",
            parse_mode=ParseMode.MARKDOWN
        )

        # Score indicators
        buy_v, sell_v, signals = score_indicators(row, "BUY")
        await update.message.reply_text(
            f"🗳 *Indicator Votes:*\n\n"
            f"BUY votes: `{buy_v}`\n"
            f"SELL votes: `{sell_v}`\n\n"
            f"RSI: {signals.get('rsi')}\n"
            f"MACD: {signals.get('macd')}\n"
            f"Stoch: {signals.get('stoch')}\n"
            f"BB: {signals.get('bb')}\n"
            f"ADX: {signals.get('adx')}\n"
            f"CCI: {signals.get('cci')}\n"
            f"Williams: {signals.get('williams')}\n",
            parse_mode=ParseMode.MARKDOWN
        )

        # Full signal analysis
        balance = get_balance(chat_id) or 1000.0
        sig = await analyze_pair("BTC/USD", tfs, balance)

        if sig is None:
            await update.message.reply_text("❌ analyze_pair returned None")
            return

        await update.message.reply_text(
            f"📋 *Signal Result:*\n\n"
            f"Direction: `{sig.direction}`\n"
            f"Confidence: `{sig.confidence}%`\n"
            f"Confluence: `{sig.confluence}/8`\n"
            f"No Trade: `{sig.no_trade}`\n\n"
            f"*No Trade Reasons:*\n" +
            ("\n".join(f"• {r}" for r in sig.no_trade_reasons) if sig.no_trade_reasons else "_none_") +
            f"\n\n*Warnings:*\n" +
            ("\n".join(f"• {w}" for w in sig.warnings) if sig.warnings else "_none_"),
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Debug error: `{e}`", parse_mode=ParseMode.MARKDOWN)