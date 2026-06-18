import os, logging, requests, pandas as pd, numpy as np
from datetime import datetime, timezone
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger()

# ENV
KEY = os.getenv("ALPACA_KEY","").strip()
SEC = os.getenv("ALPACA_SECRET","").strip()
PAPER = os.getenv("ALPACA_PAPER","true").lower()=="true"
TG_TOKEN = os.getenv("TELEGRAM_TOKEN","").strip()
TG_CHAT = os.getenv("TELEGRAM_CHAT","").strip()
FRED = os.getenv("FRED_API_KEY","").strip()
MODE = os.getenv("RUN_MODE","crypto").lower()

trade = TradingClient(KEY, SEC, paper=PAPER)
stock = StockHistoricalDataClient(KEY, SEC)
crypto = CryptoHistoricalDataClient()

def tg(m):
    if TG_TOKEN and TG_CHAT:
        try: requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id":TG_CHAT,"text":m}, timeout=10)
        except: pass

def atr(df,n=14):
    tr = pd.concat([df.high-df.low,(df.high-df.close.shift()).abs(),(df.low-df.close.shift()).abs()],1).max(1)
    return tr.rolling(n).mean()

def rsi(s,n=14):
    d=s.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean()
    dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+up/dn)

def curve():
    if not FRED: return 1.0
    try:
        v=requests.get(f"https://api.stlouisfed.org/fred/series/observations?series_id=T10Y2Y&api_key={FRED}&file_type=json&limit=1&sort_order=desc",timeout=10).json()["observations"][0]["value"]
        return float(v) if v!="." else 1.0
    except: return 1.0

def scan_crypto():
    pairs = ["BTC/USD","ETH/USD","SOL/USD","AVAX/USD","LINK/USD","DOGE/USD","ADA/USD","XRP/USD","LTC/USD","BCH/USD",
             "DOT/USD","MATIC/USD","UNI/USD","ATOM/USD","ALGO/USD","FIL/USD","AAVE/USD","SHIB/USD","TRX/USD","ETC/USD"]
    acct = trade.get_account(); eq=float(acct.equity); crv=curve(); risk=0.01*(0.5 if crv<0 else 1.2) # aggressive when curve positive
    tg(f"🚀 CRYPTO SCAN START\nEquity: ${eq:,.0f}\nYield Curve: {crv:.2f}\nRisk/trade: {risk*100:.1f}%\nScanning {len(pairs)} pairs...")
    signals=0; trades=0
    for p in pairs:
        try:
            df=crypto.get_crypto_bars(CryptoBarsRequest(symbol_or_symbols=p,timeframe=TimeFrame.Hour,limit=200)).df.reset_index()
            df=df[df.symbol==p];
            if len(df)<60: continue
            df['ema20']=df.close.ewm(20).mean(); df['ema50']=df.close.ewm(50).mean()
            df['rsi']=rsi(df.close); df['atr']=atr(df)
            l=df.iloc[-1]
            reason=""
            if l.ema20>l.ema50 and l.rsi<65: reason="EMA bull + RSI room"
            elif l.close > df.high.rolling(20).max().iloc[-2] and l.rsi<70: reason="20h breakout"
            if reason:
                signals+=1
                qty = max(0.001, round((eq*risk)/(2*l.atr),4))
                tg(f"📈 SIGNAL {p}\nPrice ${l.close:.2f}\nRSI {l.rsi:.1f} | EMA20>{'↑' if l.ema20>l.ema50 else '↓'}\nATR ${l.atr:.2f}\nReason: {reason}\nSize: {qty}")
                try:
                    trade.submit_order(MarketOrderRequest(symbol=p.replace('/',''), qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.GTC))
                    trades+=1; tg(f"✅ BUY EXECUTED {p} {qty}")
                except Exception as e: tg(f"❌ Order fail {p}: {e}")
        except Exception as e: log.error(e)
    tg(f"🏁 SCAN COMPLETE\nSignals: {signals}\nTrades placed: {trades}\nMode: {'PAPER' if PAPER else 'LIVE'}")

def scan_equities():
    # similar logic for stocks, runs during market hours
    tg("📊 EQUITIES SCAN (market hours only)")
    #... add your 30-stock list here...

if __name__=="__main__":
    tg(f"⚡ v3.2 ACTIVATED mode={MODE} {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
    if MODE=="crypto": scan_crypto()
    else: scan_equities()