import json, os
from datetime import datetime
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

MEMORY_FILE = "memory.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {"patterns": [], "trades": [], "start_equity": 100000}

def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

memory = load_memory()

equity = 102788
cash = -114599
positions = [
    {"symbol": "NVDA", "qty": 965, "price": 207.88, "pnl": 1.4},
    {"symbol": "QQQ", "qty": 19, "price": 736.37, "pnl": 0.6}
]

memory["patterns"].append({
    "time": datetime.now().isoformat(),
    "nvda": 207.88,
    "qqq": 736.37
})
memory["patterns"] = memory["patterns"][-100:]

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

token = os.getenv("TELEGRAM_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT")

if token and chat_id:
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": chat_id, "text": message})

    plt.figure(figsize=(8,4))
    prices = [p.get('nvda', 0) for p in memory['patterns']]
    plt.plot(prices, marker='o', linewidth=2)
    plt.title(f'NVDA Memory Track - {patterns_count} points')
    plt.ylabel('Price')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig('chart.png')
    plt.close()

    with open('chart.png', 'rb') as photo:
        requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                      data={"chat_id": chat_id, "caption": "📈 Live Memory Graph"},
                      files={"photo": photo})

save_memory(memory)