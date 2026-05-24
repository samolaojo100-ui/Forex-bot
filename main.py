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

SF      = "/tmp/settings.json"
JF      = "/tmp/journal.json"
WF      = "/tmp/waiting.json"
SIG_LOG = "/tmp/sig_log.json"

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

def load_sig_log():
    try:
        return json.load(open(SIG_LOG))
    except:
        return []

def save_sig_log(d):
    json.dump(d, open(SIG_LOG, "w"))

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

def detect_candles(opens, highs, lows, closes):
    patterns = []
    if len(closes) < 3:
        return patterns
    o1, h1, l1, c1 = opens[-2], highs[-2], lows[-2], closes[-2]
    o2, h2, l2, c2 = opens[-1], highs[-1], lows[-1], closes[-1]
    body2  = abs(c2 - o2)
    range2 = h2 - l2 if h2 - l2 > 0 else 0.0001
    if c1 < o1 and c2 > o2 and c2 > o1 and o2 < c1:
        patterns.append(("bullish_engulfing", "✅ Bullish Engulfing — strong BUY signal", 2))
    if c1 > o1 and c2 < o2 and c2 < o1 and o2 > c1:
        patterns.append(("bearish_engulfing", "✅ Bearish Engulfing — strong SELL signal", 2))
    lower_wick = min(o2, c2) - l2
    upper_wick = h2 - max(o2, c2)
    if lower_wick > body2 * 2 and upper_wick < body2 * 0.5:
        patterns.append(("pin_bar_bull", "✅ Bullish Pin Bar — rejection of lows", 1))
    if upper_wick > body2 * 2 and lower_wick < body2 * 0.5:
        patterns.append(("pin_bar_bear", "✅ Bearish Pin Bar — rejection of highs", 1))
    if body2 < range2 * 0.1:
        patterns.append(("doji", "⚠️ Doji — indecision, wait for confirmation", 0))
    return patterns

def detect_structure(closes, highs, lows):
    if len(closes) < 10:
        return "unknown", "⚠️ Not enough data for structure"
    rh = highs[-10:]
    rl = lows[-10:]
    hh = rh[-1] > max(rh[:-1])
    hl = rl[-1]  > min(rl[:-1])
    lh = rh[-1] < max(rh[:-1])
    ll = rl[-1]  < min(rl[:-1])
    if hh and hl:
        return "bullish", "✅ Structure: Higher Highs + Higher Lows — Uptrend"
    elif lh and ll:
        return "bearish", "✅ Structure: Lower Highs + Lower Lows — Downtrend"
    elif hh and ll:
        return "breakout", "⚠️ Structure: Expansion — possible breakout"
    else:
        return "ranging", "⚠️ Structure: Ranging — no clear trend"

def get_tf_bias(ticker):
    biases = {}
    tf_list = [("1h","1mo","1h"), ("4h","3mo","1h"), ("1d","3mo","1d")]
    for tf_name, period, interval in tf_list:
        try:
            h = yf.Ticker(ticker).history(period=period, interval=interval)
            if h is None or h.empty or len(h) < 20:
                continue
            if tf_name == "4h":
                h = h.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
            closes = h["Close"].tolist()
            if len(closes) < 20:
                continue
            e50  = calc_ema(closes[-50:] if len(closes)>=50 else closes, 50)
            e200 = calc_ema(closes[-200:] if len(closes)>=200 else closes, 200)
            biases[tf_name] = "bull" if e50 > e200 else "bear"
        except:
            pass
        time.sleep(0.3)
    return biases

