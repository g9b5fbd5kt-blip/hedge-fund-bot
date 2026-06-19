import os, time, datetime, pytz, requests, sqlite3
import alpaca_trade_api as tradeapi
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("TELEGRAM_CHAT")
KEY = os.getenv("ALPACA_KEY")
SECRET = os.getenv("ALPACA_SECRET")
LIVE = os.getenv("LIVE_MODE","false")=="true"

api = tradeapi.REST(KEY, SECRET, "https://api.alpaca.markets" if LIVE else "https://paper-api.alpaca.markets")
tz = pytz.timezone('US/Eastern')

# persistent db
conn = sqlite3.connect("/data/bot.db", check_same_thread=False)
conn.execute("CREATE TABLE IF NOT EXISTS trades (ts TEXT, sym TEXT, side TEXT, qty REAL, price REAL, pnl REAL)")

def rsi(series, n=14):
    delta = series.diff()
    up = delta.clip(lower=0).ewm(alpha=1/n).mean()
    down = -delta.clip(upper=0).ewm(alpha=1/n).mean()
    return 100 - 100/(1+up/down)

def chart():
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10,5), facecolor='#0A0E14')
    ax.set_facecolor('#0A0E14')
    bars = api.get_bars("SPY", "5Min", limit=78).df
    ax.plot(bars.index, bars.close, '#00FF88', lw=2.5)
    ax.fill_between(bars.index, bars.close, bars.close.min(), alpha=0.15, color='#00FF88')
    ax.set_title(f'SPY {bars.close.iloc[-1]:.2f} • RSI {rsi(bars.close).iloc[-1]:.0f}', color='white')
    ax.grid(alpha=0.2)
    plt.xticks(rotation=45)
    plt.tight_layout()
    p='/tmp/c.png'; plt.savefig(p, dpi=180, bbox_inches='tight'); plt.close(); return p

def think_and_trade():
    acct = api.get_account()
    eq = float(acct.equity); bp = float(acct.buying_power)
    positions = {p.symbol: float(p.qty) for p in api.list_positions()}

    thoughts = []
    action = "HOLD"

    for sym in ["SPY","QQQ","BTC/USD","ETH/USD"]:
        bars = api.get_bars(sym, "1Min", limit=20).df
        if len(bars)<20: continue
        last = bars.close.iloc[-1]
        chg = (last/bars.close.iloc[-5]-1)*100
        r = rsi(bars.close).iloc[-1]
        ema = bars.close.ewm(span=20).mean().iloc[-1]

        thoughts.append(f"• {sym}: {chg:+.2f}% • RSI {r:.0f} • {'below' if last<ema else 'above'} EMA")

        # strategy: oversold bounce with trend filter
        if sym in positions: continue
        if len(positions)>=3 or bp<25: continue
        if chg < -0.5 and r < 35 and last > ema*0.998:
            qty = 1 if '/' not in sym else 0.001
            try:
                api.submit_order(sym, qty, "buy", "market", "day",
                    order_class="bracket",
                    stop_loss={"stop_price": round(last*0.99,2)},
                    take_profit={"limit_price": round(last*1.015,2)})
                conn.execute("INSERT INTO trades VALUES (?,?,?,?,?,?)",
                    (datetime.datetime.now().isoformat(), sym, "BUY", qty, last, 0))
                conn.commit()
                action = f"BUY {sym} @ ${last:.2f} (RSI {r:.0f})"
                break
            except Exception as e:
                thoughts.append(f" ⚠️ {e}")

    # build message
    now = datetime.datetime.now(tz)
    msg = f"🤖 *MARKET ANALYSIS AI* • {'LIVE' if LIVE else 'PAPER'}\n"
    msg += f"🕒 {now.strftime('%I:%M %p ET')}\n\n"
    msg += f"💭 *THINKING:*\n" + "\n".join(thoughts[:4]) + f"\n• Decision: {action}\n\n"
    msg += f"📊 *PORTFOLIO:*\n💵 Equity: ${eq:,.2f}\n💰 BP: ${bp:,.2f}\n📈 Positions: {len(positions)}/3"

    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
        data={"chat_id":CHAT, "caption":msg, "parse_mode":"Markdown"},
        files={"photo": open(chart(),'rb')})

# main loop
while True:
    try:
        et = datetime.datetime.now(tz)
        # run every 5 min, plus summaries at 8,16,22
        if et.minute % 5 == 0:
            think_and_trade()
        time.sleep(55)
    except Exception as e:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id":CHAT, "text": f"🚨 {e}"})
        time.sleep(60)