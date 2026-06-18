import os, json, logging, requests, pandas as pd, numpy as np
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

import gspread
from oauth2client.service_account import ServiceAccountCredentials

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# --- CONFIG ---
IS_PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"
ALPACA_KEY = os.getenv("ALPACA_KEY", "")
ALPACA_SECRET = os.getenv("ALPACA_SECRET", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT", "")
GSPREAD_JSON = os.getenv("GSPREAD_JSON", "")
SHEET_ID = os.getenv("SHEET_ID", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
RUN_MODE = os.getenv("RUN_MODE", "equities") # equities | crypto | both

EQUITY_SYMBOLS = ["SPY","QQQ","IWM","EFA","AGG","EWU","EWG","EWJ","EWH","FXI","EWY","EWA","INDA"]
CRYPTO_SYMBOLS = ["BTC/USD","ETH/USD","SOL/USD"]

EQUITY_RISK = 0.01
CRYPTO_RISK = 0.005
MAX_EQUITY_POS = 3
MAX_CRYPTO_POS = 2
MAX_DD = 0.15
LOOKBACK = 200
ATR_PERIOD = 14

# --- HELPERS ---
def tg(msg):
    log.info(f"TG_CHECK token={bool(TELEGRAM_TOKEN)} chat={bool(TELEGRAM_CHAT)}")
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        log.warning("Telegram skipped - missing secrets")
        return
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": msg}, timeout=10)
        log.info(f"Telegram status={r.status_code} body={r.text[:80]}")
    except Exception as e:
        log.error(f"Telegram exception: {e}")

def get_yield_curve():
    if not FRED_API_KEY: return 1.0
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=T10Y2Y&api_key={FRED_API_KEY}&file_type=json&limit=1&sort_order=desc"
        return float(requests.get(url, timeout=10).json()["observations"][0]["value"])
    except: return 1.0

def rsi(s, p=14):
    d = s.diff(); g = d.clip(lower=0).ewm(alpha=1/p, adjust=False).mean()
    l = -d.clip(upper=0).ewm(alpha=1/p, adjust=False).mean()
    return 100 - 100/(1+g/l.replace(0, np.nan))

def macd(s):
    e12 = s.ewm(span=12, adjust=False).mean(); e26 = s.ewm(span=26, adjust=False).mean()
    m = e12-e26; sig = m.ewm(span=9, adjust=False).mean(); return m, sig

def atr(df): # true ATR using HLC
    h,l,c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/ATR_PERIOD, adjust=False).mean()

def fetch_equities(syms):
    end = datetime.now(timezone.utc); start = end - timedelta(days=LOOKBACK+100)
    try:
        bars = stock_client().get_stock_bars(StockBarsRequest(
            symbol_or_symbols=syms, timeframe=TimeFrame.Day,
            start=start, end=end, adjustment="all", feed="iex")).df
        return {s: bars.xs(s, level=0)[['open','high','low','close']] for s in syms if s in bars.index.get_level_values(0)}
    except Exception as e:
        tg(f"Equity data fail: {e}"); return {}

def fetch_crypto(syms):
    end = datetime.now(timezone.utc); start = end - timedelta(days=LOOKBACK+100)
    try:
        bars = crypto_client().get_crypto_bars(CryptoBarsRequest(
            symbol_or_symbols=syms, timeframe=TimeFrame.Day, start=start, end=end)).df
        return {s: bars.xs(s, level=0)[['open','high','low','close']] for s in syms if s in bars.index.get_level_values(0)}
    except Exception as e:
        tg(f"Crypto data fail: {e}"); return {}

def signal(df_dict, is_crypto=False):
    out = {}
    for sym, df in df_dict.items():
        if len(df) < LOOKBACK: continue
        c = df['close']; price = c.iloc[-1]; sma = c.rolling(200).mean().iloc[-1]
        mom = price/c.iloc[-LOOKBACK]-1; r = rsi(c).iloc[-1]
        m, ms = macd(c); m_ok = m.iloc[-1] > ms.iloc[-1]
        r_low, r_high = (30,75) if is_crypto else (35,72)
        sig = (price>sma) and (mom>0) and (r_low<r<r_high) and m_ok
        score = mom * (1-abs(r-50)/50) if sig else 0
        out[sym] = {"signal":sig, "price":price, "atr":atr(df).iloc[-1], "score":score}
    return out

def live_sharpe(df_dict):
    rets = []
    for df in df_dict.values():
        if len(df)>252: rets.extend(df['close'].pct_change().dropna().tail(252).tolist())
    if not rets: return 0
    r = pd.Series(rets); return float((r.mean()-0.045/252)/r.std()*np.sqrt(252))

def log_trade(sym, side, qty, price, reason):
    if not GSPREAD_JSON or not SHEET_ID: return
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GSPREAD_JSON),
            ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive'])
        gspread.authorize(creds).open_by_key(SHEET_ID).sheet1.append_row(
            [datetime.now().strftime('%Y-%m-%d %H:%M'), sym, side, qty, round(price,4), reason])
    except Exception as e: tg(f"Sheet skip: {e}")