def get_market_status():
    now_utc = datetime.now(timezone.utc)
    weekday = now_utc.weekday()
    hour    = now_utc.hour
    if weekday == 5:
        return False, "closed", "📴 Market closed — reopens Sunday 21:00 UTC"
    if weekday == 6 and hour < 21:
        reopen_in = 21 - hour
        return False, "closed", f"📴 Market closed — reopens in ~{reopen_in} hours (Sun 21:00 UTC)"
    if weekday == 4 and hour >= 21:
        return False, "closed", "📴 Market just closed — reopens Sunday 21:00 UTC"
    sessions = []
    if hour >= 21 or hour < 6:  sessions.append("🇦🇺 Sydney")
    if 0  <= hour < 9:          sessions.append("🇯🇵 Tokyo")
    if 7  <= hour < 16:         sessions.append("🇬🇧 London")
    if 12 <= hour < 21:         sessions.append("🇺🇸 New York")
    if not sessions:
        sessions = ["🌐 Inter-session (low liquidity)"]
    if 8 <= hour < 12:
        quality = "🔥 BEST — London session (high liquidity)"
    elif 13 <= hour < 17:
        quality = "🔥 BEST — London/NY overlap (highest liquidity)"
    elif 12 <= hour < 21:
        quality = "✅ GOOD — New York session"
    elif 7 <= hour < 16:
        quality = "✅ GOOD — London session"
    else:
        quality = "⚠️ LOW — Asian session (less movement)"
    session_txt = " + ".join(sessions)
    return True, session_txt, quality

def get_news_warnings():
    try:
        r = requests.get(
            "https://api.rss2json.com/v1/api.json",
            params={"rss_url": "https://www.forexlive.com/feed/news"},
            timeout=10)
        items = r.json().get("items", [])[:8]
        warnings = []
        high_impact = ["CPI","NFP","FOMC","GDP","interest rate","Federal Reserve",
                       "inflation","employment","central bank","rate decision","PMI"]
        for item in items:
            title = item.get("title","").upper()
            for keyword in high_impact:
                if keyword.upper() in title:
                    warnings.append(f"⚠️ *High Impact News:* {item.get('title','')}")
                    break
        return warnings
    except:
        return []

def get_news():
    try:
        items = requests.get(
            "https://api.rss2json.com/v1/api.json",
            params={"rss_url": "https://www.forexlive.com/feed/news"},
            timeout=10).json().get("items", [])[:6]
        if not items:
            return "⚠️ No news available right now."
        lines = ["📰 *Latest Forex News*\n" + "━"*22]
        for item in items:
            lines.append(f"• {item.get('title','')}")
        lines.append(f"\n⏰ {now()}")
        return "\n".join(lines)
    except:
        return "⚠️ Could not fetch news right now."

def get_currency_strength():
    currencies = ["USD","EUR","GBP","JPY","CAD","AUD","NZD","CHF"]
    strength   = {c: 0 for c in currencies}
    pairs_map  = {
        "EURUSD=X":("EUR","USD"), "GBPUSD=X":("GBP","USD"),
        "USDJPY=X":("USD","JPY"), "USDCAD=X":("USD","CAD"),
        "AUDUSD=X":("AUD","USD"), "NZDUSD=X":("NZD","USD"),
        "USDCHF=X":("USD","CHF"), "EURGBP=X":("EUR","GBP"),
        "EURJPY=X":("EUR","JPY"), "GBPJPY=X":("GBP","JPY"),
    }
    for ticker, (base, quote) in pairs_map.items():
        try:
            h = yf.Ticker(ticker).history(period="5d", interval="1d")
            if h is None or len(h) < 2:
                continue
            closes = h["Close"].tolist()
            chg = (closes[-1] - closes[-2]) / closes[-2]
            strength[base]  += chg
            strength[quote] -= chg
        except:
            pass
        time.sleep(0.3)
    return strength

def format_strength_ranking(strength):
    ranked = sorted(strength.items(), key=lambda x: x[1], reverse=True)
    lines  = ["📊 *Currency Strength Ranking*\n" + "━"*22]
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"]
    for i, (cur, score) in enumerate(ranked):
        bar   = "█" * min(int(abs(score)*500)+1, 8)
        trend = "▲" if score > 0 else "▼"
        lines.append(f"{medals[i]} *{cur}* {trend} {bar}")
    strongest = ranked[0][0]
    weakest   = ranked[-1][0]
    lines.append(f"\n💡 *Best Setup:* BUY {strongest}/{weakest}")
    lines.append(f"⏰ {now()}")
    return "\n".join(lines)

