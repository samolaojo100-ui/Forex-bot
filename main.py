import os
import requests
import time
import schedule
import threading
import json
from datetime import datetime, timezone
import yfinance as yf

TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
URL     = f"https://api.telegram.org/bot{TOKEN}"

# All major pairs to scan
ALL_PAIRS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDCAD": "USDCAD=X",
    "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X",
    "USDCHF": "USDCHF=X",
    "XAUUSD": "GC=F",
}

SF = "/tmp/settings.json"
JF = "/tmp/journal.json"
WF = "/tmp/waiting.json"

MENU = [["📡 Signal", "🔍 Best Setup"], ["📰 News", "💼 Portfolio"], ["📓 Journal", "⚙️ Settings"]]

# ── UTILS ──────────────────────────────────────────────────────────────────────
def send(cid, txt, buttons=None):
    body = {"chat_id": cid, "text": txt, "parse_mode": "Markdown"}
    if buttons:
        body["reply_markup"] = {
            "keyboard": buttons,
            "resize_keyboard": True,
            "one_time_keyboard": False
        }
    try:
        requests.post(f"{URL}/sendMessage", json=body, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

def get_updates(offset=None):
    try:
        r = requests.get(f"{URL}/getUpdates",
                         params={"timeout": 30, "offset": offset}, timeout=35)
        return r.json()
    except:
        return {"ok": False}

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# ── STORAGE ────────────────────────────────────────────────────────────────────
def ls():
    try:
        return json.load(open(SF))
    except:
        return {"account": None, "risk": 2, "setup_done": False}

def ss(d):
    json.dump(d, open(SF, "w"))

def lw():
    try:
        return json.load(open(WF))
    except:
        return {}

def sw(d):
    json.dump(d, open(WF, "w"))

def get_wait(cid):
    return lw().get(str(cid))

def set_wait(cid, state):
    w = lw(); w[str(cid)] = state; sw(w)

def clear_wait(cid):
    w = lw(); w.pop(str(cid), None); sw(w)

def lj():
    try:
        return json.load(open(JF))
    except:
        return []

def sj(d):
    json.dump(d, open(JF, "w"))

# ── INDICATORS ─────────────────────────────────────────────────────────────────
def calc_ema(closes, period):
    if not closes or len(closes) < 2:
        return closes[-1] if closes else 0
    k = 2 / (period + 1)
    e = closes[0]
    for c in closes[1:]:
        e = c * k + e * (1 - k)
    return round(e, 5)

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

# ── MARKET DATA ────────────────────────────────────────────────────────────────
def fetch(ticker, period, interval):
    try:
        h = yf.Ticker(ticker).history(period=period, interval=interval)
        if h is None or h.empty:
            return None
        return h
    except Exception as e:
        print(f"Fetch error {ticker}: {e}")
        return None

# ── SCORE A PAIR ───────────────────────────────────────────────────────────────
def score_pair(name, ticker):
    """Returns (score, direction, signal_data) or None if data unavailable."""
    is_gold = "XAU" in name
    is_jpy  = "JPY" in name

    # Get daily data for trend
    daily = fetch(ticker, "3mo", "1d")
    if daily is None or len(daily) < 21:
        return None

    closes = daily["Close"].tolist()
    highs  = daily["High"].tolist()
    lows   = daily["Low"].tolist()
    price  = round(closes[-1], 2 if is_gold else 3 if is_jpy else 5)

    ema50  = calc_ema(closes[-50:] if len(closes) >= 50 else closes, 50)
    ema200 = calc_ema(closes[-200:] if len(closes) >= 200 else closes, 200)
    rsi    = calc_rsi(closes[-30:] if len(closes) >= 30 else closes)

    chg = round(((closes[-1] - closes[-2]) / closes[-2]) * 100, 3)

    r_high = round(max(highs[-20:]), 5)
    r_low  = round(min(lows[-20:]), 5)
    rng    = r_high - r_low
    pos    = (price - r_low) / rng if rng > 0 else 0.5

    ema_gap = round(abs(ema50 - ema200) / price * 100, 3)

    # Scoring
    bull = 0
    bear = 0
    factors = []

    # EMA trend (weight 2)
    if ema50 > ema200:
        bull += 2
        factors.append(f"✅ EMA trend: Bullish (EMA50 > EMA200)")
    else:
        bear += 2
        factors.append(f"✅ EMA trend: Bearish (EMA50 < EMA200)")

    # RSI (weight 2)
    if rsi < 35:
        bull += 2
        factors.append(f"✅ RSI {rsi}: Oversold — strong BUY signal")
    elif rsi > 65:
        bear += 2
        factors.append(f"✅ RSI {rsi}: Overbought — strong SELL signal")
    elif rsi < 48:
        bull += 1
        factors.append(f"⚠️ RSI {rsi}: Leaning bearish")
    else:
        bear += 1
        factors.append(f"⚠️ RSI {rsi}: Leaning bullish")

    # Momentum (weight 1)
    if chg > 0.1:
        bull += 1
        factors.append(f"✅ Momentum: Strong bullish +{chg}%")
    elif chg < -0.1:
        bear += 1
        factors.append(f"✅ Momentum: Strong bearish {chg}%")
    else:
        factors.append(f"⚠️ Momentum: Weak ({chg}%)")

    # Support/Resistance (weight 1)
    if pos < 0.25:
        bull += 1
        factors.append(f"✅ Near support — good BUY zone")
    elif pos > 0.75:
        bear += 1
        factors.append(f"✅ Near resistance — good SELL zone")
    else:
        factors.append(f"⚠️ Mid-range — no clear S/R edge")

    # EMA strength (weight 1)
    if ema_gap > 0.15:
        if ema50 > ema200:
            bull += 1
        else:
            bear += 1
        factors.append(f"✅ Strong EMA separation ({ema_gap}%)")
    else:
        factors.append(f"⚠️ Weak EMA separation ({ema_gap}%)")

    total   = bull + bear
    is_buy  = bull > bear
    winning = bull if is_buy else bear
    score   = winning  # max 7

    return {
        "name":      name,
        "ticker":    ticker,
        "price":     price,
        "direction": "BUY" if is_buy else "SELL",
        "score":     score,
        "bull":      bull,
        "bear":      bear,
        "rsi":       rsi,
        "ema50":     ema50,
        "ema200":    ema200,
        "r_high":    r_high,
        "r_low":     r_low,
        "factors":   factors,
        "is_gold":   is_gold,
        "is_jpy":    is_jpy,
    }

# ── FORMAT SIGNAL ──────────────────────────────────────────────────────────────
def format_signal(d, acc, risk):
    name      = d["name"]
    price     = d["price"]
    direction = d["direction"]
    score     = d["score"]
    is_gold   = d["is_gold"]
    is_jpy    = d["is_jpy"]

    # Confidence label
    if score >= 6:
        conf = "🔥 VERY HIGH"
    elif score >= 5:
        conf = "✅ HIGH"
    elif score >= 4:
        conf = "⚠️ MEDIUM"
    else:
        conf = "❌ LOW"

    color = "🟢" if direction == "BUY" else "🔴"

    # Pip values
    pip     = 1.0 if is_gold else (0.01 if is_jpy else 0.0001)
    sl_pips = 50 if is_gold else (20 if is_jpy else 15)
    tp_pips = sl_pips * 2

    if direction == "BUY":
        sl = round(price - pip * sl_pips, 2 if is_gold else 3 if is_jpy else 5)
        tp = round(price + pip * tp_pips, 2 if is_gold else 3 if is_jpy else 5)
    else:
        sl = round(price + pip * sl_pips, 2 if is_gold else 3 if is_jpy else 5)
        tp = round(price - pip * tp_pips, 2 if is_gold else 3 if is_jpy else 5)

    # Money management
    risk_usd = round(acc * (risk / 100), 2)
    pip_val  = 1.0 if is_gold else 10
    lot      = round(risk_usd / (sl_pips * pip_val), 4) if sl_pips > 0 else 0
    profit   = round(risk_usd * 2, 2)

    factors_txt = "\n".join(f"│ {f}" for f in d["factors"])
    dir_emoji = "📈" if direction == "BUY" else "📉"

    return (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{color} *{name}* {dir_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Direction:  *{direction}*\n"
        f"⚡ Confidence: *{conf}*\n"
        f"🕐 {now()}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Entry:        `{price}`\n"
        f"✅ Take Profit:  `{tp}`\n"
        f"🛑 Stop Loss:    `{sl}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Account:  ${acc}\n"
        f"💸 Risk:     ${risk_usd} ({risk}%)\n"
        f"📦 Lot Size: {lot}\n"
        f"💵 Profit:   ${profit}\n"
        f"📐 R:R:      1:2\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Signal Reasons:*\n"
        f"{factors_txt}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

# ── SCAN AND SEND SOLID PAIRS ──────────────────────────────────────────────────
def find_solid_pairs(cid, acc, risk):
    send(cid, "🔍 Scanning all major pairs...\n⏳ Please wait (30-60 seconds)", buttons=MENU)

    results = []
    for name, ticker in ALL_PAIRS.items():
        try:
            data = score_pair(name, ticker)
            if data:
                results.append(data)
        except Exception as e:
            print(f"Score error {name}: {e}")
        time.sleep(1)

    # Only keep HIGH and VERY HIGH confidence (score >= 5)
    solid = [r for r in results if r["score"] >= 5]
    solid.sort(key=lambda x: x["score"], reverse=True)

    if not solid:
        # If nothing is very strong, take top 3 by score
        solid = sorted(results, key=lambda x: x["score"], reverse=True)[:3]
        send(cid,
            "⚠️ *No very high confidence setups right now.*\n\n"
            "Showing top 3 best available pairs instead.\n"
            "_Consider waiting for stronger setups._")

    else:
        send(cid,
            f"✅ *Found {len(solid)} solid setup(s)!*\n\n"
            f"Only showing HIGH confidence signals 🎯")

    for d in solid:
        send(cid, format_signal(d, acc, risk))
        time.sleep(1)

# ── BEST SINGLE SETUP ──────────────────────────────────────────────────────────
def best_setup(cid, acc, risk):
    send(cid, "🔍 Finding single best setup...", buttons=MENU)
    results = []
    for name, ticker in ALL_PAIRS.items():
        try:
            data = score_pair(name, ticker)
            if data:
                results.append(data)
        except:
            pass
        time.sleep(1)

    if not results:
        send(cid, "⚠️ Could not fetch market data. Try again.")
        return

    best = sorted(results, key=lambda x: x["score"], reverse=True)[0]
    d = best
    color = "🟢" if d["direction"] == "BUY" else "🔴"

    send(cid,
        f"🏆 *Best Setup Right Now*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{color} *{d['name']}* — *{d['direction']}*\n"
        f"⭐ Score: {d['score']}/7\n"
        f"📉 RSI: {d['rsi']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"_Tap 📡 Signal to see full analysis_")

# ── NEWS ───────────────────────────────────────────────────────────────────────
def get_news():
    try:
        items = requests.get(
            "https://api.rss2json.com/v1/api.json",
            params={"rss_url": "https://www.forexlive.com/feed/news"},
            timeout=10).json().get("items", [])[:5]
        if not items:
            return "⚠️ No news available right now."
        lines = ["📰 *Latest Forex News*\n" + "━" * 22]
        for item in items:
            lines.append(f"• {item.get('title', '')}")
        lines.append(f"\n⏰ {now()}")
        return "\n".join(lines)
    except:
        return "⚠️ Could not fetch news right now."

# ── SETUP FLOW ─────────────────────────────────────────────────────────────────
def start_setup(cid):
    set_wait(cid, "waiting_account")
    send(cid,
        "👋 *Welcome to Forex Signal Bot Pro!*\n\n"
        "I scan *8 major pairs* and only send you\n"
        "the strongest setups automatically.\n\n"
        "First, let me personalise your risk settings.\n\n"
        "💰 *What is your account balance?*\n"
        "_(Type the amount e.g. 500)_")

def handle_setup(cid, txt, s):
    wait = get_wait(cid)
    if wait == "waiting_account":
        try:
            amt = float(txt.replace("$", "").replace(",", ""))
            s["account"] = amt
            ss(s)
            set_wait(cid, "waiting_risk")
            send(cid,
                f"✅ Account: *${amt}*\n\n"
                f"📊 *What % risk per trade?*\n\n"
                f"• Safe:       *1%* = ${round(amt*0.01,2)}/trade\n"
                f"• Moderate:   *2%* = ${round(amt*0.02,2)}/trade\n"
                f"• Aggressive: *3%* = ${round(amt*0.03,2)}/trade\n\n"
                f"_(Type a number e.g. 2)_")
        except:
            send(cid, "❌ Please type just the number e.g. *500*")

    elif wait == "waiting_risk":
        try:
            pct = float(txt.replace("%", ""))
            if pct > 10:
                send(cid, "⚠️ Too high! Please enter between 1-5%")
                return
            s["risk"] = pct
            s["setup_done"] = True
            ss(s)
            clear_wait(cid)
            risk_usd = round(s["account"] * (pct / 100), 2)
            send(cid,
                f"🎯 *Setup Complete!*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 Account: ${s['account']}\n"
                f"📊 Risk: {pct}% = ${risk_usd}/trade\n"
                f"💵 Max profit/trade: ${round(risk_usd*2,2)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"All signals are now personalised for you!\n"
                f"Tap a button below to get started 👇",
                buttons=MENU)
        except:
            send(cid, "❌ Please type just the number e.g. *2*")

# ── COMMAND HANDLER ────────────────────────────────────────────────────────────
def handle(cid, txt):
    s   = ls()
    txt = txt.strip()
    wait = get_wait(cid)

    # Setup flow
    if wait in ["waiting_account", "waiting_risk"]:
        handle_setup(cid, txt, s)
        return

    # Force setup if not done
    if not s.get("setup_done") and txt.lower() not in ["/start", "⚙️ settings"]:
        start_setup(cid)
        return

    cmd = txt.lower()

    if cmd == "/start":
        if not s.get("setup_done"):
            start_setup(cid)
        else:
            send(cid,
                f"👋 *Welcome back!*\n\n"
                f"💰 Account: ${s['account']} | Risk: {s['risk']}%\n\n"
                f"I scan 8 pairs and only show solid setups.\n"
                f"What would you like to do? 👇",
                buttons=MENU)

    elif cmd in ["📡 signal", "/signal"]:
        threading.Thread(
            target=find_solid_pairs,
            args=(cid, s["account"], s["risk"]),
            daemon=True).start()

    elif cmd in ["🔍 best setup", "/scan"]:
        threading.Thread(
            target=best_setup,
            args=(cid, s["account"], s["risk"]),
            daemon=True).start()

    elif cmd in ["📰 news", "/news"]:
        send(cid, get_news(), buttons=MENU)

    elif cmd in ["⚙️ settings", "/settings"]:
        start_setup(cid)

    elif cmd in ["💼 portfolio", "/portfolio"]:
        j = lj()
        if not j:
            send(cid, "📁 No trades yet.\nUse 📓 Journal to log your first trade.", buttons=MENU)
            return
        cl = [t for t in j if t["result"] in ["win", "loss"]]
        w  = len([t for t in cl if t["result"] == "win"])
        wr = round(w / len(cl) * 100, 1) if cl else 0
        send(cid,
            f"💼 *Portfolio Dashboard*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Account: ${s['account']}\n"
            f"📊 Risk/trade: {s['risk']}%\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 Total: {len(j)}\n"
            f"✅ Wins: {w}\n"
            f"❌ Losses: {len(cl)-w}\n"
            f"🎯 Win Rate: {wr}%\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{'🔥 Excellent!' if wr>=60 else '💪 Keep going!' if wr>=40 else '⚠️ Review strategy'}",
            buttons=MENU)

    elif cmd in ["📓 journal", "/journal"]:
        send(cid,
            "📓 *Trade Journal*\n\n"
            "➕ Log trade:\n"
            "`/jadd EURUSD BUY 1.16 1.17 1.155`\n\n"
            "✅ Close trade:\n"
            "`/jclose 0 win` or `/jclose 0 loss`\n\n"
            "📊 Stats:\n"
            "`/jstats`",
            buttons=MENU)

    elif cmd.startswith("/jadd"):
        p = txt.split()
        try:
            t = {
                "pair": p[1].upper(), "dir": p[2].upper(),
                "entry": float(p[3]), "tp": float(p[4]),
                "sl": float(p[5]), "date": now(), "result": "open"
            }
            j = lj(); j.append(t); sj(j)
            rr = round(abs(t['tp']-t['entry'])/abs(t['sl']-t['entry']), 2)
            send(cid,
                f"✅ *Trade #{len(j)-1} Logged*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 {t['pair']} | {t['dir']}\n"
                f"🎯 Entry: {t['entry']}\n"
                f"✅ TP: {t['tp']}\n"
                f"🛑 SL: {t['sl']}\n"
                f"📐 R:R = 1:{rr}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━",
                buttons=MENU)
        except:
            send(cid, "❌ Use: `/jadd EURUSD BUY 1.16 1.17 1.155`", buttons=MENU)

    elif cmd.startswith("/jclose"):
        p = txt.split()
        try:
            j = lj(); j[int(p[1])]["result"] = p[2]; sj(j)
            send(cid, f"✅ Trade #{p[1]} marked *{p[2].upper()}*", buttons=MENU)
        except:
            send(cid, "❌ Use: `/jclose 0 win`", buttons=MENU)

    elif cmd == "/jstats":
        j = lj()
        if not j:
            send(cid, "No trades yet.", buttons=MENU)
            return
        cl = [t for t in j if t["result"] in ["win", "loss"]]
        w  = len([t for t in cl if t["result"] == "win"])
        wr = round(w / len(cl) * 100, 1) if cl else 0
        send(cid,
            f"📊 *Journal Stats*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Total: {len(j)} | ✅ {w}W | ❌ {len(cl)-w}L\n"
            f"🎯 Win Rate: {wr}%\n"
            f"🟡 Open: {len([t for t in j if t['result']=='open'])}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━",
            buttons=MENU)

    elif cmd.startswith("/risk"):
        p = txt.split()
        try:
            pair    = p[1].upper()
            d       = p[2].upper()
            ent     = float(p[3])
            sl_p    = float(p[4])
            is_gold = "XAU" in pair
            is_jpy  = "JPY" in pair
            pip     = 1.0 if is_gold else (0.01 if is_jpy else 0.0001)
            pips    = round(abs(ent - sl_p) / pip, 1)
            ru      = round(s["account"] * (s["risk"] / 100), 2)
            pip_val = 1.0 if is_gold else 10
            lot     = round(ru / (pips * pip_val), 4) if pips > 0 else 0
            tp      = round(ent + (ent - sl_p) * 2 if d == "BUY" else ent - (sl_p - ent) * 2, 5)
            send(cid,
                f"🧮 *Risk Calculator*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 {pair} | {d}\n"
                f"🎯 Entry: {ent}\n"
                f"🛑 SL: {sl_p} ({pips} pips)\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 Account: ${s['account']}\n"
                f"💸 Risk: ${ru} ({s['risk']}%)\n"
                f"📦 Lot: {lot}\n"
                f"✅ TP: {tp}\n"
                f"💵 Profit: ${round(ru*2,2)}\n"
                f"📐 R:R: 1:2\n"
                f"━━━━━━━━━━━━━━━━━━━━━━",
                buttons=MENU)
        except:
            send(cid, "❌ Use: `/risk EURUSD BUY 1.1620 1.1580`", buttons=MENU)

# ── DAILY JOB ──────────────────────────────────────────────────────────────────
def daily_job():
    s = ls()
    if not s.get("account"):
        return
    find_solid_pairs(CHAT_ID, s["account"], s["risk"])

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
def run_scheduler():
    schedule.every().day.at("08:00").do(daily_job)
    while True:
        schedule.run_pending()
        time.sleep(30)

def main():
    print("Bot running...")
    threading.Thread(target=run_scheduler, daemon=True).start()
    offset = None
    while True:
        try:
            ups = get_updates(offset)
            if ups.get("ok"):
                for u in ups.get("result", []):
                    offset = u["update_id"] + 1
                    msg = u.get("message", {})
                    if "text" in msg:
                        handle(msg["chat"]["id"], msg["text"])
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()