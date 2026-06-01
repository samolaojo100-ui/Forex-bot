import os
import sys
import time
import requests
import logging
from datetime import datetime, timezone, timedelta

TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send(text, reply_markup=None):
    try:
        payload = {
            "chat_id":    CHAT_ID,
            "text":       text,
            "parse_mode": "HTML"
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json=payload,
            timeout=15,
        )
    except Exception as e:
        logger.error("Send error: %s", e)

def main_menu():
    return {
        "keyboard": [
            [{"text": "📡 Get Signals"}, {"text": "🕐 Schedule"}],
            [{"text": "ℹ️ Help"},        {"text": "📊 Status"}],
        ],
        "resize_keyboard":   True,
        "persistent":        True,
    }

def round_price(price, pair):
    if "JPY" in pair:
        return round(price, 3)
    if pair.startswith(("BTC",)):
        return round(price, 1)
    if pair.startswith(("ETH","BNB","SOL","AVAX")):
        return round(price, 2)
    if pair.startswith(("XRP","ADA","DOGE","MATIC","DOT")):
        return round(price, 4)
    return round(price, 5)

def format_signal_message(signal, session="Auto Scan"):
    pair     = signal["pair"]
    direction = signal["direction"]
    entry    = round_price(signal["entry"], pair)
    sl       = round_price(signal["sl"], pair)
    tp       = round_price(signal["tp"], pair)
    sl_pips  = signal["sl_pips"]
    tp_pips  = signal["tp_pips"]
    lot_size = signal["lot_size"]
    rr       = signal["rr"]
    tf_sigs  = signal.get("tf_signals", {})
    now      = datetime.now(timezone.utc).strftime("%H:%M UTC  %d %b %Y")

    arrow = "BUY" if direction == "BUY" else "SELL"

    tf_map = {"m15": "15 Min", "h1": "1 Hour", "daily": "Daily"}
    tf_lines = ""
    for k, label in tf_map.items():
        if k in tf_sigs:
            d = tf_sigs[k]["direction"]
            mark = "✅" if d == direction else "⚪"
            tf_lines += f"{mark} {label:<10} {d}\n"

    return (
        f"<b>{'━'*28}</b>\n"
        f"<b>  {pair[:3]}/{pair[3:]}  —  {arrow}</b>\n"
        f"<b>{'━'*28}</b>\n\n"
        f"<b>TIMEFRAMES</b>\n"
        f"<code>{tf_lines}</code>\n"
        f"<b>{'─'*28}</b>\n"
        f"<b>Entry      :</b>  <code>{entry}</code>\n"
        f"<b>Stop Loss  :</b>  <code>{sl}</code>  ({sl_pips:.0f} pips)\n"
        f"<b>Take Profit:</b>  <code>{tp}</code>  ({tp_pips:.0f} pips)\n"
        f"<b>Lot Size   :</b>  <code>{lot_size}</code>\n"
        f"<b>Risk/Reward:</b>  <code>1:{rr}</code>\n"
        f"<b>{'─'*28}</b>\n"
        f"<b>Session    :</b>  {session}\n"
        f"<b>Time       :</b>  {now}\n\n"
        f"<i>Tap any value to copy. Trade at your own risk.</i>"
    )

def run_scan_and_send(session="Manual Request"):
    send("⏳ Scanning market... Please wait.")
    try:
        from signal_generator import scan_all_pairs
        from signal_cache import is_duplicate, mark_sent, clear_old_entries
        from config import TOP_SIGNALS

        clear_old_entries()
        signals = scan_all_pairs()
        fresh = [s for s in signals if not is_duplicate(s["pair"], s["direction"])]
        top = fresh[:TOP_SIGNALS]

        if not top:
            send(
                "📊 Scan complete — No strong signals right now.\n"
                "Try again in 30 minutes.",
                reply_markup=main_menu()
            )
            return

        send(
            f"📡 Found <b>{len(top)}</b> signal(s):",
            reply_markup=main_menu()
        )
        for sig in top:
            send(format_signal_message(sig, session))
            mark_sent(sig["pair"], sig["direction"])
            time.sleep(0.5)

    except Exception as e:
        send(f"❌ Error: {e}", reply_markup=main_menu())
        logger.error("Scan error: %s", e)

