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

ET = pytz.timezone('US/Eastern')

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
BASE_STOCK_SIZE = 0.10
BASE_CRYPTO_SIZE = 0.05
CONFIDENCE_THRESHOLD = 70
KILL_STOCK = 0.02
MAX_TECH_EXPOSURE = 0.40

BRAIN_FILE = "brain.json"
TRADES_FILE = "trades.csv"
_cache = {}

def load_brain():
    try:
        with open(BRAIN_FILE, 'r') as f:
            brain = json.load(f)
            brain.setdefault("memory", {})
            brain.setdefault("stats", {"wins":0, "losses":0, "avg_win":0.02, "avg_loss":0.015})
            brain.setdefault("mode", "paper")
            brain.setdefault("paused", False)
            brain.setdefault("last_update_id", 0)
            return brain
    except:
        return {"trades":0, "wins":0, "accuracy":0, "day_start_equity":100000, "day":"", 
                "memory":{}, "stats":{"wins":0,"losses":0,"avg_win":0.02,"avg_loss":0.015},
                "mode":"paper", "paused":False, "last_update_id":0}

def save_brain(brain):
    with open(BRAIN_FILE, 'w') as f:
        json.dump(brain, f)

def check_telegram_commands(brain):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
        response = requests.get(url, params={"offset": brain["last_update_id"] + 1, "timeout": 3}, timeout=5)
        updates = response.json().get("result", [])
        
        for update in updates:
            brain["last_update_id"] = update["update_id"]
            msg = update.get("message", {})
            text = msg.get("text", "").lower()
            chat_id = str(msg.get("chat", {}).get("id", ""))
            
            if chat_id != TG_CHAT:
                continue
                
            if "/live" in text:
                brain["mode"] = "live"
                send_tg("🚀 LIVE MODE REQUESTED\n⚠️ No funded account detected - staying in paper\nAdd live keys to enable")
                brain["mode"] = "paper"  # Force paper until funded
            elif "/paper" in text:
                brain["mode"] = "paper"
                send_tg("📝 PAPER MODE ACTIVE\nSafe trading enabled")
            elif "/pause" in text:
                brain["paused"] = True
                send_tg("⏸️ BOT PAUSED\nUse /resume to continue")
            elif "/resume" in text:
                brain["paused"] = False
                send_tg("▶️ BOT RESUMED")
            elif "/status" in text:
                mode = brain["mode"].upper()
                paused = "PAUSED" if brain["paused"] else "ACTIVE"
                trades = brain["stats"]["wins"] + brain["stats"]["losses"]
                win_rate = brain["stats"]["wins"] / max(trades, 1) * 100
                memory = sum(len(v) for v in brain["memory"].values())
                status = f"📊 STATUS\nMode: {mode} ({paused})\nTrades: {trades}\nWin Rate: {win_rate:.1f}%\nMemory: {memory} patterns\nKelly: {'Active' if trades >= 20 else 'Learning'}"
                send_tg(status)
            elif "/memory" in text:
                total = sum(len(v) for v in brain["memory"].values())
                send_tg(f"🧠 MEMORY BANK\n{total} market patterns stored\nLearning from each trade")
            elif "/risk" in text:
                send_tg(f"🛡️ RISK GUARDS\nKill Switch: -2%\nMax Tech: 40%\nKelly: Half-size\nCorrelation: Active")
        
        save_brain(brain)
    except:
        pass
    return brain

def send_tg(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                     json={"chat_id": TG_CHAT, "text": text}, timeout=5)
    except:
        pass

def get_api_client(mode):
    # Always use paper until funded
    return REST(API_KEY, API_SECRET, "https://paper-api.alpaca.markets")

def get_bars(symbol, timeframe="1Min", limit=1000):
    key = f"{symbol}_{timeframe}"
    if key in _cache and time.time() - _cache[key][0] < 300:
        return _cache[key][1]
    
    try:
        api_temp = get_api_client("paper")
        bars = api_temp.get_bars(symbol, timeframe, limit=limit).df
        if not bars.empty:
            _cache[key] = (time.time(), bars)
            return bars
    except:
        pass
    
    try:
        yf_sym = symbol.replace('/USD', '-USD')
        period = "5d" if timeframe == "1Min" else "1y"
        interval = "1m" if timeframe == "1Min" else "1d"
        df = yf.download(yf_sym, period=period, interval=interval, progress=False)
        if not df.empty:
            df = df.rename(columns={'Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'})
            _cache[key] = (time.time(), df)
            return df
    except:
        pass
    return pd.DataFrame()

