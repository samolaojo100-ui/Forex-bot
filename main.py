import os,requests,time,schedule,threading,json
from datetime import datetime,timezone
import yfinance as yf

TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")
URL=f"https://api.telegram.org/bot{TOKEN}"
PAIRS=["EURUSD=X","GBPUSD=X","USDCAD=X","USDJPY=X","AUDUSD=X"]
SF="/tmp/settings.json"
JF="/tmp/journal.json"
WF="/tmp/waiting.json"

# ── HELPERS ────────────────────────────────────────────────────────────────────
def send(cid,txt,buttons=None):
    body={"chat_id":cid,"text":txt,"parse_mode":"Markdown"}
    if buttons:
        body["reply_markup"]={"keyboard":buttons,"resize_keyboard":True,"one_time_keyboard":False}
    try:requests.post(f"{URL}/sendMessage",json=body,timeout=10)
    except:pass

def updates(off=None):
    try:return requests.get(f"{URL}/getUpdates",params={"timeout":30,"offset":off},timeout=35).json()
    except:return{"ok":False}

def now():return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# ── SETTINGS ───────────────────────────────────────────────────────────────────
def ls():
    try:return json.load(open(SF))
    except:return{"account":None,"risk":2,"setup_done":False}

def ss(d):json.dump(d,open(SF,"w"))

# ── WAITING STATE ──────────────────────────────────────────────────────────────
def lw():
    try:return json.load(open(WF))
    except:return{}

def sw(d):json.dump(d,open(WF,"w"))

def get_wait(cid):return lw().get(str(cid))
def set_wait(cid,state):w=lw();w[str(cid)]=state;sw(w)
def clear_wait(cid):w=lw();w.pop(str(cid),None);sw(w)

# ── JOURNAL ────────────────────────────────────────────────────────────────────
def lj():
    try:return json.load(open(JF))
    except:return[]
def sj(d):json.dump(d,open(JF,"w"))

# ── MAIN MENU BUTTONS ──────────────────────────────────────────────────────────
MENU=[["📡 Signal","🔍 Scan"],["📰 News","💼 Portfolio"],["📓 Journal","⚙️ Settings"]]

# ── MARKET DATA ────────────────────────────────────────────────────────────────
def get_data(pair,period,interval):
    try:
        h=yf.Ticker(pair).history(period=period,interval=interval)
        if h.empty:return None
        if interval=="1h" and period=="15d":
            h=h.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
        return h
    except:return None

def calc_rsi(c,p=14):
    if len(c)<p+1:return 50
    g,l=[],[]
    for i in range(1,p+1):
        d=c[i]-c[i-1];(g if d>0 else l).append(abs(d))
    ag=sum(g)/p if g else .001;al=sum(l)/p if l else .001
    return round(100-(100/(1+ag/al)),1)

# ── SIGNAL FORMATTER ───────────────────────────────────────────────────────────
def format_signal(pair,tf,period,interval,acc,risk):
    h=get_data(pair,period,interval)
    if h is None or len(h)<6:return None
    c=h["Close"].tolist();hi=h["High"].tolist();lo=h["Low"].tolist()
    price=round(c[-1],5);chg=round(((c[-1]-c[-2])/c[-2])*100,3)
    s5=round(sum(c[-min(5,len(c)):])/min(5,len(c)),5)
    s20=round(sum(c[-min(20,len(c)):])/min(20,len(c)),5)
    r=calc_rsi(c[-30:] if len(c)>=30 else c)
    rh=round(max(hi[-14:]) if len(hi)>=14 else max(hi),5)
    rl=round(min(lo[-14:]) if len(lo)>=14 else min(lo),5)

    bu=be=0
    if s5>s20:bu+=2
    else:be+=2
    if r<40:bu+=2
    elif r>60:be+=2
    elif r<50:bu+=1
    else:be+=1
    if chg>0:bu+=1
    else:be+=1
    if (rh-rl)>0:
        pos=(price-rl)/(rh-rl)
        if pos<0.3:bu+=1
        elif pos>0.7:be+=1

    buy=bu>be
    direction="BUY 📈" if buy else "SELL 📉"
    conf=min(50+abs(bu-be)*8,82)
    pip=0.01 if"JPY"in pair else 0.0001
    sl_pips=15;tp_pips=30

    if buy:
        entry=price
        sl=round(price-pip*sl_pips,5)
        tp=round(price+pip*tp_pips,5)
    else:
        entry=price
        sl=round(price+pip*sl_pips,5)
        tp=round(price-pip*tp_pips,5)

    # Money management
    risk_usd=round(acc*(risk/100),2)
    pip_val=10 if"JPY"not in pair else 8
    lot=round(risk_usd/(sl_pips*pip_val),4)
    profit=round(risk_usd*2,2)
    rr="1:2"

    rsi_txt="Oversold 🟢" if r<40 else("Overbought 🔴" if r>60 else"Neutral ⚪")
    trend="Bullish ↑" if s5>s20 else"Bearish ↓"
    dir_arrow="▲" if buy else"▼"

    return(
        f"┌─────────────────────┐\n"
        f"│ ⏱ *{tf} Signal*\n"
        f"├─────────────────────┤\n"
        f"│ {direction}  |  📊 {conf}% confidence\n"
        f"├─────────────────────┤\n"
        f"│ 🎯 *Entry:*      `{entry}`\n"
        f"│ ✅ *Take Profit:* `{tp}`\n"
        f"│ 🛑 *Stop Loss:*  `{sl}`\n"
        f"├─────────────────────┤\n"
        f"│ 💰 *Account:*  ${acc}\n"
        f"│ 💸 *Risk:*     ${risk_usd} ({risk}%)\n"
        f"│ 📦 *Lot Size:* {lot}\n"
        f"│ 💵 *Profit:*   ${profit}\n"
        f"│ 📐 *R:R Ratio:* {rr}\n"
        f"├─────────────────────┤\n"
        f"│ 📉 RSI: {r} — {rsi_txt}\n"
        f"│ 📈 Trend: {trend}\n"
        f"│ 📏 Range: {rl} — {rh}\n"
        f"└─────────────────────┘"
    )

