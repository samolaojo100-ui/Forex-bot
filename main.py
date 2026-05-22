import os,requests,time,schedule,threading,json
from datetime import datetime,timezone
import yfinance as yf
TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")
URL=f"https://api.telegram.org/bot{TOKEN}"
PAIRS=["EURUSD=X","GBPUSD=X","USDCAD=X","USDJPY=X","AUDUSD=X"]
SF="/tmp/settings.json"
JF="/tmp/journal.json"
def send(cid,txt):
 try:requests.post(f"{URL}/sendMessage",json={"chat_id":cid,"text":txt,"parse_mode":"Markdown"},timeout=10)
 except:pass
def updates(off=None):
 try:return requests.get(f"{URL}/getUpdates",params={"timeout":30,"offset":off},timeout=35).json()
 except:return{"ok":False}
def now():return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
def ls():
 try:return json.load(open(SF))
 except:return{"account":1000,"risk":2}
def ss(d):json.dump(d,open(SF,"w"))
def lj():
 try:return json.load(open(JF))
 except:return[]
def sj(d):json.dump(d,open(JF,"w"))
def rsi(c,p=14):
 if len(c)<p+1:return 50
 g,l=[],[]
 for i in range(1,p+1):
  d=c[i]-c[i-1]
  (g if d>0 else l).append(abs(d))
 ag=sum(g)/p if g else .001;al=sum(l)/p if l else .001
 return round(100-(100/(1+ag/al)),1)
def data(pair,period,interval):
 try:
  h=yf.Ticker(pair).history(period=period,interval=interval)
  if h.empty:return None
  if interval=="1h" and period=="15d":
   h=h.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
  return h
 except:return None
def sig(pair,tf,period,interval,acc,risk):
 h=data(pair,period,interval)
 if h is None or len(h)<6:return None
 c=h["Close"].tolist();hi=h["High"].tolist();lo=h["Low"].tolist()
 price=round(c[-1],5);chg=round(((c[-1]-c[-2])/c[-2])*100,3)
 s5=round(sum(c[-5:])/5,5);s20=round(sum(c[-min(20,len(c)):])/min(20,len(c)),5)
 r=rsi(c[-30:] if len(c)>=30 else c)
 rh=round(max(hi[-14:]),5);rl=round(min(lo[-14:]),5)
 bu=be=0
 if s5>s20:bu+=2
 else:be+=2
 if r<40:bu+=2
 elif r>60:be+=2
 elif r<50:bu+=1
 else:be+=1
 if chg>0:bu+=1
 else:be+=1
 buy=bu>be;pip=0.01 if "JPY" in pair else 0.0001
 d="BUY 📈" if buy else "SELL 📉";conf=min(50+abs(bu-be)*8,82)
 if buy:sl=round(price-pip*15,5);tp=round(price+pip*30,5);ent=f"{price}—{round(price+pip*5,5)}"
 else:sl=round(price+pip*15,5);tp=round(price-pip*30,5);ent=f"{round(price-pip*5,5)}—{price}"
 ru=round(acc*(risk/100),2);lot=round(ru/(15*10),4);tu=round(ru*2,2)
 rn="oversold🟢" if r<40 else("overbought🔴" if r>60 else "neutral⚪")
 tr="Bullish↑" if s5>s20 else "Bearish↓"
 return f"⏱*{tf}*|{d}|{conf}%\n🎯`{ent}`\n✅`{tp}`(+${tu}) 🛑`{sl}`(-${ru})\n📦Lot:{lot} 💸Risk:${ru}\n📉RSI:{r}({rn})|{tr}\n📏{rl}—{rh}"
def full(pair,acc,risk):
 n=pair.replace("=X","")
 tfs=[("15M","2d","15m"),("30M","5d","30m"),("1H","5d","1h"),("4H","15d","1h"),("Daily","1mo","1d")]
 parts=[f"📊*{n}*\n💰${acc}|{risk}%\n{'─'*20}"]
 for tf,p,i in tfs:
  s=sig(pair,tf,p,i,acc,risk);parts.append(s if s else f"⚠️No data {tf}");time.sleep(1)
 return"\n\n".join(parts)
def calc(pair,d,ent,sl,acc,risk):
 pip=0.01 if"JPY"in pair else 0.0001
 pips=round(abs(ent-sl)/pip,1);ru=round(acc*(risk/100),2)
 lot=round(ru/(pips*10),4) if pips>0 else 0;tp=round(ent+(ent-sl)*2 if d=="BUY" else ent-(sl-ent)*2,5)
 return f"🧮*Risk Calc*\n\n💰${acc}|{risk}%\n{d} {pair}@{ent}\n🛑SL:{sl}({pips}pips)\n\n💸Risk:${ru}\n📦Lot:{lot}\n✅TP:{tp}\n💵Profit:${round(ru*2,2)}\n📐RR:1:2"
