import os, pytz, random, io, csv
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

openers = ["GETTING THAT PAPER 💸","Working for that bread 🍞","Another day another dollar 💰","pimpin ain't easy 😎","Stacking chips 📈","Clocked in 💼"]
opener = random.choice(openers)

account = api.get_account()
equity = float(account.equity)
last_equity = float(account.last_equity)
day_change = equity - last_equity
day_pct = (day_change / last_equity * 100) if last_equity else 0
buying_power = float(account.buying_power)

positions = api.list_positions()
pos_dict = {p.symbol: p for p in positions}

holdings_text = ""
for p in positions[:5]:
    pl = float(p.unrealized_intraday_plpc) * 100
    arrow = "▲" if pl >= 0 else "▼"
    holdings_text += f"- {p.symbol} {p.qty} {arrow} {abs(pl):.1f}%\n"
if not holdings_text:
    holdings_text = "- Cash only\n"

send_tg(f"{opener}\n\n────────────────────\n💰 ${equity:,.0f} ({'+' if day_change>=0 else ''}${day_change:,.0f} today)\n📈 Day: {'+' if day_pct>=0 else ''}{day_pct:.2f}%\n\nHoldings\n{holdings_text}────────────────────")

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
        color = 'green' if trend == "Bullish" else 'red'

        plt.figure(figsize=(6,3))
        plt.plot(bars.index, bars['close'], color=color, linewidth=2)
        plt.plot(bars.index, bars['MA20'], '--', color='gray', alpha=0.6)
        plt.title(f"{sym} - {score}% confident", color=color)
        plt.grid(alpha=0.2)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        plt.close()
        buf.seek(0)

        thinking = f"I'm {score}% sure because {', '.join(reasons[:2])}."
        caption = f"*{sym}* — {trend}\n{thinking}\nConfidence: {score}% | RSI: {rsi_now:.0f}"

        # TRADING LOGIC
        in_position = sym in pos_dict
        action_taken = None

        if score >= 75 and not in_position and len(positions) < 5:
            qty = int((buying_power * 0.10) // price)
            if qty > 0:
                api.submit_order(symbol=sym, qty=qty, side='buy', type='market', time_in_force='day')
                log_trade(sym, 'BUY', score, price, thinking)
                caption = f"🚀 BOUGHT {sym}\n{thinking}\nConfidence: {score}% | Qty: {qty}"
                action_taken = 'BUY'

        elif score <= 30 and in_position:
            qty = int(float(pos_dict[sym].qty) * 0.5)
            if qty > 0:
                api.submit_order(symbol=sym, qty=qty, side='sell', type='market', time_in_force='day')
                log_trade(sym, 'SELL', score, price, thinking)
                caption = f"📉 SOLD {sym}\n{thinking}\nConfidence: {score}% | Qty: {qty}"
                action_taken = 'SELL'

        send_photo(buf, caption)

    except Exception as e:
        send_tg(f"⚠️ {sym} skipped: {str(e)[:50]}")