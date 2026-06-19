import os, random, requests, datetime, pytz, sqlite3, json
import alpaca_trade_api as tradeapi
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT")

# --- STATE ---
conn = sqlite3.connect("bot_state.db")
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT)")
cur.execute("INSERT OR IGNORE INTO state VALUES ('mode','paper'), ('paused','0'), ('update_id','0')")
conn.commit()

mode = cur.execute("SELECT v FROM state WHERE k='mode'").fetchone()[0]
paused = cur.execute("SELECT v FROM state WHERE k='paused'").fetchone()[0] == '1'
last_update = int(cur.execute("SELECT v FROM state WHERE k='update_id'").fetchone()[0])

BASE_URL = "https://api.alpaca.markets" if mode=='live' else "https://paper-api.alpaca.markets"
api = tradeapi.REST(ALPACA_KEY, ALPACA_SECRET, BASE_URL)

PHRASES = ["making bank baby 💸","getting to that paper 📈","checking stocks not flipping rocks","real ones invest","paper chasing","put your trust in that paper","real boss moves","real bosses sit back we don't talk. We just listen. 😎","clean money over here 🧼","first in my generation","who really want it","first you stack your paper then you make boss moves"]

def tg(method, data=None, files=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    return requests.post(url, data=data, json=data if not files else None, files=files).json()

def make_real_chart():
    plt.style.use('dark_background')
    fig, (ax1, ax2) = plt.subplots(2,1, figsize=(7,4), facecolor='#0A0E14', gridspec_kw={'height_ratios':[3,1]})
    fig.patch.set_facecolor('#0A0E14')

    for ax in [ax1, ax2]:
        ax.set_facecolor('#0A0E14')
        ax.tick_params(colors='#888', labelsize=8)
        ax.grid(True, color='#222', linestyle='--', alpha=0.3)

    try:
        # Real data - last 2 hours
        bars = api.get_bars("SPY", "5Min", limit=24).df
        ax1.plot(bars.index, bars.close, color='#00FF88', linewidth=2.5, label='SPY')
        ax1.fill_between(bars.index, bars.close, bars.close.min(), color='#00FF88', alpha=0.1)
        ax1.set_title(f'SPY ${bars.close.iloc[-1]:.2f} ({bars.close.iloc[-1]/bars.close.iloc[0]-1:+.2%})', color='white', fontsize=11, pad=10)
        ax1.legend(loc='upper left', fontsize=8)

        # Volume
        ax2.bar(bars.index, bars.volume, color='#444', width=0.002)
        ax2.set_ylabel('Vol', color='#888', fontsize=8)

        # Format time
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=pytz.timezone('US/Eastern')))
        fig.autofmt_xdate()
    except Exception as e:
        ax1.text(0.5,0.5, f'Chart error: {e}', ha='center', color='red', transform=ax1.transAxes)

    plt.tight_layout()
    path = '/tmp/chart.png'
    plt.savefig(path, dpi=180, bbox_inches='tight', facecolor='#0A0E14')
    plt.close()
    return path

def send_status():
    et = datetime.datetime.now(pytz.timezone('US/Eastern'))
    acct = api.get_account()
    equity = float(acct.equity)
    bp = float(acct.buying_power)
    positions = api.list_positions()

    status = f"*{random.choice(PHRASES)}*\n\n"
    status += f"🕒 {et.strftime('%I:%M %p ET')} • {mode.upper()}\n"
    status += f"💵 Equity: ${equity:,.2f}\n"
    status += f"💰 BP: ${bp:,.2f}\n"
    status += f"📊 Positions: {len(positions)}/3\n\n"

    for sym in ["SPY","QQQ","BTC/USD","ETH/USD"]:
        try:
            b = api.get_bars(sym, "5Min", limit=2).df
            chg = (b.close.iloc[-1]/b.close.iloc[-2]-1)*100
            status += f"• {sym}: ${b.close.iloc[-1]:.2f} ({chg:+.2f}%)\n"
        except: pass

    kb = {"inline_keyboard": [
        [{"text":"📊 Chart","callback_data":"chart"},{"text":"💰 P&L","callback_data":"pnl"}],
        [{"text":"⏸️ Pause","callback_data":"pause"},{"text":"▶️ Resume","callback_data":"resume"}],
        [{"text": f"🔴 LIVE" if mode=='paper' else "🟢 PAPER", "callback_data":"toggle"}]
    ]}

    tg("sendMessage", {"chat_id": TELEGRAM_CHAT, "text": status, "parse_mode":"Markdown", "reply_markup": json.dumps(kb)})
    tg("sendPhoto", data={"chat_id": TELEGRAM_CHAT}, files={"photo": open(make_real_chart(),'rb')})

# --- HANDLE BUTTONS ---
updates = tg("getUpdates", {"offset": last_update+1, "timeout":0})
for u in updates.get('result', []):
    last_update = max(last_update, u['update_id'])
    if 'callback_query' in u:
        data = u['callback_query']['data']
        cid = u['callback_query']['id']
        tg("answerCallbackQuery", {"callback_query_id": cid})

        if data == 'chart':
            tg("sendPhoto", data={"chat_id": TELEGRAM_CHAT, "caption":"📊 Live chart"}, files={"photo": open(make_real_chart(),'rb')})
        elif data == 'pnl':
            acct = api.get_account()
            pnl = float(acct.equity) - 1000 # adjust base
            tg("sendMessage", {"chat_id": TELEGRAM_CHAT, "text": f"💰 *P&L:* ${pnl:+.2f}\nEquity: ${float(acct.equity):,.2f}", "parse_mode":"Markdown"})
        elif data == 'pause':
            cur.execute("UPDATE state SET v='1' WHERE k='paused'"); conn.commit()
            tg("sendMessage", {"chat_id": TELEGRAM_CHAT, "text":"⏸️ Paused - will not trade"})
        elif data == 'resume':
            cur.execute("UPDATE state SET v='0' WHERE k='paused'"); conn.commit()
            tg("sendMessage", {"chat_id": TELEGRAM_CHAT, "text":"▶️ Resumed"})
        elif data == 'toggle':
            new_mode = 'live' if mode=='paper' else 'paper'
            cur.execute("UPDATE state SET v=? WHERE k='mode'", (new_mode,)); conn.commit()
            tg("sendMessage", {"chat_id": TELEGRAM_CHAT, "text": f"Switched to {new_mode.upper()} mode"})

cur.execute("UPDATE state SET v=? WHERE k='update_id'", (str(last_update),)); conn.commit()

# --- MAIN RUN ---
if not paused:
    send_status()
    # your trading logic here...
else:
    tg("sendMessage", {"chat_id": TELEGRAM_CHAT, "text":"⏸️ Bot paused - heartbeat only"})