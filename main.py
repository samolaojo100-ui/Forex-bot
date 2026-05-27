import os
import requests
import time
import schedule
import threading
from datetime import datetime, timezone

# ── ENV VARS ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")
GEMINI_KEY      = os.getenv("GEMINI_KEY")
CHAT_ID         = os.getenv("CHAT_ID")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
PAIRS    = ["EUR/USD", "GBP/USD", "USD/CAD", "USD/JPY", "AUD/USD"]

# ── USER SETTINGS (per chat_id) ──────────────────────────────────────────────
user_settings: dict[str, dict] = {}

def get_settings(chat_id: str) -> dict:
    cid = str(chat_id)
    if cid not in user_settings:
        user_settings[cid] = {"account": 1000.0, "risk_pct": 1.0}
    return user_settings[cid]

# ── TELEGRAM HELPERS ─────────────────────────────────────────────────────────
def send_message(chat_id, text: str):
    try:
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        print(f"[send_message] error: {e}")

def get_updates(offset=None):
    try:
        r = requests.get(f"{BASE_URL}/getUpdates",
                         params={"timeout": 30, "offset": offset},
                         timeout=35)
        return r.json()
    except Exception as e:
        print(f"[get_updates] error: {e}")
        return {"ok": False}

# ── MARKET DATA ───────────────────────────────────────────────────────────────
def get_candles(pair: str, interval: str = "1day", size: int = 20):
    """Fetch OHLCV candles from TwelveData."""
    try:
        r = requests.get("https://api.twelvedata.com/time_series", params={
            "symbol":     pair,
            "interval":   interval,
            "outputsize": size,
            "apikey":     TWELVE_DATA_KEY
        }, timeout=10)
        data = r.json()
        if data.get("status") == "error":
            print(f"[get_candles] TwelveData error for {pair}/{interval}: {data.get('message')}")
            return None
        return data.get("values")
    except Exception as e:
        print(f"[get_candles] exception: {e}")
        return None

def calc_atr(candles: list, period: int = 14) -> float:
    """Average True Range over `period` candles."""
    trs = []
    for i in range(min(period, len(candles) - 1)):
        c = candles[i]
        p = candles[i + 1]
        high  = float(c["high"])
        low   = float(c["low"])
        prev_close = float(p["close"])
        tr = max(high - low,
                 abs(high - prev_close),
                 abs(low  - prev_close))
        trs.append(tr)
    return round(sum(trs) / len(trs), 5) if trs else 0.0

def calc_sma(closes: list, period: int) -> float:
    if len(closes) < period:
        return 0.0
    return round(sum(closes[:period]) / period, 5)

# ── SIGNAL LOGIC ─────────────────────────────────────────────────────────────
TIMEFRAME_CONFIG = {
    "5min":  {"interval": "5min",  "atr_sl_mult": 1.0, "atr_tp_mult": 1.5, "label": "5M"},
    "1h":    {"interval": "1h",    "atr_sl_mult": 1.5, "atr_tp_mult": 2.5, "label": "1H"},
    "4h":    {"interval": "4h",    "atr_sl_mult": 2.0, "atr_tp_mult": 3.0, "label": "4H"},
    "1day":  {"interval": "1day",  "atr_sl_mult": 2.5, "atr_tp_mult": 4.0, "label": "Daily"},
}

def analyze_tf(pair: str, interval: str) -> dict | None:
    """
    Analyze a single pair on a single timeframe.
    Returns a dict with direction, entry, tp, sl, atr, trend.
    Returns None if data is unavailable.
    """
    cfg     = TIMEFRAME_CONFIG[interval]
    candles = get_candles(pair, cfg["interval"], 25)
    if not candles or len(candles) < 21:
        return None

    closes  = [float(v["close"]) for v in candles]
    latest  = candles[0]
    entry   = float(latest["close"])
    atr     = calc_atr(candles, 14)
    sma5    = calc_sma(closes, 5)
    sma20   = calc_sma(closes, 20)

    direction = "BUY" if sma5 > sma20 else "SELL"
    sl_dist   = round(atr * cfg["atr_sl_mult"], 5)
    tp_dist   = round(atr * cfg["atr_tp_mult"], 5)

    if direction == "BUY":
        sl = round(entry - sl_dist, 5)
        tp = round(entry + tp_dist, 5)
    else:
        sl = round(entry + sl_dist, 5)
        tp = round(entry - tp_dist, 5)

    change = round(
        ((float(candles[0]["close"]) - float(candles[1]["close"])) /
         float(candles[1]["close"])) * 100, 4
    )

    return {
        "label":     cfg["label"],
        "interval":  interval,
        "direction": direction,
        "entry":     entry,
        "tp":        tp,
        "sl":        sl,
        "atr":       atr,
        "sma5":      sma5,
        "sma20":     sma20,
        "change":    change,
        "high":      float(latest["high"]),
        "low":       float(latest["low"]),
    }

