import os, random, traceback, requests, sqlite3
from datetime import datetime, timezone

KEY=os.getenv("ALPACA_KEY",""); SEC=os.getenv("ALPACA_SECRET","")
TG_T=os.getenv("TELEGRAM_TOKEN",""); TG_C=os.getenv("TELEGRAM_CHAT","")
MODE=os.getenv("RUN_MODE","crypto").lower()

def tg(m):
    try:
        r = requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage",
                         json={"chat_id":TG_C,"text":str(m)[:4000]}, timeout=10)
        print(f"Telegram status: {r.status_code}")  # shows in Actions log
    except Exception as e:
        print(f"Telegram error: {e}")

# TEST MESSAGE FIRST
tg(f"✅ BOT TEST {datetime.now(timezone.utc).strftime('%H:%M')} - If you see this, Telegram works")

PHRASES=["MAKING BANK 💸","RACKING UP THAT PAPER 📈","LET'S GET THIS BREAD"]
tg(f"⚡ {random.choice(PHRASES)}\nv8.1 online")

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame
    import pandas as pd, numpy as np

    trade=TradingClient(KEY, SEC, paper=True)
    acct=trade.get_account()
    tg(f"✅ Alpaca connected\nEquity: ${float(acct.equity):,.0f}")

    # Simple scan so you see activity
    c_data=CryptoHistoricalDataClient()
    df=c_data.get_crypto_bars(CryptoBarsRequest(symbol_or_symbols="BTC/USD", timeframe=TimeFrame.Hour, limit=5)).df
    tg(f"BTC last: ${df['close'].iloc[-1]:.0f}")

except Exception as e:
    tg(f"🚨 ERROR: {e}")
    print(traceback.format_exc())