import os
import requests
import time
import schedule
import threading
import json
from datetime import datetime, timezone
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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

# ── TELEGRAM ───────────────────────────────────────────────────────────────────
def send(cid, txt, buttons=None):
    body = {"chat_id": cid, "text": txt, "parse_mode": "Markdown"}
    if buttons:
        body["reply_markup"] = {"keyboard": buttons, "resize_keyboard": True, "one_time_keyboard": False}
    try:
        requests.post(f"{URL}/sendMessage", json=body, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

def send_photo(cid, filepath, caption=""):
    try:
        with open(filepath, "rb") as f:
            requests.post(f"{URL}/sendPhoto",
                files={"photo": f},
                data={"chat_id": cid, "caption": caption, "parse_mode": "Markdown"},
                timeout=30)
    except Exception as e:
        print(f"Photo error: {e}")

def get_updates(offset=None):
    try:
        r = requests.get(f"{URL}/getUpdates", params={"timeout": 30, "offset": offset}, timeout=35)
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

def load_sig_log():
    try:
        return json.load(open(SIG_LOG))
    except:
        return []

def save_sig_log(d):
    json.dump(d, open(SIG_LOG, "w"))

# ── MARKET STATUS ─────────────────────────────────────────────────────────────
def get_market_status():
    n       = datetime.now(timezone.utc)
    weekday = n.weekday()
    hour    = n.hour
    if weekday == 5:
        return False, "closed", "Market closed — reopens Sunday 21:00 UTC"
    if weekday == 6 and hour < 21:
        return False, "closed", f"Market closed — reopens in ~{21-hour} hours"
    if weekday == 4 and hour >= 21:
        return False, "closed", "Market just closed — reopens Sunday 21:00 UTC"
    sessions = []
    if hour >= 21 or hour < 6:  sessions.append("Sydney")
    if 0  <= hour < 9:          sessions.append("Tokyo")
    if 7  <= hour < 16:         sessions.append("London")
    if 12 <= hour < 21:         sessions.append("New York")
    if not sessions:
        sessions = ["Inter-session"]
    if 8 <= hour < 12:
        quality = "BEST — London session"
    elif 13 <= hour < 17:
        quality = "BEST — London/NY overlap"
    elif 12 <= hour < 21:
        quality = "GOOD — New York session"
    elif 7 <= hour < 16:
        quality = "GOOD — London session"
    else:
        quality = "LOW — Asian session"
    return True, " + ".join(sessions), quality

def is_prime_session():
    """Returns True only during London or NY session — highest win rate times."""
    n    = datetime.now(timezone.utc)
    hour = n.hour
    return 7 <= hour < 21

# ── NEWS & NEWS BLOCKER ────────────────────────────────────────────────────────
def get_news_warnings():
    try:
        r = requests.get(
            "https://api.rss2json.com/v1/api.json",
            params={"rss_url": "https://www.forexlive.com/feed/news"},
            timeout=10)
        items    = r.json().get("items", [])[:10]
        warnings = []
        keywords = ["CPI", "NFP", "FOMC", "GDP", "interest rate", "Federal Reserve",
                    "inflation", "employment", "central bank", "rate decision", "PMI",
                    "nonfarm", "payroll", "bank of england", "ECB", "BOJ"]
        for item in items:
            title = item.get("title", "").upper()
            for kw in keywords:
                if kw.upper() in title:
                    warnings.append(item.get("title", ""))
                    break
        return warnings
    except:
        return []

def is_news_safe():
    """Returns (safe, reason). Blocks trading if high impact news detected."""
    warnings = get_news_warnings()
    if warnings:
        return False, warnings[:2]
    return True, []

def get_news():
    try:
        items = requests.get(
            "https://api.rss2json.com/v1/api.json",
            params={"rss_url": "https://www.forexlive.com/feed/news"},
            timeout=10).json().get("items", [])[:6]
        if not items:
            return "No news available right now."
        lines = ["📰 *Latest Forex News*\n" + "━"*22]
        for item in items:
            lines.append(f"• {item.get('title','')}")
        lines.append(f"\n⏰ {now()}")
        return "\n".join(lines)
    except:
        return "Could not fetch news right now."

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
    for i in range(1, min(period+1, len(closes))):
        diff = closes[i] - closes[i-1]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_g = sum(gains)/period if gains else 0.001
    avg_l = sum(losses)/period if losses else 0.001
    return round(100-(100/(1+avg_g/avg_l)), 1)

def calc_volume_strength(volumes):
    """Checks if recent volume is above average — confirms institutional interest."""
    if len(volumes) < 10:
        return False, "Not enough volume data"
    avg_vol    = sum(volumes[-20:]) / min(20, len(volumes))
    recent_vol = volumes[-1]
    if recent_vol > avg_vol * 1.3:
        return True, f"High volume confirmation (+{round((recent_vol/avg_vol-1)*100)}% above average)"
    elif recent_vol > avg_vol * 0.8:
        return None, f"Normal volume (within average range)"
    else:
        return False, f"Low volume — weak signal, institutions not active"

def detect_candles(opens, highs, lows, closes):
    patterns = []
    if len(closes) < 3:
        return patterns
    o1,h1,l1,c1 = opens[-2],highs[-2],lows[-2],closes[-2]
    o2,h2,l2,c2 = opens[-1],highs[-1],lows[-1],closes[-1]
    body2  = abs(c2-o2)
    range2 = h2-l2 if h2-l2>0 else 0.0001
    if c1<o1 and c2>o2 and c2>o1 and o2<c1:
        patterns.append(("bullish_engulfing","Bullish Engulfing candle — strong BUY confirmation",2))
    if c1>o1 and c2<o2 and c2<o1 and o2>c1:
        patterns.append(("bearish_engulfing","Bearish Engulfing candle — strong SELL confirmation",2))
    lower_wick = min(o2,c2)-l2
    upper_wick = h2-max(o2,c2)
    if lower_wick>body2*2 and upper_wick<body2*0.5:
        patterns.append(("pin_bar_bull","Bullish Pin Bar — buyers rejected lower prices",1))
    if upper_wick>body2*2 and lower_wick<body2*0.5:
        patterns.append(("pin_bar_bear","Bearish Pin Bar — sellers rejected higher prices",1))
    if body2<range2*0.1:
        patterns.append(("doji","Doji candle — market indecision, wait for confirmation",0))
    return patterns

def detect_structure(closes, highs, lows):
    if len(closes)<10:
        return "unknown","Not enough data for market structure"
    rh=highs[-10:]; rl=lows[-10:]
    hh=rh[-1]>max(rh[:-1]); hl=rl[-1]>min(rl[:-1])
    lh=rh[-1]<max(rh[:-1]); ll=rl[-1]<min(rl[:-1])
    if hh and hl:   return "bullish","Market structure: Higher Highs + Higher Lows — Uptrend"
    elif lh and ll: return "bearish","Market structure: Lower Highs + Lower Lows — Downtrend"
    elif hh and ll: return "breakout","Market structure: Expansion — possible breakout"
    else:           return "ranging","Market structure: Ranging — no clear trend"

# ── MULTI-TIMEFRAME (STRICT) ───────────────────────────────────────────────────
def get_tf_bias(ticker):
    """Gets bias for 1H, 4H, and Daily. All must agree for high confidence."""
    biases = {}
    for tf_name, period, interval in [("1h","1mo","1h"), ("4h","3mo","1h"), ("1d","3mo","1d")]:
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
            biases[tf_name] = "bull" if e50>e200 else "bear"
        except:
            pass
        time.sleep(0.3)
    return biases

def all_timeframes_agree(biases, direction):
    """Returns True only if ALL available timeframes agree with the signal direction."""
    if not biases:
        return False
    expected = "bull" if direction == "BUY" else "bear"
    return all(bias == expected for bias in biases.values())

# ── FETCH DATA ─────────────────────────────────────────────────────────────────
def fetch(ticker, period, interval):
    try:
        h = yf.Ticker(ticker).history(period=period, interval=interval)
        if h is None or h.empty:
            return None
        return h
    except Exception as e:
        print(f"Fetch error {ticker}: {e}")
        return None

# ── SCORE PAIR ─────────────────────────────────────────────────────────────────
def score_pair(name, ticker):
    is_gold = "XAU" in name
    is_jpy  = "JPY" in name
    daily   = fetch(ticker, "3mo", "1d")
    if daily is None or len(daily) < 21:
        return None
    closes  = daily["Close"].tolist()
    highs   = daily["High"].tolist()
    lows    = daily["Low"].tolist()
    opens   = daily["Open"].tolist()
    volumes = daily["Volume"].tolist() if "Volume" in daily.columns else []
    price   = round(closes[-1], 2 if is_gold else 3 if is_jpy else 5)
    ema50   = calc_ema(closes[-50:] if len(closes)>=50 else closes, 50)
    ema200  = calc_ema(closes[-200:] if len(closes)>=200 else closes, 200)
    rsi     = calc_rsi(closes[-30:] if len(closes)>=30 else closes)
    chg     = round(((closes[-1]-closes[-2])/closes[-2])*100, 3)
    r_high  = round(max(highs[-20:]), 5)
    r_low   = round(min(lows[-20:]),  5)
    rng     = r_high - r_low
    pos     = (price-r_low)/rng if rng>0 else 0.5
    ema_gap = round(abs(ema50-ema200)/price*100, 3)

    bull = 0; bear = 0; factors = []

    # 1. EMA Trend (weight 2)
    if ema50 > ema200:
        bull += 2; factors.append("EMA trend: Bullish — EMA50 above EMA200")
    else:
        bear += 2; factors.append("EMA trend: Bearish — EMA50 below EMA200")

    # 2. RSI (weight 2)
    if rsi < 35:
        bull += 2; factors.append(f"RSI {rsi} — Oversold, price likely to rise")
    elif rsi > 65:
        bear += 2; factors.append(f"RSI {rsi} — Overbought, price likely to fall")
    elif rsi < 48:
        bull += 1; factors.append(f"RSI {rsi} — Slightly below midpoint")
    else:
        bear += 1; factors.append(f"RSI {rsi} — Slightly above midpoint")

    # 3. Momentum (weight 1)
    if chg > 0.1:
        bull += 1; factors.append(f"Strong upward momentum (+{chg}%)")
    elif chg < -0.1:
        bear += 1; factors.append(f"Strong downward momentum ({chg}%)")
    else:
        factors.append(f"Weak momentum ({chg}%)")

    # 4. Support/Resistance (weight 1)
    if pos < 0.25:
        bull += 1; factors.append("Price near support level — good BUY zone")
    elif pos > 0.75:
        bear += 1; factors.append("Price near resistance level — good SELL zone")
    else:
        factors.append("Price in middle of range")

    # 5. EMA Strength (weight 1)
    if ema_gap > 0.15:
        if ema50 > ema200: bull += 1
        else: bear += 1
        factors.append(f"Strong trend — EMAs well separated ({ema_gap}%)")
    else:
        factors.append(f"Weak trend — EMAs close together ({ema_gap}%)")

    # 6. Candlestick patterns (weight 1-2)
    candles = detect_candles(opens, highs, lows, closes)
    for ctype, cdesc, cscore in candles:
        if "bull" in ctype:   bull += cscore; factors.append(cdesc)
        elif "bear" in ctype: bear += cscore; factors.append(cdesc)
        else:                 factors.append(cdesc)

    # 7. Market Structure (weight 1)
    struct, struct_desc = detect_structure(closes, highs, lows)
    if struct == "bullish":   bull += 1; factors.append(struct_desc)
    elif struct == "bearish": bear += 1; factors.append(struct_desc)
    else:                     factors.append(struct_desc)

    # 8. Volume confirmation (weight 1)
    if volumes:
        vol_strong, vol_desc = calc_volume_strength(volumes)
        if vol_strong is True:
            if ema50 > ema200: bull += 1
            else: bear += 1
            factors.append(f"✅ {vol_desc}")
        elif vol_strong is False:
            factors.append(f"⚠️ {vol_desc}")
        else:
            factors.append(f"Volume: {vol_desc}")

    is_buy  = bull > bear
    score   = bull if is_buy else bear
    max_s   = bull + bear

    return {
        "name": name, "ticker": ticker, "price": price,
        "direction": "BUY" if is_buy else "SELL",
        "score": score, "bull": bull, "bear": bear, "max_score": max_s,
        "rsi": rsi, "ema50": ema50, "ema200": ema200,
        "r_high": r_high, "r_low": r_low,
        "factors": factors, "is_gold": is_gold, "is_jpy": is_jpy,
    }

# ── FORMAT SIGNAL ─────────────────────────────────────────────────────────────
def format_signal(d, acc, risk, tf_biases=None, tf_agree=False):
    price     = d["price"]; direction = d["direction"]
    score     = d["score"]; max_score = d["max_score"]
    is_gold   = d["is_gold"]; is_jpy = d["is_jpy"]

    pct = round((score/max_score)*100) if max_score>0 else 50
    if pct >= 80:   conf = "VERY HIGH"
    elif pct >= 65: conf = "HIGH"
    elif pct >= 55: conf = "MEDIUM"
    else:           conf = "LOW — Consider waiting"

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
    lot      = round(risk_usd/(sl_pips*pip_val), 4) if sl_pips>0 else 0
    profit   = round(risk_usd*2, 2)

    factors_txt = "\n".join(f"  {i+1}. {f}" for i,f in enumerate(d["factors"][:8]))

    tf_txt = ""
    if tf_biases:
        tf_lines = []; agreements = 0
        for tf, bias in tf_biases.items():
            match = (bias=="bull" and direction=="BUY") or (bias=="bear" and direction=="SELL")
            icon  = "✅" if match else "❌"
            if match: agreements += 1
            tf_lines.append(f"  {icon} {tf.upper()}: {'Bullish' if bias=='bull' else 'Bearish'}")
        agree_txt = "ALL AGREE ✅" if tf_agree else f"{agreements}/{len(tf_biases)} agree"
        tf_txt = (
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"TIMEFRAME CHECK — {agree_txt}\n"
            + "\n".join(tf_lines) + "\n"
        )

    msg = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{'🟢' if direction=='BUY' else '🔴'} *{d['name']}  —  {direction}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Confidence:   *{conf}*  ({pct}%)\n"
        f"Score:        {score}/{max_score} factors confirmed\n"
        f"Time:         {now()}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Entry:        `{price}`\n"
        f"Take Profit:  `{tp}`\n"
        f"Stop Loss:    `{sl}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Account:      ${acc}\n"
        f"Risk Amount:  ${risk_usd}  ({risk}%)\n"
        f"Lot Size:     {lot}\n"
        f"Potential:    ${profit}\n"
        f"R:R Ratio:    1:2\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"ANALYSIS\n"
        f"{factors_txt}\n"
        f"{tf_txt}"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    return msg, tp, sl

# ── CHART GENERATOR ────────────────────────────────────────────────────────────
def generate_chart(name, ticker, direction, entry, tp, sl, ema50_val, ema200_val):
    try:
        h = yf.Ticker(ticker).history(period="1mo", interval="1d")
        if h is None or h.empty or len(h) < 5:
            return None
        h      = h.tail(40)
        opens  = h["Open"].tolist()
        highs  = h["High"].tolist()
        lows   = h["Low"].tolist()
        closes = h["Close"].tolist()
        xs     = list(range(len(closes)))

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8),
                                        gridspec_kw={"height_ratios": [3, 1]},
                                        facecolor="#0d1117")
        for ax in [ax1, ax2]:
            ax.set_facecolor("#0d1117")
            ax.tick_params(colors="#8b949e", labelsize=8)
            for spine in ax.spines.values():
                spine.set_color("#30363d")

        for i in xs:
            o, h_val, l, c = opens[i], highs[i], lows[i], closes[i]
            color = "#3fb950" if c >= o else "#f85149"
            ax1.plot([i, i], [l, h_val], color=color, linewidth=1, zorder=2)
            ax1.bar(i, abs(c-o), bottom=min(o,c), color=color, width=0.7, alpha=0.95, zorder=3)

        ax1.axhline(ema50_val,  color="#58a6ff", linewidth=1.5, linestyle="--",
                    alpha=0.9, label=f"EMA50  {round(ema50_val,5)}", zorder=4)
        ax1.axhline(ema200_val, color="#e3b341", linewidth=1.5, linestyle="--",
                    alpha=0.9, label=f"EMA200 {round(ema200_val,5)}", zorder=4)
        ax1.axhline(entry, color="#ffffff", linewidth=1.8, linestyle="-",
                    alpha=1.0, label=f"Entry  {entry}", zorder=5)
        ax1.axhline(tp, color="#3fb950", linewidth=1.8, linestyle="-",
                    alpha=1.0, label=f"TP     {tp}", zorder=5)
        ax1.axhline(sl, color="#f85149", linewidth=1.8, linestyle="-",
                    alpha=1.0, label=f"SL     {sl}", zorder=5)

        ax1.fill_between(xs, entry, tp,
                         color="#3fb950" if direction=="BUY" else "#f85149", alpha=0.07)
        ax1.fill_between(xs, entry, sl,
                         color="#f85149" if direction=="BUY" else "#3fb950", alpha=0.07)

        dir_color = "#3fb950" if direction=="BUY" else "#f85149"
        dir_icon  = "▲ BUY" if direction=="BUY" else "▼ SELL"
        ax1.set_title(f"  {name}  |  {dir_icon}  |  Daily Chart",
                      color=dir_color, fontsize=14, fontweight="bold", loc="left", pad=12)
        ax1.legend(loc="upper left", facecolor="#161b22", edgecolor="#30363d",
                   labelcolor="#c9d1d9", fontsize=8, framealpha=0.9)
        ax1.set_xlim(-1, len(xs))
        ax1.set_xticks([])
        ax1.set_ylabel("Price", color="#8b949e", fontsize=9)
        ax1.grid(axis="y", color="#21262d", linewidth=0.5, zorder=1)

        rsi_vals = [calc_rsi(closes[max(0,j-14):j+1]) for j in range(len(closes))]
        ax2.plot(xs, rsi_vals, color="#bc8cff", linewidth=1.5)
        ax2.axhline(70, color="#f85149", linewidth=0.8, linestyle="--", alpha=0.6)
        ax2.axhline(30, color="#3fb950", linewidth=0.8, linestyle="--", alpha=0.6)
        ax2.axhline(50, color="#8b949e", linewidth=0.5, linestyle="--", alpha=0.4)
        ax2.fill_between(xs, rsi_vals, 50,
                         where=[r>=50 for r in rsi_vals], color="#bc8cff", alpha=0.12)
        ax2.fill_between(xs, rsi_vals, 50,
                         where=[r<50 for r in rsi_vals], color="#bc8cff", alpha=0.06)
        ax2.set_ylim(0, 100)
        ax2.set_xlim(-1, len(xs))
        ax2.set_ylabel("RSI", color="#8b949e", fontsize=9)
        ax2.set_xticks([])
        ax2.grid(axis="y", color="#21262d", linewidth=0.5)

        fig.text(0.98, 0.02, "SamSos Forex Bot", color="#30363d", fontsize=9,
                 ha="right", va="bottom")
        plt.tight_layout(pad=1.5)
        path = f"/tmp/chart_{name}.png"
        plt.savefig(path, dpi=110, bbox_inches="tight", facecolor="#0d1117")
        plt.close()
        return path
    except Exception as e:
        print(f"Chart error: {e}")
        return None