def multi_tf_agree(results: list) -> tuple[str | None, list]:
    """
    Check if majority of timeframes agree on direction.
    Returns (consensus_direction or None, list_of_agreeing_labels).
    """
    if not results:
        return None, []
    buys  = [r for r in results if r["direction"] == "BUY"]
    sells = [r for r in results if r["direction"] == "SELL"]
    if len(buys) >= len(sells) and len(buys) >= 2:
        return "BUY",  [r["label"] for r in buys]
    if len(sells) > len(buys) and len(sells) >= 2:
        return "SELL", [r["label"] for r in sells]
    return None, []

# ── LOT SIZE CALCULATOR ───────────────────────────────────────────────────────
def calc_lot_size(account: float, risk_pct: float,
                  sl_pips: float, pair: str) -> float:
    """
    Simplified lot-size: risk_amount / (sl_pips * pip_value_per_lot).
    Uses $10/pip per standard lot as a conservative default for majors.
    """
    risk_amount = account * (risk_pct / 100)
    if sl_pips <= 0:
        return 0.01
    pip_value = 10.0       # $ per pip per standard lot (approximate for USD pairs)
    raw  = risk_amount / (sl_pips * pip_value)
    lot  = max(0.01, round(raw, 2))
    return lot

def pips(pair: str, price_dist: float) -> float:
    """Convert price distance to approximate pips."""
    if "JPY" in pair:
        return round(price_dist / 0.01, 1)
    return round(price_dist / 0.0001, 1)

# ── GEMINI AI ─────────────────────────────────────────────────────────────────
def ask_gemini(prompt: str) -> str:
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20
        )
        print(f"[Gemini] HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"[Gemini] body: {r.text[:300]}")
            return "AI analysis unavailable right now."
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"[Gemini] exception: {e}")
        return "AI analysis unavailable right now."

def get_news_summary(pair: str) -> str:
    prompt = (
        f"You are a forex analyst. In 3 plain-English sentences explain "
        f"the current market sentiment for {pair}. "
        f"Focus on: what is driving the price, key risk events this week, "
        f"and what a retail trader should watch out for. No jargon. "
        f"End with one action sentence: 'Watch for...' or 'Avoid trading when...'."
    )
    return ask_gemini(prompt)

# ── SIGNAL BUILDER ─────────────────────────────────────────────────────────────
def build_signal(pair: str, chat_id=None, require_agreement: bool = True) -> str:
    """
    Run multi-timeframe analysis and build a Telegram message.
    If require_agreement=True, only send when TFs agree.
    """
    settings = get_settings(chat_id) if chat_id else {"account": 1000.0, "risk_pct": 1.0}
    account  = settings["account"]
    risk_pct = settings["risk_pct"]

    # Analyze all timeframes
    results = []
    for tf in TIMEFRAME_CONFIG:
        r = analyze_tf(pair, tf)
        if r:
            results.append(r)
        time.sleep(0.5)   # avoid TwelveData rate limits

    if not results:
        return f"❌ Could not fetch data for *{pair}*"

    direction, agreeing = multi_tf_agree(results)
    if require_agreement and not direction:
        return (f"⚠️ *{pair}* — TFs disagree\n"
                f"No high-confidence signal right now.\n"
                f"BUY: {sum(1 for r in results if r['direction']=='BUY')} TF | "
                f"SELL: {sum(1 for r in results if r['direction']=='SELL')} TF")

    if not direction:
        direction = results[0]["direction"]
        agreeing  = [results[0]["label"]]

    emoji  = "🟢" if direction == "BUY" else "🔴"
    now    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build per-timeframe table
    tf_lines = []
    for r in results:
        sl_p  = pips(pair, abs(r["entry"] - r["sl"]))
        tp_p  = pips(pair, abs(r["entry"] - r["tp"]))
        lot   = calc_lot_size(account, risk_pct, sl_p, pair)
        agree_mark = "✅" if r["label"] in agreeing else "⬜"
        tf_lines.append(
            f"{agree_mark} *{r['label']}* | {r['direction']}\n"
            f"   Entry: `{r['entry']}` | TP: `{r['tp']}` | SL: `{r['sl']}`\n"
            f"   SL {sl_p}p / TP {tp_p}p | Lot: `{lot}`"
        )

    # News / context from Gemini
    news = get_news_summary(pair)

    msg = (
        f"📊 *{pair}* {emoji} *{direction}*\n"
        f"⏰ {now}\n"
        f"Agreement: {', '.join(agreeing)}\n\n"
        + "\n\n".join(tf_lines) +
        f"\n\n💬 *Market Context*\n{news}\n\n"
        f"💰 Account: ${account:,.0f} | Risk: {risk_pct}%"
    )
    return msg

