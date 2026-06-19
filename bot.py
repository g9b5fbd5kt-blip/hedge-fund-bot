import json, os, time
from datetime import datetime, timedelta
import requests
import yfinance as yf
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

MEMORY_FILE = "memory.json"

def safe_float(v, d=0.0):
    try:
        f = float(v); return d if np.isnan(f) else f
    except: return d

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
            for p in data.get("patterns", []):
                p.setdefault("equity", data.get("last_equity", 100000))
            data.setdefault("trades", []); data.setdefault("decisions", []); data.setdefault("pending_orders", [])
            return data
    return {"patterns": [], "trades": [], "decisions": [], "pending_orders": [], "start_equity": 100000, "last_equity": 100000}

def save_memory(d):
    with open(MEMORY_FILE, "w") as f: json.dump(d, f, indent=2)

def rsi(s, p=14):
    d = s.diff(); g = d.clip(lower=0).rolling(p).mean(); l = -d.clip(upper=0).rolling(p).mean()
    rs = g / l; return 100 - (100 / (1 + rs))

def get_tech(sym, fb=100):
    try:
        h = yf.Ticker(sym).history(period="3mo")
        if h.empty: raise ValueError()
        c = h['Close']; price = safe_float(c.iloc[-1], fb)
        sma20 = safe_float(c.rolling(20).mean().iloc[-1], price)
        sma50 = safe_float(c.rolling(50).mean().iloc[-1], price)
        r = safe_float(rsi(c).iloc[-1], 50)
        macd = c.ewm(12).mean() - c.ewm(26).mean(); sig = macd.ewm(9).mean()
        return {"symbol": sym, "price": price, "sma20": sma20, "sma50": sma50, "rsi": r, "macd_bull": bool(macd.iloc[-1] > sig.iloc[-1])}
    except:
        return {"symbol": sym, "price": fb, "sma20": fb, "sma50": fb, "rsi": 50, "macd_bull": False}

memory = load_memory()

KEY = os.getenv("ALPACA_KEY"); SEC = os.getenv("ALPACA_SECRET")
HDR = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SEC}
BASE = "https://paper-api.alpaca.markets"

try:
    acct = requests.get(f"{BASE}/v2/account", headers=HDR, timeout=10).json()
    equity = safe_float(acct.get('equity'), 102788); cash = safe_float(acct.get('cash'), -114599)
    pos_raw = requests.get(f"{BASE}/v2/positions", headers=HDR, timeout=10).json()
    positions = [{"symbol":p['symbol'],"qty":float(p['qty']),"available":float(p.get('qty_available',p['qty'])),"price":safe_float(p['current_price']),"value":safe_float(p['market_value']),"pnl":safe_float(p['unrealized_plpc'])*100} for p in pos_raw]
except:
    equity, cash = 102788, -114599
    positions = [{"symbol":"NVDA","qty":965,"available":0,"price":210.69,"value":203315,"pnl":1.4},{"symbol":"QQQ","qty":19,"available":0,"price":740.62,"value":14072,"pnl":0.6}]

# ===== VERIFY AND CANCEL STALE =====
verified = []; errors = []; now = datetime.now()
for po in memory["pending_orders"][:]:
    try:
        age = now - datetime.fromisoformat(po['time'])
        o = requests.get(f"{BASE}/v2/orders/{po['id']}", headers=HDR, timeout=5).json()
        if o.get('status') in ['filled','partially_filled']:
            fq = safe_float(o.get('filled_qty'),0); fp = safe_float(o.get('filled_avg_price'), po['price'])
            pnl = (fp - po['price'])/po['price']*100 * (-1 if po['side']=='sell' else 1)
            memory["trades"].append({"time":now.isoformat(),"symbol":po['symbol'],"side":po['side'],"qty":fq,"price":fp,"pnl":pnl})
            memory["pending_orders"].remove(po); verified.append(f"{po['side'].upper()} {fq:.0f} {po['symbol']}")
        elif age > timedelta(minutes=10):
            requests.delete(f"{BASE}/v2/orders/{po['id']}", headers=HDR, timeout=5)
            memory["pending_orders"].remove(po)
            errors.append(f"Cancelled stale {po['symbol']} order ({age.seconds//60}m old)")
    except: pass

# ===== SCAN =====
universe = list(set([p['symbol'] for p in positions] + ['NVDA','QQQ','SPY','AAPL','MSFT','AMD','TSM','AVGO','META','GOOGL','AMZN','TSLA','BTC-USD','ETH-USD']))
market = {s: get_tech(s, next((p['price'] for p in positions if p['symbol']==s), 100)) for s in universe}