# ── CURRENCY STRENGTH ─────────────────────────────────────────────────────────
def get_currency_strength():
    currencies = ["USD","EUR","GBP","JPY","CAD","AUD","NZD","CHF"]
    strength   = {c: 0 for c in currencies}
    pairs_map  = {
        "EURUSD=X":("EUR","USD"), "GBPUSD=X":("GBP","USD"),
        "USDJPY=X":("USD","JPY"), "USDCAD=X":("USD","CAD"),
        "AUDUSD=X":("AUD","USD"), "NZDUSD=X":("NZD","USD"),
        "USDCHF=X":("USD","CHF"), "EURGBP=X":("EUR","GBP"),
    }
    for ticker,(base,quote) in pairs_map.items():
        try:
            h = yf.Ticker(ticker).history(period="5d", interval="1d")
            if h is None or len(h)<2: continue
            closes = h["Close"].tolist()
            chg = (closes[-1]-closes[-2])/closes[-2]
            strength[base]+=chg; strength[quote]-=chg
        except: pass
        time.sleep(0.3)
    return strength

def format_strength_ranking(strength):
    ranked = sorted(strength.items(), key=lambda x: x[1], reverse=True)
    lines  = ["📊 *Currency Strength*\n"+"━"*22]
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"]
    for i,(cur,score) in enumerate(ranked):
        bar   = "█" * min(int(abs(score)*500)+1, 8)
        trend = "▲" if score>0 else "▼"
        lines.append(f"{medals[i]} *{cur}* {trend} {bar}")
    strongest = ranked[0][0]; weakest = ranked[-1][0]
    lines.append(f"\nBest Setup: BUY {strongest}/{weakest}")
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
        return "No signals tracked yet.\nSignals are auto-tracked when you tap Signal."
    closed = [s for s in log if s["result"] in ["win","loss"]]
    wins   = len([s for s in closed if s["result"]=="win"])
    wr     = round(wins/len(closed)*100,1) if closed else 0
    open_c = len([s for s in log if s["result"]=="open"])
    lines  = [
        "📊 *Signal Performance*\n"+"━"*22,
        f"Total Signals: {len(log)}",
        f"Wins: {wins}  |  Losses: {len(closed)-wins}",
        f"Win Rate: {wr}%",
        f"Open Signals: {open_c}",
        "━"*22,
        "Excellent!" if wr>=60 else "Keep improving." if wr>=45 else "Review your entries.",
    ]
    return "\n".join(lines)

