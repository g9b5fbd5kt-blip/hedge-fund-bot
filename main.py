import os, pytz
from datetime import datetime
from alpaca_trade_api.rest import REST, TimeFrame
import requests

# --- CONFIG ---
ACCOUNT_RISK_PCT = 0.01
EXTENDED_RISK_MULT = 0.5
CONFIDENCE_THRESHOLD = 0.75

api = REST(os.getenv('ALPACA_KEY'), os.getenv('ALPACA_SECRET'), base_url='https://paper-api.alpaca.markets')
tg_token = os.getenv('TELEGRAM_TOKEN')
tg_chat = os.getenv('TELEGRAM_CHAT')

def send_tg(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage",
                      json={"chat_id": tg_chat, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_session():
    now_et = datetime.now(pytz.timezone('US/Eastern'))
    clock = api.get_clock()
    is_open = clock.is_open
    hour = now_et.hour
    weekday = now_et.weekday() < 5
    extended = weekday and ((4 <= hour < 9) or (16 <= hour < 20))
    if is_open:
        return "REGULAR", ["AAPL", "MSFT", "NVDA"]
    elif extended:
        return "EXTENDED", ["SPY", "QQQ"]
    else:
        return "CRYPTO", ["BTC/USD", "ETH/USD"]

def position_size(account_value, entry, stop, is_extended=False):
    risk_pct = ACCOUNT_RISK_PCT * (EXTENDED_RISK_MULT if is_extended else 1)
    risk_dollars = account_value * risk_pct
    trade_risk = abs(entry - stop)
    if trade_risk == 0:
        return 0
    return int(risk_dollars / trade_risk)

# --- MAIN ---
session, universe = get_session()
account = api.get_account()
account_value = float(account.equity)
now_cst = datetime.now(pytz.timezone('US/Central')).strftime('%I:%M %p')

risk_per_trade = account_value * ACCOUNT_RISK_PCT
msg = f"✅ *Heartbeat* {now_cst}\nSession: {session}\nAccount: ${account_value:.2f}\nRisk/trade: ${risk_per_trade:.2f} (1%)\nScanning: {', '.join(universe)}"
send_tg(msg)

for ticker in universe:
    try:
        if "/" in ticker:
            price = float(api.get_latest_crypto_trade(ticker).price)
        else:
            price = float(api.get_latest_trade(ticker).price)
        
        confidence = 0.82
        rsi