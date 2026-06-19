import pytz
from datetime import datetime

now_et = datetime.now(pytz.timezone('US/Eastern'))
market_open = now_et.replace(hour=9, minute=30) <= now_et <= now_et.replace(hour=16, minute=0) and now_et.weekday() < 5

if market_open:
    mode = "TRADE"
    universe = ["AAPL","MSFT","NVDA"] # your stocks
else:
    mode = "RESEARCH"
    universe = ["BTC/USD","ETH/USD"] # 24/7 assets, or set to []import os, time, requests, random
from datetime import datetime, timezone

KEY = os.getenv("ALPACA_KEY",""); SEC = os.getenv("ALPACA_SECRET","")
TG_T = os.getenv("TELEGRAM_TOKEN",""); TG_C = os.getenv("TELEGRAM_CHAT","")
MODE = os.getenv("RUN_MODE","crypto").lower()

PHRASES = ["MAKING BANK 💸","RACKING PAPER 📈","LET'S GET THIS BREAD","GETTING THAT PAPER","NO LIMITS 🚀"]

def tg(m, tag="INFO"):
    try: requests.post(f"https://api.telegram.org/bot{TG_T}/sendMessage", json={"chat_id":TG_C,"text":f"[{tag}] {m}"[:4000]}, timeout=10)
    except: pass

tg(f"v9.1 START {datetime.now(timezone.utc).strftime('%H:%M')}", "HEARTBEAT")
tg(random.choice(PHRASES), "START")

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
    from strategy import analyze_all

    trade = TradingClient(KEY, SEC, paper=True)
    s_data = StockHistoricalDataClient(KEY, SEC)
    c_data = CryptoHistoricalDataClient()

    acct = trade.get_account()
    equity = float(acct.equity)
    tg(f"Connected | Equity ${equity:,.0f}", "ACCOUNT")

    # Get current positions to avoid duplicates
    positions = trade.get_all_positions()
    held = {p.symbol for p in positions}
    if held: tg(f"Holding: {', '.join(held)}", "POSITIONS")

    symbols = ["BTC/USD","ETH/USD","SOL/USD","AVAX/USD","LINK/USD"] if MODE=="crypto" else ["NVDA","TSLA","SPY"]
    is_crypto = {s: "/" in s for s in symbols}

    signals = analyze_all(symbols, is_crypto, {"stock": s_data, "crypto": c_data})
    tg(f"Scanning {len(symbols)} | Found {len(signals)} setups", "SCAN")

    actions = 0
    for sig in signals[:3]:
        if sig.score < 5.5: continue
        
        sym_clean = sig.symbol.replace("/","")
        # SKIP if already holding
        if sym_clean in held:
            continue

        # Cap position to 25% of equity max
        risk_pct = 0.02
        stop_dist = sig.atr * 2
        qty = (equity * risk_pct) / max(stop_dist, sig.price*0.01)
        
        max_position_value = equity * 0.25
        if qty * sig.price > max_position_value:
            qty = max_position_value / sig.price
        
        if not is_crypto[sig.symbol]:
            qty = int(qty)
            tif = TimeInForce.DAY
        else:
            qty = round(qty, 6)
            tif = TimeInForce.GTC

        if qty < 1: continue

        try:
            order = MarketOrderRequest(symbol=sym_clean, qty=qty, side=OrderSide.BUY, time_in_force=tif)
            trade.submit_order(order)
            tg(f"BUY {sig.symbol} ${sig.price:.2f} x{qty} | Score {sig.score:.1f}", "TRADE")
            actions += 1
            time.sleep(1)
        except Exception as e:
            pass  # silent fail to reduce noise

    tg(f"DONE | Actions:{actions} | Equity ${equity:,.0f}", "SUMMARY")

except Exception as e:
    tg(f"FATAL {str(e)[:100]}", "FATAL")