import os, requests
TG_T=os.getenv("TELEGRAM_TOKEN",""); TG_C=os.getenv("TELEGRAM_CHAT","")
def tg(m): requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage",json={"chat_id":TG_C,"text":m[:4000]})

KEY=os.getenv("ALPACA_KEY",""); SEC=os.getenv("ALPACA_SECRET","")
tg(f"KEY starts: {KEY[:4]}... len {len(KEY)}\nSEC len {len(SEC)}")
# Test direct API
r=requests.get("https://paper-api.alpaca.markets/v2/account", auth=(KEY,SEC), timeout=10)
tg(f"Alpaca test: {r.status_code} {r.text[:100]}")

# === TELEGRAM CORE - NEVER FAILS ===
TG_T = os.getenv("TELEGRAM_TOKEN","").strip()
TG_C = os.getenv("TELEGRAM_CHAT","").strip()
def tg(msg):
    try:
        if TG_T and TG_C:
            requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage",
                         json={"chat_id":TG_C,"text":str(msg)[:4000]}, timeout=12)
    except: pass

# === YOUR PHRASES ===
PHRASES = ["MAKING BANK 💸","RACKING UP THAT PAPER 📈","LET'S GET THIS BREAD",
           "MAKING PAPER BABY","ANOTHER DAY ANOTHER DOLLAR","TIME TO PRINT",
           "MONEY NEVER SLEEPS","WE UP","BAG SECURED","COOKING","LOCKED IN"]
tg(f"⚡ {random.choice(PHRASES)}\nHedge AI v7 starting {datetime.now(timezone.utc).strftime('%H:%M')}")