# ── COMMAND HANDLER ──────────────────────────────────────────────────────────
def handle(chat_id, text: str):
    text = text.strip()
    settings = get_settings(chat_id)

    if text == "/start":
        send_message(chat_id,
            "👋 *Forex Signal Bot — Upgraded*\n\n"
            "📌 *Commands*\n"
            "• /signal — all pairs (multi-TF)\n"
            "• /analyze EURUSD — single pair\n"
            "• /pairs — list pairs\n"
            "• /setaccount 2000 — set account size\n"
            "• /setrisk 2 — set risk % per trade\n"
            "• /settings — show your settings\n\n"
            "📅 *Auto Signals*\n"
            "🇯🇵 Tokyo:    00:00 UTC\n"
            "🇬🇧 London:   07:00 UTC\n"
            "🇺🇸 New York: 12:00 UTC\n"
            "🔥 Overlap:   13:00 UTC\n"
            "🇦🇺 Sydney:   21:00 UTC\n\n"
            "✅ Signals only fire when multiple TFs agree."
        )

    elif text.startswith("/setaccount"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Usage: `/setaccount 2000`")
            return
        try:
            amount = float(parts[1])
            settings["account"] = amount
            send_message(chat_id, f"✅ Account set to *${amount:,.2f}*")
        except ValueError:
            send_message(chat_id, "❌ Invalid amount. Use: `/setaccount 2000`")

    elif text.startswith("/setrisk"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Usage: `/setrisk 2`")
            return
        try:
            pct = float(parts[1])
            if not (0.1 <= pct <= 10):
                send_message(chat_id, "⚠️ Risk must be between 0.1% and 10%")
                return
            settings["risk_pct"] = pct
            send_message(chat_id, f"✅ Risk set to *{pct}%* per trade")
        except ValueError:
            send_message(chat_id, "❌ Invalid value. Use: `/setrisk 2`")

    elif text == "/settings":
        send_message(chat_id,
            f"⚙️ *Your Settings*\n\n"
            f"💰 Account: *${settings['account']:,.2f}*\n"
            f"⚠️ Risk:    *{settings['risk_pct']}%* per trade\n"
            f"💵 Risk $:  *${settings['account'] * settings['risk_pct'] / 100:,.2f}* per trade"
        )

    elif text == "/signal":
        send_message(chat_id, "⏳ Analyzing all pairs across 4 timeframes...")
        for pair in PAIRS:
            msg = build_signal(pair, chat_id, require_agreement=True)
            send_message(chat_id, msg)
            time.sleep(3)

    elif text.startswith("/analyze"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Usage: `/analyze EURUSD`")
            return
        raw  = parts[1].upper()
        pair = (raw[:3] + "/" + raw[3:]) if "/" not in raw else raw
        send_message(chat_id, f"⏳ Analyzing *{pair}* across all timeframes...")
        msg = build_signal(pair, chat_id, require_agreement=False)
        send_message(chat_id, msg)

    elif text == "/pairs":
        send_message(chat_id, "📈 *Pairs*\n\n" + "\n".join(f"• {p}" for p in PAIRS))

    else:
        send_message(chat_id,
            "❓ Unknown command. Send /start for help."
        )

# ── AUTO SESSION SIGNALS ──────────────────────────────────────────────────────
def session_job(session_name: str, flag: str):
    print(f"[scheduler] {session_name} session signal firing")
    header = f"{flag} *{session_name} Session Signals*\n\n"
    send_message(CHAT_ID, header + "⏳ Scanning all pairs for high-confidence setups...")
    sent = 0
    for pair in PAIRS:
        msg = build_signal(pair, CHAT_ID, require_agreement=True)
        # Only forward real signals (skip "TFs disagree" messages)
        if "disagree" not in msg and "Could not" not in msg:
            send_message(CHAT_ID, msg)
            sent += 1
        time.sleep(3)
    if sent == 0:
        send_message(CHAT_ID,
            f"{flag} *{session_name}* — No high-confidence setups right now. "
            f"TFs are mixed. Wait for alignment.")

def run_scheduler():
    # Session schedule (UTC)
    schedule.every().day.at("00:00").do(session_job, "Tokyo",    "🇯🇵")
    schedule.every().day.at("07:00").do(session_job, "London",   "🇬🇧")
    schedule.every().day.at("12:00").do(session_job, "New York", "🇺🇸")
    schedule.every().day.at("13:00").do(session_job, "Overlap",  "🔥")
    schedule.every().day.at("21:00").do(session_job, "Sydney",   "🇦🇺")

    while True:
        schedule.run_pending()
        time.sleep(30)

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────
def main():
    print("Bot running...")
    threading.Thread(target=run_scheduler, daemon=True).start()

    offset = None
    while True:
        try:
            updates = get_updates(offset)
            if updates.get("ok"):
                for u in updates.get("result", []):
                    offset = u["update_id"] + 1
                    msg    = u.get("message", {})
                    if "text" in msg:
                        handle(msg["chat"]["id"], msg["text"])
        except Exception as e:
            print(f"[main] error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
