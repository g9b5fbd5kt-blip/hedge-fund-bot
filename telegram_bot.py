import os
import aiohttp

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as s:
        await s.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})

def format_message(account, positions, signals=None, actions=None):
    for p in positions:
        sym = p.get('symbol')
        qty = p.get('qty')
        intraday_plpc = float(p.get('unrealized_intraday_plpc', 0)) * 100
        arrow = "▲" if intraday_plpc >= 0 else "▼"
        lines.append(f"- {sym}  {qty}  {arrow} {abs(intraday_plpc):.1f}%")
    
    if not positions:
        lines.append("- (none)")
    
    lines.extend(["", "━━━━━━━━━━━━━━━━━━━━"])
    return "\n".join(lines)