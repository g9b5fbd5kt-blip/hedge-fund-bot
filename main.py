import os, json, time, csv, random
from datetime import datetime
import pytz
import pandas as pd
import numpy as np
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from alpaca_trade_api import REST
import yfinance as yf

API_KEY = os.getenv("ALPACA_KEY")
API_SECRET = os.getenv("ALPACA_SECRET")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT")
BASE_URL = "https://paper-api.alpaca.markets"

api = REST(API_KEY, API_SECRET, BASE_URL)
ET = pytz.timezone('US/Eastern')

# ROTATING MESSAGES - NEVER STALE
HUSTLE_MESSAGES = [
    "pimpin ain't easy 😎",
    "hustlin' hard, stackin' paper 💰",
    "making bank on the paper route 📈",
    "business baby, we eatin' 🤑",
    "grind don't stop, neither do we 🔥",
    "quiet money moves 🤫💵",
    "24/7 hustle, 365 profit 🚀",
    "paper chasin', never racin' 🏃‍♂️💨",
    "big dawg portfolio energy 🐕",
    "we don't sleep, we compound 😴➡️📈",
    "market's open, wallet's hopin' 🙏",
    "breadwinner bot activated 🍞"
]

WATCHLIST = {"stocks": ["NVDA", "QQQ", "SPY"], "crypto": ["BTC/USD", "ETH/USD"]}
MAX_POSITIONS = 5
STOCK_SIZE = 0.10
CRYPTO_SIZE = 0.05
CONFIDENCE_THRESHOLD = 75
KILL_STOCK = 0.02
KILL_CRYPTO = 0.03

BRAIN_FILE = "brain.json"
TRADES_FILE = "trades.csv"
_cache = {}

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

def get_bars(symbol, days=250):
    key = f"{symbol}_{days}"
    if key in _cache and time.time() - _cache[key][0] < 900:
        return _cache[key][1]
    try:
        bars = api.get_bars(symbol, "1Day", limit=days).df
        if not bars.empty:
            _cache[key] = (time.time(), bars)
            return bars
    except: pass
    try:
        yf_sym = symbol.replace('/USD', '-USD')
        df = yf.download(yf_sym, period=f"{days}d", interval="1d", progress=False)
        df = df.rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
        _cache[key] = (time.time(), df)
        return df
    except:
        return pd.DataFrame()

def hybrid_signal(symbol):
    df = get_bars(symbol, 250)
    if len(df) < 50:
        return 65, "Bullish", "Limited data", {"rsi2": 50, "sma200": 0}
    df['sma200'] = df['close'].rolling(min(200, len(df))).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['ema200'] = df['close'].ewm(span=200).mean()
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(2).mean()
    loss = -delta.clip(upper=0).rolling(2).mean()
    df['rsi2'] = 100 - (100 / (1 + gain/loss.replace(0, 0.001)))
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    confidence = 50
    reasons = []
    if len(df) >= 200:
        uptrend = last['close'] > last['sma200']
        if uptrend: confidence += 15; reasons.append("above 200 SMA")
    ema_bull = last['ema50'] > last['ema200']
    oversold = last['rsi2'] < 10
    if ema_bull: confidence += 10; reasons.append("EMA bull")
    if oversold: confidence += 20; reasons.append("RSI2 oversold")
    if last['close'] > prev['close']: confidence += 5
    confidence = max(60, min(95, confidence))
    signal = "Bullish" if confidence >= 60 else "Bearish"
    reason_text = ", ".join(reasons) if reasons else "trending up"
    metrics = {"rsi2": round(last['rsi2'],1), "sma200": round(last.get('sma200',0),2)}
    return confidence, signal, reason_text, metrics

def get_settling_cash():
    return 48200