def full_signal(pair,acc,risk):
    name=pair.replace("=X","")
    tfs=[("15M","2d","15m"),("30M","5d","30m"),("1H","5d","1h"),("4H","15d","1h"),("Daily","1mo","1d")]
    out=[f"📊 *{name} — Full Analysis*\n💰 Account: ${acc} | Risk: {risk}%\n{'━'*22}"]
    for tf,p,i in tfs:
        s=format_signal(pair,tf,p,i,acc,risk)
        out.append(s if s else f"⚠️ No data for {tf}")
        time.sleep(1)
    return"\n\n".join(out)

# ── SCAN ───────────────────────────────────────────────────────────────────────
def scan():
    best=None;bs=0;bd=""
    for pair in PAIRS:
        h=get_data(pair,"1mo","1d")
        if h is None or len(h)<6:continue
        c=h["Close"].tolist()
        s5=sum(c[-5:])/5;s20=sum(c[-20:])/20
        r=calc_rsi(c[-30:] if len(c)>=30 else c)
        bu=be=0
        if s5>s20:bu+=2
        else:be+=2
        if r<40:bu+=3
        elif r>60:be+=3
        sc=abs(bu-be)
        if sc>bs:bs=sc;best=pair;bd="BUY 📈" if bu>be else"SELL 📉"
        time.sleep(1)
    if best:
        n=best.replace("=X","")
        return(f"🔍 *Best Setup Right Now*\n\n"
               f"┌─────────────────────┐\n"
               f"│ 🏆 Pair:  *{n}*\n"
               f"│ 🔵 Direction: {bd}\n"
               f"│ ⭐ Score: {bs}/5\n"
               f"└─────────────────────┘\n\n"
               f"_Type /signal for full analysis_")
    return"⚠️ No strong setups found right now."

# ── NEWS ───────────────────────────────────────────────────────────────────────
def news():
    try:
        items=requests.get("https://api.rss2json.com/v1/api.json",
            params={"rss_url":"https://www.forexlive.com/feed/news"},timeout=10).json().get("items",[])[:5]
        if not items:return"⚠️ No news right now."
        out=["📰 *Latest Forex News*\n"+"━"*22]
        for item in items:out.append(f"• {item.get('title','')}")
        out.append(f"\n⏰ {now()}")
        return"\n".join(out)
    except:return"⚠️ Could not fetch news."

# ── SETUP FLOW ─────────────────────────────────────────────────────────────────
def start_setup(cid):
    set_wait(cid,"waiting_account")
    send(cid,
        "👋 *Welcome to Forex Bot Pro!*\n\n"
        "Before we start, I need to personalise everything for YOUR account.\n\n"
        "💰 *What is your trading account balance?*\n"
        "_(Type the amount, e.g. 2000)_")

