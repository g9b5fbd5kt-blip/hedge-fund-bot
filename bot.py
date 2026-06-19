import json, os, requests, yfinance as yf
from datetime import datetime, timedelta
import numpy as np

MEMORY_FILE = "memory.json"
HDR = {"APCA-API-KEY-ID": os.getenv("ALPACA_KEY"), "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET")}
BASE = "https://paper-api.alpaca.markets"
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT")

def load_mem():
    if os.path.exists(MEMORY_FILE):
        return json.load(open(MEMORY_FILE))
    return {"open_trades": {}, "closed_trades": [], "pending": [], "equity_start": 1000}

def save_mem(m): json.dump(m, open(MEMORY_FILE, "w"), indent=2)

def rsi(prices, p=14):
    d = prices.diff()
    gain = d.clip(lower=0).rolling(p).mean()
    loss = -d.clip(upper=0).rolling(p).mean()
    return 100 - (100 / (1 + gain/loss))

mem = load_mem()
now = datetime.now()

# 1. Clean up old pending orders
for po in mem["pending"][:]:
    try:
        o = requests.get(f"{BASE}/v2/orders/{po['id']}", headers=HDR, timeout=5).json()
        age = now - datetime.fromisoformat(po["time"])
        if o["status"] in ["filled", "canceled", "rejected", "expired"] or age > timedelta(minutes=15):
            if o["status"] == "filled":
                mem["open_trades"][po["symbol"]] = {"entry": float(o["filled_avg_price"]), "qty": float(o["filled_qty"]), "time": po["time"]}
            mem["pending"].remove(po)
            if o["status"] != "filled":
                requests.delete(f"{BASE}/v2/orders/{po['id']}", headers=HDR)
    except: pass

# 2. Get account
acct = requests.get(f"{BASE}/v2/account", headers=HDR).json()
equity = float(acct["equity"]); cash = float(acct["cash"])
positions = requests.get(f"{BASE}/v2/positions", headers=HDR).json()
pos_map = {p["symbol"]: {"qty": float(p["qty"]), "plpc": float(p["unrealized_plpc"])*100, "price": float(p["current_price"])} for p in positions}

# 3. Calculate Kelly from real closed trades
closed = mem["closed_trades"]
wins = [t for t in closed if t["pnl"] > 0]
win_rate = len(wins) / len(closed) if closed else 0.5
avg_win = np.mean([t["pnl"] for t in wins]) if wins else 2.5
avg_loss = abs(np.mean([t["pnl"] for t in closed if t["pnl"] < 0])) if len(closed) > len(wins) else 1.5
kelly = max(0.03, min(0.08, win_rate - (1-win_rate)*(avg_loss/avg_win)))

# 4. Sell logic first
sold = []
for sym, pos in pos_map.items():
    # check technicals
    hist = yf.Ticker(sym).history(period="3mo")["Close"]
    r = rsi(hist).iloc[-1] if len(hist) > 20 else 50
    # sell if +3% profit, -2% loss, or overbought
    if pos["plpc"] > 3 or pos["plpc"] < -2 or r > 70:
        try:
            requests.post(f"{BASE}/v2/orders", headers=HDR, json={"symbol": sym, "qty": pos["qty"], "side": "sell", "type": "market", "time_in_force": "day"})
            sold.append(f"{sym} {pos['plpc']:+.1f}%")
            # record closed trade
            entry = mem["open_trades"].get(sym, {}).get("entry", pos["price"])
            mem["closed_trades"].append({"symbol": sym, "pnl": pos["plpc"], "entry": entry, "exit": pos["price"], "time": now.isoformat()})
            if sym in mem["open_trades"]: del mem["open_trades"][sym]
        except: pass

# 5. Buy logic - only if room
bought = []
if len(pos_map) < 3 and cash > 40 and len(mem["pending"]) == 0:
    universe = ["SCHD", "T", "VZ", "PFE", "KMI", "F", "KO"]
    for sym in universe:
        if sym in pos_map or sym in [p["symbol"] for p in mem["pending"]]: continue
        try:
            hist = yf.Ticker(sym).history(period="3mo")["Close"]
            price = hist.iloc[-1]; sma20 = hist.rolling(20).mean().iloc[-1]; sma50 = hist.rolling(50).mean().iloc[-1]
            r = rsi(hist).iloc[-1]
            # buy signal: uptrend and not overbought
            if price > sma20 > sma50 and 40 < r < 60 and cash > price:
                o = requests.post(f"{BASE}/v2/orders", headers=HDR, json={"symbol": sym, "qty": 1, "side": "buy", "type": "market", "time_in_force": "day"}).json()
                if "id" in o:
                    mem["pending"].append({"id": o["id"], "symbol": sym, "time": now.isoformat()})
                    bought.append(sym)
                    break  # only one buy per cycle
        except: continue

# 6. Save and report
save_mem(mem)
holdings = ", ".join([f"{s} ({p['plpc']:+.1f}%)" for s,p in pos_map.items()]) or "None"
msg = f"""🔥 $1K LIVE PREP v3
💰 ${equity:.0f} | Cash ${cash:.0f} | Holdings: {len(pos_map)}/3
📊 Trades: {len(closed)} closed | Win {win_rate*100:.0f}% | Kelly {kelly*100:.1f}%
🎯 {holdings}
⚡ Sold: {', '.join(sold) if sold else '—'} | Bought: {', '.join(bought) if bought else '—'}
Next: 5 min"""

if TG_TOKEN and TG_CHAT:
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": TG_CHAT, "text": msg})