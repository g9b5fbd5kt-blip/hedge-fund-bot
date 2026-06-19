import json, os 
from datetime import datetime
import requests

# ===== MEMORY PERSISTENCE (new) =====
MEMORY_FILE = "memory.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
    else:
        data = {"patterns": [], "trades": [], "start_equity": 100000}
    return data

def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

# Load memory first
memory = load_memory()

# ===== YOUR BOT LOGIC (keep your real code here later) =====
# For now, this replicates your current output
equity = 102788
cash = -114599
positions = [
    {"symbol": "NVDA", "qty": 965, "price": 207.88, "pnl": 1.4},
    {"symbol": "QQQ", "qty": 19, "price": 736.37, "pnl": 0.6}
]

# Add a pattern each run (this is what makes memory grow)
memory["patterns"].append({
    "time": datetime.now().isoformat(),
    "nvda": 207.88,
    "qqq": 736.37
})
# Keep only last 100 to stay small
memory["patterns"] = memory["patterns"][-100:]

# ===== TELEGRAM OUTPUT (matches your screenshot) =====
patterns_count = len(memory["patterns"])
status = "WARMING UP" if patterns_count < 20 else "LEARNING"

message = f"""🔥 HEDGE FUND COMMAND CENTER
pimpin ain't easy 😎
────────────────────
💰 ${equity:,} (+0.0% today)
📊 All-Time: +2.8% | Win: 0% | Trades: 0
💵 Cash: ${cash:,}

🎯 ACTIVE POSITIONS (2)
- NVDA {positions[0]['qty']} @ ${positions[0]['price']} ▲ {positions[0]['pnl']}%
- QQQ {positions[1]['qty']} @ ${positions[1]['price']} ▲ {positions[1]['pnl']}%

💎 CRYPTO WATCH
- BTC: 🟡 60% Neutral
- ETH: 🟡 60% Neutral

🧠 BRAIN STATUS
- Memory: {patterns_count} patterns
- Kelly: 10.0% sizing
- Learning: {status}

🛡️ RISK GUARD
- Tech exposure: 211% (limit 40%)
- Daily loss: 0.0% (kill at -2%)
────────────────────
Next scan: 5 min | Mode: PAPER"""

# Send to Telegram (uses your existing secret)
token = os.getenv("TELEGRAM_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")
if token and chat_id:
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": chat_id, "text": message})

# ===== SAVE MEMORY LAST (critical) =====
save_memory(memory)
print(f"Saved memory with {patterns_count} patterns")