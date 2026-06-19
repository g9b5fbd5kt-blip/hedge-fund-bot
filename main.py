import os, pytz, random
from datetime import datetime
from alpaca_trade_api.rest import REST
import requests

api = REST(os.getenv('ALPACA_KEY'), os.getenv('ALPACA_SECRET'), base_url='https://paper-api.alpaca.markets')
tg_token = os.getenv('TELEGRAM_TOKEN')
tg_chat = os.getenv('TELEGRAM_CHAT')

def send_tg(msg):
    requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage",
                  json={"chat_id": tg_chat, "text": msg, "parse_mode": "Markdown"})

# --- ROTATING OPENERS ---
openers = [
    "GETTING THAT PAPER 💸",
    "Working for that bread 🍞",
    "Another day another dollar 💰",
    "pimpin ain't easy 😎",
    "Stacking chips 📈",
    "Clocked in 💼"
]
opener = random.choice(openers)

# --- ACCOUNT DATA ---
account = api.get_account()
equity = float(account.equity)
last_equity = float(account.last_equity)
buying_power = float(account.buying_power)
day_change = equity - last_equity
day_pct = (day_change / last_equity * 100) if last_equity else 0

# --- POSITIONS (holdings) ---
positions = api.list_positions()
holdings_text = ""
for p in positions[:5]:  # top 5
    symbol = p.symbol
    qty = p.qty
    pl_pct = float(p.unrealized_intraday_plpc) * 100
    arrow = "▲" if pl_pct >= 0 else "▼"
    # simple text graph bar
    bar = "█" * max(1, int(abs(pl_pct)))
    holdings_text += f"- {symbol}  {qty}  {arrow} {abs(pl_pct):.1f}% {bar}\n"

if not holdings_text:
    holdings_text = "- No open positions\n"

# --- BUILD MESSAGE (your screenshot format) ---
msg = f"""{opener}

────────────────────
💰 ${equity:,.0f} ({'+' if day_change>=0 else ''}${day_change:,.0f} today)
📊 Buying Power: ${buying_power:,.0f}
📈 Day: {'+' if day_pct>=0 else ''}{day_pct:.2f}%

Holdings
{holdings_text}────────────────────"""

send_tg(msg)