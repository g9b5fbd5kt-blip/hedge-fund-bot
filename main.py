import os, pytz, requests
from datetime import datetime
from alpaca_trade_api.rest import REST

api = REST(os.getenv('ALPACA_KEY'), os.getenv('ALPACA_SECRET'), base_url='https://paper-api.alpaca.markets')
tg_token = os.getenv('TELEGRAM_TOKEN')
tg_chat = os.getenv('TELEGRAM_CHAT')

def send_tg(msg):
    requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", json={"chat_id": tg_chat, "text": msg})

now_et = datetime.now(pytz.timezone('US/Eastern'))
clock = api.get_clock()
is_open = clock.is_open
hour = now_et.hour
weekday = now_et.weekday() < 5
extended = weekday and ((4 <= hour < 9) or (16 <= hour < 20))

if is_open:
    session = "REGULAR"
    universe = ["AAPL","MSFT","NVDA"]
elif extended:
    session = "EXTENDED"
    universe = ["SPY","QQQ"]
else:
    session = "CRYPTO"
    universe = ["BTC/USD","ETH/USD"]

account = api.get_account()
account_value = float(account.equity)
now_cst = datetime.now(pytz.timezone('US/Central')).strftime('%I:%M %p')
risk = account_value * 0.01

send_tg(f"✅ Heartbeat {now_cst}\nSession: {session}\nAccount: ${account_value:.2f}\nRisk: ${risk:.2f}\nTickers: {', '.join(universe)}")

for ticker in universe:
    try:
        if "/" in ticker:
            price = float(api.get_latest_crypto_trade(ticker).price)
        else:
            price = float(api.get_latest_trade(ticker).price)
        send_tg(f"📊 {ticker} @ ${price:.2f} — watching (no trade, confidence filter active)")
    except Exception as e:
        send_tg(f"⚠️ {ticker} error")