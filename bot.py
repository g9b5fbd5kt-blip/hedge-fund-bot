import json, os
from datetime import datetime, timedelta
import requests
import yfinance as yf
import numpy as np

MEMORY_FILE = "memory.json"

def load_memory():
    return json.load(open(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else {"patterns":[],"trades":[],"pending_orders":[],"start_equity":1000}

def save_memory(d): json.dump(d, open(MEMORY_FILE,"w"), indent=2)

def get_price(sym):
    try: return float(yf.Ticker(sym).history(period="5d")['Close'].iloc[-1])
    except: return 100.0

memory=load_memory()
HDR={"APCA-API-KEY-ID":os.getenv("ALPACA_KEY"),"APCA-API-SECRET-KEY":os.getenv("ALPACA_SECRET")}
BASE="https://paper-api.alpaca.markets"

acct=requests.get(f"{BASE}/v2/account",headers=HDR).json()
equity=float(acct['equity']); cash=float(acct['cash'])
positions=requests.get(f"{BASE}/v2/positions",headers=HDR).json()
pos_syms=[p['symbol'] for p in positions]

# clean pending
now=datetime.now()
for po in memory["pending_orders"][:]:
    o=requests.get(f"{BASE}/v2/orders/{po['id']}",headers=HDR).json()
    if o['status'] in ['filled','canceled','rejected','expired']:
        memory["pending_orders"].remove(po)

pending_syms={p['symbol'] for p in memory["pending_orders"]}
universe=['SPY','SCHD','KO','PFE','T','VZ']  # $30-60 stocks perfect for $1k
executed=[]

for sym in universe:
    if len(pos_syms)+len(pending_syms) >= 3: break
    if sym in pos_syms or sym in pending_syms: continue
    price=get_price(sym); qty=max(1, int(40/price))  # ~$40 per position
    if cash > qty*price:
        r=requests.post(f"{BASE}/v2/orders",headers=HDR,json={"symbol":sym,"qty":qty,"side":"buy","type":"market","time_in_force":"day"}).json()
        if 'id' in r:
            memory["pending_orders"].append({"id":r['id'],"symbol":sym,"time":now.isoformat()})
            executed.append(f"{qty}x {sym} (~${qty*price:.0f})"); cash-=qty*price

msg=f"""🔥 $1K LIVE PREP MODE
💰 ${equity:.0f} | Cash: ${cash:.0f}
🎯 Positions: {len(pos_syms)} | Pending: {len(pending_syms)}
⚡ {', '.join(executed) if executed else 'All orders cleared - ready'}
Next: buys $40 chunks of $30-60 stocks"""

requests.post(f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/sendMessage",json={"chat_id":os.getenv('TELEGRAM_CHAT'),"text":msg})
save_memory(memory)