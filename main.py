import os, random, requests, datetime, pytz, sqlite3
import alpaca_trade_api as tradeapi
import matplotlib.pyplot as plt

# === SECRETS - DO NOT RENAME ===
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT")
DB_URL = os.getenv("DATABASE_URL")

api = tradeapi.REST(ALPACA_KEY, ALPACA_SECRET, "https://paper-api.alpaca.markets")

# === PHRASES ===
PHRASES = [
    "making bank baby 💸",
    "getting to that paper 📈",
    "checking stocks not flipping rocks",
    "real ones invest",
    "paper chasing",
    "put your trust in that paper",
    "real boss moves",
    "real bosses sit back we don't talk. We just listen. 😎",
    "clean money over here 🧼",
    "first in my generation",
    "who really want it",
    "first you stack your paper then you make boss moves"
]
MORNING = "Here's how we did big Pimpin"

# === MEMORY UPGRADE ===
try:
    import psycopg2
    conn = psycopg2.connect(DB_URL) if DB_URL else sqlite3.connect("trades.db")
except:
    conn = sqlite3.connect("trades.db")
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS trades
    (time TEXT, symbol TEXT, side TEXT, qty REAL, price REAL, pnl REAL)""")
conn.commit()

# === FAILSAFE AGENT ===
def safe_check():
    try:
        acct = api.get_account()
        bp = float(acct.buying_power)
        equity = float(acct.equity)
        positions = api.list_positions()

        if len(positions) >= 3:
            return False, "MAX 3 positions"
        if bp < 25:
            return False, "Low cash"
        if float(acct.portfolio_value) > equity * 1.05: # using margin
            return False, "Margin detected"
        return True, "OK"
    except Exception as e:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": f"🚨 ERROR: {str(e)[:80]}"})
        return False, str(e)

# === SLEEK DARK CHART ===
def make_chart():
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(6,3), facecolor='#0A0E14')
    ax.set_facecolor('#0A0E14')
    # pull last 20 trades for real curve
    try:
        cur.execute("SELECT pnl FROM trades ORDER BY time DESC LIMIT 20")
        pnls = [r[0] or 0 for r in cur.fetchall()][::-1]
        equity = [1000 + sum(pnls[:i+1]) for i in range(len(pnls))]
    except:
        equity = [1000, 1005, 1002, 1010]
    ax.plot(equity, color='#00FF88', linewidth=2.5)
    ax.axis('off')
    plt.tight_layout(pad=0)
    path = '/tmp/chart.png'
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#0A0E14')
    plt.close()
    return path

# === TELEGRAM ===
def tg_send(text, photo=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    kb = {"inline_keyboard": [[
        {"text":"📊 Chart","callback_data":"c"},
        {"text":"💰 P&L","callback_data":"p"},
        {"text":"⏸️ Pause","callback_data":"x"},
        {"text":"▶️ Resume","callback_data":"r"}
    ]]}
    requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": text,
                            "parse_mode": "Markdown", "reply_markup": kb})
    if photo:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT}, files={"photo": open(photo,'rb')})

# === 4-LAYER STRATEGY ===
def trade():
    ok, reason = safe_check()
    if not ok:
        return 0

    acct = api.get_account()
    equity = float(acct.equity)
    risk_per_trade = equity * 0.08 # max 8%

    symbols = ["SPY", "QQQ", "AAPL", "BTC/USD", "ETH/USD"]
    for sym in symbols:
        try:
            bars = api.get_bars(sym, "1Min", limit=10).df
            if len(bars) < 5: continue

            # Layer 1: scalper
            drop = bars.close.iloc[-1] / bars.close.iloc[-5] - 1
            if drop < -0.005:
                qty = 1 if "/" not in sym else round(risk_per_trade / bars.close.iloc[-1], 4)
                if qty * bars.close.iloc[-1] > risk_per_trade: continue

                api.submit_order(sym, qty, "buy", "market", "day")
                cur.execute("INSERT INTO trades VALUES (?,?,?,?,?,?)",
                    (datetime.datetime.now().isoformat(), sym, "BUY", float(qty),
                     float(bars.close.iloc[-1]), 0))
                conn.commit()
                break # one trade per minute max
        except:
            continue
    return equity

# === REPORTS ===
def morning():
    eq = float(api.get_account().equity)
    cur.execute("SELECT SUM(pnl) FROM trades WHERE time > datetime('now','-12 hours')")
    night = cur.fetchone()[0] or 0
    text = f"*{MORNING}*\n\n💵 Equity: `${eq:,.2f}`\n🌙 Overnight: `${night:+.2f}`\n📡 Status: Online"
    tg_send(text, make_chart())

def evening():
    phrase = random.choice(PHRASES)
    eq = float(api.get_account().equity)
    cur.execute("SELECT COUNT(*) FROM trades WHERE date(time)=date('now')")
    trades = cur.fetchone()[0]
    text = f"*{phrase}*\n\n💰 Close: `${eq:,.2f}`\n📊 Trades: {trades}\n🛡️ Risk: 8% max"
    tg_send(text, make_chart())

# === MAIN ===
et = datetime.datetime.now(pytz.timezone('US/Eastern'))
try:
    if et.hour == 8 and et.minute < 3:
        morning()
    elif et.hour == 16 and et.minute < 6:
        evening()
    elif et.hour == 22 and et.minute < 3:
        evening()
    else:
        trade()
except Exception as e:
    tg_send(f"🚨 Crash: {str(e)[:100]}") 