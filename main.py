import os, pytz, random, io
from datetime import datetime, timedelta
from alpaca_trade_api.rest import REST, TimeFrame
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

api = REST(os.getenv('ALPACA_KEY'), os.getenv('ALPACA_SECRET'), base_url='https://paper-api.alpaca.markets')
tg_token = os.getenv('TELEGRAM_TOKEN')
tg_chat = os.getenv('TELEGRAM_CHAT')

def send_tg(text):
    requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", json={"chat_id": tg_chat, "text": text, "parse_mode": "Markdown"})

def send_photo(buf, caption):
    requests.post(f"https://api.telegram.org/bot{tg_token}/sendPhoto", files={'photo':('chart.png', buf)}, data={'chat_id': tg_chat, 'caption': caption, 'parse_mode': 'Markdown'})

openers = ["GETTING THAT PAPER 💸","Working for that bread 🍞","Another day another dollar 💰","pimpin ain't easy 😎","Stacking chips 📈","Clocked in 💼"]
opener = random.choice(openers)

account = api.get_account()
equity = float(account.equity)
last_equity = float(account.last_equity)
day_change = equity - last_equity
day_pct = (day_change / last_equity * 100) if last_equity else 0

positions = api.list_positions()
holdings_text = ""
for p in positions[:5]:
    pl = float(p.unrealized_intraday_plpc) * 100
    arrow = "▲" if pl >= 0 else "▼"
    holdings_text += f"- {p.symbol}  {p.qty}  {arrow} {abs(pl):.1f}%\n"
if not holdings_text:
    holdings_text = "- Cash only\n"

send_tg(f"{opener}\n\n────────────────────\n💰 ${equity:,.0f} ({'+' if day_change>=0 else ''}${day_change:,.0f} today)\n📈 Day: {'+' if day_pct>=0 else ''}{day_pct:.2f}%\n\nHoldings\n{holdings_text}────────────────────")

for p in positions[:3]:
    sym = p.symbol
    try:
        start = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        bars = api.get_bars(sym, TimeFrame.Day, start=start, feed='iex').df.tail(30)
        if bars.empty or len(bars) < 20:
            continue
        
        bars['MA20'] = bars['close'].rolling(20).mean()
        bars['VolAvg'] = bars['volume'].rolling(10).mean()
        price = bars['close'].iloc