def log_signal(name, direction, entry, tp, sl):
    log = load_sig_log()
    log.append({"pair":name,"direction":direction,"entry":entry,
                "tp":tp,"sl":sl,"date":now(),"result":"open"})
    save_sig_log(log)

def get_performance():
    log = load_sig_log()
    if not log:
        return "📊 No signals tracked yet.\nSignals are auto-tracked when you tap 📡 Signal."
    closed = [s for s in log if s["result"] in ["win","loss"]]
    wins   = len([s for s in closed if s["result"]=="win"])
    losses = len(closed) - wins
    wr     = round(wins/len(closed)*100,1) if closed else 0
    open_c = len([s for s in log if s["result"]=="open"])
    pairs  = {}
    for s in closed:
        p = s["pair"]
        if p not in pairs:
            pairs[p] = {"w":0,"l":0}
        if s["result"]=="win": pairs[p]["w"] += 1
        else: pairs[p]["l"] += 1
    best_pair = max(pairs, key=lambda x: pairs[x]["w"]) if pairs else "N/A"
    lines = [
        "📊 *Signal Performance*\n" + "━"*22,
        f"📈 Total: {len(log)}",
        f"✅ Wins: {wins}  ❌ Losses: {losses}",
        f"🎯 Win Rate: {wr}%",
        f"🟡 Open: {open_c}",
        f"🏆 Best Pair: {best_pair}",
        "━"*22,
        "🔥 Excellent!" if wr>=60 else "💪 Keep improving." if wr>=45 else "⚠️ Review your entries.",
    ]
    return "\n".join(lines)

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
    is_jpy  = "JPY" in name
    daily   = fetch(ticker, "3mo", "1d")
    if daily is None or len(daily) < 21:
        return None
    closes = daily["Close"].tolist()
    highs  = daily["High"].tolist()
    lows   = daily["Low"].tolist()
    opens  = daily["Open"].tolist()
    price  = round(closes[-1], 2 if is_gold else 3 if is_jpy else 5)
    ema50  = calc_ema(closes[-50:] if len(closes)>=50 else closes, 50)
    ema200 = calc_ema(closes[-200:] if len(closes)>=200 else closes, 200)
    rsi    = calc_rsi(closes[-30:] if len(closes)>=30 else closes)
    chg    = round(((closes[-1]-closes[-2])/closes[-2])*100, 3)
    r_high = round(max(highs[-20:]), 5)
    r_low  = round(min(lows[-20:]),  5)
    rng    = r_high - r_low
    pos    = (price - r_low) / rng if rng > 0 else 0.5
    ema_gap = round(abs(ema50-ema200)/price*100, 3)
    bull = 0
    bear = 0
    factors = []
    if ema50 > ema200:
        bull += 2; factors.append("✅ EMA trend: Bullish (EMA50 > EMA200)")
    else:
        bear += 2; factors.append("✅ EMA trend: Bearish (EMA50 < EMA200)")
    if rsi < 35:
        bull += 2; factors.append(f"✅ RSI {rsi}: Oversold — strong BUY")
    elif rsi > 65:
        bear += 2; factors.append(f"✅ RSI {rsi}: Overbought — strong SELL")
    elif rsi < 48:
        bull += 1; factors.append(f"⚠️ RSI {rsi}: Slightly bearish")
    else:
        bear += 1; factors.append(f"⚠️ RSI {rsi}: Slightly bullish")
    if chg > 0.1:
        bull += 1; factors.append(f"✅ Strong bullish momentum (+{chg}%)")
    elif chg < -0.1:
        bear += 1; factors.append(f"✅ Strong bearish momentum ({chg}%)")
    else:
        factors.append(f"⚠️ Weak momentum ({chg}%)")
    if pos < 0.25:
        bull += 1; factors.append("✅ Near support — good BUY zone")
    elif pos > 0.75:
        bear += 1; factors.append("✅ Near resistance — good SELL zone")
    else:
        factors.append("⚠️ Mid-range — no clear S/R edge")
    if ema_gap > 0.15:
        if ema50 > ema200: bull += 1
        else: bear += 1
        factors.append(f"✅ Strong EMA separation ({ema_gap}%)")
    else:
        factors.append(f"⚠️ Weak EMA separation ({ema_gap}%)")
    candles = detect_candles(opens, highs, lows, closes)
    for ctype, cdesc, cscore in candles:
        if "bull" in ctype:
            bull += cscore; factors.append(cdesc)
        elif "bear" in ctype:
            bear += cscore; factors.append(cdesc)
        else:
            factors.append(cdesc)
    struct, struct_desc = detect_structure(closes, highs, lows)
    if struct == "bullish":
        bull += 1; factors.append(struct_desc)
    elif struct == "bearish":
        bear += 1; factors.append(struct_desc)
    else:
        factors.append(struct_desc)
    is_buy  = bull > bear
    winning = bull if is_buy else bear
    score   = winning
    return {
        "name":name,"ticker":ticker,"price":price,
        "direction":"BUY" if is_buy else "SELL",
        "score":score,"bull":bull,"bear":bear,
        "rsi":rsi,"ema50":ema50,"ema200":ema200,
        "r_high":r_high,"r_low":r_low,
        "factors":factors,"is_gold":is_gold,"is_jpy":is_jpy,
    }