def handle_setup(cid,txt,s):
    wait=get_wait(cid)
    if wait=="waiting_account":
        try:
            amt=float(txt.replace("$","").replace(",",""))
            s["account"]=amt;ss(s)
            set_wait(cid,"waiting_risk")
            send(cid,
                f"✅ Account set to *${amt}*\n\n"
                f"📊 *What % of your account do you want to risk per trade?*\n\n"
                f"Recommended:\n"
                f"• Conservative: *1%* (${round(amt*0.01,2)} per trade)\n"
                f"• Moderate: *2%* (${round(amt*0.02,2)} per trade)\n"
                f"• Aggressive: *3%* (${round(amt*0.03,2)} per trade)\n\n"
                f"_(Type a number, e.g. 2)_")
        except:
            send(cid,"❌ Please type just the number, e.g. *2000*")
    elif wait=="waiting_risk":
        try:
            pct=float(txt.replace("%",""))
            if pct>10:send(cid,"⚠️ Risk too high! Please enter between 1-5%");return
            s["risk"]=pct;s["setup_done"]=True;ss(s);clear_wait(cid)
            risk_usd=round(s["account"]*(pct/100),2)
            send(cid,
                f"✅ *Setup Complete!*\n\n"
                f"┌─────────────────────┐\n"
                f"│ 💰 Account: ${s['account']}\n"
                f"│ 📊 Risk: {pct}% = ${risk_usd}/trade\n"
                f"│ 💵 Max profit/trade: ${round(risk_usd*2,2)}\n"
                f"└─────────────────────┘\n\n"
                f"Everything is now customised for your account!\n"
                f"Tap a button below to get started 👇",
                buttons=MENU)
        except:
            send(cid,"❌ Please type just the number, e.g. *2*")

