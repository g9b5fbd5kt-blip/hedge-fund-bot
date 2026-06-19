import json, os
from datetime import datetime, timedelta
import requests
import yfinance as yf
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

MEMORY_FILE = "memory.json"

def safe_float(v, d=0.0):
    try: f=float(v); return d if np.isnan(f) else f
    except: return d

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE,"r") as f: data=json.load(f)
    else: data={"patterns":[],"trades":[],"decisions":[],"pending_orders":[],"start_equity":1000,"last_equity":1000}
    for k in ["patterns","trades","decisions","pending_orders"]: data.setdefault(k,[])
    return data

def save_memory(d):
    with open(MEMORY_FILE,"w") as f: json.dump(d,f,indent=2)

def rsi(s,p=14):
    d=s.diff(); g=d.clip(lower=0).rolling(p).mean(); l=-d.clip(upper=0).rolling(p).mean()
    return 100-(100/(1+g/l))

def get_tech(sym):
    try:
        h=yf.Ticker(sym).history(period="3mo"); c=h['Close']; price=safe_float(c.iloc[-1])
        return {"symbol":sym,"price":price,"sma20":safe_float(c.rolling(20).mean().iloc[-1]),"sma50":safe_float(c.rolling(50).mean().iloc[-1]),"rsi":safe_float(rsi(c).iloc[-1],50),"macd_bull":bool((c.ewm(12).mean()-c.ewm(26).mean()).iloc[-1] > (c.ewm(12).mean()-c.ewm(26).mean()).ewm(9).mean().iloc[-1])}
    except: return {"symbol":sym,"price":100,"sma20":100,"sma50":100,"rsi":50,"macd_bull":False}

memory=load_memory()
KEY=os.getenv("ALPACA_KEY"); SEC=os.getenv("ALPACA_SECRET")
HDR={"APCA-API-KEY-ID":KEY,"APCA-API-SECRET-KEY":SEC}; BASE="https://paper-api.alpaca.markets"
now=datetime.now()

acct=requests.get(f"{BASE}/v2/account",headers=HDR,timeout=10).json()
equity=safe_float(acct.get('equity'),1000); cash=safe_float(acct.get('cash'),1000)
pos_raw=requests.get(f"{BASE}/v2/positions",headers=HDR,timeout=10).json()
positions=[{"symbol":p['symbol'],"qty":float(p['qty']),"value":safe_float(p['market_value']),"price":safe_float(p['current_price'])} for p in pos_raw]

verified=[]; errors=[]
for po in memory["pending_orders"][:]:
    o=requests.get(f"{BASE}/v2/orders/{po['id']}",headers=HDR,timeout=5).json()
    if o.get('status') in ['filled','partially_filled']:
        fq=safe_float(o.get('filled_qty')); fp=safe_float(o.get('filled_avg_price'),po['price'])
        pnl=(fp-po['price'])/po['price']*100 * (1 if po['side']=='buy' else -1)
        memory["trades"].append({"time":now.isoformat(),"symbol":po['symbol'],"side":po['side'],"qty":fq,"price":fp,"pnl":pnl})
        memory["pending_orders"].remove(po); verified.append(f"{po['side'].upper()} {po['symbol']} ${fp:.2f}")
    elif (now-datetime.fromisoformat(po['time']))>timedelta(minutes=10):
        requests.delete(f"{BASE}/v2/orders/{po['id']}",headers=HDR,timeout=5); memory["pending_orders"].remove(po)

universe=['SPY','QQQ','AAPL','MSFT','AMD','TSM','NVDA','VOO','SCHD','TLT']
market={s:get_tech(s) for s in universe}

trades=memory["trades"]; wins=[t for t in trades if t['pnl']>0]
win_rate=len(wins)/len(trades) if trades else 0.5
avg_w=np.mean([t['pnl'] for t in wins]) if wins else 1.5
avg_l=abs(np.mean([t['pnl'] for t in trades if t['pnl']<0])) if len(trades)>len(wins) else 1.0
kelly=max(0.02, min(0.10, win_rate - (1-win_rate)*(avg_l/avg_w)))

memory["patterns"].append({"time":now.isoformat(),"equity":equity}); memory["patterns"]=memory["patterns"][-200:]

decisions=[]; executed=[]
for sym,td in sorted(market.items(), key=lambda x: x[1]['rsi']):
    score=sum([td['price']>td['sma20'], td['sma20']>td['sma50'], 40<td['rsi']<60, td['macd_bull']])
    pos=next((p for p in positions if p['symbol']==sym), None)

    if score>=3 and not pos and cash>20 and len(positions)<5:
        notional=min(50, equity*kelly*2) # $20-50 per trade for $1k account
        try:
            r=requests.post(f"{BASE}/v2/orders",headers=HDR,json={"symbol":sym,"notional":round(notional,2),"side":"buy","type":"market","time_in_force":"day"},timeout=5)
            if 'id' in r.json():
                memory["pending_orders"].append({"id":r.json()['id'],"symbol":sym,"side":"buy","qty":0,"price":td['price'],"time":now.isoformat()})
                executed.append(f"BUY ${notional:.0f} {sym}"); decisions.append({"symbol":sym,"action":"BUY","score":score})
                cash-=notional
        except: pass
    elif pos and score<=1:
        try:
            r=requests.post(f"{BASE}/v2/orders",headers=HDR,json={"symbol":sym,"qty":pos['qty'],"side":"sell","type":"market","time_in_force":"day"},timeout=5)
            if 'id' in r.json(): executed.append(f"SELL {sym}")
        except: pass

msg=f"""🔥 $1K LIVE PREP MODE
pimpin ain't easy 😎
────────────────────
💰 ${equity:.0f} | Cash: ${cash:.0f}
📊 Trades: {len(trades)} | Win: {win_rate*100:.0f}% | Kelly: {kelly*100:.1f}%
🎯 Positions: {len(positions)}
""" + "\n".join([f"- {p['symbol']} ${p['value']:.0f}" for p in positions]) + f"""

🧠 LEARNING
- Verified fills: {len(verified)}
- Next trade size: ${equity*kelly*2:.0f}

⚡ {', '.join(executed) if executed else 'Holding - waiting for setup'}
────────────────────
30-day clock started"""

token=os.getenv("TELEGRAM_TOKEN"); chat=os.getenv("TELEGRAM_CHAT")
if token and chat:
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":msg})

save_memory(memory)