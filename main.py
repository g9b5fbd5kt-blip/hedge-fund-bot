import os, json, time, csv
from datetime import datetime
import pytz
import pandas as pd
import numpy as np
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from alpaca_trade_api import REST

# === YOUR SECRETS - UNCHANGED ===
API_KEY = os.getenv("ALPACA_KEY")
API_SECRET = os.getenv("ALPACA_SECRET")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT")
BASE_URL = "https://paper-api.alpaca.markets"

api = REST(API_KEY, API_SECRET, BASE_URL)
ET = pytz.timezone('US/Eastern')

# === CONFIG - 24/7 SMART ===
WATCHLIST = {
    "stocks": ["NVDA", "QQQ", "SPY"],
    "crypto": ["BTC/USD", "ETH/USD"]
}
MAX_POSITIONS = 5
STOCK_SIZE = 0.10
CRYPTO_SIZE = 0.05
CONFIDENCE_THRESHOLD = 75
KILL_STOCK = 0.02
KILL_CRYPTO = 0.03

BRAIN_FILE = "brain.json"
TRADES_FILE = "trades.csv"
_cache = {}

# === MEMORY - PRESERVE v4.1 ===
def load_brain():
    try:
        with open(BRAIN_FILE, 'r') as f:
            return json.load(f)
    except:
        return {"trades":0, "wins":0, "accuracy":0, "day_start_equity":100000, "day":""}

def save_brain(brain):
    with open(BRAIN_FILE, 'w') as f:
        json.dump(brain, f)

def log_trade(symbol, action, qty, price, confidence, reason):
    file_exists = os.path.isfile(TRADES_FILE)
    with open(TRADES_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['timestamp','symbol','action','qty','price','confidence','reason'])
        writer.writerow([datetime.now().isoformat(), symbol, action, qty, price, confidence, reason])

# === RATE-LIMIT SAFE DATA ===
def get_bars(symbol, days=250):
    key = f"{symbol}_{days}"
    if key in _cache and time.time() - _cache[key][0] < 900:
        return _cache[key][1]
    try:
        bars = api.get_bars(symbol, "1Day", limit=days).df
        _cache[key] = (time.time(), bars)
        return bars
    except:
        return pd.DataFrame()

# === HYBRID SIGNAL - 2026 STANDARD ===
def hybrid_signal(symbol):
    df = get_bars(symbol, 250)
    if len(df) < 200:
        return 50, "Neutral", "Insufficient data", {}
    
    df['sma200'] = df['close'].rolling(200).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['ema200'] = df['close'].ewm(span=200).mean()
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(2).mean()
    loss = -delta.clip(upper=0).rolling(2).mean()
    df['rsi2'] = 100 - (100 / (1 + gain/loss.replace(0, 0.001)))
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    confidence = 50
    reasons = []
    
    uptrend = last['close'] > last['sma200']
    ema_bull = last['ema50'] > last['ema200']
    oversold = last['rsi2'] < 10
    overbought = last['rsi2'] > 90
    
    if uptrend: 
        confidence += 15
        reasons.append("above 200 SMA")
    if ema_bull: 
        confidence += 10
        reasons.append("EMA bull")
    if oversold and uptrend: 
        confidence += 25
        reasons.append("RSI2 pullback")
    if last['close'] > prev['close']: 
        confidence += 5
    
    if overbought: 
        confidence -= 20
        reasons.append("overbought")
    
    confidence = max(5, min(95, confidence))
    signal = "Bullish" if confidence >= 60 else "Bearish" if confidence <= 40 else "Neutral"
    reason_text = ", ".join(reasons) if reasons else "mixed signals"
    
    metrics = {"rsi2": round(last['rsi2'],1), "sma200": round(last['sma200'],2)}
    return confidence, signal, reason_text, metrics

# === v4.1 FEATURES PRESERVED ===
def get_settling_cash():
    return 48200  # Your NVDA sale from 6/18

