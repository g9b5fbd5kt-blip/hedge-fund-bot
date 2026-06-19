import os, random, requests, datetime, pytz, sqlite3
import alpaca_trade_api as tradeapi
import matplotlib.pyplot as plt

ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT")
DB_URL = os.getenv("DATABASE_URL")

api = tradeapi.REST(ALPACA_KEY, ALPACA_SECRET, "https://paper-api.alpaca.markets")

PHRASES = ["making bank baby 💸","getting to that paper 📈","checking stocks not flipping rocks","real ones invest","paper chasing","put your trust in that paper","real boss moves","real bosses sit back we don't talk. We just listen. 😎","clean money over here 🧼","first in my generation","who really want it","first you stack your paper then you make boss moves"]
MORNING = "Here's how we did big Pimpin"

try:
    import psycopg2
    conn = psycopg2.connect(DB_URL) if DB_URL else sqlite3.connect("trades.db")
except:
    conn = sqlite3.connect("trades.db")
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS trades (time TEXT, symbol TEXT, side TEXT, qty REAL, price REAL, pnl REAL)")
conn.commit()

def safe_check():
    try:
        acct = api.get_account()
        bp = float(acct.buying_power)
        positions = api.list_positions()
        return True, acct, positions
    except Exception as e:
        return False, None, []

def make_chart(equity=1000):
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(6,3), facecolor='#0A0E14')
    ax.set_facecolor('#0A0E14')
    ax.plot([equity*0.99, equity*1.005, equity*0.998, equity*1.01], color='#00FF88', linewidth=2.5)
    ax.axis('off')
    path = '/tmp/chart.png'
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#0A0E14')
    plt.close()
    return path

def tg_send(text, photo=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    kb = {"inline_keyboard": [[{"text":"📊 Chart","callback_data":"c"},{"text":"💰 P&L","callback_data":"p"},{"text":"⏸️ Pause","callback_data":"x"},{"text":"▶️ Resume","callback_data":"r"}]]}
    requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": text, "parse_mode": "Markdown", "reply_markup": kb})
    if photo: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", data={"chat_id": TELEGRAM_CHAT}, files={"photo": open(photo,'rb')})

et = datetime.datetime.now(pytz.timezone('US/Eastern'))
ok, acct, positions = safe_check()

if not ok:
    tg_send("🚨 *Bot offline* - can't reach Alpaca")
else:
    equity = float(acct.equity)
    bp = float(acct.buying_power)
    
    # HEARTBEAT - every 5 min
    status = f"*{random.choice(PHRASES)}*\n\n"
    status += f"🕒 {et.strftime('%I:%M %p ET')}\n"
    status += f"💵 Equity: ${equity:,.2f}\n"
    status += f"💰 BP: ${bp:,.2f}\n"
    status += f"📊 Positions: {len(positions)}/3\n"
    
    action = "Scanning SPY, QQQ, BTC, ETH..."
    for sym in ["SPY","QQQ","BTC/USD","ETH/USD"]:
        try:
            bars = api.get_bars(sym, "1Min", limit=5).df
            if len(bars)>=5:
                chg = (bars.close.iloc[-1]/bars.close.iloc[-5]-1)*100
                status += f"\n• {sym}: {chg:+.2f}%"
                if chg < -0.5 and len(positions)<3 and bp>25:
                    qty = 1 if "/" not in sym else 0.001
                    api.submit_order(sym, qty, "buy", "market", "day")
                    cur.execute("INSERT INTO trades VALUES (?,?,?,?,?,?)", (datetime.datetime.now().isoformat(), sym, "BUY", float(qty), float(bars.close.iloc[-1]), 0))
                    conn.commit()
                    action = f"✅ BOUGHT {sym}"
                    break
        except: pass
    
    status += f"\n\n{action}"
    
    # Keep your original summaries too
    if et.hour==8 and et.minute<5:
        tg_send(f"*{MORNING}*\n\n{status}", make_chart(equity))
    elif et.hour in [16,22] and et.minute<6:
        tg_send(status, make_chart(equity))
    else:
        tg_send(status, make_chart(equity))