# ── COMMAND HANDLER ────────────────────────────────────────────────────────────
def handle(cid,txt):
    s=ls();txt=txt.strip()
    wait=get_wait(cid)

    # Handle setup flow
    if wait in["waiting_account","waiting_risk"]:
        handle_setup(cid,txt,s);return

    # Check if account is set
    if not s.get("setup_done") and txt not in["/start","⚙️ Settings"]:
        start_setup(cid);return

    cmd=txt.lower()

    if cmd in["/start"]:
        if not s.get("setup_done"):
            start_setup(cid)
        else:
            send(cid,
                f"👋 Welcome back!\n\n"
                f"💰 Account: ${s['account']} | Risk: {s['risk']}%\n\n"
                f"What would you like to do?",buttons=MENU)

    elif cmd in["📡 signal","/signal"]:
        send(cid,f"⏳ Running full analysis...\n💰 ${s['account']} | {s['risk']}% risk",buttons=MENU)
        for pair in PAIRS:
            send(cid,f"{full_signal(pair,s['account'],s['risk'])}\n\n⏰ {now()}")
            time.sleep(2)

    elif cmd in["🔍 scan","/scan"]:
        send(cid,"🔍 Scanning all pairs for best setup...",buttons=MENU)
        send(cid,scan())

    elif cmd in["📰 news","/news"]:
        send(cid,news(),buttons=MENU)

    elif cmd in["⚙️ settings","/settings"]:
        start_setup(cid)

    elif cmd in["💼 portfolio","/portfolio"]:
        j=lj()
        if not j:send(cid,"📁 No trades yet.\nUse 📓 Journal to log your first trade.",buttons=MENU);return
        cl=[t for t in j if t["result"]in["win","loss"]]
        w=len([t for t in cl if t["result"]=="win"])
        wr=round(w/len(cl)*100,1) if cl else 0
        send(cid,
            f"💼 *Portfolio Dashboard*\n\n"
            f"┌─────────────────────┐\n"
            f"│ 💰 Account: ${s['account']}\n"
            f"│ 📊 Risk/trade: {s['risk']}%\n"
            f"├─────────────────────┤\n"
            f"│ 📈 Total Trades: {len(j)}\n"
            f"│ ✅ Wins: {w}\n"
            f"│ ❌ Losses: {len(cl)-w}\n"
            f"│ 🎯 Win Rate: {wr}%\n"
            f"├─────────────────────┤\n"
            f"│ 📅 Last: {j[-1]['date']}\n"
            f"│ {j[-1]['dir']} {j[-1]['pair']}@{j[-1]['entry']}\n"
            f"└─────────────────────┘",buttons=MENU)

    elif cmd in["📓 journal","/journal"]:
        send(cid,
            "📓 *Journal Commands:*\n\n"
            "`/jadd EURUSD BUY 1.16 1.17 1.155`\n"
            "_pair direction entry TP SL_\n\n"
            "`/jclose 0 win` or `/jclose 0 loss`\n\n"
            "`/jstats` — see your stats",buttons=MENU)

    elif cmd.startswith("/jadd"):
        p=txt.split()
        try:
            t={"pair":p[1].upper(),"dir":p[2].upper(),"entry":float(p[3]),
               "tp":float(p[4]),"sl":float(p[5]),"date":now(),"result":"open"}
            j=lj();j.append(t);sj(j)
            rr=round(abs(t['tp']-t['entry'])/abs(t['sl']-t['entry']),2)
            send(cid,
                f"✅ *Trade #{len(j)-1} Logged*\n\n"
                f"┌─────────────────────┐\n"
                f"│ 📊 {t['pair']} | {t['dir']}\n"
                f"│ 🎯 Entry: {t['entry']}\n"
                f"│ ✅ TP: {t['tp']}\n"
                f"│ 🛑 SL: {t['sl']}\n"
                f"│ 📐 R:R = 1:{rr}\n"
                f"└─────────────────────┘",buttons=MENU)
        except:send(cid,"❌ Use: `/jadd EURUSD BUY 1.16 1.17 1.155`",buttons=MENU)

    elif cmd.startswith("/jclose"):
        p=txt.split()
        try:
            j=lj();j[int(p[1])]["result"]=p[2];sj(j)
            send(cid,f"✅ Trade #{p[1]} marked as *{p[2].upper()}*",buttons=MENU)
        except:send(cid,"❌ Use: `/jclose 0 win`",buttons=MENU)

    elif cmd in["/jstats"]:
        j=lj()
        if not j:send(cid,"No trades yet.",buttons=MENU);return
        cl=[t for t in j if t["result"]in["win","loss"]]
        w=len([t for t in cl if t["result"]=="win"])
        wr=round(w/len(cl)*100,1) if cl else 0
        send(cid,
            f"📊 *Journal Stats*\n\n"
            f"┌─────────────────────┐\n"
            f"│ Total Trades: {len(j)}\n"
            f"│ ✅ Wins: {w}\n"
            f"│ ❌ Losses: {len(cl)-w}\n"
            f"│ 🎯 Win Rate: {wr}%\n"
            f"│ 🟡 Open: {len([t for t in j if t['result']=='open'])}\n"
            f"└─────────────────────┘",buttons=MENU)

    elif cmd.startswith("/risk"):
        p=txt.split()
        try:
            pair=p[1].upper();d=p[2].upper()
            ent=float(p[3]);sl=float(p[4])
            pip=0.01 if"JPY"in pair else 0.0001
            pips=round(abs(ent-sl)/pip,1)
            ru=round(s["account"]*(s["risk"]/100),2)
            lot=round(ru/(pips*10),4) if pips>0 else 0
            tp=round(ent+(ent-sl)*2 if d=="BUY" else ent-(sl-ent)*2,5)
            send(cid,
                f"🧮 *Risk Calculator*\n\n"
                f"┌─────────────────────┐\n"
                f"│ 📊 {pair} | {d}\n"
                f"│ 🎯 Entry: {ent}\n"
                f"│ 🛑 Stop Loss: {sl}\n"
                f"│    ({pips} pips)\n"
                f"├─────────────────────┤\n"
                f"│ 💰 Account: ${s['account']}\n"
                f"│ 💸 Risk: ${ru} ({s['risk']}%)\n"
                f"│ 📦 Lot Size: {lot}\n"
                f"│ ✅ Take Profit: {tp}\n"
                f"│ 💵 Potential: ${round(ru*2,2)}\n"
                f"│ 📐 R:R Ratio: 1:2\n"
                f"└─────────────────────┘",buttons=MENU)
        except:send(cid,"❌ Use: `/risk EURUSD BUY 1.1620 1.1580`",buttons=MENU)

# ── DAILY JOB ──────────────────────────────────────────────────────────────────
def daily():
    s=ls()
    if not s.get("account"):return
    for pair in PAIRS:
        send(CHAT_ID,f"{full_signal(pair,s['account'],s['risk'])}\n\n⏰ {now()}")
        time.sleep(2)

def scheduler():
    schedule.every().day.at("08:00").do(daily)
    while True:schedule.run_pending();time.sleep(30)

# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    print("Bot running...")
    threading.Thread(target=scheduler,daemon=True).start()
    off=None
    while True:
        try:
            ups=updates(off)
            if ups.get("ok"):
                for u in ups.get("result",[]):
                    off=u["update_id"]+1
                    msg=u.get("message",{})
                    if"text"in msg:handle(msg["chat"]["id"],msg["text"])
        except Exception as e:print(f"Error:{e}");time.sleep(5)

if __name__=="__main__":main()
