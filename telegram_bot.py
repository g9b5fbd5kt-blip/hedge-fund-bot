import os
import aiohttp

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram(session, text):
    if not TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    # use the session passed from bot.py
    await session.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})

def format_message(account, positions, signals=None, actions=None):
    equity = float(account.get('equity', 0))
    last_equity = float(account.get('last_equity', equity))
    bp = float(account.get('buying_power', 0))
    
    day_change = equity - last_equity
    day_pct = (day_change / last_equity * 100) if last_equity else 0
    
    sign = "+" if day_change >= 0 else ""
    lines = [
        "GETTING THAT PAPER 💸",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💰 ${equity:,.0f} ({sign}${abs(day_change):,.0f} today)",
        f"📊 Buying Power: ${bp:,.0f}",
        f"📈 Day: {sign}{abs(day_pct):.2f}%",
        "",
        "Holdings"
    ]
    
    for p in positions:
        sym = p.get('symbol')
        qty = p.get('qty')
        intraday_plpc = float(p.get('unrealized_intraday_plpc', 0)) * 100
        arrow = "▲" if intraday_plpc >= 0 else "▼"
        lines.append(f"- {sym}  {qty}  {arrow} {abs(intraday_plpc):.1f}%")
    
    if not positions:
        lines.append("- (none)")
    
    lines.extend(["", "━━━━━━━━━━━━━━━━━━━━"])
    return "\n".join(lines)msg = f"""🤖 BOT THINKING — {ticker}

Mode: {mode}
Confidence: {confidence}%
Reasoning:
• RSI: {rsi:.1f}
• News: {sentiment}
• Volume: {vol_ratio}x

Decision: {decision}
Next check: {next_run}"""
send_telegram(msg)