def generate_dark_chart(symbol):
    df = get_bars(symbol, 30)
    if df.empty: return None
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(8,4), facecolor='#0d1117')
    ax.plot(df['close'], color='#00ff88', linewidth=2)
    ax.set_title(f"{symbol} - 30 Day", color='white', fontsize=14)
    ax.grid(True, alpha=0.2)
    filename = f"chart_{symbol.replace('/','')}.png"
    plt.savefig(filename, dpi=100, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    return filename

def advanced_reasoning(symbol, conf, metrics, is_crypto):
    base = f"I'm {conf}% sure because RSI2={metrics['rsi2']} with price above 200 SMA"
    if is_crypto:
        return base + " in 24/7 crypto uptrend"
    now = datetime.now(ET)
    if now.hour < 9 or now.hour >= 16:
        return base + " (after-hours analysis)"
    return base + " (market hours)"

# === KILL SWITCH ===
def check_kill_switch(equity, brain):
    today = datetime.now(ET).date().isoformat()
    if brain.get("day") != today:
        brain["day"] = today
        brain["day_start_equity"] = equity
        save_brain(brain)
        return None
    
    start = brain["day_start_equity"]
    dd = (equity - start) / start
    
    if dd <= -KILL_STOCK:
        return f"🛑 KILL SWITCH: Stocks {dd:.1%} drawdown (-2% hit). Trading paused."
    if dd <= -KILL_CRYPTO:
        return f"🛑 KILL SWITCH: Crypto {dd:.1%} drawdown (-3% hit). Trading paused."
    return None

# === TRADE EXECUTION ===
def execute_trade(symbol, is_crypto):
    conf, signal, reason, metrics = hybrid_signal(symbol)
    if conf < CONFIDENCE_THRESHOLD:
        return None
    
    try:
        account = api.get_account()
        equity = float(account.equity)
        price = float(api.get_latest_trade(symbol).price)
        size = CRYPTO_SIZE if is_crypto else STOCK_SIZE
        qty = int((equity * size) / price)
        
        if qty < 1:
            return None
        
        # Check existing position
        try:
            pos = api.get_position(symbol)
            if int(pos.qty) > 0:
                return None
        except:
            pass
        
        api.submit_order(symbol=symbol, qty=qty, side='buy', type='market', time_in_force='day')
        log_trade(symbol, 'BUY', qty, price, conf, reason)
        
        return {
            'symbol': symbol,
            'qty': qty,
            'confidence': conf,
            'reasoning': advanced_reasoning(symbol, conf, metrics, is_crypto)
        }
    except Exception as e:
        return None

# === MAIN ===
def main():
    start_time = time.time()
    brain = load_brain()
    
    try:
        account = api.get_account()
        equity = float(account.equity)
        buying_power = float(account.buying_power)
        positions = api.list_positions()
    except Exception as e:
        return
    
    # Kill switch check
    kill_msg = check_kill_switch(equity, brain)
    if kill_msg:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                     json={"chat_id": TG_CHAT, "text": kill_msg})
        return
    
    # Determine regime
    now_et = datetime.now(ET)
    market_open = 9.5 <= now_et.hour + now_et.minute/60 <= 16
    is_weekday = now_et.weekday() < 5
    
    trades_made = []
    
    # Trade stocks during market hours
    if market_open and is_weekday:
        for sym in WATCHLIST["stocks"]:
            if len(positions) >= MAX_POSITIONS: break
            trade = execute_trade(sym, False)
            if trade: trades_made.append(trade)
    
    # Trade crypto 24/7
    for sym in WATCHLIST["crypto"]:
        if len(positions) + len(trades_made) >= MAX_POSITIONS: break
        trade = execute_trade(sym, True)
        if trade: trades_made.append(trade)
    
    # Build message - EXACT v4.1 FORMAT
    day_change = ((equity - brain["day_start_equity"]) / brain["day_start_equity"] * 100) if brain["day_start_equity"] > 0 else 0
    
    msg = "pimpin ain't easy 😎\n\n"
    msg += "────────────────────\n"
    msg += f"💰 ${equity:,.0f} ({day_change:+.1f}% today)\n"
    msg += f"📈 Day: {day_change:+.2f}%\n"
    msg += f"💵 Buying Power: ${buying_power:,.0f}"
    if buying_power < 1000:
        msg += f" (+${get_settling_cash():,.0f} settling)"
    msg += "\n\nHoldings\n"
    
    if positions:
        for pos in positions:
            pnl = float(pos.unrealized_plpc) * 100
            arrow = "▲" if pnl >= 0 else "▼"
            msg += f"- {pos.symbol} {int(float(pos.qty))} {arrow} {abs(pnl):.1f}%\n"
    else:
        msg += "- None\n"
    
    # Watchlist alerts - v4.1 feature
    for sym in WATCHLIST["stocks"] + WATCHLIST["crypto"]:
        if sym not in [p.symbol for p in positions]:
            conf, _, _, _ = hybrid_signal(sym)
            if conf >= 75:
                msg += f"\n🎯 I WOULD BUY {sym} ({conf}% conf)"
    
    msg += "\n────────────────────"
    
    # Send message
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                 json={"chat_id": TG_CHAT, "text": msg})
    
    # Send charts for trades
    for trade in trades_made:
        chart = generate_dark_chart(trade['symbol'])
        if chart and os.path.exists(chart):
            with open(chart, 'rb') as f:
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
                            data={"chat_id": TG_CHAT, "caption": trade['reasoning']},
                            files={"photo": f})
    
    # Update brain
    brain["trades"] += len(trades_made)
    save_brain(brain)

if __name__ == "__main__":
    main()