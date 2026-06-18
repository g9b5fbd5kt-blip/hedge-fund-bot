import os, logging, requests, pandas as pd, numpy as np, sqlite3, json
from datetime import datetime, timezone
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger()

KEY=os.getenv("ALPACA_KEY",""); SEC=os.getenv("ALPACA_SECRET","")
PAPER=os.getenv("ALPACA_PAPER","true")=="true"
TG_T=os.getenv("TELEGRAM_TOKEN",""); TG_C=os.getenv("TELEGRAM_CHAT","")
MODE=os.getenv("RUN_MODE","crypto")

trade=TradingClient(KEY,SEC,paper=PAPER)
stock=StockHistoricalDataClient(KEY,SEC)
crypto=CryptoHistoricalDataClient()

DB="research.db"
def init_db():
    con=sqlite3.connect(DB); con.execute("""CREATE TABLE IF NOT EXISTS signals
    (ts TEXT, symbol TEXT, price REAL, rsi REAL, ema_spread REAL, vol_ratio REAL, pattern TEXT, outcome TEXT)"""); con.commit(); con.close()

def tg(m): 
    if TG_T and TG_C:
        try: requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage",json={"chat_id":TG_C,"text":m},timeout=8)
        except: pass

def rsi(s): d=s.diff(); u=d.clip(lower=0).ewm(14).mean(); d=(-d.clip(upper=0)).ewm(14).mean(); return 100-100/(1+u/d)
def get_memory_pattern(sym):
    con=sqlite3.connect(DB); df=pd.read_sql("SELECT * FROM signals WHERE symbol=? AND outcome='win' ORDER BY ts DESC LIMIT 20",(sym,),con); con.close()
    return df

def scan_universe(symbols, data_client, is_crypto):
    init_db(); acct=trade.get_account(); eq=float(acct.equity)
    tg(f"⚡ v4 DAY-TRADER START\nMode: {MODE}\nEquity: ${eq:,.0f}\nScanning {len(symbols)} assets @ {datetime.now(timezone.utc).strftime('%H:%M')}")
    wins=0; trades=0
    for sym in symbols[:150]: # GitHub time limit - scan top 150 per run, rotates
        try:
            tf=TimeFrame.Minute if not is_crypto else TimeFrame.FiveMinute
            req = (CryptoBarsRequest if is_crypto else StockBarsRequest)(symbol_or_symbols=sym, timeframe=tf, limit=200)
            df = (crypto if is_crypto else stock).get_crypto_bars(req).df.reset_index() if is_crypto else stock.get_stock_bars(req).df.reset_index()
            df=df[df.symbol==sym]; 
            if len(df)<50: continue
            df['ema9']=df.close.ewm(9).mean(); df['ema21']=df.close.ewm(21).mean(); df['vwap']=(df.close*df.volume).cumsum()/df.volume.cumsum()
            df['rsi']=rsi(df.close); df['vol_avg']=df.volume.rolling(20).mean(); df['vol_ratio']=df.volume/df.vol_avg
            l=df.iloc[-1]; prev=df.iloc[-2]
            # ANTICIPATION: EMA cross imminent + volume building + RSI room
            ema_squeeze = abs(l.ema9-l.ema21)/l.close < 0.002
            vol_build = l.vol_ratio > 1.5 and l.vol_ratio > prev.vol_ratio
            rsi_room = 45 < l.rsi < 62
            pattern="none"
            if ema_squeeze and vol_build and rsi_room: pattern="anticipate_breakout"
            elif l.close > l.vwap and l.ema9 > l.ema21 and l.vol_ratio>2: pattern="momentum_confirm"
            
            # MEMORY CHECK
            mem = get_memory_pattern(sym)
            memory_boost = len(mem[mem.pattern==pattern]) > 3
            
            if pattern!="none":
                risk_pct = 0.015 if memory_boost else 0.01
                atr = (df.high-df.low).rolling(14).mean().iloc[-1]
                qty = max(1, int((eq*risk_pct)/(2*max(atr,0.01))))
                reason = f"{pattern} {'+MEMORY' if memory_boost else ''} | RSI {l.rsi:.0f} Vol {l.vol_ratio:.1f}x"
                tg(f"🎯 {sym} ${l.close:.2f}\n{reason}\nSize: {qty}")
                # store research
                con=sqlite3.connect(DB); con.execute("INSERT INTO signals VALUES (?,?,?,?,?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), sym, float(l.close), float(l.rsi), float(l.ema9-l.ema21), float(l.vol_ratio), pattern, "pending")); con.commit(); con.close()
                try:
                    trade.submit_order(MarketOrderRequest(symbol=sym.replace('/',''), qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
                    trades+=1; wins+=1 if memory_boost else 0
                except Exception as e: tg(f"❌ {sym} {e}")
        except Exception as e: continue
    tg(f"🏁 SCAN DONE\nTrades: {trades}\nMemory-boosted wins: {wins}\nNext run in 5m")

if __name__=="__main__":
    # Full market lists - top volume (you can expand)
    crypto_list = ["BTC/USD","ETH/USD","SOL/USD","AVAX/USD","LINK/USD","DOGE/USD","ADA/USD","XRP/USD","LTC/USD","BCH/USD","DOT/USD","MATIC/USD","UNI/USD","ATOM/USD","ALGO/USD","FIL/USD","AAVE/USD","SHIB/USD","TRX/USD","ETC/USD","APT/USD","ARB/USD","OP/USD","SUI/USD","PEPE/USD","WIF/USD","BONK/USD","NEAR/USD","RNDR/USD","INJ/USD"]
    stock_list = ["AAPL","MSFT","NVDA","TSLA","AMD","AMZN","META","GOOGL","SPY","QQQ","NFLX","COIN","MARA","RIOT","SOXL","TQQQ","SQQQ","PLTR","SMCI","AVGO","TSM","MU","INTC","BA","DIS","JPM","BAC","XOM","CVX","PFE"] # expand to 500 later
    if MODE=="crypto": scan_universe(crypto_list, crypto, True)
    else: scan_universe(stock_list, stock, False)