memory["patterns"].append({"time":now.isoformat(),"nvda":market['NVDA']['price'],"qqq":market['QQQ']['price'],"equity":equity,"cash":cash})
memory["patterns"] = memory["patterns"][-200:]; memory["last_equity"] = equity

tech_syms = ['NVDA','QQQ','AAPL','MSFT','AMD','TSM','AVGO','SMH','SOXL','SPY']
tech_val = sum(p['value'] for p in positions if p['symbol'] in tech_syms)
tech_exp = tech_val / equity * 100 if equity else 0
prev_eq = memory["patterns"][-2].get('equity', equity) if len(memory["patterns"])>1 else equity
day_chg = (equity - prev_eq) / prev_eq * 100 if prev_eq else 0

trades = memory["trades"]; wins = [t for t in trades if t.get('pnl',0)>0]
win_rate = len(wins)/len(trades) if trades else 0.55
avg_w = np.mean([t['pnl'] for t in wins]) if wins else 2.0
avg_l = abs(np.mean([t['pnl'] for t in trades if t.get('pnl',0)<0])) if len(trades)>len(wins) else 1.5
kelly = max(0.05, min(0.25, win_rate - (1-win_rate)*(avg_l/avg_w if avg_w else 1)))

decisions = []; executed = []
recent = {t['symbol'] for t in trades if datetime.fromisoformat(t['time']) > now - timedelta(minutes=15)}
pending_syms = {p['symbol'] for p in memory["pending_orders"]}
risk_override = tech_exp > 200

for sym, td in market.items():
    score = sum([td['price']>td['sma20'], td['sma20']>td['sma50'], 35<td['rsi']<65, td['macd_bull'], tech_exp<50])
    pos = next((p for p in positions if p['symbol']==sym), None)
    action = "HOLD"; reason = f"Score {score}/5"

    if not risk_override and (sym in pending_syms or sym in recent):
        reason += " - cooldown"; decisions.append({"symbol":sym,"action":action,"score":score,"price":td['price'],"reason":reason}); continue

    if pos and (tech_exp>55 or risk_override):
        available = pos.get('available', 0)
        if available >= 1:
            qty = int(min(available, 5)) # smaller chunks for stuck market
            action = "SELL"
            try:
                # Use limit order at bid to force fill in paper
                r = requests.post(f"{BASE}/v2/orders", headers=HDR, json={"symbol":sym,"qty":qty,"side":"sell","type":"limit","limit_price":round(td['price']*0.99,2),"time_in_force":"day"}, timeout=5)
                resp = r.json()
                if 'id' in resp:
                    memory["pending_orders"].append({"id":resp['id'],"symbol":sym,"side":"sell","qty":qty,"price":td['price'],"time":now.isoformat()})
                    executed.append(f"SELL {qty} {sym} limit")
            except Exception as e:
                errors.append(f"{sym} order fail")

    decisions.append({"symbol":sym,"action":action,"score":score,"price":td['price'],"reason":reason})

memory["decisions"] = (memory["decisions"] + [{"time":now.isoformat(),"decisions":decisions[:5]}])[-50:]

top = sorted(decisions, key=lambda x: x['score'], reverse=True)[:3]
msg = f"""🔥 HEDGE FUND COMMAND CENTER
pimpin ain't easy 😎
────────────────────
💰 ${equity:,.0f} | Cash: ${cash:,.0f}
📊 Trades: {len(trades)} | Kelly: {kelly*100:.1f}%
🎯 POSITIONS: NVDA {positions[0]['qty']:.0f}({positions[0]['available']:.0f} free) QQQ {positions[1]['qty']:.0f}({positions[1]['available']:.0f} free)
🧠 Risk Override: {'ON' if risk_override else 'OFF'} | Pending: {len(memory['pending_orders'])}
🧮 TOP: {', '.join([f"{d['symbol']} {d['action']}" for d in top])}
{chr(10)+'✅ '+chr(10).join(verified) if verified else ''}
{chr(10)+'⚡ '+chr(10).join(executed) if executed else ''}
{chr(10)+'❌ '+chr(10).join(errors[:2]) if errors else ''}
🛡️ Tech: {tech_exp:.1f}%"""

token = os.getenv("TELEGRAM_TOKEN"); chat = os.getenv("TELEGRAM_CHAT")
if token and chat:
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id":chat,"text":msg})

save_memory(memory)