# ── MAIN SCANNER ─────────────────────────────────────────────────────────────
def find_solid_pairs(cid, acc, risk):
    is_open, session, status = get_market_status()
    if not is_open:
        send(cid,
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📴 *MARKET CLOSED*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{status}\n\n"
            f"I will notify you when market reopens.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━",
            buttons=MENU)
        return

    # Check session quality
    prime = is_prime_session()
    if not prime:
        send(cid,
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ *LOW QUALITY SESSION*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Session: {session}\n"
            f"Quality: {status}\n\n"
            f"Best signals come during London (07:00-16:00 UTC)\n"
            f"or New York (12:00-21:00 UTC) sessions.\n\n"
            f"Scanning anyway — but be extra cautious.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━")
    else:
        send(cid,
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 *MARKET OPEN*\n"
            f"Session: {session}\n"
            f"Quality: {status}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Scanning 8 pairs... please wait 30-60 seconds.")

    # Check news safety
    news_safe, news_warnings = is_news_safe()
    if not news_safe:
        send(cid,
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ *HIGH IMPACT NEWS DETECTED*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(f"• {w}" for w in news_warnings)
            + f"\n\nSignals sent but trade with caution.\n"
            f"Consider waiting for news to pass.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━")

    results = []
    for name, ticker in ALL_PAIRS.items():
        try:
            data = score_pair(name, ticker)
            if data:
                results.append(data)
        except Exception as e:
            print(f"Score error {name}: {e}")
        time.sleep(1)

    # STRICT FILTER: minimum score 6, all timeframes must agree
    premium = []
    for r in results:
        try:
            tf_biases = get_tf_bias(r["ticker"])
            r["tf_biases"] = tf_biases
            r["tf_agree"]  = all_timeframes_agree(tf_biases, r["direction"])
            pct = round((r["score"]/r["max_score"])*100) if r["max_score"]>0 else 0
            if pct >= 65 and r["tf_agree"]:
                premium.append(r)
        except:
            r["tf_biases"] = {}
            r["tf_agree"]  = False
        time.sleep(1)

    premium.sort(key=lambda x: x["score"], reverse=True)

    if not premium:
        # Fallback: top 2 by score even if not all TFs agree
        fallback = sorted(results, key=lambda x: x["score"], reverse=True)[:2]
        send(cid,
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ No premium setups right now.\n"
            "Timeframes not fully aligned.\n\n"
            "Showing top 2 available — trade small or wait.\n"
            "━━━━━━━━━━━━━━━━━━━━━━")
        for d in fallback:
            tf_biases = d.get("tf_biases", {})
            tf_agree  = d.get("tf_agree", False)
            msg, tp, sl = format_signal(d, acc, risk, tf_biases, tf_agree)
            chart_path = generate_chart(d["name"],d["ticker"],d["direction"],
                                        d["price"],tp,sl,d["ema50"],d["ema200"])
            if chart_path:
                send_photo(cid, chart_path, caption=f"*{d['name']}* — {d['direction']}")
            send(cid, msg)
            log_signal(d["name"],d["direction"],d["price"],tp,sl)
            time.sleep(1)
    else:
        send(cid,
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ *{len(premium)} PREMIUM SETUP(S) FOUND*\n"
            f"All timeframes aligned — highest confidence.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━")
        for d in premium:
            tf_biases = d.get("tf_biases", {})
            tf_agree  = d.get("tf_agree", False)
            msg, tp, sl = format_signal(d, acc, risk, tf_biases, tf_agree)
            chart_path = generate_chart(d["name"],d["ticker"],d["direction"],
                                        d["price"],tp,sl,d["ema50"],d["ema200"])
            if chart_path:
                send_photo(cid, chart_path, caption=f"*{d['name']}* — {d['direction']}")
            send(cid, msg)
            log_signal(d["name"],d["direction"],d["price"],tp,sl)
            time.sleep(1)

