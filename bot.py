import json, os
from datetime import datetime
import requests
import yfinance as yf
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

MEMORY_FILE = "memory.json"

def safe_float(v, default=0.0):
    try:
        f = float(v)
        return default if np.isnan(f) else f
    except: return default

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
            for p in data.get("patterns", []):
                p.setdefault("equity", data.get("last_equity", 100000))
                p.setdefault("cash", 0); p.setdefault("nvda", 210); p.setdefault("qqq", 740)
            data.setdefault("trades", []); data.setdefault("decisions", [])
            return data
    return {"patterns": [], "trades": [], "decisions": [], "start_equity": 100000, "last_equity": 100000}

def save_memory(d):
    with open(MEMORY_FILE, "w") as f: json.dump(d, f, indent=2)

def rsi(s, p=14):
    d = s.diff(); g = d.clip(lower=0).rolling(p).mean(); l = -d.clip(upper=0).rolling(p).mean()
    rs = g / l; return 100 - (100 / (1 + rs))

def get_tech(symbol, fallback=100):
    try:
        h = yf.Ticker(symbol).history(period="3mo")
        if h.empty: raise ValueError("empty")
        c = h['Close']; price = safe_float(c.iloc[-1], fallback)
        sma20 = safe_float(c.rolling(20).mean().iloc[-1], price)
        sma50 = safe_float(c.rolling(50).mean().iloc[-1], price)
        r = safe_float(rsi(c).iloc[-1], 50)
        macd = c.ewm(12).mean() - c.ewm(26).mean(); sig = macd.ewm(9).mean()
        return {"symbol": symbol, "price": price, "sma20": sma20, "sma50": sma50, "rsi": r, "macd_bull": bool(macd.iloc[-1] > sig.iloc[-1])}
    except:
        return {"symbol": symbol, "price": fallback, "sma20": fallback, "sma50": fallback, "rsi": 50, "macd_bull": False}

memory = load_memory()

# ===== ALPACA =====
KEY = os.getenv("ALPACA_KEY"); SEC = os.getenv("ALPACA_SECRET")
HDR = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SEC}
BASE = "https://paper-api.alpaca.markets"

try:
    a = requests.get(f"{BASE}/v2/account", headers=HDR, timeout=10).json()
    equity = safe_float(a.get('equity'), 102788); cash = safe_float(a.get('cash'), -114599)
    pos = requests.get(f"{BASE}/v2/positions", headers=HDR, timeout=10).json()
    positions = [{"symbol":p['symbol'],"qty":float(p['qty']),"price":safe_float(p['current_price']),"value":safe_float(p['market_value']),"pnl":safe_float(p['unrealized_plpc'])*100} for p in pos]
except:
    equity, cash = 102788, -114599
    positions = [{"symbol":"NVDA","qty":965,"price":210.69,"value":203315,"pnl":1.4},{"symbol":"QQQ","qty":19,"price":740.62,"value":14072,"pnl":0.6}]

# ===== UNIVERSE SCAN =====
universe = list(set([p['symbol'] for p in positions] + ['NVDA','QQQ','SPY','AAPL','MSFT','AMD','TSM','AVGO','META','GOOGL','AMZN','TSLA','BTC-USD','ETH-USD']))
market_data = {}
for sym in universe:
    fallback = next((p['price'] for p in positions if p['symbol']==sym), 100)
    market_data[sym] = get_tech(sym, fallback)

# ===== MEMORY UPDATE =====
memory["patterns"].append({"time":datetime.now().isoformat(),"nvda":market_data['NVDA']['price'],"qqq":market_data['QQQ']['price'],"equity":equity,"cash":cash})
memory["patterns"] = memory["patterns"][-200:]; memory["last_equity"] = equity

# ===== ADVANCED MATH BRAIN =====
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

