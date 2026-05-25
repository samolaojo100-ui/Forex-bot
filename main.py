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
    n    = datetime.now(timezone.utc)
    hour = n.hour
    return 7 <= hour < 21

def get_news_warnings():
    try:
        r = requests.get(
            "https://api.rss2json.com/v1/api.json",
            params={"rss_url": "https://www.forexlive.com/feed/news"},
            timeout=10)
        items    = r.json().get("items", [])[:10]
        warnings = []
        keywords = ["CPI","NFP","FOMC","GDP","interest rate","Federal Reserve",
                    "inflation","employment","central bank","rate decision","PMI",
                    "nonfarm","payroll","bank of england","ECB","BOJ"]
        for item in items:
            title = item.get("title","").upper()
            for kw in keywords:
                if kw.upper() in title:
                    warnings.append(item.get("title",""))
                    break
        return warnings
    except:
        return []

def is_news_safe():
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
    if len(volumes) < 10:
        return False, "Not enough volume data"
    avg_vol    = sum(volumes[-20:]) / min(20, len(volumes))
    recent_vol = volumes[-1]
    if recent_vol > avg_vol * 1.3:
        return True, f"High volume — institutions active"
    elif recent_vol > avg_vol * 0.8:
        return None, f"Normal volume"
    else:
        return False, f"Low volume — weak signal"