def best_setup(cid, acc, risk):
    is_open, session, status = get_market_status()
    if not is_open:
        send(cid,
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📴 *MARKET CLOSED*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{status}",
            buttons=MENU)
        return
    send(cid, "Finding best setup...", buttons=MENU)
    results = []
    for name, ticker in ALL_PAIRS.items():
        try:
            data = score_pair(name, ticker)
            if data: results.append(data)
        except: pass
        time.sleep(1)
    if not results:
        send(cid, "Could not fetch data. Try again."); return
    best = sorted(results, key=lambda x: x["score"], reverse=True)[0]
    d    = best
    color = "🟢" if d["direction"]=="BUY" else "🔴"
    chart_path = generate_chart(d["name"],d["ticker"],d["direction"],
                                d["price"],
                                round(d["price"]+(0.003 if d["direction"]=="BUY" else -0.003),5),
                                round(d["price"]-(0.0015 if d["direction"]=="BUY" else -0.0015),5),
                                d["ema50"],d["ema200"])
    if chart_path:
        send_photo(cid, chart_path, caption=f"Best Setup: *{d['name']}*")
    pct = round((d["score"]/d["max_score"])*100) if d["max_score"]>0 else 0
    send(cid,
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 *BEST SETUP RIGHT NOW*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{color} Pair:       *{d['name']}*\n"
        f"Direction:  *{d['direction']}*\n"
        f"Confidence: {pct}%\n"
        f"RSI:        {d['rsi']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Tap Signal for full analysis.")

