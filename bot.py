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

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
            for p in data.get("patterns", []):
                p.setdefault("equity", data.get("last_equity", 100000))
                p.setdefault("cash", 0)
                p.setdefault("nvda", 207.88)
                p.setdefault("qqq", 736.37)
            data.setdefault("trades", [])
            return data
    return {"patterns": [], "trades": [], "start_equity": 100000, "last_equity": 100000}

def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_technicals(symbol):
    try:
        hist = yf.Ticker(symbol).history(period="3mo")
        close = hist['Close']
        sma20 = close.rolling(20).mean().iloc[-1]
        sma50 = close.rolling(50).mean().iloc[-1]
        rsi_val = rsi(close).iloc[-1]
        macd = close.ewm(12).mean() - close.ewm(26).mean()
        signal = macd.ewm(9).mean()
        return {
            "price": float(close.iloc[-1]),
            "sma20": float(sma20),
            "sma50": float(sma50),
            "rsi": float(rsi_val),
            "macd_bull": bool(macd.iloc[-1] > signal.iloc[-1])
        }
    except:
        return {"price": 0, "sma20": 0, "sma50": 0, "rsi": 50, "macd_bull": False}

memory = load_memory()

# ===== ALPACA LIVE =====
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
HEADERS = {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}
BASE = "https://paper-api.alpaca.markets"

try:
    acct = requests.get(f"{BASE}/v2/account", headers=HEADERS, timeout=10).json()
    equity = float(acct.get('equity', 100000))
    cash = float(acct.get('cash', 0))
    positions = [{
        "symbol": p['symbol'],
        "qty": float(p['qty']),
        "price": float(p['current_price']),
        "market_value": float(p['market_value']),
        "pnl": float(p['unrealized_plpc']) * 100
    } for p in requests.get(f"{BASE}/v2/positions", headers=HEADERS, timeout=10).json()]
except:
    equity, cash = 102788, -114599
    positions = [
        {"symbol": "NVDA", "qty": 965, "price": 210.69, "market_value": 203315, "pnl": 1.4},
        {"symbol": "QQQ", "qty": 19, "price": 740.62, "market_value": 14072, "pnl": 0.6}
    ]

# ===== MARKET INTELLIGENCE =====
nvda_ta = get_technicals("NVDA")
qqq_ta = get_technicals("QQQ")
btc = get_technicals("BTC-USD")
eth = get_technicals("ETH-USD")

# ===== MEMORY UPDATE =====
memory["patterns"].append({
    "time": datetime.now().isoformat(),
    "nvda": nvda_ta["price"],
    "qqq": qqq_ta["price"],
    "equity": equity,
    "cash": cash
})
memory["patterns"] = memory["patterns"][-200:]
memory["last_equity"] = equity

# ===== HIGHER-LEVEL BRAIN =====
tech_symbols = ['NVDA','QQQ','AAPL','MSFT','AMD','TSM','AVGO','SMH','SOXL']
tech_value = sum(p['market_value'] for p in positions if p['symbol'] in tech_symbols)
tech_exposure = tech_value / equity * 100 if equity else 0

prev_equity = memory["patterns"][-2].get('equity', equity) if len(memory["patterns"])>1 else equity
daily_change = (equity - prev_equity) / prev_equity * 100

# Kelly from real trades
trades = memory["trades"]
wins = len([t for t in trades if t.get('pnl',0) > 0])
win_rate = wins / len(trades) if trades else 0.55
avg_win = np.mean([t['pnl'] for t in trades if t.get('pnl',0)>0]) if wins else 2.0
avg_loss = abs(np.mean([t['pnl'] for t in trades if t.get('pnl',0)<0])) if len(trades)-wins else 1.5
kelly_f = max(0.05, min(0.25, win_rate - (1-win_rate)*(avg_loss/avg_win))) if avg_loss else 0.10

# Multi-factor score for NVDA
nvda_score = 0
if nvda_ta["price"] > nvda_ta["sma20"]: nvda_score += 1
if nvda_ta["sma20"] > nvda_ta["sma50"]: nvda_score += 1
if 30 < nvda_ta["rsi"] < 70: nvda_score += 1
if nvda_ta["macd_bull"]: nvda_score += 1
if tech_exposure < 40: nvda_score += 1

reasoning = []
orders_executed = []

