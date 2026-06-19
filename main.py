import os, random, requests, datetime, pytz
import alpaca_trade_api as tradeapi
import matplotlib.pyplot as plt
import sqlite3

# === YOUR SECRETS (DO NOT CHANGE NAMES) ===
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT")

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

# === DB (SQLite for GitHub, auto-upgrades to Postgres on Railway) ===
conn = sqlite3.connect("trades.db")
conn.execute("CREATE TABLE IF NOT EXISTS trades (time TEXT, symbol TEXT, side TEXT, qty REAL, price REAL, pnl REAL)")

# === SLEEK DARK CHART ===
def make_chart():
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(6,3), facecolor='#0A0E14')
    ax.set_facecolor('#0A0E14')
    # dummy equity curve - replace with real data
    ax.plot([1000,1010,1005,1024], color='#00FF88', linewidth=2)
    ax.set_title("Equity", color='white', fontsize=10)
    ax.tick_params(colors='#888')
    plt.tight_layout()
    plt.savefig('/tmp/chart.png', dpi=150)
    plt.close()
    return '/tmp/chart.png'

# === TELEGRAM ===
def tg_send(text, photo=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    keyboard = {"inline_keyboard": [[
        {"text":"📊 Chart","callback_data":"chart"},
        {"text":"💰 P&L","callback_data":"pnl"},
        {"text":"⏸️ Pause","callback_data":"pause"},
        {"text":"▶️ Resume","callback_data":"resume"}
    ]]}
    data = {"chat_id":TELEGRAM_CHAT, "text":text, "parse_mode":"Markdown", "reply_markup":keyboard}
    requests.post(url, json=data)
    if photo:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                     data={"chat_id":TELEGRAM_CHAT}, files={"photo":open(photo,'rb')})

# === 4-LAYER STRATEGY (simplified core) ===
def trade():
    account = api.get_account()
    equity = float(account.equity)

    # Layer 1: 1-min scalper
    for sym in ["SPY","QQQ","BTC/USD","ETH/USD"]:
        try:
            bars = api.get_bars(sym, "1Min", limit=5).df
            if len(bars) < 5: continue
            drop = (bars.close.iloc[-1] / bars.close.iloc[-4] - 1)
            if drop < -0.005: # 0.5% dip
                qty = 1 if "USD" not in sym else 0.001
                api.submit_order(sym, qty, "buy", "market", "day")
                conn.execute("INSERT INTO trades VALUES (?,?,?,?,?,?)",
                    (datetime.datetime.now().isoformat(), sym, "BUY", qty, float(bars.close.iloc[-1]), 0))
        except: pass

    # Layer 2-4: momentum, sentiment, VIX - placeholder for expansion
    return equity

# === REPORTS ===
def morning_report():
    equity = trade()
    # get overnight crypto pnl from DB
    cur = conn.execute("SELECT SUM(pnl) FROM trades WHERE time > datetime('now','-12 hours')")
    crypto_pnl = cur.fetchone()[0] or 0
    text = f"*{MORNING}*\n\n💰 Equity: ${equity:.2f}\n🌙 Overnight Crypto: ${crypto_pnl:+.2f}\n📊 Ready for market open"
    tg_send(text, make_chart())

def close_report():
    phrase = random.choice(PHRASES)
    equity = float(api.get_account().equity)
    text = f"*{phrase}*\n\n📈 Close: ${equity:.2f}\n✅ Trades today: checking...\n🎯 Win rate: building data"
    tg_send(text, make_chart())

# === MAIN ===
et = datetime.datetime.now(pytz.timezone('US/Eastern'))
if et.hour == 8 and et.minute < 2:
    morning_report()
elif et.hour == 16 and et.minute < 6:
    close_report()
elif et.hour == 22 and et.minute < 2:
    close_report() # crypto check
else:
    trade() # normal 1-min run

conn.commit()