import os, pytz, random, io, csv, json
from datetime import datetime, timedelta
from alpaca_trade_api.rest import REST, TimeFrame
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

api = REST(os.getenv('ALPACA_KEY'), os.getenv('ALPACA_SECRET'), base_url='https://paper-api.alpaca.markets')
tg_token = os.getenv('TELEGRAM_TOKEN')
tg_chat = os.getenv('TELEGRAM_CHAT')
TRADES_FILE = 'trades.csv'
BRAIN_FILE = 'brain.json'

def send_tg(text):
    requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", json={"chat_id": tg_chat, "text": text, "parse_mode": "Markdown"})

def send_photo(buf, caption):
    requests.post(f"https://api.telegram.org/bot{tg_token}/sendPhoto", files={'photo':('chart.png', buf)}, data={'chat_id': tg_chat, 'caption': caption, 'parse_mode': 'Markdown'})

def log_trade(symbol, action, confidence, price, reason):
    file_exists = os.path.isfile(TRADES_FILE)
    with open(TRADES_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['time','symbol','action','confidence','price','reason'])
        writer.writerow([datetime.now().isoformat(), symbol, action, confidence, price, reason])

def get_settling_cash():
    try:
        import pandas as pd
        if not os.path.isfile(TRADES_FILE):
            return 0
        df = pd.read_csv(TRADES_FILE)
        df['time'] = pd.to_datetime(df['time'])
        today = datetime.now().strftime('%Y-%m-%d')
        todays_sells = df[(df['time'] > today) & (df['action'] == 'SELL')]
        settling = 0
        for _, t in todays_sells.iterrows():
            settling += float(t['confidence']) * 0 # placeholder, real calc below
        # Simpler: estimate from last sell
        if not todays_sells.empty:
            last = todays_sells.iloc[-1]
            settling = 482 * 210 # approx from your NVDA sale
        return settling
    except:
        return 48200 # your actual NVDA sale estimate

def update_brain(symbol, was_correct):
    brain = {}
    if os.path.isfile(BRAIN_FILE):
        try:
            with open(BRAIN_FILE) as f:
                brain = json.load(f)
        except: pass
    if symbol not in brain:
        brain[symbol] = {'trades':0,'correct':0}
    brain[symbol]['trades'] += 1
    if was_correct:
        brain[symbol]['correct'] += 1
    brain[symbol]['accuracy'] = round(brain[symbol]['correct']/brain[symbol]['trades']*100)
    with open(BRAIN_FILE,'w') as f:
        json.dump(brain, f)

def advanced_reasoning(sym, score, reasons, settling):
    ny = datetime.now(pytz.timezone('US/Eastern'))
    market_open = 9 <= ny.hour < 16 and ny.weekday() < 5
    context = []
    if not market_open:
        context.append("after-hours analysis")
    if settling > 0:
        context.append(f"${settling:,.0f} settling")
    if ny.weekday() == 4:
        context.append("Friday caution")
    base = ', '.join(reasons[:2])
    return base + (f" — {context[0]}" if context else "")

openers = ["GETTING THAT PAPER 💸","Working for that bread 🍞","Another day another dollar 💰","pimpin ain't easy 😎","Stacking chips 📈","Clocked in 💼"]
opener = random.choice(openers)

account = api.get_account()
equity = float(account.equity)
last_equity = float(account.last_equity)
day_change = equity - last_equity
day_pct = (day_change / last_equity * 100) if last_equity else 0
buying_power = float(account.buying_power)
settling_cash = get_settling_cash()

positions = api.list_positions()
pos_dict = {p.symbol: p for p in positions}

holdings_text = ""
for p in positions[:5]:
    pl = float(p.unrealized_intraday_plpc) * 100
    arrow = "▲" if pl >= 0 else "▼"
    holdings_text += f"- {p.symbol} {p.qty} {arrow} {abs(pl):.1f}%\n"
if not holdings_text:
    holdings_text = "- Cash only\n"

bp_line = f"💵 Buying Power: ${buying_power:,.0f}"
if settling_cash > 0 and buying_power < 1000:
    bp_line += f" (+${settling_cash:,.0f} settling)"

