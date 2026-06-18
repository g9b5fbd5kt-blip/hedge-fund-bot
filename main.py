import os, random, traceback, requests, sqlite3, time
from datetime import datetime, timezone

# === YOUR SECRETS - UNCHANGED ===
KEY=os.getenv("ALPACA_KEY",""); SEC=os.getenv("ALPACA_SECRET","")
TG_T=os.getenv("TELEGRAM_TOKEN",""); TG_C=os.getenv("TELEGRAM_CHAT","")
MODE=os.getenv("RUN_MODE","crypto").lower()

def tg(m, tag="INFO"):
    try:
        msg=f"[{tag}] {m}"
        r=requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage",
                       json={"chat_id":TG_C,"text":msg[:4000]}, timeout=15)
        print(f"TG {tag}: {r.status_code}")
        return r.status_code==200
    except Exception as e:
        print(f"TG FAIL: {e}")
        return False

# Immediate heartbeat
if not tg(f"v8.2 START {datetime.now(timezone.utc).strftime('%H:%M UTC')}", "HEARTBEAT"):
    print("CRITICAL: Telegram failed - check token/chat")

PHRASES=["MAKING BANK 💸","RACKING PAPER 📈","LET'S GET THIS BREAD","NO LIMITS"]
tg(random.choice(PHRASES), "START")

try:
    import pandas as pd, numpy as np
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    # === INIT WITH VALIDATION ===
    if not KEY or not SEC:
        raise ValueError("Alpaca keys missing")

    trade=TradingClient(KEY, SEC, paper=True)
    s_data=StockHistoricalDataClient(KEY, SEC)
    c_data=CryptoHistoricalDataClient()

    acct=trade.get_account()
    equity=float(acct.equity)
    tg(f"Connected | Equity ${equity:,.0f} | Buying Power ${float(acct.buying_power):,.0f}", "ACCOUNT")

    # === MEMORY ===
    con=sqlite3.connect("/tmp/hedge_memory.db", timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS trades
        (id TEXT PRIMARY KEY, ts TEXT, symbol TEXT, side TEXT, price REAL, qty REAL, reason TEXT, pnl REAL)""")
    con.commit()

    # Calculate adaptive risk
    cur=con.execute("SELECT COUNT(*), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END), AVG(pnl) FROM trades WHERE pnl IS NOT NULL")
    total,wins,avg_pnl=cur.fetchone()
    total=total or 0; wins=wins or 0
    winrate = (wins/total*100) if total>5 else 50
    risk_pct = 0.03 if winrate>60 and total>20 else 0.022 if winrate>55 else 0.015

    tg(f"Memory: {total} trades | WR {winrate:.1f}% | Risk {risk_pct*100:.1f}%", "BRAIN")

    # === ANALYSIS ENGINE ===
    def analyze(symbol, is_crypto):
        try:
            # Multi-timeframe
            tf_data={}
            for tf, limit in [(TimeFrame.FiveMinute, 50), (TimeFrame.Hour, 50)]:
                req=(CryptoBarsRequest if is_crypto else StockBarsRequest)(symbol_or_symbols=symbol, timeframe=tf, limit=limit)
                df=(c_data if is_crypto else s_data).get_crypto_bars(req).df if is_crypto else s_data.get_stock_bars(req).df
                if len(df)>20:
                    df=df[df.symbol==symbol] if 'symbol' in df.columns else df
                    tf_data[tf]=df

            if not tf_data: return None

            df5=tf_data[TimeFrame.FiveMinute]
            close=df5['close']; rsi=100-(100/(1+close.diff().clip(lower=0).ewm(14).mean()/(-close.diff().clip(upper=0).ewm(14).mean()).replace(0,0.001)))
            ema9=close.ewm(9).mean().iloc[-1]; ema21=close.ewm(21).mean().iloc[-1]
            vol_ratio=df5['volume'].iloc[-5:].mean()/df5['volume'].iloc[-20:-5].mean()

            # Advanced reasoning
            score=0; reasons=[]
            if ema9>ema21: score+=2; reasons.append("uptrend")
            if 35<rsi.iloc[-1]<65: score+=1; reasons.append("rsi_ok")
            if vol_ratio>1.2: score+=1; reasons.append("vol_up")
            if len(tf_data)>1 and tf_data[TimeFrame.Hour]['close'].iloc[-1] > tf_data[TimeFrame.Hour]['close'].iloc[-5]:
                score+=1; reasons.append("htf_up")

            return {"score":score, "price":close.iloc[-1], "rsi":rsi.iloc[-1], "reasons":",".join(reasons)}
        except Exception as e:
            tg(f"Analyze fail {symbol}: {str(e)[:100]}", "ERROR")
            return None

    # === TRADE EXECUTION ===
    actions=0; symbols=["BTC/USD","ETH/USD","SOL/USD"] if MODE=="crypto" else ["AAPL","MSFT","SPY"]

    for sym in symbols:
        result=analyze(sym, "/" in sym)
        if result and result["score"]>=3:
            try:
                qty = round((