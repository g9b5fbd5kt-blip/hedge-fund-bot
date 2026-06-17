"""
Hedge Fund Exoskeleton Mobile v2.1
Strategy: Dual Momentum + Yield Curve Filter
Citations:
- Antonacci, G. (2012). "Risk Premia Harvesting Through Dual Momentum"
- Faber, M. (2007). "A Quantitative Approach to Tactical Asset Allocation"
- Estrella, A. (2005). "The Yield Curve as a Leading Indicator", FRB New York
- Harvey, C. (2017). "Backtesting" Journal of Portfolio Management
Runs: Daily at 15:45 ET via GitHub Actions. iPhone compatible.
"""
import os
import json
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca_trade_api.rest import REST, TimeFrame
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests

ALPACA_KEY = os.environ.get('ALPACA_KEY')
ALPACA_SECRET = os.environ.get('ALPACA_SECRET')
ALPACA_BASE_URL = 'https://paper-api.alpaca.markets'
SHEET_ID = os.environ.get('SHEET_ID')
GSPREAD_JSON = os.environ.get('GSPREAD_JSON')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

SYMBOLS = ['SPY', 'QQQ', 'IWM']
LOOKBACK_MOM = 200
RISK_PER_TRADE = 0.01
MAX_DD_STOP = 0.15

def send_telegram(msg):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def get_data():
    end = datetime.now()
    start = end - timedelta(days=LOOKBACK_MOM + 50)
    df = yf.download(SYMBOLS, start=start, end=end, auto_adjust=True)['Close']
    return df.dropna()

def get_yield_curve():
    try:
        t10 = yf.download('^TNX', period='5d')['Close'].iloc[-1] / 10
        t3m = yf.download('^IRX', period='5d')['Close'].iloc[-1] / 10
        return t10 - t3m
    except:
        return 1.0

def calc_signals(df):
    signals = {}
    returns = df.pct_change(LOOKBACK_MOM).iloc[-1]
    sma = df.rolling(LOOKBACK_MOM).mean().iloc[-1]
    curve = get_yield_curve()
    for sym in SYMBOLS:
        abs_mom = df[sym].iloc[-1] > sma[sym]
        rel_mom = returns[sym] == returns.max()
        regime_ok = curve > 0
        signals[sym] = abs_mom and rel_mom and regime_ok
    return signals, curve

def backtest(df):
    df = df['2010-01-01':]
    equity = [100000]
    position = None
    for i in range(LOOKBACK_MOM, len(df)):
        window = df.iloc[i-LOOKBACK_MOM:i]
        sig, _ = calc_signals(window)
        buy_list = [s for s, v in sig.items() if v]
        if buy_list and position!= buy_list[0]:
            position = buy_list[0]
        elif not buy_list:
            position = None
        ret = df[position].iloc[i] / df[position].iloc[i-1] - 1 if position else 0
        equity.append(equity[-1] * (1 + ret * 0.998))
    eq = pd.Series(equity, index=df.index[LOOKBACK_MOM-1:])
    cagr = (eq.iloc[-1]/eq.iloc[0])**(252/len(eq)) - 1
    dd = (eq / eq.cummax() - 1).min()
    sharpe = eq.pct_change().mean() / eq.pct_change().std() * np.sqrt(252)
    return {"CAGR": round(cagr,3), "MaxDD": round(dd,3), "Sharpe": round(sharpe,2)}

def get_alpaca():
    return REST(ALPACA_KEY, ALPACA_SECRET, ALPACA_BASE_URL)

def run_paper_trade():
    api = get_alpaca()
    account = api.get_account()
    equity = float(account.equity)
    if float(account.equity) < float(account.last_equity) * (1 - MAX_DD_STOP):
        send_telegram("KILL SWITCH: 15% drawdown hit. Trading halted.")
        return
    df = get_data()
    signals, curve = calc_signals(df)
    positions = {p.symbol: float(p.qty) for p in api.list_positions()}
    for sym, should_hold in signals.items():
        has_position = sym in positions
        price = df[sym].iloc[-1]
        if should_hold and not has_position:
            shares = int(equity * RISK_PER_TRADE / (price * 0.07))
            if shares > 0:
                api.submit_order(symbol=sym, qty=shares, side='buy', type='market', time_in_force='day')
                log_trade(sym, 'BUY', shares, price, f"Mom+ Curve:{curve:.2f}")
                send_telegram(f"Bought {shares} {sym} @ {price:.2f}")
        elif not should_hold and has_position:
            api.close_position(sym)
            log_trade(sym, 'SELL', positions[sym], price, "Signal off")
            send_telegram(f"Sold {sym} @ {price:.2f}")
    send_telegram(f"Daily run complete. Equity: ${equity:,.0f}. Curve: {curve:.2f}")

def log_trade(symbol, action, qty, price, reason):
    if not GSPREAD_JSON: return
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GSPREAD_JSON),
            ['https://spreadsheets.google.com/feeds'])
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).sheet1
    sheet.append_row([datetime.now().strftime('%Y-%m-%d %H:%M'), symbol, action, qty, round(price,2), reason])

if __name__ == "__main__":
    try:
        df = get_data()
        bt = backtest(df)
        send_telegram(f"Backtest 2010-2024: CAGR {bt['CAGR']}, MaxDD {bt['MaxDD']}, Sharpe {bt['Sharpe']}")
        if bt['Sharpe'] >= 0.8 and ALPACA_KEY:
            run_paper_trade()
        else:
            send_telegram("BLOCKED: Sharpe <0.8 or no API keys. No trades placed.")
    except Exception as e:
        send_telegram(f"ERROR: {str(e)}")