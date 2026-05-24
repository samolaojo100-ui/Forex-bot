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