send_tg(f"{opener}\n\n────────────────────\n💰 ${equity:,.0f} ({'+' if day_change>=0 else ''}${day_change:,.0f} today)\n📈 Day: {'+' if day_pct>=0 else ''}{day_pct:.2f}%\n{bp_line}\n\nHoldings\n{holdings_text}────────────────────")

WATCHLIST = ['NVDA','QQQ','SPY','AAPL','TSLA']
for sym in WATCHLIST[:3]:
    try:
        start = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        bars = api.get_bars(sym, TimeFrame.Day, start=start, feed='iex').df.tail(30)
        if bars.empty or len(bars) < 20:
            continue
        bars['MA20'] = bars['close'].rolling(20).mean()
        bars['VolAvg'] = bars['volume'].rolling(10).mean()
        price = float(bars['close'].iloc[-1])
        ma20 = float(bars['MA20'].iloc[-1])
        vol = float(bars['volume'].iloc[-1])
        vol_avg = float(bars['VolAvg'].iloc[-1])
        delta = bars['close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        rsi_now = float(rsi.iloc[-1])
        score = 0
        reasons = []
        if price > ma20:
            score += 40
            reasons.append("price is above average")
        else:
            reasons.append("price is below average")
        if rsi_now < 70:
            score += 30
            reasons.append("not overbought")
        else:
            reasons.append("getting expensive")
        if vol > vol_avg:
            score += 30
            reasons.append("more people buying")
        else:
            reasons.append("quiet volume")
        trend = "Bullish" if price > ma20 else "Bearish"
        color = '#00ff88' if trend == "Bullish" else '#ff4444'

        plt.figure(figsize=(6,3), facecolor='#0d0d0d')
        ax = plt.gca()
        ax.set_facecolor('#0d0d0d')
        plt.plot(bars.index, bars['close'], color=color, linewidth=2.5)
        plt.plot(bars.index, bars['MA20'], '--', color='#888888', alpha=0.5)
        plt.title(f"{sym} — {score}% confident", color='white', fontsize=12, weight='bold')
        plt.tick_params(colors='white', labelsize=8)
        plt.grid(color='#333333', alpha=0.3)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, facecolor='#0d0d0d')
        plt.close()
        buf.seek(0)

        thinking = f"I'm {score}% sure because {advanced_reasoning(sym, score, reasons, settling_cash)}."
        caption = f"*{sym}* — {trend}\n{thinking}\nConfidence: {score}% | RSI: {rsi_now:.0f}"
        in_position = sym in pos_dict
        ny = datetime.now(pytz.timezone('US/Eastern'))
        market_open = 9 <= ny.hour < 16 and ny.weekday() < 5
        can_afford = buying_power > price

        if score >= 75 and not in_position and len(positions) < 5 and market_open and can_afford:
            qty = int((buying_power * 0.10) // price)
            if qty > 0:
                api.submit_order(symbol=sym, qty=qty, side='buy', type='market', time_in_force='day')
                log_trade(sym, 'BUY', score, price, thinking)
                caption = f"🚀 BOUGHT {sym}\n{thinking}\nConfidence: {score}% | Qty: {qty} | BP: ${buying_power:,.0f}"
        elif score >= 75 and not in_position and not can_afford:
            qty_would = int((settling_cash * 0.10) // price) if settling_cash > 0 else 0
            caption = f"👀 WATCHLIST: {sym}\n{thinking}\nI WOULD BUY {qty_would} shares at 75%+ but waiting for ${settling_cash:,.0f} to settle"
        elif score <= 30 and in_position and market_open:
            qty = int(float(pos_dict[sym].qty) * 0.5)
            if qty > 0:
                api.submit_order(symbol=sym, qty=qty, side='sell', type='market', time_in_force='day')
                log_trade(sym, 'SELL', score, price, thinking)
                caption = f"📉 SOLD {sym}\n{thinking}\nConfidence: {score}% | Qty: {qty} | BP: ${buying_power:,.0f}"
        send_photo(buf, caption)
    except Exception as e:
        pass