import json, os, requests, yfinance as yf
from datetime import datetime

MEMORY_FILE="memory.json"
HDR={"APCA-API-KEY-ID":os.getenv("ALPACA_KEY"),"APCA-API-SECRET-KEY":os.getenv("ALPACA_SECRET")}
BASE="https://paper-api.alpaca.markets"

# FORCE CANCEL ALL OPEN ORDERS
try: requests.delete(f"{BASE}/v2/orders", headers=HDR, timeout=5)
except: pass

memory={"patterns":[],"trades":[],"pending_orders":[],"start_equity":1000}
acct=requests.get(f"{BASE}/v2/account",headers=HDR).json()
equity=float(acct['equity']); cash=float(acct['cash'])
positions=requests.get(f"{BASE}/v2/positions",headers=HDR).json()

# liquidate any stray positions
for p in positions:
    requests.delete(f"{BASE}/v2/positions/{p['symbol']}",headers=HDR)

symbols=['SCHD','KO','T']  # three $25-35 stocks = perfect for $1k
executed=[]
for sym in symbols:
    price=float(yf.Ticker(sym).history(period="1d")['Close'].iloc[-1])
    qty=1
    if cash>price*1.1:
        r=requests.post(f"{BASE}/v2/orders",headers=HDR,json={"symbol":sym,"qty":qty,"side":"buy","type":"market","time_in_force":"day"}).json()
        if 'id' in r: executed.append(f"1x {sym} @ ${price:.2f}"); cash-=price

msg=f"🔥 $1K RESET COMPLETE\n💰 ${equity:.0f} → buying 3 stocks\n⚡ {', '.join(executed)}\nNext scan in 5 min"
requests.post(f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/sendMessage",json={"chat_id":os.getenv('TELEGRAM_CHAT'),"text":msg})

with open(MEMORY_FILE,"w") as f: json.dump(memory,f)