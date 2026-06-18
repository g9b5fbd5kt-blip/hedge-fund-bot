def simple_breakout(bars):
    if not bars or len(bars) < 2:
        return "HOLD", 0
    last = bars[-1]
    prev = bars[-2]
    if last['c'] > prev['h'] * 1.001:
        return "BUY", last['c']
    elif last['c'] < prev['l'] * 0.999:
        return "SELL", last['c']
    return "HOLD", last['c']

def analyze_data(data):
    signals = {}
    stocks = data.get('stocks', {}).get('bars', {})
    for symbol in ['NVDA', 'QQQ']:
        bars = stocks.get(symbol, [])
        signals[symbol] = simple_breakout(bars)
    crypto = data.get('crypto', {}).get('bars', {})
    for symbol in ['BTC/USD', 'ETH/USD']:
        bars = crypto.get(symbol, [])
        signals[symbol] = simple_breakout(bars)
    return signals