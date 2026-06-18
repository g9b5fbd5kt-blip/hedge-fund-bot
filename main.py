import os, math, time, logging, requests, pandas as pd, numpy as np
from datetime import datetime, timezone, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

# --- ENV ---
ALPACA_KEY = os.getenv("ALPACA_KEY","").strip()
ALPACA_SECRET = os.getenv("ALPACA_SECRET","").strip()
PAPER = os.getenv("ALPACA_PAPER","true").lower()=="true"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN","").strip()
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT","").strip()
FRED_API_KEY = os.getenv("FRED_API_KEY","").strip()
RUN_MODE = os.getenv("RUN_MODE","equities").lower()

# --- CLIENTS ---
trade_client = TradingClient(ALPACA_KEY, ALPACA_SECRET, paper=PAPER)
stock_data = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)
crypto_data = CryptoHistoricalDataClient()

# --- TELEGRAM ---
def tg(msg):
    log.info(f"TG check token={bool(TELEGRAM_TOKEN)} chat={bool(TELEGRAM_CHAT)}")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                          json={"chat_id": TELEGRAM_CHAT, "text": msg}, timeout=10)
        log.info(f"Telegram {r.status_code}")
    except Exception as e:
        log.error(f"Telegram error: {e}")

# --- HELPERS ---
def atr(df, n=14):
    h,l,c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - (100/(1+rs))

def get_curve():
    if not FRED_API_KEY: return 1.0
    try:
        u = f"https://api.stlouisfed.org/fred/series/observations?series_id=T10Y2Y&api_key={FRED_API_KEY}&file_type=json&limit=1&sort_order=desc"
        v = requests.get(u, timeout=10).json()["observations"][0]["value"]
        return float(v) if v!="." else 1.0
    except: return 1.0

def position_size(equity, risk_pct, atr_val, price):
    if atr_val<=0: return 0
    risk_dollars = equity * risk_pct
    shares = risk_dollars / (2*atr_val)
    return int(shares)

# --- EQUITIES ---
def run_equities():
    tg(f"v3.1 EQUITIES start paper={PAPER}")
    curve = get_curve()
    acct = trade_client.get_account()
    equity = float(acct.equity)
    risk_pct = 0.01 * (0.5 if curve < 0 else 1.0)

    universe = ["AAPL","MSFT","NVDA","SPY","QQQ"]
    for sym in universe:
        try:
            req = StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Day, limit=100)
            df = stock_data.get_stock_bars(req).df.reset_index()
            df = df[df['symbol']==sym]
            if len(df)<50: continue
            df['atr'] = atr(df)
            df['rsi'] = rsi(df['close'])
            last = df.iloc[-1]
            if last['close'] > df['close'].rolling(20).mean().iloc[-1] and last['rsi']<70:
                qty = position_size(equity, risk_pct, last['atr'], last['close'])
                if qty>0:
                    trade_client.submit_order(MarketOrderRequest(symbol=sym, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
                    tg(f"BUY {sym} {qty} @ {last['close']:.2f}")
        except Exception as e:
            log.error(f"{sym} error {e}")
    tg("Equities run complete")

# --- CRYPTO ---
def run_crypto():
    tg(f"v3.1 CRYPTO start paper={PAPER}")
    pairs = ["BTC/USD","ETH/USD"]
    for sym in pairs:
        try:
            req = CryptoBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Hour, limit=200)
            df = crypto_data.get_crypto_bars(req).df.reset_index()
            df = df[df['symbol']==sym]
            if len(df)<50: continue
            df['ema20'] = df['close'].ewm(span=20).mean()
            df['ema50'] = df['close'].ewm(span=50).mean()
            last = df.iloc[-1]
            if last['ema20'] > last['ema50']:
                tg(f"CRYPTO SIGNAL {sym} bullish")
        except Exception as e:
            log.error(f"{sym} crypto error {e}")
    tg("Crypto run complete")

if __name__ == "__main__":
    tg(f"v3.1 start mode={RUN_MODE}")
    if RUN_MODE == "crypto":
        run_crypto()
    else:
        run_equities()