def notify_market_open():
    s = ls()
    if not s.get("account"): return
    send(CHAT_ID,
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 *MARKET NOW OPEN*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Sydney session has started.\n"
        "New trading week begins.\n\n"
        "Tap Signal to get your first setup.",
        buttons=MENU)

# ── SETUP FLOW ────────────────────────────────────────────────────────────────
def start_setup(cid):
    set_wait(cid, "waiting_account")
    send(cid,
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "👋 *FOREX SIGNAL BOT PRO*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "I scan 8 major pairs and send you\n"
        "only the strongest setups with real charts.\n\n"
        "First, let me personalise your risk settings.\n\n"
        "What is your account balance?\n"
        "_(Type the amount e.g. 500)_")

def handle_setup(cid, txt, s):
    wait = get_wait(cid)
    if wait == "waiting_account":
        try:
            amt = float(txt.replace("$","").replace(",",""))
            s["account"] = amt; ss(s); set_wait(cid,"waiting_risk")
            send(cid,
                f"Account set: *${amt}*\n\n"
                f"What % risk per trade?\n\n"
                f"  Safe:       1% = ${round(amt*0.01,2)}/trade\n"
                f"  Moderate:   2% = ${round(amt*0.02,2)}/trade\n"
                f"  Aggressive: 3% = ${round(amt*0.03,2)}/trade\n\n"
                f"_(Type a number e.g. 2)_")
        except:
            send(cid, "Please type just the number e.g. *500*")
    elif wait == "waiting_risk":
        try:
            pct = float(txt.replace("%",""))
            if pct > 10:
                send(cid, "Too high. Please enter between 1-5%"); return
            s["risk"] = pct; s["setup_done"] = True; ss(s); clear_wait(cid)
            risk_usd = round(s["account"]*(pct/100), 2)
            send(cid,
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ *SETUP COMPLETE*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Account:        ${s['account']}\n"
                f"Risk per trade: {pct}% = ${risk_usd}\n"
                f"Max profit:     ${round(risk_usd*2,2)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"All signals are now personalised for you.\n"
                f"Tap a button to get started.",
                buttons=MENU)
        except:
            send(cid, "Please type just the number e.g. *2*")

