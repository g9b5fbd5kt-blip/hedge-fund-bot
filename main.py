import os, random, traceback, requests, sqlite3, json
from datetime import datetime, timezone, timedelta

# === TELEGRAM FIRST ===
TG_T = os.getenv("TELEGRAM_TOKEN","").strip()
TG_C = os.getenv("TELEGRAM_CHAT","").strip()
def tg(msg, photo=None):
    try:
        if not TG_T or not TG_C: return
        if photo:
            requests.post(f"https://api.telegram.org/bot{TG_T}/sendPhoto",
                         data={"chat_id":TG_C,"caption":msg[:1000]},
                         files={"photo":open(photo,'rb')}, timeout=15)
        else:
            requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage",
                         json={"chat_id":TG_C,"text":msg[:4000]}, timeout=10)
    except: pass

# === STARTUP PHRASES - YOUR STYLE ===
phrases = [
    "MAKING BANK 💸", "RACKING UP THAT PAPER 📈", "LET'S GET THIS BREAD",
    "MAKING PAPER BABY", "ANOTHER DAY ANOTHER DOLLAR", "TIME TO PRINT",
    "MONEY NEVER SLEEPS", "WE UP", "BAG SECURED"
]
tg(f"⚡ {random.choice(phrases)}\nAI Trader v6 online {datetime.now(timezone.utc).strftime('%H:%M UTC')}")