# Decision Engine
if tech_exposure > 45:
    excess = tech_value - (equity * 0.40)
    shares_trim = int(excess / nvda_ta["price"])
    reasoning.append(f"MATH: Exposure {tech_exposure:.1f}% > 45%. Kelly optimal trim = {shares_trim} NVDA (${excess:,.0f})")
    if shares_trim > 0 and ALPACA_KEY:
        try:
            order = requests.post(f"{BASE}/v2/orders", headers=HEADERS, json={
                "symbol": "NVDA", "qty": shares_trim, "side": "sell",
                "type": "market", "time_in_force": "day"
            }, timeout=10).json()
            orders_executed.append(f"SELL {shares_trim} NVDA @ market")
            memory["trades"].append({"time": datetime.now().isoformat(), "symbol": "NVDA", "side": "sell", "qty": shares_trim})
        except: pass
elif nvda_score >= 4 and cash > 5000:
    buy_size = int((equity * kelly_f * 0.25) / nvda_ta["price"])
    reasoning.append(f"MATH: NVDA score {nvda_score}/5, RSI {nvda_ta['rsi']:.0f}, trend bullish. Kelly size = {buy_size} shares")
    if buy_size > 0 and ALPACA_KEY:
        try:
            requests.post(f"{BASE}/v2/orders", headers=HEADERS, json={
                "symbol": "NVDA", "qty": buy_size, "side": "buy",
                "type": "market", "time_in_force": "day"
            }, timeout=10)
            orders_executed.append(f"BUY {buy_size} NVDA @ market")
            memory["trades"].append({"time": datetime.now().isoformat(), "symbol": "NVDA", "side": "buy", "qty": buy_size})
        except: pass
else:
    reasoning.append(f"MATH: No edge. NVDA score {nvda_score}/5, exposure {tech_exposure:.1f}%. HOLD")

if cash < 0:
    reasoning.append(f"MATH: Margin debt ${cash:,.0f}. Priority: free cash before new entries")

trend = "UP" if nvda_ta["price"] > nvda_ta["sma20"] > nvda_ta["sma50"] else "DOWN" if nvda_ta["price"] < nvda_ta["sma20"] else "FLAT"
optimal_action = "TRADE EXECUTED" if orders_executed else "HOLD"

patterns_count = len(memory["patterns"])
status = "OPERATIONAL" if patterns_count >= 20 else "WARMING UP"

message = f"""🔥 HEDGE FUND COMMAND CENTER
pimpin ain't easy 😎
────────────────────
💰 ${equity:,.0f} ({daily_change:+.2f}% today)
📊 All-Time: {((equity/100000)-1)*100:+.1f}% | Trades: {len(trades)}
💵 Cash: ${cash:,.0f}

🎯 POSITIONS ({len(positions)})
""" + "\n".join([f"- {p['symbol']} {p['qty']:.0f} @ ${p['price']:.2f} {'▲' if p['pnl']>0 else '▼'}{abs(p['pnl']):.1f}%" for p in positions[:4]]) + f"""

💎 MARKET INTEL
- NVDA: ${nvda_ta['price']:.2f} | RSI {nvda_ta['rsi']:.0f} | SMA20>{'✓' if nvda_ta['price']>nvda_ta['sma20'] else '✗'}
- QQQ: ${qqq_ta['price']:.2f}
- BTC: ${btc['price']:,.0f}

🧠 BRAIN STATUS
- Kelly: {kelly_f*100:.1f}% (win {win_rate*100:.0f}%)
- Learning: {status}
- Score: {nvda_score}/5

🧮 DEEP ANALYSIS
""" + "\n".join([f"• {r}" for r in reasoning]) + f"""
{chr(10)+'⚡ EXECUTED:'+chr(10)+'• ' + chr(10)+'• '.join(orders_executed) if orders_executed else ''}

🛡️ RISK
- Tech: {tech_exposure:.1f}% (target 40%)
- Action: {optimal_action}
────────────────────
Next: 5 min | Mode: PAPER AUTO"""

token = os.getenv("TELEGRAM_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT")

if token and chat_id:
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": message})
    
    plt.figure(figsize=(11,5.5))
    eq = [p.get('equity', equity) for p in memory['patterns']]
    plt.plot(eq, linewidth=2.5)
    plt.fill_between(range(len(eq)), eq, alpha=0.2)
    plt.title(f'Live Equity + Brain Decisions - ${equity:,.0f}', fontweight='bold')
    plt.ylabel('Portfolio')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('chart.png', dpi=150)
    plt.close()
    
    with open('chart.png', 'rb') as f:
        requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                      data={"chat_id": chat_id, "caption": f"🧠 Score {nvda_score}/5 | Kelly {kelly_f*100:.1f}% | {optimal_action}"},
                      files={"photo": f})

save_memory(memory)