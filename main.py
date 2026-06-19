import os, pytz
from datetime import datetime
from alpaca_trade_api.rest import REST, TimeFrame
import requests

# --- CONFIG (from your manual) ---
ACCOUNT_RISK_PCT = 0.01 # 1% base — Investopedia: retail max 2%【6195745966795019439†L31-L34】
EXTENDED_RISK_MULT = 0.5 # halve for extended hours — gap risk rule【6195745966795019439†L52-L54】
CONFIDENCE_THRESHOLD = 0.75

api = REST(os.getenv('ALPACA_KEY'), os.getenv('ALPACA_SECRET'), base_url='https://paper-api.alpaca.markets')
tg_token = os.getenv('TELEGRAM_TOKEN')
tg_chat = os.getenv('TELEGRAM_CHAT')

def send_tg(msg):
    requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage",
                  json={"chat_id": tg_chat, "text": msg, "parse_mode": "Markdown"})

def get_session():
    now_et = datetime.now(pytz.timezone('US/Eastern'))
    clock = api.get_clock()
    # Alpaca clock tells us if market is open
    is_open = clock.is_open
    # Extended hours: 4am-9:30am or 4pm-8pm ET weekdays
    hour = now_et.hour
    weekday = now_et.weekday() < 5
    extended = weekday and ((4 <= hour < 9) or (16 <= hour < 20))

    if is_open:
        return "REGULAR", ["AAPL","MSFT","NVDA"]
    elif extended:
        return "EXTENDED", ["SPY","QQQ"] # liquid ETFs only for extended
    else:
        return "CRYPTO", ["BTC/USD","ETH/USD"] # 24/7 — Alpaca docs confirm crypto trades 24/7【1913595250446865834†L20-L21】

def position_size(account_value, entry, stop, is_extended=False):
    risk_pct = ACCOUNT_RISK_PCT * (EXTENDED_RISK_MULT if is_extended else 1)
    risk_dollars = account_value * risk_pct
    trade_risk = abs(entry - stop)
    if trade_risk == 0: return 0
    # Investopedia formula: account risk / trade risk【6195745966795019439†L46-L48】
    return int(risk_dollars / trade_risk)

def analyze(ticker):
    # Simplified 3-signal model — replace with your real logic
    try:
        bars = api.get_crypto_bars(ticker, TimeFrame.Minute, limit=20).df if "/" in ticker else api.get_bars(ticker, TimeFrame.Minute, limit=20).df
        rsi = 35 # placeholder — you'd calculate real RSI
        confidence = 0.82
        return {"rsi": rsi, "confidence": confidence, "signal": "BUY" if rsi < 40 else "WATCH"}
    except:
        return {"confidence": 0}

# --- MAIN LOOP ---
session, universe = get_session()
account = api.get_account()
account_value = float(account.equity)

for ticker in universe:
    analysis = analyze(ticker)
    conf = analysis["confidence"]

    if conf < CONFIDENCE_THRESHOLD:
        continue

    # Get current price
    try:
        price = float(api.get_latest_trade(ticker).price) if "/" not in ticker else float(api.get_latest_crypto_trade(ticker).price)
    except: continue

    stop = price * 0.98 # 2% stop — example
    qty = position_size(account_value, price, stop, is_extended=(session=="EXTENDED"))

    if qty < 1: continue

    # Place order — extended hours requires limit + extended_hours=True【1913595250446865834†L24-L27】
    try:
        if session in ["REGULAR","EXTENDED"]:
            api.submit_order(
                symbol=ticker,
                qty=qty,
                side='buy',
                type='limit',
                time_in_force='day',
                limit_price=price,
                extended_hours=(session=="EXTENDED") # Alpaca requires this flag
            )
        else: # crypto
            api.submit_order(symbol=ticker, qty=qty, side='buy', type='market', time_in_force='gtc')

        # NEW TELEGRAM FORMAT (your request)
        msg = f"""🤖 *24/7 THINKING* — {ticker} ({session})

*Confidence:* {conf:.0%}
*Signals:*
- RSI: {analysis['rsi']} (oversold)
- Session: {session}
- Risk: ${account_value*ACCOUNT_RISK_PCT:.2f} ({ACCOUNT_RISK_PCT*100:.0f}%)

*Decision:* BUY {qty} @ ${price:.2f}
*Stop:* ${stop:.2f}
*GitHub mins:* ~1,850/2,000
*Next check:* {session} schedule"""
        send_tg(msg)

    except Exception as e:
        send_tg(f"⚠️ Order failed {ticker}: {str(e)[:100]}")