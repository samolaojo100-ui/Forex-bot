import os
import requests
import time
import schedule
import threading
from datetime import datetime, timezone
import json

# ── ENV VARS ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")
GEMINI_KEY      = os.getenv("GEMINI_KEY")
CHAT_ID         = os.getenv("CHAT_ID")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ✅ ONLY PAIRS SUPPORTED BY TWELVEDATA FREE PLAN
SCAN_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY",
    "USD/CAD", "AUD/USD", "USD/CHF",
    "NZD/USD", "EUR/JPY", "GBP/JPY",
    "AUD/JPY", "EUR/GBP", "EUR/AUD",
    "GBP/AUD", "AUD/CAD", "CAD/JPY"
]

# ✅ RISK PROFILES
RISK_PROFILES = {
    "1": {"label": "🟢 Normal",     "pct": 0.5,  "desc": "0.5% per trade — safest"},
    "2": {"label": "🟡 Moderate",   "pct": 1.0,  "desc": "1.0% per trade — balanced"},
    "3": {"label": "🔴 Aggressive", "pct": 2.0,  "desc": "2.0% per trade — higher risk"},
}

# ── USER SETTINGS ─────────────────────────────────────────────────────────────
user_settings: dict[str, dict] = {}
pending_signal: dict[str, dict] = {}

def get_settings(chat_id: str) -> dict:
    cid = str(chat_id)
    if cid not in user_settings:
        user_settings[cid] = {"account": None, "risk_pct": None}
    return user_settings[cid]

# ── PRICE ALERTS ──────────────────────────────────────────────────────────────
price_alerts: list[dict] = []

def check_price_alerts():
    while True:
        triggered = []
        for alert in price_alerts:
            try:
                candles = get_candles(alert["pair"], "5min", 1)
                if not candles:
                    continue
                current_price = float(candles[0]["close"])
                hit = (
                    (alert["direction"] == "above" and current_price >= alert["price"]) or
                    (alert["direction"] == "below" and current_price <= alert["price"])
                )
                if hit:
                    send_message(alert["chat_id"],
                        f"🔔 *PRICE ALERT TRIGGERED!*\n\n"
                        f"*{alert['pair']}* has reached *{current_price}*\n"
                        f"Your alert was set at *{alert['price']}*\n\n"
                        f"⚡ Run `/analyze {alert['pair'].replace('/', '')}` now!"
                    )
                    triggered.append(alert)
            except Exception as e:
                print(f"[check_price_alerts] error: {e}")
        for t in triggered:
            price_alerts.remove(t)
        time.sleep(60)

# ── TELEGRAM HELPERS ──────────────────────────────────────────────────────────
def send_message(chat_id, text: str):
    try:
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id":    chat_id,
            "text":       text,
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

# ── SET COMMAND MENU ──────────────────────────────────────────────────────────
def set_bot_commands():
    commands = [
        {"command": "start",        "description": "Welcome and all commands"},
        {"command": "signal",       "description": "Smart scan all pairs for best signals"},
        {"command": "analyze",      "description": "Analyze one pair e.g analyze EURUSD"},
        {"command": "pairs",        "description": "List all scannable pairs"},
        {"command": "news",         "description": "AI market context e.g news EURUSD"},
        {"command": "alert",        "description": "Set price alert e.g alert EURUSD above 1.1200"},
        {"command": "alerts",       "description": "View your active alerts"},
        {"command": "cancelalerts", "description": "Cancel all your alerts"},
        {"command": "settings",     "description": "View your current settings"},
        {"command": "reset",        "description": "Reset account and risk profile"},
        {"command": "app",          "description": "Open SOS Trading Mini App"},
    ]
    try:
        r = requests.post(f"{BASE_URL}/setMyCommands",
                          json={"commands": commands}, timeout=10)
        if r.json().get("result"):
            print("✅ Command menu registered.")
    except Exception as e:
        print(f"[set_bot_commands] error: {e}")