def safe_run():
 try:
    import pandas as pd, numpy as np
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    # === CONFIG - HARDCODED PAPER ===
    KEY = os.getenv("ALPACA_KEY",""); SEC = os.getenv("ALPACA_SECRET","")
    if not KEY or not SEC: tg("❌ Missing Alpaca keys"); return
    PAPER = True; MODE = os.getenv("RUN_MODE","crypto").lower()

    # === INIT WITH RETRY ===
    for i in range(3):
        try:
            trade = TradingClient(KEY, SEC, paper=PAPER)
            s_data = StockHistoricalDataClient(KEY, SEC)
            c_data = CryptoHistoricalDataClient()
            acct = trade.get_account(); equity = float(acct.equity); break
        except Exception as e:
            if i==2: tg(f"🚨 Alpaca connect fail: {e}"); return
            time.sleep(2)

    tg(f"✅ LIVE\nEquity: ${equity:,.0f} | Mode: {MODE}")

    # === ADVANCED MEMORY ===
    con = sqlite3.connect("hedge_v7.db", timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS memory (
        id TEXT PRIMARY KEY, ts TEXT, symbol TEXT, action TEXT, price REAL,
        rsi REAL, strategy TEXT, trend20 REAL, volx REAL, result REAL)""")
    con.commit()

    # Self-learn
    try:
        cur = con.execute("SELECT COUNT(*), AVG(result) FROM memory WHERE result IS NOT NULL")
        total, avg = cur.fetchone(); total = total or 0
        winrate = 55.0
        if total>10:
            cur = con.execute("SELECT COUNT(*) FROM memory WHERE result>0")
            wins = cur.fetchone()[0] or 0; winrate = wins/total*100
        risk = 0.025 if winrate>60 else 0.018 if winrate>52 else 0.012
        tg(f"🧠 AI Memory: {total} trades | Win {winrate:.1f}% | Risk {risk*100:.1f}%")
    except: risk = 0.015; winrate = 50

    # === UNIVERSE - MAX COVERAGE ===
    crypto = ["BTC/USD","ETH/USD","SOL/USD","AVAX/USD","LINK/USD","DOGE/USD","ADA/USD","XRP/USD","LTC/USD","BCH/USD",
              "DOT/USD","MATIC/USD","UNI/USD","ATOM/USD","ARB/USD","OP/USD","SUI/USD","NEAR/USD","APT/USD","FIL/USD"]
    stocks = ["AAPL","MSFT","NVDA","TSLA","AMD","AMZN","META","GOOGL","SPY","QQQ","NFLX","COIN","MARA","RIOT","PLTR",
              "SOXL","TQQQ","SMCI","AVGO","MU"]
    universe = crypto if MODE=="crypto" else stocks

    def get_bars(sym, tf, lim):
        try:
            is_c = "/" in sym; client = c_data if is_c else s_data
            req = (CryptoBarsRequest if is_c else StockBarsRequest)(symbol_or_symbols=sym, timeframe=tf, limit=lim)
            df = client.get_crypto_bars(req).df.reset_index() if is_c else client.get_stock_bars(req).df.reset_index()
            return df[df.symbol==sym].copy()
        except: return pd.DataFrame()

    def rsi(s, n=14):
        try: d=s.diff(); u=d.clip(lower=0).ewm(n).mean(); d=(-d.clip(upper=0)).ewm(n).mean(); return 100-100/(1+u/d.replace(0,np.nan))
        except: return pd.Series([50]*len(s))

    buys=[]; sells=[]; analyzed=0

    for sym in universe:
     try:
        # === DEEP RESEARCH - MULTI TIMEFRAME ===
        df5 = get_bars(sym, TimeFrame.FiveMinute, 100)
        df1h = get_bars(sym, TimeFrame.Hour, 50)
        dfd = get_bars(sym, TimeFrame.Day, 30)
        if len(df5)<40 or len(dfd)<10: continue
        analyzed+=1

        # Indicators
        for df in [df5, df1h]:
            df['ema9']=df.close.ewm(9).mean(); df['ema21']=df.close.ewm(21).mean()
            df['rsi']=rsi(df.close); df['volma']=df.volume.rolling(20).mean()

        l5=df5.iloc[-1]; l1=df1h.iloc[-1]; trend20=(l5.close/dfd.close.iloc[0]-1)*100
        volx = l5.volume/max(l5.volma,1); rsi5=l5.rsi; rsi1=l1.rsi

        # === EXPERT STRATEGIES ===
        signal=None; strat=""
        # 1. Triple EMA momentum
        if l5.ema9>l5.ema21 and l1.ema9>l1.ema21 and 48<rsi5<66 and volx>1.4:
            signal="BUY"; strat="triple_ema_momo"
        # 2. Mean reversion deep
        elif rsi5<30 and l5.close < df5.close.rolling(50).mean().iloc[-1]*0.96:
            signal="BUY"; strat="deep_revert"
        # 3. RSI divergence sell
        elif rsi5>74 or (rsi5<l5.rsi and l5.close>df5.close.iloc[-5]):
            signal="SELL"; strat="rsi_fade"
        # 4. Volume breakout
        elif volx>2.2 and l5.close>df5.high.rolling(20).max().iloc[-2]:
            signal="BUY"; strat="vol_breakout"

        if signal:
            # Deduplicate
            trade_id = f"{sym}_{signal}_{int(l5.close)}"
            if con.execute("SELECT 1 FROM memory WHERE id=?", (trade_id,)).fetchone(): continue

            # Research pack
            last5 = " ".join([f"{x:.1f}" for x in df5.close.tail(5)])
            research = f"20d:{trend20:+.1f}% RSI5:{rsi5:.0f}/1h:{rsi1:.0f} Vol:{volx:.1f}x\nLast5: {last5}"
            tg(f"🎯 {signal} {sym} ${l5.close:.2f}\n{strat}\n{research}")

            # Execute with safety
            try:
                qty = 0.02 if "/" in sym else max(1, int(equity*risk/l5.close))
                if signal=="BUY":
                    trade.submit_order(MarketOrderRequest(symbol=sym.replace('/',''), qty=qty,
                        side=OrderSide.BUY, time_in_force=TimeInForce.DAY)); buys.append(sym)
                else:
                    try: trade.close_position(sym.replace('/','')); sells.append(sym)
                    except: pass
                con.execute("INSERT OR IGNORE INTO memory VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (trade_id, datetime.now(timezone.utc).isoformat(), sym, signal, float(l5.close),
                            float(rsi5), strat, float(trend20), float(volx), None))
                con.commit()
            except Exception as e: tg(f"⚠️ Order {sym} failed: {str(e)[:60]}")
     except Exception: continue

    # === FINAL REPORT ===
    try:
        pos = trade.get_all_positions()
        pos_txt = "\n".join([f"{p.symbol} {p.qty} ${float(p.market_value):.0f}" for p in pos[:8]]) or "Cash"
        pnl_day = float(acct.equity) - float(acct.last_equity)
        report = f"""📊 V7 COMPLETE
Analyzed: {analyzed} | Buys: {len(buys)} | Sells: {len(sells)}
Equity: ${equity:,.0f} ({pnl_day:+.0f} today)
Winrate: {winrate:.1f}%

POSITIONS:
{pos_txt}

ACTIONS:
Bought: {', '.join(buys[:5]) or 'None'}
Sold: {', '.join(sells[:5]) or 'None'}"""
        tg(report)
    except Exception as e: tg(f"Report error: {e}")

    con.close(); tg("✅ Cycle done - sleeping 60m")

 except Exception as e:
    tg(f"🚨 FATAL\n{str(e)[:200]}\n{traceback.format_exc()[-250:]}")

# === RUN WITH WATCHDOG ===
safe_run()