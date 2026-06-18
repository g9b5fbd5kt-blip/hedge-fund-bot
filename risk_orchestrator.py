import json, os
from datetime import datetime

STATE_FILE = "bot_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"daily_start_equity": 0, "last_date": ""}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

class RiskOrchestrator:
    def __init__(self, account, positions):
        self.equity = float(account.get("equity", 100000))
        self.buying_power = float(account.get("buying_power", 50000))
        self.positions = positions
        self.state = load_state()
        
        today = datetime.now().strftime("%Y-%m-%d")
        if self.state["last_date"] != today:
            self.state["daily_start_equity"] = self.equity
            self.state["last_date"] = today
            save_state(self.state)
    
    def check_drawdown(self):
        start = self.state["daily_start_equity"]
        if start == 0: return True
        drawdown = (start - self.equity) / start
        return drawdown < 0.05
    
    def check_exposure(self):
        positions_value = sum(float(p.get("market_value", 0)) for p in self.positions)
        return (positions_value / self.equity) < 0.80
    
    def position_size(self, symbol):
        return self.equity * 0.02  # 2% risk
    
    def can_trade(self, symbol, side):
        if not self.check_drawdown():
            return False, "Daily drawdown limit"
        if not self.check_exposure():
            return False, "Max exposure"
        if self.buying_power < 1000:
            return False, "Low buying power"
        return True, "OK"
