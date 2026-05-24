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

def send(cid, txt, buttons=None):
    body = {"chat_id": cid, "text": txt, "parse_mode": "Markdown"}
    if buttons:
        body["reply_markup"] = {"keyboard": buttons, "resize_keyboard": True, "one_time_keyboard": False}
    try:
        requests.post(f"{URL}/sendMessage", json=body, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

def get_updates(offset=None):
    try:
        r = requests.get(f"{URL}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=35)
        return r.json()
    except:
        return {"ok": False}

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

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

def fetch(ticker, period, interval):
    try:
        h = yf.Ticker(ticker).history(period=period, interval=interval)
        if h is None or h.empty:
            return None
        return h
    except Exception as e:
        print(f"Fetch error {ticker}: {e}")
        return None

def score_pair(name, ticker):
    is_gold = "XAU" in name
    is_jpy = "JPY" in name
    daily = fetch(ticker, "3mo", "1d")
    if daily is None or len(daily) < 21:
        return None
    closes = daily["Close"].tolist()
    highs = daily["High"].tolist()
    lows = daily["Low"].tolist()
    price = round(closes[-1], 2 if is_gold else 3 if is_jpy else 5)
    ema50 = calc_ema(closes[-50:] if len(closes) >= 50 else closes, 50)
    ema200 = calc_ema(closes[-200:] if len(closes) >= 200 else closes, 200)
    rsi = calc_rsi(closes[-30:] if len(closes) >= 30 else closes)
    chg = round(((closes[-1] - closes[-2]) / closes[-2]) * 100, 3)
    r_high = round(max(highs[-20:]), 5)
    r_low = round(min(lows[-20:]), 5)
    rng = r_high - r_low
    pos = (price - r_low) / rng if rng > 0 else 0.5
    ema_gap = round(abs(ema50 - ema200) / price * 100, 3)
    bull = 0
    bear = 0
    factors = []
    if ema50 > ema200:
        bull += 2
        factors.append("✅ EMA trend: Bullish")
    else:
        bear += 2
        factors.append("✅ EMA trend: Bearish")
    if rsi < 35:
        bull += 2
        factors.append(f"✅ RSI {rsi}: Oversold")
    elif rsi > 65:
        bear += 2
        factors.append(f"✅ RSI {rsi}: Overbought")
    elif rsi < 48:
        bull += 1
        factors.append(f"⚠️ RSI {rsi}: Slightly bearish")
    else:
        bear += 1
        factors.append(f"⚠️ RSI {rsi}: Slightly bullish")
    if chg > 0.1:
        bull += 1
        factors.append(f"✅ Strong bullish momentum")
    elif chg < -0.1:
        bear += 1
        factors.append(f"✅ Strong bearish momentum")
    else:
        factors.append(f"⚠️ Weak momentum")
    if pos < 0.25:
        bull += 1
        factors.append("✅ Near support zone")
    elif pos > 0.75:
        bear += 1
        factors.append("✅ Near resistance zone")
    else:
        factors.append("⚠️ Mid-range position")
    if ema_gap > 0.15:
        if ema50 > ema200:
            bull += 1
        else:
            bear += 1
        factors.append(f"✅ Strong EMA separation")
    else:
        factors.append(f"⚠️ Weak EMA separation")
    is_buy = bull > bear
    winning = bull if is_buy else bear
    score = winning
    return {
        "name": name, "ticker": ticker, "price": price,
        "direction": "BUY" if is_buy else "SELL",
        "score": score, "rsi": rsi, "ema50": ema50,
        "ema200": ema200, "r_high": r_high, "r_low": r_low,
        "factors": factors, "is_gold": is_gold, "is_jpy": is_jpy,
    }

def format_signal(d, acc, risk):
    price = d["price"]
    direction = d["direction"]
    score = d["score"]
    is_gold = d["is_gold"]
    is_jpy = d["is_jpy"]
    if score >= 6:
        conf = "🔥 VERY HIGH"
    elif score >= 5:
        conf = "✅ HIGH"
    elif score >= 4:
        conf = "⚠️ MEDIUM"
    else:
        conf = "❌ LOW"
    color = "🟢" if direction == "BUY" else "🔴"
    pip = 1.0 if is_gold else (0.01 if is_jpy else 0.0001)
    sl_pips = 50 if is_gold else (20 if is_jpy else 15)
    tp_pips = sl_pips * 2
    if direction == "BUY":
        sl = round(price - pip * sl_pips, 2 if is_gold else 3 if is_jpy else 5)
        tp = round(price + pip * tp_pips, 2 if is_gold else 3 if is_jpy else 5)
    else:
        sl = round(price + pip * sl_pips, 2 if is_gold else 3 if is_jpy else 5)
        tp = round(price - pip * tp_pips, 2 if is_gold else 3 if is_jpy else 5)
    risk_usd = round(acc * (risk / 100), 2)
    pip_val = 1.0 if is_gold else 10
    lot = round(risk_usd / (sl_pips * pip_val), 4) if sl_pips > 0 else 0
    profit = round(risk_usd * 2, 2)
    factors_txt = "\n".join(f"│ {f}" for f in d["factors"])
    dir_emoji = "📈" if direction == "BUY" else "📉"
    return (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{color} *{d['name']}* {dir_emoji}\n"
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
        f"📋 *Why this signal:*\n"
        f"{factors_txt}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

def find_solid_pairs(cid, acc, risk):
    send(cid, "🔍 Scanning all pairs...\n⏳ Please wait 30-60 seconds", buttons=MENU)
    results = []
    for name, ticker in ALL_PAIRS.items():
        try:
            data = score_pair(name, ticker)
            if data:
                results.append(data)
        except Exception as e:
            print(f"Score error {name}: {e}")
        time.sleep(1)
    solid = [r for r in results if r["score"] >= 5]
    solid.sort(key=lambda x: x["score"], reverse=True)
    if not solid:
        solid = sorted(results, key=lambda x: x["score"], reverse=True)[:3]
        send(cid, "⚠️ *No very high confidence setups right now.*\n\nShowing top 3 best available.\n_Consider waiting for stronger setups._")
    else:
        send(cid, f"✅ *Found {len(solid)} solid setup(s)!*\nOnly showing HIGH confidence signals 🎯")
    for d in solid:
        send(cid, format_signal(d, acc, risk))
        time.sleep(1)

def best_setup(cid, acc, risk):
    send(cid, "🔍 Finding best setup...", buttons=MENU)
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
        send(cid, "⚠️ Could not fetch data. Try again.")
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
        f"_Tap 📡 Signal for full analysis_")

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