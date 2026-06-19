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
        if len(positions) >= 3: return False, "MAX"
        if bp < 25: return False, "LOW"
        return True, "OK"
    except Exception as e:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT, "text": f"🚨 {str(e)[:80]}"})
        return False, str(e)

def make_chart():
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(6,3), facecolor='#0A0E14')
    ax.set_facecolor('#0A0E14')
    ax.plot([1000,1005,1002,1010], color='#00FF88', linewidth=2.5)
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

def trade():
    ok,_ = safe_check()
    if not ok: return 0
    acct = api.get_account()
    equity = float(acct.equity)
    for sym in ["SPY","QQQ","BTC/USD","ETH/USD"]:
        try:
            bars = api.get_bars(sym, "1Min", limit=5).df
            if len(bars)<5: continue
            if bars.close.iloc[-1]/bars.close.iloc[-5]-1 < -0.005:
                qty = 1 if "/" not in sym else 0.001
                api.submit_order(sym, qty, "buy", "market", "day")
                cur.execute("INSERT INTO trades VALUES (?,?,?,?,?,?)", (datetime.datetime.now().isoformat(), sym, "BUY", float(qty), float(bars.close.iloc[-1]), 0))
                conn.commit()
                break
        except: continue
    return equity

et = datetime.datetime.now(pytz.timezone('US/Eastern'))
try:
    if et.hour==8 and et.minute<3: tg_send(f"*{MORNING}*\n\n💵 Ready", make_chart())
    elif et.hour in [16,22] and et.minute<6: tg_send(f"*{random.choice(PHRASES)}*\n\n💰 Checking...", make_chart())
    else: trade()
except Exception as e: tg_send(f"🚨 Crash: {str(e)[:100]}")