def update_memory_outcome(brain, symbol, outcome, pnl):
    if symbol in brain["memory"] and brain["memory"][symbol]:
        # Update most recent memory entry
        brain["memory"][symbol][-1]["outcome"] = outcome
        brain["memory"][symbol][-1]["pnl"] = pnl
        
        # Update stats
        if outcome == "win":
            brain["stats"]["wins"] += 1
            brain["stats"]["avg_win"] = (brain["stats"]["avg_win"] * (brain["stats"]["wins"]-1) + pnl) / brain["stats"]["wins"]
        else:
            brain["stats"]["losses"] += 1
            brain["stats"]["avg_loss"] = (brain["stats"]["avg_loss"] * (brain["stats"]["losses"]-1) + abs(pnl)) / brain["stats"]["losses"]
        
        save_brain(brain)

def get_memory_adjusted_confidence(brain, symbol, features):
    if symbol not in brain["memory"] or len(brain["memory"][symbol]) < 10:
        return 0
    
    similar = []
    for mem in brain["memory"][symbol][-50:]:  # Last 50 only
        if not mem.get("outcome"):
            continue
        rsi_diff = abs(mem.get("rsi2", 50) - features["rsi2"])
        if rsi_diff < 8:
            similar.append(mem)
    
    if len(similar) < 5:
        return 0
    
    wins = sum(1 for s in similar if s["outcome"] == "win")
    win_rate = wins / len(similar)
    
    if win_rate > 0.75:
        return 20
    elif win_rate > 0.65:
        return 12
    elif win_rate < 0.35:
        return -15
    return 0

def calculate_kelly_size(brain, base_size):
    stats = brain["stats"]
    total = stats["wins"] + stats["losses"]
    if total < 20:
        return base_size
    
    win_rate = stats["wins"] / total
    b = stats["avg_win"] / max(stats["avg_loss"], 0.001)
    kelly = (win_rate * (b + 1) - 1) / b
    kelly_half = max(0, min(kelly * 0.5, base_size * 1.5))
    return kelly_half if kelly_half > 0 else base_size

def check_correlation_risk(positions, new_symbol):
    tech_symbols = ["NVDA", "QQQ", "SPY"]
    if new_symbol not in tech_symbols:
        return True
    
    tech_exposure = sum(float(p.market_value) for p in positions if p.symbol in tech_symbols)
    total_equity = sum(float(p.market_value) for p in positions) + 100000  # Approx
    
    if tech_exposure / total_equity > MAX_TECH_EXPOSURE:
        return False
    return True

def hybrid_signal(symbol, brain, api):
    # Get intraday data for live signals
    df_min = get_bars(symbol, "1Min", 500)
    df_day = get_bars(symbol, "1Day", 250)
    
    if df_day.empty or len(df_day) < 50:
        return 60, "Neutral", "Insufficient data", {"rsi2": 50}
    
    # Use daily for trend, intraday for timing
    df = df_day.copy()
    df['sma200'] = df['close'].rolling(200).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['ema200'] = df['close'].ewm(span=200).mean()
    
    # RSI2 on intraday if available
    if not df_min.empty and len(df_min) > 10:
        delta = df_min['close'].diff()
        gain = delta.clip(lower=0).rolling(2).mean()
        loss = -delta.clip(upper=0).rolling(2).mean()
        rsi2 = 100 - (100 / (1 + gain/loss.replace(0, 0.001)))
        current_rsi2 = float(rsi2.iloc[-1]) if not rsi2.empty else 50
    else:
        delta = df['close'].diff()
        gain = delta.clip(lower=0).rolling(2).mean()
        loss = -delta.clip(upper=0).rolling(2).mean()
        rsi2 = 100 - (100 / (1 + gain/loss.replace(0, 0.001)))
        current_rsi2 = float(rsi2.iloc[-1])
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    confidence = 50
    reasons = []
    
    # VWAP for intraday
    if not df_min.empty:
        vwap = (df_min['close'] * df_min['volume']).sum() / df_min['volume'].sum()
        if last['close'] > vwap:
            confidence += 8
            reasons.append("above VWAP")
    
    sma200 = last['sma200'] if not pd.isna(last['sma200']) else last['close']
    if last['close'] > sma200:
        confidence += 15
        reasons.append("above 200 SMA")
    
    if last['ema50'] > last['ema200']:
        confidence += 10
        reasons.append("EMA bull")
    
    if current_rsi2 < 10:
        confidence += 20
        reasons.append(f"RSI2 {current_rsi2:.0f} oversold")
    elif current_rsi2 > 90:
        confidence -= 15
        reasons.append("overbought")
    
    # Memory boost
    features = {"rsi2": current_rsi2, "price": float(last['close'])}
    memory_boost = get_memory_adjusted_confidence(brain, symbol, features)
    confidence += memory_boost
    if memory_boost != 0:
        reasons.append(f"memory {memory_boost:+d}%")
    
    confidence = max(55, min(95, confidence))
    signal = "Bullish" if confidence >= 65 else "Bearish" if confidence <= 45 else "Neutral"
    
    metrics = {"rsi2": round(current_rsi2, 1), "sma200": round(float(sma200), 2)}
    
    # Store in memory
    if symbol not in brain["memory"]:
        brain["memory"][symbol] = []
    brain["memory"][symbol].append({
        "timestamp": datetime.now().isoformat(),
        "rsi2": current_rsi2,
        "price": float(last['close']),
        "confidence": confidence,
        "outcome": None
    })
    if len(brain["memory"][symbol]) > 200:
        brain["memory"][symbol] = brain["memory"][symbol][-200:]
    
    return confidence, signal, ", ".join(reasons), metrics

