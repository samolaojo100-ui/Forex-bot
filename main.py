import os
import requests
import time
import schedule
import threading
import json
from datetime import datetime, timezone
import yfinance as yf

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

BASE_URL   = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
PAIRS      = ["EURUSD=X", "GBPUSD=X", "USDCAD=X", "USDJPY=X", "AUDUSD=X"]
JOURNAL_FILE = "/tmp/journal.json"

# ── HELPERS ────────────────────────────────────────────────────────────────────
def send_message(chat_id, text):
    try:
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

def get_updates(offset=None):
    try:
        r = requests.get(f"{BASE_URL}/getUpdates",
                         params={"timeout": 30, "offset": offset}, timeout=35)
        return r.json()
    except:
        return {"ok": False}

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# ── JOURNAL ────────────────────────────────────────────────────────────────────
def load_journal():
    try:
        with open(JOURNAL_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_journal(data):
    try:
        with open(JOURNAL_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Journal save error: {e}")

# ── MARKET DATA ────────────────────────────────────────────────────────────────
def get_data(pair, period, interval):
    try:
        hist = yf.Ticker(pair).history(period=period, interval=interval)
        if hist.empty:
            return None
        if interval == "1h" and period == "15d":
            hist = hist.resample("4h").agg({
                "Open": "first", "High": "max",
                "Low": "min", "Close": "last"
            }).dropna()
        return hist
    except Exception as e:
        print(f"Data error {pair}: {e}")
        return None

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_g = sum(gains) / period if gains else 0.001
    avg_l = sum(losses) / period if losses else 0.001
    return round(100 - (100 / (1 + avg_g / avg_l)), 1)

# ── SIGNAL ANALYSIS ────────────────────────────────────────────────────────────
def analyze_tf(pair, tf_name, period, interval):
    hist = get_data(pair, period, interval)
    if hist is None or len(hist) < 6:
        return None
    closes = hist["Close"].tolist()
    highs  = hist["High"].tolist()
    lows   = hist["Low"].tolist()
    price  = round(closes[-1], 5)
    change = round(((closes[-1] - closes[-2]) / closes[-2]) * 100, 3)
    n5     = min(5,  len(closes))
    n20    = min(20, len(closes))
    sma5   = round(sum(closes[-n5:])  / n5,  5)
    sma20  = round(sum(closes[-n20:]) / n20, 5)
    rsi    = calc_rsi(closes[-30:] if len(closes) >= 30 else closes)
    r_high = round(max(highs[-14:])  if len(highs) >= 14 else max(highs), 5)
    r_low  = round(min(lows[-14:])   if len(lows)  >= 14 else min(lows),  5)

    bull = bear = 0
    if sma5 > sma20:  bull += 2
    else:             bear += 2
    if rsi < 40:      bull += 2
    elif rsi > 60:    bear += 2
    elif rsi < 50:    bull += 1
    else:             bear += 1
    if change > 0:    bull += 1
    else:             bear += 1
    rng = r_high - r_low
    if rng > 0:
        pos = (price - r_low) / rng
        if pos < 0.3:   bull += 1
        elif pos > 0.7: bear += 1

    is_buy     = bull > bear
    direction  = "BUY 📈" if is_buy else "SELL 📉"
    confidence = min(50 + abs(bull - bear) * 8, 82)
    pip        = 0.01 if "JPY" in pair else 0.0001

    if is_buy:
        entry = f"{price} — {round(price + pip*5, 5)}"
        tp    = round(price + pip * 30, 5)
        sl    = round(price - pip * 15, 5)
    else:
        entry = f"{round(price - pip*5, 5)} — {price}"
        tp    = round(price - pip * 30, 5)
        sl    = round(price + pip * 15, 5)

    rsi_note = "oversold 🟢" if rsi < 40 else ("overbought 🔴" if rsi > 60 else "neutral ⚪")
    trend    = "Bullish ↑" if sma5 > sma20 else "Bearish ↓"

    return (
        f"⏱ *{tf_name}*\n"
        f"🔵 {direction} | 📊 {confidence}%\n"
        f"🎯 Entry: `{entry}`\n"
        f"✅ TP: `{tp}`  🛑 SL: `{sl}`\n"
        f"📉 RSI: {rsi} ({rsi_note})\n"
        f"📈 Trend: {trend}\n"
        f"📏 Range: {r_low} — {r_high}"
    )

def full_analysis(pair):
    name = pair.replace("=X", "")
    tfs  = [
    ("15M",  "2d",  "15m"),
    ("30M",  "5d",  "30m"),
    ("1H",   "5d",  "1h"),
    ("4H",   "15d", "1h"),
    ("Daily","1mo", "1d"),
    ]
    parts = [f"📊 *{name} — Multi-TF Analysis*\n{'─'*22}"]
    for tf_name, period, interval in tfs:
        sig = analyze_tf(pair, tf_name, period, interval)
        parts.append(sig if sig else f"⚠️ No data for {tf_name}")
        time.sleep(1)
    return "\n\n".join(parts)

# ── BEST SETUP SCANNER ─────────────────────────────────────────────────────────
def scan_best():
    best_pair  = None
    best_score = 0
    best_dir   = ""
    for pair in PAIRS:
        hist = get_data(pair, "1mo", "1d")
        if hist is None or len(hist) < 6:
            continue
        closes = hist["Close"].tolist()
        n5  = min(5,  len(closes))
        n20 = min(20, len(closes))
        sma5  = sum(closes[-n5:])  / n5
        sma20 = sum(closes[-n20:]) / n20
        rsi   = calc_rsi(closes[-30:] if len(closes) >= 30 else closes)
        bull = bear = 0
        if sma5 > sma20: bull += 2
        else:            bear += 2
        if rsi < 40:     bull += 3
        elif rsi > 60:   bear += 3
        score = abs(bull - bear)
        if score > best_score:
            best_score = score
            best_pair  = pair
            best_dir   = "BUY 📈" if bull > bear else "SELL 📉"
        time.sleep(1)
    if best_pair:
        name = best_pair.replace("=X", "")
        return f"🔍 *Best Setup Right Now*\n\n🏆 Pair: *{name}*\n🔵 Direction: {best_dir}\n⭐ Setup Score: {best_score}/5\n\n_Run /signal for full analysis_"
    return "⚠️ No strong setups found right now."

# ── NEWS ───────────────────────────────────────────────────────────────────────
def get_forex_news():
    try:
        r = requests.get(
            "https://api.rss2json.com/v1/api.json",
            params={"rss_url": "https://www.forexlive.com/feed/news"},
            timeout=10)
        items = r.json().get("items", [])[:5]
        if not items:
            return "⚠️ No news available right now."
        lines = ["📰 *Latest Forex News*\n"]
        for item in items:
            title = item.get("title", "")
            lines.append(f"• {title}")
        lines.append(f"\n⏰ {now_utc()}")
        return "\n".join(lines)
    except Exception as e:
        print(f"News error: {e}")
        return "⚠️ Could not fetch news right now."

# ── JOURNAL COMMANDS ───────────────────────────────────────────────────────────
def journal_add(parts):
    # /journal add EURUSD BUY 1.16 1.17 1.155
    try:
        pair      = parts[2].upper()
        direction = parts[3].upper()
        entry_p   = float(parts[4])
        tp_p      = float(parts[5])
        sl_p      = float(parts[6])
    except:
        return ("❌ Wrong format. Use:\n"
                "`/journal add EURUSD BUY 1.16 1.17 1.155`\n"
                "pair direction entry TP SL")
    trade = {
        "pair": pair, "direction": direction,
        "entry": entry_p, "tp": tp_p, "sl": sl_p,
        "date": now_utc(), "result": "open"
    }
    j = load_journal()
    j.append(trade)
    save_journal(j)
    rr = round(abs(tp_p - entry_p) / abs(sl_p - entry_p), 2) if abs(sl_p - entry_p) > 0 else 0
    return (f"✅ *Trade Logged*\n\n"
            f"Pair: {pair} | {direction}\n"
            f"Entry: {entry_p} | TP: {tp_p} | SL: {sl_p}\n"
            f"R:R Ratio: 1:{rr}")

def journal_close(parts):
    # /journal close 0 win   or   /journal close 0 loss
    try:
        idx    = int(parts[2])
        result = parts[3].lower()
    except:
        return "❌ Use: `/journal close 0 win` or `/journal close 0 loss`"
    j = load_journal()
    if idx >= len(j):
        return f"❌ No trade at index {idx}"
    j[idx]["result"] = result
    save_journal(j)
    return f"✅ Trade #{idx} marked as *{result.upper()}*"

def journal_stats():
    j = load_journal()
    if not j:
        return "📓 No trades logged yet.\nUse `/journal add` to log your first trade."
    closed = [t for t in j if t["result"] in ["win", "loss"]]
    open_t = [t for t in j if t["result"] == "open"]
    wins   = len([t for t in closed if t["result"] == "win"])
    losses = len([t for t in closed if t["result"] == "loss"])
    wr     = round((wins / len(closed)) * 100, 1) if closed else 0
    lines  = [
        "📊 *Trading Journal Stats*\n",
        f"📈 Total Trades: {len(j)}",
        f"✅ Wins: {wins}  ❌ Losses: {losses}",
        f"🎯 Win Rate: {wr}%",
        f"🟡 Open Trades: {len(open_t)}",
    ]
    if open_t:
        lines.append("\n📂 *Open Trades:*")
        for i, t in enumerate(j):
            if t["result"] == "open":
                lines.append(f"  #{i} {t['pair']} {t['direction']} @ {t['entry']}")
    return "\n".join(lines)

def portfolio():
    j = load_journal()
    if not j:
        return "📁 No trades yet. Use `/journal add` to start tracking."
    closed = [t for t in j if t["result"] in ["win", "loss"]]
    wins   = len([t for t in closed if t["result"] == "win"])
    losses = len(closed) - wins
    wr     = round((wins / len(closed)) * 100, 1) if closed else 0
    pairs_traded = list(set(t["pair"] for t in j))
    lines = [
        "💼 *Portfolio Dashboard*\n",
        f"📊 Total Trades: {len(j)}",
        f"✅ Wins: {wins}  ❌ Losses: {losses}",
        f"🎯 Win Rate: {wr}%",
        f"📈 Pairs Traded: {', '.join(pairs_traded)}",
        f"\n📅 Last Trade: {j[-1]['date']}",
        f"Direction: {j[-1]['direction']} {j[-1]['pair']} @ {j[-1]['entry']}",
    ]
    if wr >= 60:
        lines.append("\n🔥 Great performance! Keep it up!")
    elif wr >= 40:
        lines.append("\n💪 Decent performance. Review your losses.")
    else:
        lines.append("\n⚠️ Review your strategy. Focus on R:R ratio.")
    return "\n".join(lines)

# ── COMMAND HANDLER ────────────────────────────────────────────────────────────
def handle(chat_id, text):
    parts = text.strip().split()
    cmd   = parts[0].lower() if parts else ""

    if cmd == "/start":
        send_message(chat_id,
            "👋 *Forex Signal Bot Pro*\n\n"
            "📡 *Signals*\n"
            "• /signal — 1H, 4H & Daily for all pairs\n"
            "• /scan — find best setup now\n\n"
            "📰 *News*\n"
            "• /news — latest forex news\n\n"
            "📓 *Journal*\n"
            "• `/journal add EURUSD BUY 1.16 1.17 1.155`\n"
            "• `/journal close 0 win`\n"
            "• `/journal stats`\n\n"
            "💼 *Portfolio*\n"
            "• /portfolio — full dashboard\n\n"
            "📅 Auto-signal daily at *08:00 UTC*")

    elif cmd == "/signal":
        send_message(chat_id, "⏳ Running multi-timeframe analysis for all pairs...")
        for pair in PAIRS:
            send_message(chat_id, f"{full_analysis(pair)}\n\n⏰ {now_utc()}")
            time.sleep(2)

    elif cmd == "/scan":
        send_message(chat_id, "🔍 Scanning all pairs for best setup...")
        send_message(chat_id, scan_best())

    elif cmd == "/news":
        send_message(chat_id, get_forex_news())

    elif cmd == "/journal":
        if len(parts) < 2:
            send_message(chat_id, "Use: `/journal add`, `/journal close`, or `/journal stats`")
        elif parts[1] == "add":
            send_message(chat_id, journal_add(parts))
        elif parts[1] == "close":
            send_message(chat_id, journal_close(parts))
        elif parts[1] == "stats":
            send_message(chat_id, journal_stats())
        else:
            send_message(chat_id, "❌ Unknown journal command.")

    elif cmd == "/portfolio":
        send_message(chat_id, portfolio())

    elif cmd == "/pairs":
        lines = "\n".join(f"• {p.replace('=X','')}" for p in PAIRS)
        send_message(chat_id, f"📈 *Tracked Pairs*\n\n{lines}")

# ── SCHEDULER ──────────────────────────────────────────────────────────────────
def daily_job():
    for pair in PAIRS:
        send_message(CHAT_ID, f"{full_analysis(pair)}\n\n⏰ {now_utc()}")
        time.sleep(2)

def run_scheduler():
    schedule.every().day.at("08:00").do(daily_job)
    while True:
        schedule.run_pending()
        time.sleep(30)

# ── MAIN ───────────────────────────────────────────────────────────────────────
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
                    msg = u.get("message", {})
                    if "text" in msg:
                        handle(msg["chat"]["id"], msg["text"])
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
                    