def trade(sym, side, qty, price):
    tc = trade_client()
    if qty<=0: return
    try:
        tc.submit_order(MarketOrderRequest(symbol=sym, qty=qty, side=OrderSide.BUY if side=='BUY' else OrderSide.SELL,
            time_in_force=TimeInForce.DAY))
        tg(f"{'Bought' if side=='BUY' else 'Sold'} {qty} {sym} @ {price:.2f}")
        log_trade(sym, side, qty, price, "v3.1")
    except Exception as e: tg(f"Order fail {sym}: {e}")

def run_equities():
    tc = trade_client(); acct = tc.get_account(); eq = float(acct.equity)
    if eq < float(acct.last_equity)*(1-MAX_DD): tg("KILL SWITCH"); return
    data = fetch_equities(EQUITY_SYMBOLS)
    if not data: return
    curve = get_yield_curve(); sigs = signal(data); sharpe = live_sharpe(data)
    tg(f"Equities: Sharpe {sharpe:.2f}, Curve {curve:.2f}")
    if sharpe < 0.8 or curve < 0: tg("Risk-off, no new buys"); return

    positions = {p.symbol: float(p.qty) for p in tc.get_all_positions() if '/' not in p.symbol}
    opens = [o.symbol for o in tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))]
    if opens: tg(f"Skip, open orders: {opens}"); return

    buys = sorted([s for s,v in sigs.items() if v['signal']], key=lambda x: sigs[x]['score'], reverse=True)[:MAX_EQUITY_POS]
    for sym in EQUITY_SYMBOLS:
        has = sym in positions; want = sym in buys
        if want and not has:
            qty = int((eq*EQUITY_RISK)/sigs[sym]['price']); trade(sym,'BUY',qty,sigs[sym]['price'])
        elif not want and has:
            trade(sym,'SELL',int(positions[sym]),sigs.get(sym,{'price':0})['price'])

def run_crypto():
    tc = trade_client(); acct = tc.get_account(); eq = float(acct.equity)
    data = fetch_crypto(CRYPTO_SYMBOLS)
    if not data: return
    sigs = signal(data, is_crypto=True)
    positions = {p.symbol: float(p.qty) for p in tc.get_all_positions() if '/' in p.symbol}

    buys = sorted([s for s,v in sigs.items() if v['signal']], key=lambda x: sigs[x]['score'], reverse=True)[:MAX_CRYPTO_POS]
    for sym in CRYPTO_SYMBOLS:
        has = sym in positions; want = sym in buys
        price = sigs.get(sym,{'price':0})['price']; atr = sigs.get(sym,{'atr':price*0.02})['atr']
        if want and not has:
            risk_amt