# ── MARKET DATA ───────────────────────────────────────────────────────────────
def get_candles(pair: str, interval: str = "1day", size: int = 50):
    try:
        r = requests.get("https://api.twelvedata.com/time_series", params={
            "symbol":     pair,
            "interval":   interval,
            "outputsize": size,
            "apikey":     TWELVE_DATA_KEY
        }, timeout=10)
        data = r.json()
        if data.get("status") == "error":
            return None
        values = data.get("values")
        if not values or len(values) < 10:
            return None
        return values
    except Exception as e:
        print(f"[get_candles] exception: {e}")
        return None

# ── INDICATORS ────────────────────────────────────────────────────────────────
def calc_atr(candles: list, period: int = 14) -> float:
    trs = []
    for i in range(min(period, len(candles) - 1)):
        c          = candles[i]
        p          = candles[i + 1]
        high       = float(c["high"])
        low        = float(c["low"])
        prev_close = float(p["close"])
        tr = max(high - low,
                 abs(high - prev_close),
                 abs(low  - prev_close))
        trs.append(tr)
    return round(sum(trs) / len(trs), 5) if trs else 0.0

def calc_ema(closes: list, period: int) -> float:
    if len(closes) < period:
        return 0.0
    k   = 2 / (period + 1)
    ema = sum(closes[-period:]) / period
    for price in reversed(closes[:-period]):
        ema = price * k + ema * (1 - k)
    return round(ema, 5)

def calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(period):
        change = closes[i] - closes[i + 1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calc_macd(closes: list) -> tuple[float, float, float]:
    if len(closes) < 35:
        return 0.0, 0.0, 0.0
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd  = round(ema12 - ema26, 6)
    macd_history = []
    for i in range(9):
        e12 = calc_ema(closes[i:], 12)
        e26 = calc_ema(closes[i:], 26)
        macd_history.append(e12 - e26)
    signal    = round(sum(macd_history) / len(macd_history), 6)
    histogram = round(macd - signal, 6)
    return macd, signal, histogram

def calc_bollinger(closes: list, period: int = 20) -> tuple[float, float, float]:
    if len(closes) < period:
        return 0.0, 0.0, 0.0
    sma    = sum(closes[:period]) / period
    std    = (sum((c - sma) ** 2 for c in closes[:period]) / period) ** 0.5
    upper  = round(sma + 2 * std, 5)
    lower  = round(sma - 2 * std, 5)
    middle = round(sma, 5)
    return upper, middle, lower

def calc_stochastic(candles: list, k_period: int = 14) -> tuple[float, float]:
    if len(candles) < k_period:
        return 50.0, 50.0
    highs  = [float(c["high"])  for c in candles[:k_period]]
    lows   = [float(c["low"])   for c in candles[:k_period]]
    closes = [float(c["close"]) for c in candles[:k_period]]
    highest_high = max(highs)
    lowest_low   = min(lows)
    if highest_high == lowest_low:
        return 50.0, 50.0
    k        = round(((closes[0] - lowest_low) / (highest_high - lowest_low)) * 100, 2)
    k_values = []
    for i in range(min(3, len(candles) - k_period)):
        h = max(float(c["high"]) for c in candles[i:i + k_period])
        l = min(float(c["low"])  for c in candles[i:i + k_period])
        c = float(candles[i]["close"])
        if h != l:
            k_values.append(((c - l) / (h - l)) * 100)
    d = round(sum(k_values) / len(k_values), 2) if k_values else k
    return k, d

# ── SIGNAL LOGIC ──────────────────────────────────────────────────────────────
TIMEFRAME_CONFIG = {
    "5min":  {"interval": "5min",  "atr_sl_mult": 1.5, "atr_tp_mult": 2.5,
              "label": "5M",    "min_sl_pips": 8},
    "15min": {"interval": "15min", "atr_sl_mult": 1.5, "atr_tp_mult": 2.5,
              "label": "15M",   "min_sl_pips": 12},
    "1h":    {"interval": "1h",    "atr_sl_mult": 2.0, "atr_tp_mult": 3.0,
              "label": "1H",    "min_sl_pips": 20},
    "4h":    {"interval": "4h",    "atr_sl_mult": 2.0, "atr_tp_mult": 3.0,
              "label": "4H",    "min_sl_pips": 30},
    "1day":  {"interval": "1day",  "atr_sl_mult": 2.5, "atr_tp_mult": 4.0,
              "label": "Daily", "min_sl_pips": 50},
}

def analyze_tf(pair: str, interval: str) -> dict | None:
    cfg     = TIMEFRAME_CONFIG[interval]
    candles = get_candles(pair, cfg["interval"], 50)
    if not candles or len(candles) < 35:
        return None

    closes = [float(v["close"]) for v in candles]
    latest = candles[0]
    entry  = float(latest["close"])
    atr    = calc_atr(candles, 14)

    # 1. EMA
    ema9  = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema50 = calc_ema(closes, 50)
    ema_buy  = ema9 > ema21 > ema50
    ema_sell = ema9 < ema21 < ema50

    # 2. MACD
    macd, signal_line, histogram = calc_macd(closes)
    macd_buy  = macd > signal_line and histogram > 0
    macd_sell = macd < signal_line and histogram < 0

    # 3. RSI
    rsi      = calc_rsi(closes, 14)
    rsi_buy  = 50 < rsi < 75
    rsi_sell = 25 < rsi < 50

    # 4. Bollinger Bands
    bb_upper, bb_middle, bb_lower = calc_bollinger(closes, 20)
    bb_buy  = entry <= bb_middle
    bb_sell = entry >= bb_middle

    # 5. Stochastic
    stoch_k, stoch_d = calc_stochastic(candles, 14)
    stoch_buy  = stoch_k < 50 and stoch_d < 50
    stoch_sell = stoch_k > 50 and stoch_d > 50

    buy_confirmations = [
        ("EMA",        ema_buy),
        ("MACD",       macd_buy),
        ("RSI",        rsi_buy),
        ("Bollinger",  bb_buy),
        ("Stochastic", stoch_buy),
    ]
    sell_confirmations = [
        ("EMA",        ema_sell),
        ("MACD",       macd_sell),
        ("RSI",        rsi_sell),
        ("Bollinger",  bb_sell),
        ("Stochastic", stoch_sell),
    ]

    buy_score  = sum(1 for _, v in buy_confirmations  if v)
    sell_score = sum(1 for _, v in sell_confirmations if v)

    buy_indicators  = [n for n, v in buy_confirmations  if v]
    sell_indicators = [n for n, v in sell_confirmations if v]

    if buy_score > sell_score:
        direction  = "BUY"
        indicators = buy_indicators
        score      = buy_score
    elif sell_score > buy_score:
        direction  = "SELL"
        indicators = sell_indicators
        score      = sell_score
    else:
        direction  = "BUY" if ema9 > ema21 else "SELL"
        indicators = []
        score      = 0

    if rsi >= 75:
        warning = "⚠️ RSI overbought — caution"
    elif rsi <= 25:
        warning = "⚠️ RSI oversold — caution"
    else:
        warning = ""

    # ✅ Enforce minimum SL pips
    pip_size = 0.01 if "JPY" in pair else 0.0001
    min_sl   = cfg["min_sl_pips"] * pip_size
    sl_dist  = max(round(atr * cfg["atr_sl_mult"], 5), min_sl)
    tp_dist  = round(sl_dist * (cfg["atr_tp_mult"] / cfg["atr_sl_mult"]), 5)

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
        "label":      cfg["label"],
        "interval":   interval,
        "direction":  direction,
        "score":      score,
        "indicators": indicators,
        "entry":      entry,
        "tp":         tp,
        "sl":         sl,
        "atr":        atr,
        "ema9":       ema9,
        "ema21":      ema21,
        "ema50":      ema50,
        "rsi":        rsi,
        "macd":       macd,
        "signal":     signal_line,
        "histogram":  histogram,
        "bb_upper":   bb_upper,
        "bb_lower":   bb_lower,
        "stoch_k":    stoch_k,
        "stoch_d":    stoch_d,
        "warning":    warning,
        "change":     change,
        "high":       float(latest["high"]),
        "low":        float(latest["low"]),
        "buy_score":  buy_score,
        "sell_score": sell_score,
    }

