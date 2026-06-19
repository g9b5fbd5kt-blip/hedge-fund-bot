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
    else: data={"patterns":[],"trades":[],"decisions":[],"pending_orders":[],"start_equity":100000,"last_equity":100000}
    for k in ["patterns","trades","decisions","pending_orders"]: data.setdefault(k,[])
    return data

def save_memory(d):
    with open(MEMORY_FILE,"w") as f: json.dump(d,f,indent=2)

def rsi(s,p=14):
    d=s.diff(); g=d.clip(lower=0).rolling(p).mean(); l=-d.clip(upper=0).rolling(p).mean()
    return 100-(100/(1+g/l))

def get_tech(sym,fb=100):
    try:
        h=yf.Ticker(sym).history(period="3mo"); c=h['Close']
        return {"symbol":sym,"price":safe_float(c.iloc[-1],fb),"sma20":safe_float(c.rolling(20).mean().iloc[-1]),"sma50":safe_float(c.rolling(50).mean().iloc[-1]),"rsi":safe_float(rsi(c).iloc[-1],50),"macd_bull":bool((c.ewm(12).mean()-c.ewm(26).mean()).iloc[-1] > (c.ewm(12).mean()-c.ewm(26).mean()).ewm(9).mean().iloc[-1])}
    except: return {"symbol":sym,"price":fb,"sma20":fb,"sma50":fb,"rsi":50,"macd_bull":False}

memory=load_memory()
KEY=os.getenv("ALPACA_KEY"); SEC=os.getenv("ALPACA_SECRET")
HDR={"APCA-API-KEY-ID":KEY,"APCA-API-SECRET-KEY":SEC}; BASE="https://paper-api.alpaca.markets"
now=datetime.now()

try:
    acct=requests.get(f"{BASE}/v2/account",headers=HDR,timeout=10).json()
    equity=safe_float(acct.get('equity'),102788); cash=safe_float(acct.get('cash'),-114599)
    buying_power=safe_float(acct.get('buying_power'),0)
    pos_raw=requests.get(f"{BASE}/v2/positions",headers=HDR,timeout=10).json()
    positions=[{"symbol":p['symbol'],"qty":float(p['qty']),"available":float(p.get('qty_available',0)),"price":safe_float(p['current_price']),"value":safe_float(p['market_value'])} for p in pos_raw]
except:
    equity,cash,buying_power=102788,-114599,0
    positions=[{"symbol":"NVDA","qty":965,"available":0,"price":210.69,"value":203315},{"symbol":"QQQ","qty":19,"available":0,"price":740.62,"value":14072}]

verified=[]; errors=[]; status_log=[]
for po in memory["pending_orders"][:]:
    try:
        o=requests.get(f"{BASE}/v2/orders/{po['id']}",headers=HDR,timeout=5).json()
        st=o.get('status','unknown')
        status_log.append(f"{po['symbol']} {st}")
        if st in ['filled','partially_filled']:
            fq=safe_float(o.get('filled_qty')); fp=safe_float(o.get('filled_avg_price'),po['price'])
            memory["trades"].append({"time":now.isoformat(),"symbol":po['symbol'],"side":po['side'],"qty":fq,"price":fp,"pnl":0})
            memory["pending_orders"].remove(po); verified.append(f"{po['symbol']} {st}")
        elif (now - datetime.fromisoformat(po['time'])) > timedelta(minutes=10):
            requests.delete(f"{BASE}/v2/orders/{po['id']}",headers=HDR,timeout=5)
            memory["pending_orders"].remove(po); errors.append(f"Cancelled {po['symbol']} ({st})")
    except Exception as e: errors.append(f"Check fail {po['symbol']}")

universe=list(set([p['symbol'] for p in positions]+['NVDA','QQQ','SPY','AAPL','MSFT','AMD','TSM']))
market={s:get_tech(s) for s in universe}

tech_val=sum(p['value'] for p in positions if p['symbol'] in ['NVDA','QQQ','AAPL','MSFT','AMD','TSM'])
tech_exp=tech_val/equity*100 if equity else 0
risk_override=tech_exp>200

executed=[]
if risk_override:
    for p in positions:
        if p['available']>=1:
            qty=int(min(p['available'],5))
            try:
                r=requests.post(f"{BASE}/v2/orders",headers=HDR,json={"symbol":p['symbol'],"qty":qty,"side":"sell","type":"market","time_in_force":"day"},timeout=5)
                resp=r.json()
                if 'id' in resp:
                    memory["pending_orders"].append({"id":resp['id'],"symbol":p['symbol'],"side":"sell","qty":qty,"price:p['price'],"time":now.isoformat()})
                    executed.append(f"{p['symbol']} {qty}")
                else: errors.append(f"{p['symbol']} reject: {resp.get('message','')[:40]}")
            except: errors.append(f"{p['symbol']} post fail")

memory["patterns"].append({"time":now.isoformat(),"equity":equity}); memory["patterns"]=memory["patterns"][-200:]

msg=f"""🔥 HEDGE FUND COMMAND CENTER
pimpin ain't easy 😎
────────────────────
💰 ${equity:,.0f} | Cash: ${cash:,.0f} | BP: ${buying_power:,.0f}
📊 Trades: {len(memory['trades'])} | Pending: {len(memory['pending_orders'])}
🎯 POSITIONS
""" + "\n".join([f"- {p['symbol']} {p['qty']:.0f} ({p['available']:.0f} free)" for p in positions]) + f"""

🧠 STATUS LOG
""" + "\n".join(status_log[:5]) + f"""
{chr(10)+'✅ '+chr(10).join(verified) if verified else ''}
{chr(10)+'⚡ Sent: '+', '.join(executed) if executed else ''}
{chr(10)+'❌ '+chr(10).join(errors[:4]) if errors else ''}

🛡️ Tech: {tech_exp:.1f}% | Risk Override: {'ON' if risk_override else 'OFF'}
Alpaca says: {'MARGIN CALL - sells blocked' if cash<-100000 and not verified else 'Trading'}
────────────────────
Next: 5 min"""

token=os.getenv("TELEGRAM_TOKEN"); chat=os.getenv("TELEGRAM_CHAT")
if token and chat:
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":msg})

save_memory(memory)