def send_schedule():
    send(
        "<b>📅 SIGNAL SCHEDULE</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        "<b>CRYPTO (24/7):</b>\n"
        "Every hour, all week\n\n"
        "<b>FOREX SESSIONS (Nigeria):</b>\n"
        "🕐 1:00 AM  — Tokyo opens\n"
        "🕘 9:00 AM  — London opens\n"
        "🔥 2:00 PM  — London/NY Overlap\n"
        "🕕 6:00 PM  — New York only\n"
        "🕙 11:00 PM — Market quiets\n\n"
        "<b>BEST TIME FOR SIGNALS:</b>\n"
        "Monday–Friday 2PM–6PM Nigeria",
        reply_markup=main_menu()
    )

def send_help():
    send(
        "<b>ℹ️ FOREXHUNT BOT</b>\n"
        "<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        "Use the buttons below to:\n\n"
        "📡 <b>Get Signals</b> — Scan market now\n"
        "🕐 <b>Schedule</b>   — View signal times\n"
        "📊 <b>Status</b>     — Bot health check\n"
        "ℹ️ <b>Help</b>       — Show this message\n\n"
        "Auto signals sent every hour.\n"
        "Best: Mon–Fri 2PM–6PM Nigeria.",
        reply_markup=main_menu()
    )

def send_status():
    now = datetime.now(timezone.utc)
    hour = now.hour
    day = now.weekday()

    if day >= 5:
        market = "Closed (Weekend) — Crypto only"
    elif 13 <= hour < 17:
        market = "London/NY Overlap — BEST TIME"
    elif 8 <= hour < 17:
        market = "London Session — Active"
    elif 13 <= hour < 22:
        market = "New York Session — Active"
    elif 0 <= hour < 9:
        market = "Tokyo Session — Active"
    else:
        market = "Between Sessions"

    send(
        f"<b>📊 BOT STATUS</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"Bot        : Online\n"
        f"Market     : {market}\n"
        f"UTC Time   : {now.strftime('%H:%M  %d %b %Y')}\n"
        f"Next scan  : Top of next hour\n\n"
        f"Scanning 38 pairs every hour.",
        reply_markup=main_menu()
    )

def listen_for_commands():
    logger.info("Listening for commands...")
    updates = get_updates()
    if not updates:
        logger.info("No updates.")
        return

    for update in updates:
        message  = update.get("message", {})
        text     = message.get("text", "").strip()
        chat_id  = str(message.get("chat", {}).get("id", ""))
        msg_time = datetime.fromtimestamp(
            message.get("date", 0), tz=timezone.utc
        )

        if datetime.now(timezone.utc) - msg_time > timedelta(minutes=6):
            continue
        if chat_id != str(CHAT_ID):
            continue

        t = text.lower()
        if any(x in t for x in ["/signal", "signal", "get signal"]):
            run_scan_and_send("Manual Request")
        elif any(x in t for x in ["/schedule", "schedule"]):
            send_schedule()
        elif any(x in t for x in ["/status", "status"]):
            send_status()
        elif any(x in t for x in ["/help", "/start", "help"]):
            send_help()
            send("Welcome! Use the buttons below:", reply_markup=main_menu())

def get_updates(offset=0):
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"offset": offset},
            timeout=10,
        )
        return resp.json().get("result", [])
    except:
        return []

if __name__ == "__main__":
    if "--listen" in sys.argv:
        listen_for_commands()
    elif "--scan" in sys.argv:
        run_scan_and_send("Auto Scan")
    elif "--schedule" in sys.argv:
        send_schedule()
