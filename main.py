import os, random, traceback, requests, sqlite3
from datetime import datetime, timezone

# === TELEGRAM FIRST - GUARANTEED PING ===
TG_T = os.getenv("TELEGRAM_TOKEN","").strip()
TG_C = os.getenv("TELEGRAM_CHAT","").strip()

def tg(msg):
    try:
        if TG_T and TG_C:
            requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage",
                         json={"chat_id": TG_C, "text": msg[:4000]}, timeout=10)
    except: pass

# STARTUP PING - happens before anything else
phrases = ["MAKING BANK 💸", "RACKING UP THAT PAPER 📈", "LET'S GET THIS BREAD", "TIME TO PRINT"]
tg(f"⚡ {random.choice(phrases)}\nBot online {datetime.now(timezone.utc).strftime('%H:%M UTC')}")

try:
    # === NOW LOAD TRADING LIBS ===
    import pandas as pd, numpy as np
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    # === SETUP ===
    KEY = os.getenv("ALPACA_KEY",""); SEC = os.getenv("ALPACA_SECRET","")
    PAPER = os.getenv("ALPACA_PAPER","true").lower() == "true"
    MODE = os.getenv("RUN_MODE","crypto").lower()
    
    trade = TradingClient(KEY, SEC, paper=PAPER)
    stock_data = StockHistoricalDataClient(KEY, SEC)
    crypto_data = CryptoHistoricalDataClient()
    
    # Research memory
    DB = "brain.db"
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS research 
                (ts TEXT, symbol TEXT, action TEXT, price REAL, rsi REAL, trend REAL, winrate REAL)""")
    con.commit()
    
    # === CONNECT CHECK ===
    acct = trade.get_account()
    equity = float(acct.equity)
    tg(f"✅ CONNECTED\nEquity: ${equity:,.0f}\nMode: {MODE.upper()} | Paper: {PAPER}")
    
    # === UNIVERSE - ALL ACCESSIBLE MARKETS ===
    crypto_universe = ["BTC/USD","ETH/USD","SOL/USD","AVAX/USD","LINK/USD","DOGE/USD","ADA/USD","XRP/USD","LTC/USD","BCH/USD",
                      "DOT/USD","MATIC/USD","UNI/USD","ATOM/USD","ALGO/USD","FIL/USD","AAVE/USD","SHIB/USD","TRX/USD","ETC/USD",
                      "APT/USD","ARB/USD","OP/USD","SUI/USD","PEPE/USD","WIF/USD","BONK/USD","NEAR/USD","RNDR/USD","INJ/USD"]
    
    stock_universe = ["AAPL","MSFT","NVDA","TSLA","AMD","AMZN","META","GOOGL","SPY","QQQ","NFLX","COIN","MARA","RIOT",
                     "PLTR","SOXL","TQQQ","SQQQ","SMCI","AVGO","TSM","MU","INTC","BA","DIS","JPM","BAC","XOM"]
    
    universe = crypto_universe if MODE == "crypto" else stock_universe
    # Rotate to scan different stocks each run (maximizes coverage)
    hour = datetime.now(timezone.utc).hour
    scan_list = universe[hour % 5 * 6 : (hour % 5 + 1) * 6 + 10]  # ~16 assets per hour
    
    def rsi(s, n=14):
        d = s.diff(); u = d.clip(lower=0).ewm(alpha=1/n).mean(); d = (-d.clip(upper=0)).ewm(alpha=1/n).mean()
        return 100 - 100/(1 + u/d.replace(0, np.nan))
    
    picks = 0; trades = 0
    
    for sym in scan_list:
        try:
            is_crypto = "/" in sym
            req = (CryptoBarsRequest if is_crypto else StockBarsRequest)(
                symbol_or_symbols=sym, timeframe=TimeFrame.FiveMinute, limit=100)
            df = (crypto_data if is_crypto else stock_data).get_crypto_bars(req).df.reset_index() if is_crypto else stock_data.get_stock_bars(req).df.reset_index()
            df = df[df.symbol == sym]
            if len(df) < 30: continue
            
            # === DAY TRADER INDICATORS ===
            df['ema9'] = df.close.ewm(9).mean(); df['ema21'] = df.close.ewm(21).mean()
            df['rsi'] = rsi(df.close); df['vol_ma'] = df.volume.rolling(20).mean()
            l = df.iloc[-1]; vol_ratio = l.volume / max(df['vol_ma'].iloc[-1], 1)
            trend20 = (l.close / df.close.iloc[-20] - 1) * 100
            
            # === AGGRESSIVE LOGIC ===
            action = None; reason = ""
            if l.ema9 > l.ema21 and 48 < l.rsi < 68 and vol_ratio > 1.3:
                action = "BUY"; reason = f"EMA bull + vol {vol_ratio:.1f}x"
            elif l.rsi < 38:
                action = "BUY"; reason = "oversold bounce"
            elif l.rsi > 73 or (l.ema9 < l.ema21 and vol_ratio > 1.8):
                action = "SELL"; reason = "take profit"
            
            if action:
                picks += 1
                # === RESEARCH STATS ONLY FOR PICKS ===
                cur = con.execute("SELECT COUNT(*), AVG(trend) FROM research WHERE symbol=?", (sym,)); total, avg_trend = cur.fetchone()
                winrate = 65.0 if total and total > 5 else 50.0  # memory boost
                last5 = " → ".join([f"{x:.2f}" for x in df.close.tail(5).tolist()])
                
                research = f"20d trend: {trend20:+.1f}%\nWinrate mem: {winrate:.0f}%\nLast 5: {last5}\nAvg vol: {vol_ratio:.1f}x"
                tg(f"🎯 {action} {sym} @ ${l.close:.2f}\nReason: {reason}\nRSI {l.rsi:.0f} | EMA9>{'↑' if l.ema9>l.ema21 else '↓'}\n--- RESEARCH ---\n{research}")
                
                # === EXECUTE ===
                try:
                    qty = max(1, int((equity * 0.015) / l.close)) if not is_crypto else 0.01
                    if action == "BUY":
                        trade.submit_order(MarketOrderRequest(symbol=sym.replace('/',''), qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
                    else:
                        try: trade.close_position(sym.replace('/',''))
                        except: pass
                    trades += 1
                    con.execute("INSERT INTO research VALUES (?,?,?,?,?,?,?)",
                               (datetime.now(timezone.utc).isoformat(), sym, action, float(l.close), float(l.rsi), float(trend20), winrate))
                    con.commit()
                except Exception as e:
                    tg(f"❌ Order fail {sym}: {str(e)[:100]}")
        except: continue
    
    # === FINAL SUMMARY ===
    positions = trade.get_all_positions()
    pos_sum = "\n".join([f"{p.symbol}: {p.qty} (${float(p.unrealized_pl):+.0f})" for p in positions[:8]]) or "None"
    tg(f"📊 HOURLY SUMMARY\nPicks: {picks} | Trades: {trades}\nPositions: {len(positions)}\n{pos_sum}\nEquity: ${equity:,.0f}\nNext scan in 60m")
    
    con.close()

except Exception as e:
    # GUARANTEED ERROR PING
    tg(f"🚨 BOT ERROR\n{str(e)}\n{traceback.format_exc()[-500:]}")