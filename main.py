import os, random, traceback, requests, sqlite3, time
from datetime import datetime, timezone

KEY=os.getenv("ALPACA_KEY",""); SEC=os.getenv("ALPACA_SECRET","")
TG_T=os.getenv("TELEGRAM_TOKEN",""); TG_C=os.getenv("TELEGRAM_CHAT","")
MODE=os.getenv("RUN_MODE","crypto").lower()

def tg(m, tag="INFO"):
    try:
        msg=f"[{tag}] {m}"
        r=requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage",
                       json={"chat_id":TG_C,"text":msg[:4000]}, timeout=15)
        print(f"TG {tag}: {r.status_code}")
        return True
    except Exception as e:
        print(f"TG FAIL: {e}")
        return False

tg(f"v8.2.1 START {datetime.now(timezone.utc).strftime('%H:%M UTC')}", "HEARTBEAT")
tg(random.choice(["MAKING BANK 💸","RACKING PAPER 📈","LET'S GET THIS BREAD"]), "START")

try:
    import pandas as pd, numpy as np
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    trade=TradingClient(KEY, SEC, paper=True)
    s_data=StockHistoricalDataClient(KEY, SEC)
    c_data=CryptoHistoricalDataClient()
    acct=trade.get_account()
    equity=float(acct.equity)
    tg(f"Connected | Equity ${equity:,.0f}", "ACCOUNT")

    con=sqlite3.connect("/tmp/hedge_memory.db", timeout=10)
    con.execute("CREATE TABLE IF NOT EXISTS trades (id TEXT PRIMARY KEY, ts TEXT, symbol TEXT, side TEXT, price REAL, qty REAL, reason TEXT, pnl REAL)")
    con.commit()

    cur=con.execute("SELECT COUNT(*), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) FROM trades WHERE pnl IS NOT NULL")
    total,wins=cur.fetchone(); total=total or 0; wins=wins or 0
    winrate = (wins/total*100) if total>5 else 50
    risk_pct = 0.03 if winrate>60 and total>20 else 0.022 if winrate>55 else 0.015
    tg(f"Memory: {total} trades | WR {winrate:.1f}% | Risk {risk_pct*100:.1f}%", "BRAIN")

    def analyze(symbol, is_crypto):
        try:
            req=(CryptoBarsRequest if is_crypto else StockBarsRequest)(symbol_or_symbols=symbol, timeframe=TimeFrame.FiveMinute, limit=50)
            df=(c_data if is_crypto else s_data).get_crypto_bars(req).df if is_crypto else s_data.get_stock_bars(req).df
            if len(df)<20: return None
            df=df[df.symbol==symbol] if 'symbol' in df.columns else df
            close=df['close']; ema9=close.ewm(9).mean().iloc[-1]; ema21=close.ewm(21).mean().iloc[-1]
            rsi=100-(100/(1+close.diff().clip(lower=0).ewm(14).mean()/(-close.diff().clip(upper=0).ewm(14).mean()).replace(0,0.001)))
            score=0; reasons=[]
            if ema9>ema21: score+=2; reasons.append("uptrend")
            if 35<rsi.iloc[-1]<65: score+=1; reasons.append("rsi_ok")
            return {"score":score, "price":float(close.iloc[-1]), "rsi":float(rsi.iloc[-1]), "reasons":",".join(reasons)}
        except Exception as e:
            tg(f"Analyze {symbol} err: {e}", "ERROR")
            return None

    actions=0
    symbols=["BTC/USD","ETH/USD","SOL/USD"]
    for sym in symbols:
        res=analyze(sym, True)
        if res and res["score"]>=2:
            # FIXED: simple if/else, no broken parentheses
            if "/" in sym:
                qty = round((equity * risk_pct) / res["price"], 6)
            else:
                qty = max(1, int((equity * risk_pct) / res["price"]))

            tid=f"{sym}_{int(time.time())}"
            try:
                order=MarketOrderRequest(symbol=sym.replace("/",""), qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.GTC)
                trade.submit_order(order)
                con.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?)",
                           (tid, datetime.now(timezone.utc).isoformat(), sym, "BUY", res["price"], qty, res["reasons"], None))
                con.commit()
                tg(f"BUY {sym} ${res['price']:.2f} qty {qty} | {res['reasons']}", "TRADE")
                actions+=1
            except Exception as e:
                tg(f"Order {sym} fail: {e}", "ERROR")

    tg(f"DONE | Actions:{actions} | Equity ${equity:,.0f}", "SUMMARY")
    con.close()

except Exception as e:
    tg(f"FATAL {e}", "FATAL")
    print(traceback.format_exc())
    raise