import os, random, logging, requests, pandas as pd, numpy as np, sqlite3
from datetime import datetime, timezone, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, ClosePositionRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest, StockLatestQuoteRequest
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

DB="brain.db"
def init():
    con=sqlite3.connect(DB); con.execute("""CREATE TABLE IF NOT EXISTS research
    (ts TEXT, symbol TEXT, action TEXT, price REAL, rsi REAL, volx REAL, trend20 REAL, win_rate REAL, notes TEXT)"""); con.commit(); con.close()

def tg(m): 
    if TG_T and TG_C:
        try: requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage", json={"chat_id":TG_C,"text":m}, timeout=10)
        except: pass

def startup():
    phrases = ["making bank 💸", "racking up that paper 📈", "let's get this bread", "time to print", "another me is online"]
    tg(f"⚡ {random.choice(phrases).upper()}\nHourly scan starting {datetime.now(timezone.utc).strftime('%H:%M UTC')}")

def rsi(s): return 100-100/(1+s.diff().clip(lower=0).ewm(14).mean()/ -s.diff().clip(upper=0).ewm(14).mean())
def get_universe():
    # ALL accessible markets - top active
    try:
        assets = trade.get_all_assets()
        stocks = [a.symbol for a in assets if a.tradable and a.status=='active' and a.exchange in ['NASDAQ','NYSE']][:250]
    except: stocks = ["AAPL","MSFT","NVDA","TSLA","AMD","AMZN","META","GOOGL","SPY","QQQ","NFLX","COIN","MARA","RIOT","PLTR","SOXL","TQQQ"]
    crypto = ["BTC/USD","ETH/USD","SOL/USD","AVAX/USD","LINK/USD","DOGE/USD","ADA/USD","XRP/USD","LTC/USD","BCH/USD","DOT/USD","MATIC/USD","UNI/USD","ATOM/USD","ARB/USD","OP/USD","SUI/USD","PEPE/USD","WIF/USD","BONK/USD","NEAR/USD","RNDR/USD","INJ/USD","APT/USD","SEI/USD","TIA/USD","JUP/USD","DOGE/USD","SHIB/USD","TRX/USD"]
    return stocks + crypto

def research_stats(sym, df):
    trend20 = (df.close.iloc[-1]/df.close.iloc[-20]-1)*100
    volx = df.volume.iloc[-1]/df.volume.rolling(20).mean().iloc[-1]
    win_rate = 0
    try:
        con=sqlite3.connect(DB); cur=con.execute("SELECT COUNT(*), SUM(CASE WHEN notes LIKE '%win%' THEN 1 ELSE 0 END) FROM research WHERE symbol=?", (sym,)); tot,wins=cur.fetchone(); con.close()
        win_rate = (wins/tot*100) if tot else 0
    except: pass
    return {"trend20":trend20, "volx":volx, "win_rate":win_rate, "last5":df.close.tail(5).tolist()}

def trade_asset(sym, df, is_crypto):
    l=df.iloc[-1]; r=rsi(df.close).iloc[-1]; ema9=df.close.ewm(9).mean().iloc[-1]; ema21=df.close.ewm(21).mean().iloc[-1]
    volx = df.volume.iloc[-1]/df.volume.rolling(20).mean().iloc[-1]
    stats = research_stats(sym, df)
    action=None; reason=""
    # AGGRESSIVE DAY-TRADER LOGIC
    if ema9>ema21 and r>52 and volx>1.8 and stats['trend20']>-5: 
        action="BUY"; reason=f"momentum + vol {volx:.1f}x"
    elif r<35 and l.close < df.close.rolling(20).mean().iloc[-1]*0.98:
        action="BUY"; reason="oversold bounce"
    elif r>72 or (ema9<ema21 and volx>2):
        action="SELL"; reason="take profit / fade"
    
    if action:
        # research stats ONLY for picks
        back = f"20d trend: {stats['trend20']:+.1f}%\nWin rate memory: {stats['win_rate']:.0f}%\nLast 5: {' → '.join([f'{x:.2f}' for x in stats['last5']])}"
        tg(f"🎯 {action} {sym} @ ${l.close:.2f}\nReason: {reason}\nRSI {r:.0f} | Vol {volx:.1f}x\n--- RESEARCH ---\n{back}")
        # store
        con=sqlite3.connect(DB); con.execute("INSERT INTO research VALUES (?,?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), sym, action, float(l.close), float(r), float(volx), float(stats['trend20']), float(stats['win_rate']), reason)); con.commit(); con.close()
        # execute aggressive
        try:
            qty = 1 if is_crypto else max(1, int(1000/l.close))  # aggressive sizing
            if action=="BUY":
                trade.submit_order(MarketOrderRequest(symbol=sym.replace('/',''), qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
            else:
                try: trade.close_position(sym.replace('/',''))
                except: pass
            return True
        except Exception as e: tg(f"❌ {sym} fail: {e}")
    return False

def summary():
    acct=trade.get_account(); positions=trade.get_all_positions()
    pos_text = "\n".join([f"{p.symbol}: {p.qty} (${float(p.unrealized_pl):+.0f})" for p in positions[:10]]) or "No positions"
    tg(f"📊 HOURLY SUMMARY\nEquity: ${float(acct.equity):,.0f}\nCash: ${float(acct.cash):,.0f}\nPositions ({len(positions)}):\n{pos_text}\n---\nNext scan in 60m. Stay aggressive.")

if __name__=="__main__":
    init(); startup()
    universe = get_universe()
    log.info(f"Scanning {len(universe)} assets")
    picks=0
    for sym in universe:
        is_crypto = '/' in sym
        try:
            tf = TimeFrame.FiveMinute
            req = (CryptoBarsRequest if is_crypto else StockBarsRequest)(symbol_or_symbols=sym, timeframe=tf, limit=100)
            df = (crypto if is_crypto else stock).get_crypto_bars(req).df.reset_index() if is_crypto else stock.get_stock_bars(req).df.reset_index()
            df=df[df.symbol==sym]
            if len(df)>30 and trade_asset(sym, df, is_crypto): picks+=1
        except: continue
    tg(f"✅ Scan complete. Picks made: {picks}")
    summary()