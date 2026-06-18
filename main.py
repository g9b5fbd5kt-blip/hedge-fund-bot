import os, random, traceback, requests, sqlite3, time
from datetime import datetime, timezone

# === CORE - YOUR SECRETS UNCHANGED ===
KEY=os.getenv("ALPACA_KEY",""); SEC=os.getenv("ALPACA_SECRET","")
TG_T=os.getenv("TELEGRAM_TOKEN",""); TG_C=os.getenv("TELEGRAM_CHAT","")
MODE=os.getenv("RUN_MODE","crypto").lower()
OPT=os.getenv("ENABLE_OPTIONS","false").lower()=="true"

def tg(m):
    try:
        if TG_T and TG_C:
            requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage",
                         json={"chat_id":TG_C,"text":str(m)[:4000]}, timeout=10)
    except: pass

PHRASES=["MAKING BANK 💸","RACKING UP THAT PAPER 📈","LET'S GET THIS BREAD",
         "MAKING PAPER BABY","ANOTHER DAY ANOTHER DOLLAR","TIME TO PRINT",
         "24/7 HUSTLE","NO LIMITS","ALL MARKETS"]
tg(f"⚡ {random.choice(PHRASES)}\nv8 online {datetime.now(timezone.utc).strftime('%H:%M')}")

try:
    import pandas as pd, numpy as np
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, GetOptionContractsRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, AssetStatus
    from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient, OptionHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    # === INIT ===
    trade=TradingClient(KEY, SEC, paper=True)
    s_data=StockHistoricalDataClient(KEY, SEC)
    c_data=CryptoHistoricalDataClient()
    o_data=OptionHistoricalDataClient(KEY, SEC) if OPT else None
    acct=trade.get_account(); equity=float(acct.equity)
    tg(f"✅ CONNECTED\n${equity:,.0f} | Options:{OPT}")

    # === MEMORY ===
    con=sqlite3.connect("hedge_v8.db", timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS trades
        (id TEXT PRIMARY KEY, ts TEXT, asset TEXT, symbol TEXT, side TEXT, price REAL, strategy TEXT, pnl REAL)""")
    con.commit()

    # Self-learn
    cur=con.execute("SELECT COUNT(*), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) FROM trades WHERE pnl IS NOT NULL")
    tot,wins=cur.fetchone(); tot=tot or 0; wr=(wins/tot*100) if tot>5 else 55
    risk=0.03 if wr>62 else 0.022 if wr>55 else 0.015

    # === UNIVERSE ===
    crypto=["BTC/USD","ETH/USD","SOL/USD","AVAX/USD","LINK/USD","DOGE/USD","ADA/USD","XRP/USD","LTC/USD","DOT/USD",
            "MATIC/USD","UNI/USD","ATOM/USD","ARB/USD","OP/USD","SUI/USD","PEPE/USD","WIF/USD","BONK/USD","NEAR/USD"]
    stocks=["AAPL","MSFT","NVDA","TSLA","AMD","AMZN","META","GOOGL","SPY","QQQ","NFLX","COIN","MARA","RIOT","PLTR",
            "SOXL","TQQQ","SMCI","AVGO","MU","TSM","ARM"]
    options_underlying=["SPY","QQQ","AAPL","TSLA","NVDA"] if OPT else []

    def get_df(sym, tf, lim, is_c):
        try:
            req=(CryptoBarsRequest if is_c else StockBarsRequest)(symbol_or_symbols=sym, timeframe=tf, limit=lim)
            df=(c_data if is_c else s_data).get_crypto_bars(req).df.reset_index() if is_c else s_data.get_stock_bars(req).df.reset_index()
            return df[df.symbol==sym]
        except: return pd.DataFrame()

    def rsi(s): d=s.diff(); u=d.clip(lower=0).ewm(14).mean(); d=(-d.clip(upper=0)).ewm(14).mean(); return 100-100/(1+u/d.replace(0,np.nan))

    actions=[]
    # === CRYPTO 24/7 ===
    for sym in crypto[:15]:
        try:
            df=get_df(sym, TimeFrame.FiveMinute, 80, True)
            if len(df)<30: continue
            df['e9']=df.close.ewm(9).mean(); df['e21']=df.close.ewm(21).mean(); df['r']=rsi(df.close); l=df.iloc[-1]
            sig=None
            if l.e9>l.e21 and 45<l.r<65: sig="BUY"
            elif l.r<28: sig="BUY"
            elif l.r>78: sig="SELL"
            if sig:
                tid=f"C_{sym}_{sig}_{int(l.close)}"
                if not con.execute("SELECT 1 FROM trades WHERE id=?",(tid,)).fetchone():
                    qty=0.02; 
                    try:
                        if sig=="BUY": trade.submit_order(MarketOrderRequest(symbol=sym.replace('/',''),qty=qty,side=OrderSide.BUY,time_in_force=TimeInForce.GTC))
                        else: trade.close_position(sym.replace('/',''))
                        con.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?)",(tid,datetime.now(timezone.utc).isoformat(),"crypto",sym,sig,float(l.close),"v8",None)); con.commit()
                        actions.append(f"{sig} {sym}"); tg(f"🎯 {sig} {sym} ${l.close:.2f}")
                    except Exception as e: tg(f"⚠️ {sym} {e}")
        except: continue

    # === STOCKS (market hours only) ===
    hr=datetime.now(timezone.utc).hour
    if 13 <= hr <= 20:  # 9:30-16:00 ET approx
        for sym in stocks[:12]:
            try:
                df=get_df(sym, TimeFrame.FiveMinute, 80, False)
                if len(df)<30: continue
                df['e9']=df.close.ewm(9).mean(); df['e21']=df.close.ewm(21).mean(); df['r']=rsi(df.close); l=df.iloc[-1]
                if l.e9>l.e21 and l.r<68:
                    tid=f"S_{sym}_B_{int(l.close)}"
                    if not con.execute("SELECT 1 FROM trades WHERE id=?",(tid,)).fetchone():
                        qty=max(1,int(equity*risk/l.close))
                        try: trade.submit_order(MarketOrderRequest(symbol=sym,qty=qty,side=OrderSide.BUY,time_in_force=TimeInForce.DAY)); actions.append(f"BUY {sym}"); tg(f"📈 BUY {sym}")
                        except: pass
            except: continue

    # === OPTIONS (if enabled) ===
    if OPT:
        try:
            for ul in options_underlying[:2]:
                # simple cash-secured put scan
                req=GetOptionContractsRequest(underlying_symbols=[ul], status=AssetStatus.ACTIVE, expiration_date_gte=(datetime.now().date()), limit=5)
                contracts=trade.get_option_contracts(req)
                if contracts: tg(f"🔍 Options scan {ul}: {len(contracts)} contracts")
        except Exception as e: tg(f"Options skip: {e}")

    # === SUMMARY ===
    pos=trade.get_all_positions(); pnl=float(acct.equity)-float(acct.last_equity)
    tg(f"📊 v8 DONE\nActions: {len(actions)}\nEquity: ${equity:,.0f} ({pnl:+.0f})\nWR: {wr:.1f}% Risk:{risk*100:.1f}%\nPos: {len(pos)}")
    con.close()

except Exception as e:
    tg(f"🚨 v8 ERROR\n{e}\n{traceback.format_exc()[-200:]}")