try:
    import pandas as pd, numpy as np, matplotlib.pyplot as plt
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    # === HARDCODE PAPER - NO SECRET NEEDED ===
    KEY = os.getenv("ALPACA_KEY",""); SEC = os.getenv("ALPACA_SECRET","")
    PAPER = True  # FORCE PAPER MODE
    MODE = os.getenv("RUN_MODE","crypto").lower()
    
    trade = TradingClient(KEY, SEC, paper=PAPER)
    stock_data = StockHistoricalDataClient(KEY, SEC)
    crypto_data = CryptoHistoricalDataClient()
    
    # === ADVANCED MEMORY - NO DUPLICATES ===
    DB = "brain_v6.db"
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS trades 
                (ts TEXT, symbol TEXT, action TEXT, price REAL, rsi REAL, 
                 strategy TEXT, pnl REAL, UNIQUE(symbol, action, price))""")
    con.execute("""CREATE TABLE IF NOT EXISTS performance 
                (date TEXT PRIMARY KEY, equity REAL, trades INTEGER)""")
    con.commit()
    
    acct = trade.get_account()
    equity = float(acct.equity)
    tg(f"✅ CONNECTED PAPER\nEquity: ${equity:,.0f}\nMode: {MODE.upper()}")
    
    # === SELF-ANALYSIS - LEARN FROM PAST ===
    cur = con.execute("SELECT COUNT(*), AVG(pnl), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) FROM trades WHERE pnl IS NOT NULL")
    total, avg_pnl, wins = cur.fetchone()
    winrate = (wins/total*100) if total and total>0 else 50
    risk_pct = 0.02 if winrate > 60 else 0.015 if winrate > 50 else 0.01  # adaptive
    
    tg(f"🧠 SELF-ANALYSIS\nTrades memory: {total or 0}\nWinrate: {winrate:.1f}%\nRisk today: {risk_pct*100:.1f}%")
    
    # === UNIVERSE - MAX COVERAGE ===
    crypto_u = ["BTC/USD","ETH/USD","SOL/USD","AVAX/USD","LINK/USD","DOGE/USD","ADA/USD","XRP/USD","LTC/USD","BCH/USD",
               "DOT/USD","MATIC/USD","UNI/USD","ATOM/USD","ARB/USD","OP/USD","SUI/USD","PEPE/USD","WIF/USD","BONK/USD"]
    stock_u = ["AAPL","MSFT","NVDA","TSLA","AMD","AMZN","META","GOOGL","SPY","QQQ","NFLX","COIN","MARA","RIOT","PLTR"]
    universe = crypto_u if MODE=="crypto" else stock_u
    
    def rsi(s): return 100-100/(1+s.diff().clip(lower=0).ewm(14).mean()/(-s.diff().clip(upper=0).ewm(14).mean()).replace(0,np.nan))
    
    buys = []; sells = []; errors = []
    
    for sym in universe[:15]:  # scan 15 per run for speed
        try:
            is_c = "/" in sym
            # Deep research - 5min + daily backtrend
            req = (CryptoBarsRequest if is_c else StockBarsRequest)(symbol_or_symbols=sym, timeframe=TimeFrame.FiveMinute, limit=100)
            df = (crypto_data if is_c else stock_data).get_crypto_bars(req).df.reset_index() if is_c else stock_data.get_stock_bars(req).df.reset_index()
            df = df[df.symbol==sym]
            if len(df)<30: continue
            
            df['ema9']=df.close.ewm(9).mean(); df['ema21']=df.close.ewm(21).mean(); df['ema50']=df.close.ewm(50).mean()
            df['rsi']=rsi(df.close); df['vol_ma']=df.volume.rolling(20).mean()
            l=df.iloc[-1]; volx=l.volume/max(df['vol_ma'].iloc[-1],1)
            
            # Backtrend - 20 day
            req_d = (CryptoBarsRequest if is_c else StockBarsRequest)(symbol_or_symbols=sym, timeframe=TimeFrame.Day, limit=20)
            dd = (crypto_data if is_c else stock_data).get_crypto_bars(req_d).df.reset_index() if is_c else stock_data.get_stock_bars(req_d).df.reset_index()
            dd=dd[dd.symbol==sym]; trend20 = (l.close/dd.close.iloc[0]-1)*100 if len(dd)>0 else 0
            
            # === MILLION-DOLLAR STRATEGIES ===
            strategy=None; action=None
            # 1. Momentum breakout
            if l.ema9>l.ema21>l.ema50 and 50<l.rsi<68 and volx>1.5:
                action="BUY"; strategy="momentum_breakout"
            # 2. Mean reversion
            elif l.rsi<32 and l.close < df.close.rolling(20).mean().iloc[-1]*0.97:
                action="BUY"; strategy="mean_revert"
            # 3. VWAP fade
            elif l.rsi>75:
                action="SELL"; strategy="overbought_fade"
            
            if action:
                # Deduplicate - skip if same trade in last hour
                cur = con.execute("SELECT 1 FROM trades WHERE symbol=? AND action=? AND ts > datetime('now','-1 hour')", (sym,action))
                if cur.fetchone(): continue
                
                qty = max(1, int((equity*risk_pct)/l.close)) if not is_c else 0.02
                research = f"Trend20: {trend20:+.1f}%\nRSI: {l.rsi:.0f} Vol:{volx:.1f}x\nEMA: {'↑↑' if l.ema9>l.ema21 else '↓'}"
                
                tg(f"🎯 {action} {sym} ${l.close:.2f}\nStrategy: {strategy}\n{research}")
                
                try:
                    if action=="BUY":
                        trade.submit_order(MarketOrderRequest(symbol=sym.replace('/',''), qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
                        buys.append(f"{sym} ${l.close:.2f}")
                    else:
                        try: trade.close_position(sym.replace('/','')); sells.append(sym)
                        except: pass
                    
                    con.execute("INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?,?,?)",
                               (datetime.now(timezone.utc).isoformat(), sym, action, float(l.close), float(l.rsi), strategy, None))
                    con.commit()
                except Exception as e:
                    errors.append(f"{sym}:{str(e)[:30]}")
        except Exception as e:
            errors.append(f"{sym} err")
    
    # === FINAL SUMMARY ===
    positions = trade.get_all_positions()
    pos_text = "\n".join([f"{p.symbol}: {p.qty} ({float(p.unrealized_pl):+.0f})" for p in positions[:10]]) or "None"
    
    summary = f"""📊 V6 SUMMARY
Buys: {len(buys)} | Sells: {len(sells)}
Positions: {len(positions)}
Capital: ${equity:,.0f}

HOLDINGS:
{pos_text}

TODAY:
Bought: {', '.join(buys[:3]) or 'None'}
Sold: {', '.join(sells[:3]) or 'None'}

Errors: {len(errors)}"""
    tg(summary)
    
    # === RESEARCH GRAPH ===
    try:
        df_p = pd.read_sql("SELECT date,equity FROM performance ORDER BY date DESC LIMIT 20", con)
        if len(df_p)>2:
            plt.figure(figsize=(6,3)); plt.plot(df_p.date, df_p.equity); plt.title("Equity Curve"); plt.xticks(rotation=45)
            plt.tight_layout(); plt.savefig("/tmp/eq.png"); plt.close()
            tg("Research: 20-day equity trend", photo="/tmp/eq.png")
    except: pass
    
    # Save performance
    con.execute("INSERT OR REPLACE INTO performance VALUES (?, ?, ?)",
               (datetime.now(timezone.utc).date().isoformat(), equity, len(buys)+len(sells)))
    con.commit(); con.close()
    
    tg(f"✅ RUN COMPLETE - Next in 60m")

except Exception as e:
    tg(f"🚨 V6 CRASH\n{str(e)}\n{traceback.format_exc()[-400:]}")