def multi_tf_agree(results: list) -> tuple[str | None, list]:
    """
    ✅ At least 3 TFs must agree on SAME direction.
    ✅ Disagreeing TFs must not show opposite with high score.
    """
    if not results:
        return None, []
    buys  = [r for r in results if r["direction"] == "BUY"]
    sells = [r for r in results if r["direction"] == "SELL"]

    if len(buys) >= 3:
        # ✅ Extra check: disagreeing TFs must have low scores
        disagree_strong = any(
            r["sell_score"] >= 4 for r in buys
        )
        if not disagree_strong:
            return "BUY", [r["label"] for r in buys]

    if len(sells) >= 3:
        disagree_strong = any(
            r["buy_score"] >= 4 for r in sells
        )
        if not disagree_strong:
            return "SELL", [r["label"] for r in sells]

    return None, []

# ── LOT SIZE CALCULATOR ───────────────────────────────────────────────────────
def calc_lot_size(account: float, risk_pct: float,
                  sl_pips: float, pair: str) -> float:
    """✅ Proper risk-based lot size capped at 5.0."""
    risk_amount = account * (risk_pct / 100)
    if sl_pips <= 0:
        return 0.01
    pip_value = 6.8 if "JPY" in pair else 10.0
    raw = risk_amount / (sl_pips * pip_value)
    return max(0.01, min(round(raw, 2), 5.0))

def pips(pair: str, price_dist: float) -> float:
    if "JPY" in pair:
        return round(price_dist / 0.01, 1)
    return round(price_dist / 0.0001, 1)

def get_confidence(results: list, direction: str) -> str:
    agreeing = sum(1 for r in results if r["direction"] == direction)
    total    = len(results)
    if agreeing == total:
        return "🔥 MAXIMUM — All TFs agree"
    elif agreeing >= 4:
        return "✅ VERY HIGH — 4/5 TFs"
    elif agreeing >= 3:
        return "⚠️ MEDIUM — 3/5 TFs"
    else:
        return "❌ LOW — Skip"

# ── GEMINI AI ─────────────────────────────────────────────────────────────────
def ask_gemini(prompt: str) -> str:
    """✅ Fixed Gemini with fallback models."""
    models = [
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-pro",
    ]
    for model in models:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={GEMINI_KEY}",
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=20
            )
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            print(f"[Gemini] {model} returned {r.status_code}")
        except Exception as e:
            print(f"[Gemini] {model} exception: {e}")
    return "AI analysis unavailable right now."

def get_news_summary(pair: str) -> str:
    prompt = (
        f"You are a senior forex analyst. In 3 plain-English sentences explain "
        f"the current market sentiment for {pair}. "
        f"Focus on: what is driving price, key risk events this week, "
        f"and what a retail trader must watch. No jargon. "
        f"End with: 'Watch for...' or 'Avoid trading when...'."
    )
    return ask_gemini(prompt)

# ── FORMAT SIGNAL MESSAGE ─────────────────────────────────────────────────────
def format_signal_msg(pair: str, results: list, agreeing: list,
                      account: float, risk_pct: float) -> str:
    direction   = next(r["direction"] for r in results if r["label"] in agreeing) \
                  if agreeing else results[0]["direction"]
    emoji       = "🟢" if direction == "BUY" else "🔴"
    now         = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    confidence  = get_confidence(results, direction)
    total_score = sum(
        r["buy_score"] if r["direction"] == "BUY" else r["sell_score"]
        for r in results
    )

    tf_lines = []
    for r in results:
        sl_p = pips(pair, abs(r["entry"] - r["sl"]))
        tp_p = pips(pair, abs(r["entry"] - r["tp"]))
        lot  = calc_lot_size(account, risk_pct, sl_p, pair)
        agree_mark   = "✅" if r["label"] in agreeing else "⬜"
        warning_line = f"\n   {r['warning']}" if r["warning"] else ""
        indicators   = ", ".join(r["indicators"]) if r["indicators"] else "mixed"
        tf_lines.append(
            f"{agree_mark} *{r['label']}* | {r['direction']} | "
            f"{r['score']}/5 indicators{warning_line}\n"
            f"   ✔ {indicators}\n"
            f"   Entry: `{r['entry']}` | TP: `{r['tp']}` | SL: `{r['sl']}`\n"
            f"   SL {sl_p}p / TP {tp_p}p | Lot: `{lot}`\n"
            f"   RSI: {r['rsi']} | Stoch: {r['stoch_k']} | MACD: {r['macd']}"
        )

    news = get_news_summary(pair)

    return (
        f"📊 *{pair}* {emoji} *{direction}*\n"
        f"⏰ {now}\n"
        f"Confidence: {confidence}\n"
        f"Pair Score: *{total_score}/25*\n\n"
        + "\n\n".join(tf_lines) +
        f"\n\n💬 *Market Context*\n{news}\n\n"
        f"💰 Account: ${account:,.0f} | "
        f"Risk: {risk_pct}% (${account * risk_pct / 100:,.0f} per trade)"
    )

