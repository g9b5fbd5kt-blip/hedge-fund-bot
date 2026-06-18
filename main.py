import os, time, traceback, requests, random
from datetime import datetime, timezone

KEY = os.getenv("ALPACA_KEY",""); SEC = os.getenv("ALPACA_SECRET","")
TG_T = os.getenv("TELEGRAM_TOKEN",""); TG_C = os.getenv("TELEGRAM_CHAT","")
MODE = os.getenv("RUN_MODE","crypto").lower()
PAPER = True

PHRASES = ["MAKING BANK 💸","RACKING PAPER 📈","LET'S GET THIS BREAD","GETTING THAT PAPER","NO LIMITS 🚀"]

def tg(m, tag="INFO"):
    try: requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage", json={"chat_id":TG_C,"text":f"[{tag}] {m}"[:4000]}, timeout=10)
    except: pass

tg(f"v9-LITE START {datetime.now(timezone.utc).strftime('%H:%M')}", "HEARTBEAT")
tg(random.choice(PHRASES), "START")

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
    from strategy import analyze_all

    trade = TradingClient(KEY, SEC, paper=PAPER)
    s_data = StockHistoricalDataClient(KEY, SEC)
    c_data = CryptoHistoricalDataClient()

    acct = trade.get_account()
    equity = float(acct.equity)
    tg(f"Connected | Equity ${equity:,.0f}", "ACCOUNT")

    # Universe - expanded from Claude's recommendation
    symbols = ["BTC/USD","ETH/USD","SOL/USD","AVAX/USD","LINK/USD"] if MODE=="crypto" else ["NVDA","TSLA","SPY"]
    is_crypto = {s: "/" in s for s in symbols}

    # Analyze all concurrently (Claude's upgrade)
    data_clients = {"stock": s_data, "crypto": c_data}
    signals = analyze_all(symbols, is_crypto, data_clients)

    tg(f"Scanning {len(symbols)} | Found {len(signals)} setups", "SCAN")

    actions = 0
    for sig in signals[:3]: # max 3 trades per run to manage risk
        if sig.score < 5.5: continue

        # Kelly-inspired sizing (simplified without DB)
        risk_pct = 0.02 # 2% per trade
        stop_dist = sig.atr * 2
        qty = round((equity * risk_pct) / max(stop_dist, sig.price*0.01), 6)

        if qty * sig.price < 5: continue # skip dust

        try:
            order = MarketOrderRequest(symbol=sig.symbol.replace("/",""), qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.GTC)
            trade.submit_order(order)
            tg(f"BUY {sig.symbol} ${sig.price:.2f} | Score {sig.score:.1f}/10 | {sig.setup_type}", "TRADE")
            actions += 1
            time.sleep(1)
        except Exception as e:
            tg(f"Order fail {sig.symbol}: {str(e)[:80]}", "ERROR")

    tg(f"DONE | Actions:{actions} | Equity ${equity:,.0f}", "SUMMARY")

except Exception as e:
    tg(f"FATAL {str(e)[:150]}", "FATAL")
    raise