def handle(cid,txt):
 p=txt.strip().split();cmd=p[0].lower();s=ls()
 if cmd=="/start":
  send(cid,"👋*Forex Bot Pro*\n\n⚙️Setup:\n`/setaccount 2000`\n`/setrisk 2`\n\n📡`/signal`—all pairs\n🔍`/scan`—best setup\n📰`/news`\n🧮`/risk EURUSD BUY 1.16 1.158`\n📓`/journal add EURUSD BUY 1.16 1.17 1.155`\n📓`/journal stats`\n💼`/portfolio`")
 elif cmd=="/setaccount":
  try:s["account"]=float(p[1]);ss(s);send(cid,f"✅Account set to *${float(p[1])}*")
  except:send(cid,"❌Use:`/setaccount 2000`")
 elif cmd=="/setrisk":
  try:s["risk"]=float(p[1]);ss(s);send(cid,f"✅Risk set to *{float(p[1])}%*")
  except:send(cid,"❌Use:`/setrisk 2`")
 elif cmd=="/signal":
  send(cid,f"⏳Analyzing...💰${s['account']}|{s['risk']}%")
  for pair in PAIRS:send(cid,f"{full(pair,s['account'],s['risk'])}\n\n⏰{now()}");time.sleep(2)
 elif cmd=="/risk":
  try:send(cid,calc(p[1].upper(),p[2].upper(),float(p[3]),float(p[4]),s["account"],s["risk"]))
  except:send(cid,"❌Use:`/risk EURUSD BUY 1.16 1.158`")
 elif cmd=="/scan":
  send(cid,"🔍Scanning...");best=None;bs=0;bd=""
  for pair in PAIRS:
   h=data(pair,"1mo","1d")
   if h is None or len(h)<6:continue
   c=h["Close"].tolist();s5=sum(c[-5:])/5;s20=sum(c[-20:])/20;r=rsi(c[-30:])
   bu=be=0
   if s5>s20:bu+=2
   else:be+=2
   if r<40:bu+=3
   elif r>60:be+=3
   sc=abs(bu-be)
   if sc>bs:bs=sc;best=pair;bd="BUY📈" if bu>be else "SELL📉"
   time.sleep(1)
  send(cid,f"🏆*Best Setup*\n{best.replace('=X','')}|{bd}|Score:{bs}/5" if best else "⚠️No strong setup")
 elif cmd=="/news":
  try:
   items=requests.get("https://api.rss2json.com/v1/api.json",params={"rss_url":"https://www.forexlive.com/feed/news"},timeout=10).json().get("items",[])[:5]
   send(cid,"📰*Forex News*\n\n"+"\n".join(f"•{i['title']}" for i in items))
  except:send(cid,"⚠️News unavailable")
 elif cmd=="/journal":
  if len(p)<2:send(cid,"Use:/journal add or /journal stats")
  elif p[1]=="add":
   try:
    t={"pair":p[2].upper(),"dir":p[3].upper(),"entry":float(p[4]),"tp":float(p[5]),"sl":float(p[6]),"date":now(),"result":"open"}
    j=lj();j.append(t);sj(j);send(cid,f"✅Trade#{len(j)-1} logged\n{t['pair']} {t['dir']}@{t['entry']}")
   except:send(cid,"❌Use:`/journal add EURUSD BUY 1.16 1.17 1.155`")
  elif p[1]=="close":
   try:
    j=lj();j[int(p[2])]["result"]=p[3];sj(j);send(cid,f"✅Trade#{p[2]} marked {p[3].upper()}")
   except:send(cid,"❌Use:`/journal close 0 win`")
  elif p[1]=="stats":
   j=lj()
   if not j:send(cid,"No trades yet");return
   cl=[t for t in j if t["result"]in["win","loss"]];w=len([t for t in cl if t["result"]=="win"])
   wr=round(w/len(cl)*100,1) if cl else 0
   send(cid,f"📊*Journal*\nTotal:{len(j)}|W:{w}|L:{len(cl)-w}\nWin Rate:{wr}%")
 elif cmd=="/portfolio":
  j=lj();s2=ls()
  if not j:send(cid,"No trades yet");return
  cl=[t for t in j if t["result"]in["win","loss"]];w=len([t for t in cl if t["result"]=="win"])
  wr=round(w/len(cl)*100,1) if cl else 0
  send(cid,f"💼*Portfolio*\n💰${s2['account']}|{s2['risk']}%\nTrades:{len(j)}|W:{w}|L:{len(cl)-w}\nWin Rate:{wr}%")
def daily():
 s=ls()
 for pair in PAIRS:send(CHAT_ID,f"{full(pair,s['account'],s['risk'])}\n\n⏰{now()}");time.sleep(2)
def scheduler():
 schedule.every().day.at("08:00").do(daily)
 while True:schedule.run_pending();time.sleep(30)
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