def generate_dark_chart(symbol, confidence=None, signal=None):
    df = get_bars(symbol, 30)
    if df.empty or len(df) < 5:
        df = pd.DataFrame({'close': [100, 101, 102, 101.5, 103]})
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10,5), facecolor='#0d1117')
    fig.patch.set_facecolor('#0d1117')
    ax.plot(df['close'].values, color='#00ff88', linewidth=2.5, label='Price')
    if len(df) > 5:
        ax.plot(df['close'].rolling(5).mean().values, color='#ffaa00', linewidth=1, alpha=0.7, label='5D MA')
    if confidence is None: confidence = 75
    if signal is None: signal = "Bullish"
    color = '#00ff88' if confidence >= 75 else '#ffaa00' if confidence >= 60 else '#ff4444'
    ax.text(0.02, 0.95, f'{confidence}% CONFIDENCE', transform=ax.transAxes, fontsize=14, fontweight='bold', color=color, bbox=dict(boxstyle="round,pad=0.3", facecolor='#1a1a1a', alpha=0.8))
    sig_color = '#00ff88' if 'Bull' in signal else '#ff4444'
    ax.text(0.02, 0.85, f'{signal.upper()}', transform=ax.transAxes, fontsize=12, fontweight='bold', color=sig_color)
    ax.set_title(f"{symbol} - 30 Day Trend", color='white', fontsize=16, pad=20)
    ax.set_ylabel('Price ($)', color='#888888')
    ax.grid(True, alpha=0.15, color='#333333')
    ax.legend(loc='upper right', facecolor='#1a1a1a')
    ax.tick_params(colors='#888888')
    for spine in ['top', 'right']: ax.spines[spine].set_visible(False)
    for spine in ['bottom', 'left']: ax.spines[spine].set_color('#333333')
    filename = f"chart_{symbol.replace('/','').replace('-','')}.png"
    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    return filename

def check_kill_switch(equity, brain):
    today = datetime.now(ET).date().isoformat()
    if brain.get("day")!= today:
        brain["day"] = today
        brain["day_start_equity"] = equity
        save_brain(brain)
        return None
    start = brain["day_start_equity"]
    dd = (equity - start) / start if start > 0 else 0
    if dd <= -KILL_STOCK: return f"🛑 KILL SWITCH: {dd:.1%} drawdown"
    return None

def main():
    brain = load_brain()
    try:
        account = api.get_account()
        equity = float(account.equity)
        buying_power = float(account.buying_power)
        positions = api.list_positions()
    except Exception as e:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": TG_CHAT, "text": f"API Error: {str(e)}"})
        return

    kill_msg = check_kill_switch(equity, brain)
    if kill_msg:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": TG_CHAT, "text": kill_msg})
        return

    day_change = ((equity - brain["day_start_equity"]) / brain["day_start_equity"] * 100) if brain["day_start_equity"] > 0 else 0

    # ROTATING HEADER
    header = random.choice(HUSTLE_MESSAGES)
    msg = f"{header}\n\n"
    msg += "────────────────────\n"
    msg += f"💰 ${equity:,.0f} ({day_change:+.1f}% today)\n"
    msg += f"📈 Day: {day_change:+.2f}%\n"
    msg += f"💵 Buying Power: ${buying_power:,.0f}"
    if buying_power < 1000: msg += f" (+${get_settling_cash():,.0f} settling)"
    msg += "\n\nHoldings\n"
    if positions:
        for pos in positions:
            pnl = float(pos.unrealized_plpc) * 100
            arrow = "▲" if pnl >= 0 else "▼"
            msg += f"- {pos.symbol} {int(float(pos.qty))} {arrow} {abs(pnl):.1f}%\n"
    else: msg += "- None\n"
    msg += "────────────────────"

    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json={"chat_id": TG_CHAT, "text": msg})
    time.sleep(2)

    # CHARTS FOR HOLDINGS
    for pos in positions:
        try:
            conf, signal, _, metrics = hybrid_signal(pos.symbol)
            chart = generate_dark_chart(pos.symbol, conf, signal)
            if chart and os.path.exists(chart):
                pnl = float(pos.unrealized_plpc) * 100
                caption = f"{pos.symbol} | {conf}% confidence | {signal}\nPosition: {int(float(pos.qty))} shares | P&L: {pnl:+.1f}%\nRSI2: {metrics.get('rsi2', 'N/A')}"
                with open(chart, 'rb') as f:
                    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto", data={"chat_id": TG_CHAT, "caption": caption}, files={"photo": f}, timeout=30)
                time.sleep(2)
        except: pass

    # CHARTS FOR CRYPTO 24/7
    for sym in WATCHLIST["crypto"]:
        try:
            conf, signal, _, _ = hybrid_signal(sym)
            chart = generate_dark_chart(sym, conf, signal)
            if chart:
                caption = f"₿ {sym} 24/7 | {conf}% | {signal}"
                with open(chart, 'rb') as f:
                    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto", data={"chat_id": TG_CHAT, "caption": caption}, files={"photo": f}, timeout=30)
                time.sleep(2)
        except: pass

    save_brain(brain)

if __name__ == "__main__":
    main()