def generate_dark_chart(symbol, confidence, signal, api):
    df = get_bars(symbol, "1Day", 30)
    if df.empty:
        df = pd.DataFrame({'close': [100, 101, 102, 101.5, 103]})
    
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 5), facecolor='#0d1117')
    ax.plot(df['close'].values, color='#00ff88', linewidth=2.5)
    
    if len(df) > 5:
        ax.plot(df['close'].rolling(5).mean().values, color='#ffaa00', alpha=0.7)
    
    color = '#00ff88' if confidence >= 75 else '#ffaa00' if confidence >= 60 else '#ff4444'
    ax.text(0.02, 0.95, f'{confidence}% CONFIDENCE', transform=ax.transAxes, 
            fontsize=14, fontweight='bold', color=color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor='#1a1a1a', alpha=0.8))
    ax.text(0.02, 0.85, signal.upper(), transform=ax.transAxes, 
            fontsize=12, fontweight='bold', color=color)
    
    ax.set_title(f"{symbol} - Live", color='white', fontsize=16)
    ax.grid(True, alpha=0.15)
    ax.tick_params(colors='#888888')
    
    filename = f"chart_{symbol.replace('/','')}.png"
    plt.tight_layout()
    plt.savefig(filename, dpi=120, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    return filename

def main():
    brain = load_brain()
    brain = check_telegram_commands(brain)
    
    if brain["paused"]:
        return
    
    api = get_api_client(brain["mode"])
    
    try:
        account = api.get_account()
        equity = float(account.equity)
        positions = api.list_positions()
    except Exception as e:
        send_tg(f"❌ API Error: {str(e)[:50]}")
        return
    
    # Update memory with outcomes
    for pos in positions:
        pnl = float(pos.unrealized_plpc)
        if abs(pnl) > 0.015:  # 1.5% move
            outcome = "win" if pnl > 0 else "loss"
            update_memory_outcome(brain, pos.symbol, outcome, pnl)
    
    # Kill switch
    today = datetime.now(ET).date().isoformat()
    if brain.get("day") != today:
        brain["day"] = today
        brain["day_start_equity"] = equity
    elif equity < brain["day_start_equity"] * (1 - KILL_STOCK):
        send_tg(f"🛑 KILL SWITCH: -2% hit")
        return
    
    day_change = ((equity - brain["day_start_equity"]) / brain["day_start_equity"] * 100)
    header = random.choice(HUSTLE_MESSAGES)
    
    msg = f"{header}\n\n────────────────────\n"
    msg += f"💰 ${equity:,.0f} ({day_change:+.1f}%)\n"
    
    kelly = calculate_kelly_size(brain, BASE_STOCK_SIZE)
    if kelly > BASE_STOCK_SIZE * 1.1:
        msg += f"🔥 Kelly: {kelly:.1%}\n"
    
    msg += f"\nHoldings\n"
    for pos in positions:
        pnl = float(pos.unrealized_plpc) * 100
        arrow = "▲" if pnl >= 0 else "▼"
        msg += f"- {pos.symbol} {int(float(pos.qty))} {arrow} {abs(pnl):.1f}%\n"
    if not positions:
        msg += "- None\n"
    msg += "────────────────────"
    
    send_tg(msg)
    time.sleep(1)
    
    # Send charts
    for pos in positions[:3]:  # Limit to 3 to avoid rate limits
        try:
            conf, signal, _, metrics = hybrid_signal(pos.symbol, brain, api)
            chart = generate_dark_chart(pos.symbol, conf, signal, api)
            if os.path.exists(chart):
                pnl = float(pos.unrealized_plpc) * 100
                caption = f"{pos.symbol} | {conf}% | {signal}\nP&L: {pnl:+.1f}% | RSI2: {metrics['rsi2']}"
                with open(chart, 'rb') as f:
                    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
                                data={"chat_id": TG_CHAT, "caption": caption},
                                files={"photo": f}, timeout=10)
                time.sleep(1)
        except:
            pass
    
    save_brain(brain)

if __name__ == "__main__":
    main()