# ── MARKET SCANNER ────────────────────────────────────────────────────────────
def scan_market(chat_id, account: float, risk_pct: float):
    send_message(chat_id,
        f"🔍 *Market Scanner Running...*\n\n"
        f"Scanning *{len(SCAN_PAIRS)} pairs* across 5 timeframes.\n"
        f"Minimum: 3 TFs must agree + strong indicators.\n"
        f"This may take 2-3 minutes ⏳"
    )

    strong_signals = []
    unavailable    = 0

    for pair in SCAN_PAIRS:
        results = []
        for tf in TIMEFRAME_CONFIG:
            r = analyze_tf(pair, tf)
            if r:
                results.append(r)
            time.sleep(0.3)

        if not results:
            unavailable += 1
            continue

        direction, agreeing = multi_tf_agree(results)
        if not direction:
            continue

        total_score = sum(
            r["buy_score"] if r["direction"] == "BUY" else r["sell_score"]
            for r in results
        )
        avg_score = total_score / len(results)

        if avg_score >= 3.0:
            strong_signals.append({
                "pair":        pair,
                "direction":   direction,
                "total_score": total_score,
                "avg_score":   avg_score,
                "results":     results,
                "agreeing":    agreeing,
            })

    strong_signals.sort(key=lambda x: x["total_score"], reverse=True)

    if not strong_signals:
        send_message(chat_id,
            f"📊 *Scan Complete*\n\n"
            f"Scanned: {len(SCAN_PAIRS)} pairs\n"
            f"Unavailable: {unavailable} pairs\n\n"
            f"⛔ No strong signals found right now.\n"
            f"Markets are mixed across all pairs.\n\n"
            f"🧘 Patience is profit. Try again at next session."
        )
        return

    # ✅ Summary
    summary_lines = [
        f"✅ *Scan Complete — {len(strong_signals)} Strong Signal(s) Found*\n"
        f"Scanned: {len(SCAN_PAIRS)} | Unavailable: {unavailable}\n"
    ]
    for i, s in enumerate(strong_signals, 1):
        emoji = "🟢" if s["direction"] == "BUY" else "🔴"
        summary_lines.append(
            f"{i}. {emoji} *{s['pair']}* — {s['direction']} "
            f"| Score: {s['total_score']}/25 "
            f"| Avg: {s['avg_score']:.1f}/5"
        )
    send_message(chat_id, "\n".join(summary_lines))
    time.sleep(2)

    # ✅ Full signal per pair
    for s in strong_signals:
        msg = format_signal_msg(
            s["pair"], s["results"], s["agreeing"], account, risk_pct
        )
        send_message(chat_id, msg)
        time.sleep(2)

# ── ACCOUNT SETUP FLOW ────────────────────────────────────────────────────────
def ask_account(chat_id, context: dict):
    pending_signal[str(chat_id)] = context
    send_message(chat_id,
        "💰 *Step 1 of 2 — Account Balance*\n\n"
        "What is your current account balance?\n"
        "Reply with just the number e.g: `20000`"
    )

def ask_risk_profile(chat_id):
    send_message(chat_id,
        "⚠️ *Step 2 of 2 — Risk Profile*\n\n"
        "Choose your trading style:\n\n"
        "1️⃣ — 🟢 *Normal* (0.5% per trade) — Safest\n"
        "2️⃣ — 🟡 *Moderate* (1.0% per trade) — Balanced\n"
        "3️⃣ — 🔴 *Aggressive* (2.0% per trade) — Higher risk\n\n"
        "Reply with *1*, *2*, or *3*"
    )

