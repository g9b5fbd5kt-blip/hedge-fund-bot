import aiohttp, random, os

PHRASES = [
    "GETTING THAT PAPER 💸", "HUSTLING HARD 🔥",
    "CHECK CRYPTO TO MAKE YOU RICHO 🚀", "MAKING THE DREAM HAPPEN ✨",
    "STACKING WHILE THEY SCROLL 📈", "MONEY NEVER SLEEPS 😴",
    # ... add all 20
]

used = []
def get_phrase():
    global used
    avail = [p for p in PHRASES if p not in used]
    if not avail: used = []; avail = PHRASES
    phrase = random.choice(avail); used.append(phrase); return phrase

async def send_telegram(session, message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    await session.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})

def format_message(account, positions, signals, actions):
    phrase = get_phrase()
    equity = float(account.get("equity", 0))
    bp = float(account.get("buying_power", 0))
    
    msg = f"{phrase}\n\n━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"💰 ${equity:,.0f}\n📊 Buying Power: ${bp:,.0f}\n\n"
    
    if positions:
        msg += "Holdings\n"
        for p in positions[:4]:
            sym = p.get("symbol"); qty = float(p.get("qty",0))
            pnl = float(p.get("unrealized_plpc",0))*100
            msg += f"- {sym}  {qty:g}  {'▲' if pnl>=0 else '▼'} {abs(pnl):.1f}%\n"
    
    if actions:
        msg += "\nToday's Moves\n" + "\n".join(actions[:3])
    
    msg += "\n━━━━━━━━━━━━━━━━━━━━"
    return msg
