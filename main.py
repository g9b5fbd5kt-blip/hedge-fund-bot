import os, pytz
from datetime import datetime
from alpaca_trade_api.rest import REST
import requests

api = REST(os.getenv('ALPACA_KEY'), os.getenv('ALPACA_SECRET'), base_url='https://paper-api.alpaca.markets')
tg_token = os.getenv('TELEGRAM_TOKEN')
tg_chat = os.getenv('TELEGRAM_CHAT')

def send_tg(msg):
    requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage",
                  json={"chat_id": tg_chat, "text": msg})

# HEARTBEAT — will always fire
now = datetime.now(pytz.timezone('US/Central')).strftime('%I:%M %p')
account = api.get_account()
send_tg(f"✅ Bot alive {now}\nAccount: ${float(account.equity):.2f}\nChat ID works!")