def handle_pending(chat_id, text: str) -> bool:
    cid      = str(chat_id)
    settings = get_settings(chat_id)

    # Step 1 — account balance
    if cid in pending_signal and settings["account"] is None:
        try:
            amount = float(text.strip())
            if amount < 10:
                send_message(chat_id, "❌ Account must be at least $10. Try again:")
                return True
            settings["account"] = amount
            ask_risk_profile(chat_id)
            return True
        except ValueError:
            send_message(chat_id, "❌ Please enter a valid number e.g: `20000`")
            return True

    # Step 2 — risk profile
    if cid in pending_signal and settings["risk_pct"] is None:
        choice = text.strip()
        if choice not in RISK_PROFILES:
            send_message(chat_id,
                "❌ Please reply with *1*, *2*, or *3*\n\n"
                "1️⃣ Normal | 2️⃣ Moderate | 3️⃣ Aggressive"
            )
            return True

        profile              = RISK_PROFILES[choice]
        settings["risk_pct"] = profile["pct"]
        context              = pending_signal.pop(cid)

        send_message(chat_id,
            f"✅ *Settings Confirmed!*\n\n"
            f"💰 Account: *${settings['account']:,.2f}*\n"
            f"⚠️ Profile: *{profile['label']}*\n"
            f"📊 Risk: *{profile['pct']}%* "
            f"= ${settings['account'] * profile['pct'] / 100:,.2f} per trade\n\n"
            f"⏳ Starting market scan now..."
        )

        pair              = context.get("pair")
        require_agreement = context.get("require_agreement", True)

        if pair:
            def run_single():
                results = []
                for tf in TIMEFRAME_CONFIG:
                    r = analyze_tf(pair, tf)
                    if r:
                        results.append(r)
                    time.sleep(0.3)

                if not results:
                    send_message(chat_id, f"❌ Could not fetch data for *{pair}*")
                    return

                direction, agreeing = multi_tf_agree(results)

                if require_agreement and not direction:
                    buys  = sum(1 for r in results if r["direction"] == "BUY")
                    sells = sum(1 for r in results if r["direction"] == "SELL")
                    detail = "\n".join(
                        f"  {'🟢' if r['direction'] == 'BUY' else '🔴'} "
                        f"{r['label']}: {r['direction']} "
                        f"({r['buy_score'] if r['direction'] == 'BUY' else r['sell_score']}/5)"
                        for r in results
                    )
                    send_message(chat_id,
                        f"⛔ *{pair}* — Signal blocked\n\n"
                        f"Less than 3 TFs agree.\n"
                        f"BUY: {buys} TF | SELL: {sells} TF\n\n"
                        f"{detail}\n\n"
                        f"⏳ Wait for at least 3 TFs to align."
                    )
                    return

                if not direction:
                    direction = results[0]["direction"]
                    agreeing  = [results[0]["label"]]

                msg = format_signal_msg(
                    pair, results, agreeing,
                    settings["account"], settings["risk_pct"]
                )
                send_message(chat_id, msg)

            threading.Thread(target=run_single, daemon=True).start()
        else:
            threading.Thread(
                target=scan_market,
                args=(chat_id, settings["account"], settings["risk_pct"]),
                daemon=True
            ).start()
        return True

    return False