# ── COMMAND HANDLER ───────────────────────────────────────────────────────────
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
            market_line = f"🟢 {session}" if is_open else "📴 Market Closed"
            send(cid,
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👋 *FOREX SIGNAL BOT PRO*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Account: ${s['account']}  |  Risk: {s['risk']}%\n"
                f"Status:  {market_line}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Select an option below.",
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
        prime = is_prime_session()
        send(cid,
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{'🟢 MARKET OPEN' if is_open else '📴 MARKET CLOSED'}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Session: {session}\n"
            f"Quality: {status}\n"
            f"Prime:   {'Yes — good time to trade' if prime else 'No — wait for London/NY'}\n"
            f"Time:    {now()}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━",
            buttons=MENU)

    elif cmd == "/strength":
        send(cid, "Calculating currency strength...", buttons=MENU)
        try:
            strength = get_currency_strength()
            send(cid, format_strength_ranking(strength), buttons=MENU)
        except:
            send(cid, "Could not calculate strength right now.", buttons=MENU)

    elif cmd == "/performance":
        send(cid, get_performance(), buttons=MENU)

    elif cmd in ["📓 journal","/journal"]:
        send(cid,
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "*TRADE JOURNAL*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Log a trade:\n"
            "`/jadd EURUSD BUY 1.16 1.17 1.155`\n\n"
            "Close a trade:\n"
            "`/jclose 0 win`\n"
            "`/jclose 0 loss`\n\n"
            "View stats:  `/jstats`\n"
            "Session:     `/session`\n"
            "Strength:    `/strength`\n"
            "Performance: `/performance`",
            buttons=MENU)

    elif cmd.startswith("/jadd"):
        p = txt.split()
        try:
            t = {"pair":p[1].upper(),"dir":p[2].upper(),"entry":float(p[3]),
                 "tp":float(p[4]),"sl":float(p[5]),"date":now(),"result":"open"}
            j = lj(); j.append(t); sj(j)
            rr = round(abs(t["tp"]-t["entry"])/abs(t["sl"]-t["entry"]), 2)
            send(cid,
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ *TRADE #{len(j)-1} LOGGED*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Pair:      {t['pair']}\n"
                f"Direction: {t['dir']}\n"
                f"Entry:     {t['entry']}\n"
                f"TP:        {t['tp']}\n"
                f"SL:        {t['sl']}\n"
                f"R:R:       1:{rr}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━",
                buttons=MENU)
        except:
            send(cid, "Use: `/jadd EURUSD BUY 1.16 1.17 1.155`", buttons=MENU)

    elif cmd.startswith("/jclose"):
        p = txt.split()
        try:
            j = lj(); j[int(p[1])]["result"] = p[2]; sj(j)
            send(cid, f"Trade #{p[1]} marked *{p[2].upper()}*", buttons=MENU)
        except:
            send(cid, "Use: `/jclose 0 win`", buttons=MENU)

    elif cmd == "/jstats":
        j = lj()
        if not j:
            send(cid, "No trades logged yet.", buttons=MENU); return
        cl = [t for t in j if t["result"] in ["win","loss"]]
        w  = len([t for t in cl if t["result"]=="win"])
        wr = round(w/len(cl)*100,1) if cl else 0
        send(cid,
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*JOURNAL STATS*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Total:    {len(j)}\n"
            f"Wins:     {w}\n"
            f"Losses:   {len(cl)-w}\n"
            f"Win Rate: {wr}%\n"
            f"Open:     {len([t for t in j if t['result']=='open'])}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━",
            buttons=MENU)

    elif cmd.startswith("/risk"):
        p = txt.split()
        try:
            pair    = p[1].upper(); d = p[2].upper()
            ent     = float(p[3]);  sl_p = float(p[4])
            is_gold = "XAU" in pair; is_jpy = "JPY" in pair
            pip     = 1.0 if is_gold else (0.01 if is_jpy else 0.0001)
            pips    = round(abs(ent-sl_p)/pip, 1)
            ru      = round(s["account"]*(s["risk"]/100), 2)
            pip_val = 1.0 if is_gold else 10
            lot     = round(ru/(pips*pip_val), 4) if pips>0 else 0
            tp      = round(ent+(ent-sl_p)*2 if d=="BUY" else ent-(sl_p-ent)*2, 5)
            send(cid,
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧮 *RISK CALCULATOR*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Pair:       {pair}\n"
                f"Direction:  {d}\n"
                f"Entry:      {ent}\n"
                f"Stop Loss:  {sl_p}  ({pips} pips)\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Account:    ${s['account']}\n"
                f"Risk:       ${ru}  ({s['risk']}%)\n"
                f"Lot Size:   {lot}\n"
                f"Take Profit:{tp}\n"
                f"Profit:     ${round(ru*2,2)}\n"
                f"R:R Ratio:  1:2\n"
                f"━━━━━━━━━━━━━━━━━━━━━━",
                buttons=MENU)
        except:
            send(cid, "Use: `/risk EURUSD BUY 1.1620 1.1580`", buttons=MENU)

# ── SCHEDULER ────────────────────────────────────────────────────────────────
def daily_job():
    s = ls()
    if not s.get("account"): return
    is_open,_,_ = get_market_status()
    if not is_open: return
    find_solid_pairs(CHAT_ID, s["account"], s["risk"])

def run_scheduler():
    schedule.every().day.at("08:00").do(daily_job)
    schedule.every().sunday.at("21:00").do(notify_market_open)
    while True:
        schedule.run_pending()
        time.sleep(30)

# ── MAIN ─────────────────────────────────────────────────────────────────────
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
