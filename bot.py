import json, os
from datetime import datetime, timedelta
import requests
import yfinance as yf
import numpy as np

MEMORY_FILE = "memory.json"

def safe_float(v, d=0.0):
    try: f=float(v); return d if np.isnan(f) else f
    except: return d

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE,"r") as f: return json.load(f)
    return {"patterns":[],"trades":[],"decisions":[],"pending_orders":[],"start_equity":1000,"last_equity":1000}

def save_memory(d):
    with open(MEMORY_FILE,"w") as f: json.dump(d,f,indent=2)

def rsi(s,p=14):
    d=s.diff(); g=d.clip(lower=0).rolling(p).mean(); l=-d.clip(upper=0).rolling(p).mean()
    return 100-(100/(1+g/l))

def get_tech(sym):
    try:
        h=yf.Ticker(sym).history(period="3mo"); c=h['Close']
        return {"symbol":sym,"price":safe_float(c.iloc[-1]),"sma20":safe_float(c.rolling(20).mean().iloc[-1]),"sma50":safe_float(c.rolling(50).mean().iloc[-1]),"rsi":safe_float(rsi(c).iloc[-1],50),"macd":bool((c.ewm(12).mean()-c.ewm(26).mean()).iloc[-1] > 0)}
    except: return {"symbol":sym,"price":100,"sma20":100,"sma50":100,"rsi":50,"macd":False}

memory=load_memory()
KEY=os.getenv("ALPACA_KEY"); SEC=os.getenv("ALPACA_SECRET")
HDR={"APCA-API-KEY-ID":KEY,"APCA-API-SECRET-KEY":SEC}; BASE="https://paper-api.alpaca.markets"
now=datetime.now()

acct=requests.get(f"{BASE}/v2/account",headers=HDR,timeout=10).json()
equity=safe_float(acct.get('equity'),1000); cash=safe_float(acct.get('cash'),1000)
positions=requests.get(f"{BASE}/v2/positions",headers=HDR,timeout=10).json()
pos_list=[p['symbol'] for p in positions]

verified=[]; status=[]
for po in memory["pending_orders"][:]:
    try:
        o=requests.get(f"{BASE}/v2/orders/{po['id']}",headers=HDR,timeout=5).json()
        st=o.get('status','unknown'); status.append(f"{po['symbol']}:{st}")
        if st in ['filled','partially_filled']:
            fp=safe_float(o.get('filled_avg_price'),po['price'])
            memory["trades"].append({"time":now.isoformat(),"symbol":po['symbol'],"side":po['side'],"price":fp,"pnl":0})
            memory["pending_orders"].remove(po); verified.append(po['symbol'])
        elif (now-datetime.fromisoformat(po['time']))>timedelta(minutes=15):
            requests.delete(f"{BASE}/v2/orders/{po['id']}",headers=HDR,timeout=5)
            memory["pending_orders"].remove(po)
    except: pass

pending_syms={p['symbol'] for p in memory["pending_orders"]}
universe=['SPY','VOO','QQQ','SCHD','AMD','TSM']
market={s:get_tech(s) for s in universe}

trades=memory["trades"]; win_rate=0.5 if not trades else len([t for t in trades if t.get('pnl',0)>0])/len(trades)
kelly=max(0.03, min(0.08, win_rate*0.15))
trade_size=min(40, equity*kelly)

executed=[]
for sym,td in sorted(market.items(), key=lambda x: x[1]['rsi']):
    if len(pos_list)+len(pending_syms) >= 3: break
    if sym in pos_list or sym in pending_syms: continue
    score=sum([td['price']>td['sma20'], td['sma20']>td['sma50'], 45<td['rsi']<55])
    if score>=2 and cash>trade_size:
        try:
            r=requests.post(f"{BASE}/v2/orders",headers=HDR,json={"symbol":sym,"notional":round(trade_size,2),"side":"buy","type":"market","time_in_force":"day"},timeout=5).json()
            if 'id' in r:
                memory["pending_orders"].append({"id":r['id'],"symbol":sym,"side":"buy","price":td['price'],"time":now.isoformat()})
                executed.append(f"${trade_size:.0f} {sym}"); cash-=trade_size; pending_syms.add(sym)
        except: pass

msg=f"""🔥 $1K LIVE PREP MODE
pimpin ain't easy 😎
────────────────────
💰 ${equity:.0f} | Cash: ${cash:.0f}
📊 Trades: {len(trades)} | Kelly: {kelly*100:.1f}%
🎯 Positions: {len(pos_list)} | Pending: {len(pending_syms)}

🧠 STATUS
- {', '.join(status[:3]) if status else 'No orders yet'}
- Verified: {len(verified)}

⚡ {', '.join(executed) if executed else 'Waiting for fills...'}
────────────────────
Next size: ${trade_size:.0f} | Max 3 positions"""

requests.post(f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/sendMessage",json={"chat_id":os.getenv('TELEGRAM_CHAT'),"text":msg})
save_memory(memory)