# ── COMMAND HANDLER ───────────────────────────────────────────────────────────
def handle(chat_id, text: str):
    text = text.strip()

    if handle_pending(chat_id, text):
        return

    if text == "/start":
        user_settings[str(chat_id)] = {"account": None, "risk_pct": None}
        send_message(chat_id,
            "👋 *Welcome to SOS Trading Signal Bot*\n\n"
            "📌 *Commands*\n"
            "• /signal — smart scan all pairs\n"
            "• /analyze EURUSD — single pair deep analysis\n"
            "• /pairs — list all scannable pairs\n"
            "• /news EURUSD — AI market context\n"
            "• /alert EURUSD above 1.1200\n"
            "• /alerts — view active alerts\n"
            "• /cancelalerts — cancel all alerts\n"
            "• /settings — view last used settings\n"
            "• /reset — reset account & risk\n"
            "• /app — open Mini App\n\n"
            "🔍 *Smart Scanner*\n"
            "Scans 15 verified pairs dynamically.\n"
            "Minimum 3 TFs must agree.\n"
            "Pairs ranked by strength score.\n\n"
            "📊 *Timeframes*: 5M | 15M | 1H | 4H | Daily\n"
            "🔒 *Indicators*: EMA + MACD + RSI + BB + Stoch\n"
            "⚠️ *Risk Profiles*: Normal | Moderate | Aggressive\n\n"
            "Type /signal to start! 🚀"
        )

    elif text == "/reset":
        user_settings[str(chat_id)] = {"account": None, "risk_pct": None}
        send_message(chat_id,
            "🔄 Settings reset.\n"
            "Account and risk will be asked fresh next signal."
        )

    elif text == "/app":
        keyboard = {
            "inline_keyboard": [[{
                "text": "📱 Open SOS Trading App",
                "web_app": {"url": "https://sparkly-biscochitos-5477ba.netlify.app/"}
            }]]
        }
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id":      chat_id,
            "text":         "Tap below to open SOS Trading App 👇",
            "reply_markup": keyboard
        })

    elif text == "/signal":
        user_settings[str(chat_id)] = {"account": None, "risk_pct": None}
        ask_account(chat_id, {"pair": None, "require_agreement": True})

    elif text.startswith("/analyze"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Usage: `/analyze EURUSD`")
            return
        raw  = parts[1].upper()
        pair = (raw[:3] + "/" + raw[3:]) if "/" not in raw else raw
        user_settings[str(chat_id)] = {"account": None, "risk_pct": None}
        ask_account(chat_id, {"pair": pair, "require_agreement": False})

    elif text == "/settings":
        s = get_settings(chat_id)
        if s["account"] is None or s["risk_pct"] is None:
            send_message(chat_id,
                "⚙️ No settings saved yet.\n"
                "Run /signal or /analyze to set them."
            )
        else:
            profile_label = next(
                (p["label"] for p in RISK_PROFILES.values()
                 if p["pct"] == s["risk_pct"]), f"{s['risk_pct']}%"
            )
            send_message(chat_id,
                f"⚙️ *Last Used Settings*\n\n"
                f"💰 Account: *${s['account']:,.2f}*\n"
                f"⚠️ Profile: *{profile_label}*\n"
                f"📊 Risk:    *{s['risk_pct']}%* per trade\n"
                f"💵 Risk $:  *${s['account'] * s['risk_pct'] / 100:,.2f}*\n\n"
                f"These will be asked again next signal."
            )

    elif text.startswith("/alert"):
        parts = text.split()
        if len(parts) < 4:
            send_message(chat_id,
                "Usage: `/alert EURUSD above 1.1200`\n"
                "Or:    `/alert EURUSD below 1.1000`"
            )
            return
        try:
            raw       = parts[1].upper()
            pair      = (raw[:3] + "/" + raw[3:]) if "/" not in raw else raw
            direction = parts[2].lower()
            price     = float(parts[3])
            if direction not in ["above", "below"]:
                send_message(chat_id,
                    "❌ Use *above* or *below*.\n"
                    "Example: `/alert EURUSD above 1.1200`"
                )
                return
            price_alerts.append({
                "chat_id":   chat_id,
                "pair":      pair,
                "direction": direction,
                "price":     price
            })
            send_message(chat_id,
                f"🔔 *Alert Set!*\n\n"
                f"Pair: *{pair}*\n"
                f"Trigger: Price goes *{direction}* `{price}`\n\n"
                f"I'll notify you the moment it's hit! ✅"
            )
        except ValueError:
            send_message(chat_id,
                "❌ Invalid price.\n"
                "Example: `/alert EURUSD above 1.1200`"
            )

    elif text == "/alerts":
        user_alerts = [a for a in price_alerts if str(a["chat_id"]) == str(chat_id)]
        if not user_alerts:
            send_message(chat_id,
                "📭 No active alerts.\n"
                "Set one with `/alert EURUSD above 1.1200`"
            )
            return
        lines = ["🔔 *Your Active Alerts*\n"]
        for i, a in enumerate(user_alerts, 1):
            lines.append(f"{i}. *{a['pair']}* — {a['direction']} `{a['price']}`")
        send_message(chat_id, "\n".join(lines))

    elif text == "/cancelalerts":
        before = len([a for a in price_alerts if str(a["chat_id"]) == str(chat_id)])
        price_alerts[:] = [a for a in price_alerts if str(a["chat_id"]) != str(chat_id)]
        send_message(chat_id, f"✅ Cancelled *{before}* alert(s).")

    elif text == "/pairs":
        send_message(chat_id,
            "📈 *Scannable Pairs*\n\n"
            "*Majors:*\n"
            "EUR/USD | GBP/USD | USD/JPY | USD/CHF\n"
            "USD/CAD | AUD/USD | NZD/USD\n\n"
            "*Minors:*\n"
            "EUR/JPY | EUR/GBP | EUR/AUD\n"
            "GBP/JPY | GBP/AUD | AUD/JPY\n"
            "AUD/CAD | CAD/JPY\n\n"
            "All scanned dynamically on /signal 🔍"
        )

    elif text.startswith("/news"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "Usage: `/news EURUSD`")
            return
        raw  = parts[1].upper()
        pair = (raw[:3] + "/" + raw[3:]) if "/" not in raw else raw
        send_message(chat_id, f"📰 Fetching AI analysis for *{pair}*...")
        summary = get_news_summary(pair)
        send_message(chat_id, f"📰 *{pair} — Market Context*\n\n{summary}")

    else:
        if text.lower().startswith("/"):
            send_message(chat_id,
                "❓ Unknown command.\n\n"
                "/signal /analyze /pairs\n"
                "/alert /alerts /cancelalerts\n"
                "/settings /reset /news\n"
                "/app /start"
            )
        else:
            send_message(chat_id,
                "💬 I only respond to commands.\n"
                "Send /start to see the full list."
            )

# ── WEB APP DATA HANDLER ──────────────────────────────────────────────────────
def handle_web_app(chat_id, raw_data: str):
    try:
        data = json.loads(raw_data)
        if data["action"] == "signal":
            pair = data["pair"]
            user_settings[str(chat_id)] = {"account": None, "risk_pct": None}
            ask_account(chat_id, {"pair": pair, "require_agreement": False})
        elif data["action"] == "settings":
            settings = get_settings(chat_id)
            settings["account"]  = float(data["account"])
            settings["risk_pct"] = float(data["risk"])
            send_message(chat_id,
                f"✅ Settings updated!\n"
                f"💰 Account: *${settings['account']:,.2f}*\n"
                f"⚠️ Risk: *{settings['risk_pct']}%*\n"
                f"💵 Risk $: "
                f"*${settings['account'] * settings['risk_pct'] / 100:,.2f}*"
            )
    except Exception as e:
        print(f"[handle_web_app] error: {e}")
        send_message(chat_id, "❌ Error processing app request.")

# ── AUTO SESSION SIGNALS ──────────────────────────────────────────────────────
def session_job(session_name: str, flag: str):
    print(f"[scheduler] {session_name} firing")
    s        = get_settings(CHAT_ID)
    account  = s["account"]  or 20000.0
    risk_pct = s["risk_pct"] or 0.5
    send_message(CHAT_ID,
        f"{flag} *{session_name} Session — Auto Scan*\n\n"
        f"🔍 Scanning {len(SCAN_PAIRS)} pairs dynamically...\n"
        f"Minimum 3 TFs must agree."
    )
    scan_market(CHAT_ID, account, risk_pct)

def run_scheduler():
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
    print("SOS Trading Bot running...")
    set_bot_commands()
    threading.Thread(target=run_scheduler,      daemon=True).start()
    threading.Thread(target=check_price_alerts, daemon=True).start()

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
                    if "web_app_data" in msg:
                        handle_web_app(
                            msg["chat"]["id"],
                            msg["web_app_data"]["data"]
                        )
        except Exception as e:
            print(f"[main] error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()