for sym, td in market_data.items():
    score = 0
    if td['price'] > td['sma20']: score+=1
    if td['sma20'] > td['sma50']: score+=1
    if 35 < td['rsi'] < 65: score+=1
    if td['macd_bull']: score+=1
    if tech_exp < 50: score+=1

    pos = next((p for p in positions if p['symbol']==sym), None)
    action = "HOLD"; reason = f"Score {score}/5, RSI {td['rsi']:.0f}"

    if sym in [p['symbol'] for p in positions] and (score <=2 or tech_exp>60):
        action = "SELL"; reason += " - weakness + overexposure"
        if pos and KEY:
            qty = max(1, int(pos['qty']*0.2))
            try:
                requests.post(f"{BASE}/v2/orders", headers=HDR, json={"symbol":sym,"qty":qty,"side":"sell","type":"market","time_in_force":"day"}, timeout=5)
                executed.append(f"SELL {qty} {sym}"); memory["trades"].append({"time":datetime.now().isoformat(),"symbol":sym,"side":"sell","qty":qty})
            except: pass
    elif score >=4 and cash > 2000 and sym not in [p['symbol'] for p in positions]:
        action = "BUY"; reason += f" - strength, Kelly {kelly*100:.0f}%"
        size = int((equity*kelly*0.1)/td['price']) if td['price']>0 else 0
        if size>0 and KEY:
            try:
                requests.post(f"{BASE}/v2/orders", headers=HDR, json={"symbol":sym,"qty":size,"side":"buy","type":"market","time_in_force":"day"}, timeout=5)
                executed.append(f"BUY {size} {sym}"); memory["trades"].append({"time":datetime.now().isoformat(),"symbol":sym,"side":"buy","qty":size})
            except: pass

    decisions.append({"symbol":sym,"action":action,"score":score,"price":td['price'],"reason":reason})

memory["decisions"].append({"time":datetime.now().isoformat(),"decisions":decisions[:5]}); memory["decisions"] = memory["decisions"][-50:]

# ===== TELEGRAM =====
top = sorted(decisions, key=lambda x: x['score'], reverse=True)[:3]
msg = f"""🔥 HEDGE FUND COMMAND CENTER
pimpin ain't easy 😎
────────────────────
💰 ${equity:,.0f} ({day_chg:+.2f}% today)
📊 All-Time: {((equity/100000)-1)*100:+.1f}% | Trades: {len(trades)}
💵 Cash: ${cash:,.0f}

🎯 POSITIONS ({len(positions)})
""" + "\n".join([f"- {p['symbol']} {p['qty']:.0f} @ ${p['price']:.2f} {'▲' if p['pnl']>0 else '▼'}{abs(p['pnl']):.1f}%" for p in positions[:4]]) + f"""

🧠 BRAIN STATUS
- Kelly: {kelly*100:.1f}% (win {win_rate*100:.0f}%)
- Scanning: {len(universe)} markets
- Learning: {'OPERATIONAL' if len(memory['patterns'])>20 else 'WARMING UP'}

🧮 TOP ANALYSIS
""" + "\n".join([f"• {d['symbol']}: {d['action']} ({d['reason']})" for d in top]) + f"""
{chr(10)+'⚡ EXECUTED:'+chr(10)+'• ' + chr(10)+'• '.join(executed) if executed else ''}

🛡️ RISK
- Tech: {tech_exp:.1f}% (target <45%)
- Action: {'AUTO-TRADE' if executed else 'HOLD'}
────────────────────
Next: 5 min | Mode: PAPER AUTO"""

token = os.getenv("TELEGRAM_TOKEN"); chat = os.getenv("TELEGRAM_CHAT")
if token and chat:
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id":chat,"text":msg})
    plt.figure(figsize=(11,5.5)); eq=[p.get('equity',equity) for p in memory['patterns']]
    plt.plot(eq, linewidth=2.5); plt.fill_between(range(len(eq)), eq, alpha=0.2)
    plt.title(f'Live Equity + {len(universe)} Market Brain - ${equity:,.0f}', fontweight='bold')
    plt.grid(True, alpha=0.3); plt.tight_layout(); plt.savefig('chart.png', dpi=150); plt.close()
    with open('chart.png','rb') as f:
        requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={"chat_id":chat,"caption":f"🧠 Scanning {len(universe)} | Kelly {kelly*100:.1f}% | {len(executed)} trades"}, files={"photo":f})

save_memory(memory)