def format_signal(d, acc, risk, tf_biases=None, news_warns=None):
    price     = d["price"]
    direction = d["direction"]
    score     = d["score"]
    is_gold   = d["is_gold"]
    is_jpy    = d["is_jpy"]
    max_score = d["bull"] + d["bear"]
    if score >= 7:   conf = "🔥 VERY HIGH"
    elif score >= 5: conf = "✅ HIGH"
    elif score >= 4: conf = "⚠️ MEDIUM"
    else:            conf = "❌ LOW — Consider waiting"
    color     = "🟢" if direction == "BUY" else "🔴"
    dir_emoji = "📈" if direction == "BUY" else "📉"
    pip     = 1.0 if is_gold else (0.01 if is_jpy else 0.0001)
    sl_pips = 50 if is_gold else (20 if is_jpy else 15)
    tp_pips = sl_pips * 2
    if direction == "BUY":
        sl = round(price-pip*sl_pips, 2 if is_gold else 3 if is_jpy else 5)
        tp = round(price+pip*tp_pips, 2 if is_gold else 3 if is_jpy else 5)
    else:
        sl = round(price+pip*sl_pips, 2 if is_gold else 3 if is_jpy else 5)
        tp = round(price-pip*tp_pips, 2 if is_gold else 3 if is_jpy else 5)
    risk_usd = round(acc*(risk/100), 2)
    pip_val  = 1.0 if is_gold else 10
    lot      = round(risk_usd/(sl_pips*pip_val), 4) if sl_pips > 0 else 0
    profit   = round(risk_usd*2, 2)
    factors_txt = "\n".join(f"│ {f}" for f in d["factors"][:7])
    tf_txt = ""
    if tf_biases:
        tf_lines   = []
        agreements = 0
        for tf, bias in tf_biases.items():
            match = (bias=="bull" and direction=="BUY") or (bias=="bear" and direction=="SELL")
            icon  = "✅" if match else "❌"
            if match: agreements += 1
            tf_lines.append(f"│ {icon} {tf.upper()}: {'Bullish ↑' if bias=='bull' else 'Bearish ↓'}")
        tf_txt = (
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔭 *Multi-TF ({agreements}/{len(tf_biases)} agree):*\n"
            + "\n".join(tf_lines) + "\n"
        )
    news_txt = ""
    if news_warns:
        news_txt = (
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📰 *News Alert:*\n"
            + "\n".join(f"│ {w}" for w in news_warns[:2]) + "\n"
        )
    msg = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{color} *{d['name']}* {dir_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Direction:  *{direction}*\n"
        f"⚡ Confidence: *{conf}* ({score}/{max_score})\n"
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
        f"📋 *Signal Analysis:*\n"
        f"{factors_txt}\n"
        f"{tf_txt}"
        f"{news_txt}"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    return msg, tp, sl

def find_solid_pairs(cid, acc, risk):
    is_open, session, status = get_market_status()
    if not is_open:
        send(cid,
            f"📴 *Market is Currently Closed*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{status}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"_I will notify you when market reopens_ 🔔",
            buttons=MENU)
        return
    send(cid,
        f"🟢 *Market Open*\n"
        f"📍 Session: {session}\n"
        f"⚡ Quality: {status}\n\n"
        f"🔍 Scanning all pairs...\n⏳ Please wait 30-60 seconds")
    news_warns = get_news_warnings()
    if news_warns:
        send(cid, "📰 *News Warning Before Trading:*\n\n" + "\n".join(news_warns[:3]))
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
        try:
            tf_biases = get_tf_bias(d["ticker"])
        except:
            tf_biases = {}
        msg, tp, sl = format_signal(d, acc, risk, tf_biases, news_warns)
        send(cid, msg)
        log_signal(d["name"], d["direction"], d["price"], tp, sl)
        time.sleep(1)

def best_setup(cid, acc, risk):
    is_open, session, status = get_market_status()
    if not is_open:
        send(cid,
            f"📴 *Market is Closed*\n\n{status}\n\n"
            f"_Come back when market reopens!_",
            buttons=MENU)
        return
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
    d    = best
    color = "🟢" if d["direction"] == "BUY" else "🔴"
    send(cid,
        f"🏆 *Best Setup Right Now*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{color} *{d['name']}* — *{d['direction']}*\n"
        f"⭐ Score: {d['score']}/{d['bull']+d['bear']}\n"
        f"📉 RSI: {d['rsi']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"_Tap 📡 Signal for full analysis_")

def notify_market_open():
    s = ls()
    if not s.get("account"):
        return
    send(CHAT_ID,
        "🟢 *Forex Market is Now Open!*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🇦🇺 Sydney session started\n"
        "📈 New trading week begins\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap 📡 Signal to get your first setup!",
        buttons=MENU)

def start_setup(cid):
    set_wait(cid, "waiting_account")
    send(cid,
        "👋 *Welcome to Forex Signal Bot Pro!*\n\n"
        "I scan 8 major pairs and only send you\n"
        "the strongest setups automatically.\n\n"
        "💰 *What is your account balance?*\n"
        "_(Type the amount e.g. 500)_")

def handle_setup(cid, txt, s):
    wait = get_wait(cid)
    if wait == "waiting_account":
        try:
            amt = float(txt.replace("$","").replace(",",""))
            s["account"] = amt; ss(s)
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
            pct = float(txt.replace("%",""))
            if pct > 10:
                send(cid, "⚠️ Too high! Please enter between 1-5%")
                return
            s["risk"] = pct; s["setup_done"] = True; ss(s); clear_wait(cid)
            risk_usd = round(s["account"]*(pct/100), 2)
            send(cid,
                f"🎯 *Setup Complete!*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 Account: ${s['account']}\n"
                f"📊 Risk: {pct}% = ${risk_usd}/trade\n"
                f"💵 Max profit/trade: ${round(risk_usd*2,2)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"All signals personalised for you!\n"
                f"Tap a button below 👇",
                buttons=MENU)
        except:
            send(cid, "❌ Please type just the number e.g. *2*")

def handle(cid, txt):
    s    = ls()
    txt  = txt.strip()
    wait = get_wait(cid)
    if wait in ["waiting_account","waiting_risk"]:
        handle_setup(cid, txt, s); return
    if not s.get("setup_done") and txt.lower() not in ["/start","⚙️ settings"]:
        start_setup(cid); return
    cmd = txt.lower()
    if cmd == "/start":
        if not s.get("setup_done"):
            start_setup(cid)
        else:
            is_open, session, status = get_market_status()
            market_line = f"🟢 {session} | {status}" if is_open else f"📴 Market Closed"
            send(cid,
                f"👋 *Welcome back!*\n\n"
                f"💰 ${s['account']} | {s['risk']}% risk\n"
                f"{market_line}\n\n"
                f"What would you like to do? 👇",
                buttons=MENU)
    elif cmd in ["📡 signal","/signal"]:
        threading.Thread(target=find_solid_pairs, args=(cid,s["account"],s["risk"]), daemon=True).start()
    elif cmd in ["🔍 best setup","/scan"]:
        threading.Thread(target=best_setup, args=(cid,s["account"],s["risk"]), daemon=True).start()
    elif cmd in ["📰 news","/news"]:
        send(cid, get_news(), buttons=MENU)
    elif cmd in ["⚙️ settings","/settings"]:
        start_setup(cid)
    elif cmd in ["💼 portfolio","/portfolio"]:
        send(cid, get_performance(), buttons=MENU)
    elif cmd == "/session":
        is_open, session, status = get_market_status()
        icon = "🟢" if is_open else "📴"
        send(cid,
            f"{icon} *Market Status*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{'🟢 OPEN' if is_open else '📴 CLOSED'}\n"
            f"📍 {session}\n"
            f"⚡ {status}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {now()}",
            buttons=MENU)
    elif cmd == "/strength":
        send(cid, "⏳ Calculating currency strength...", buttons=MENU)
        try:
            strength = get_currency_strength()
            send(cid, format_strength_ranking(strength), buttons=MENU)
        except:
            send(cid, "⚠️ Could not calculate strength right now.", buttons=MENU)
    elif cmd == "/performance":
        send(cid, get_performance(), buttons=MENU)
    elif cmd in ["📓 journal","/journal"]:
        send(cid,
            "📓 *Trade Journal*\n\n"
            "➕ Log trade:\n"
            "`/jadd EURUSD BUY 1.16 1.17 1.155`\n\n"
            "✅ Close trade:\n"
            "`/jclose 0 win` or `/jclose 0 loss`\n\n"
            "📊 Stats: `/jstats`\n"
            "📈 Strength: `/strength`\n"
            "📊 Session: `/session`",
            buttons=MENU)
    elif cmd.startswith("/jadd"):
        p = txt.split()
        try:
            t = {"pair":p[1].upper(),"dir":p[2].upper(),"entry":float(p[3]),
                 "tp":float(p[4]),"sl":float(p[5]),"date":now(),"result":"open"}
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
            send(cid, "No trades yet.", buttons=MENU); return
        cl = [t for t in j if t["result"] in ["win","loss"]]
        w  = len([t for t in cl if t["result"]=="win"])
        wr = round(w/len(cl)*100,1) if cl else 0
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
            pips    = round(abs(ent-sl_p)/pip, 1)
            ru      = round(s["account"]*(s["risk"]/100), 2)
            pip_val = 1.0 if is_gold else 10
            lot     = round(ru/(pips*pip_val), 4) if pips > 0 else 0
            tp      = round(ent+(ent-sl_p)*2 if d=="BUY" else ent-(sl_p-ent)*2, 5)
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

def daily_job():
    s = ls()
    if not s.get("account"):
        return
    is_open, _, _ = get_market_status()
    if not is_open:
        return
    find_solid_pairs(CHAT_ID, s["account"], s["risk"])

def run_scheduler():
    schedule.every().day.at("08:00").do(daily_job)
    schedule.every().sunday.at("21:00").do(notify_market_open)
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
